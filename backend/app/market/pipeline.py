"""Market pipeline: provider stream -> bounded queue -> dedupe -> aggregate -> history ->
batched persistence -> features -> shock detector -> event sink.

Design notes
- One producer task per provider reads ``provider.stream()`` into a bounded ``asyncio.Queue``.
  Overflow policy for live providers is drop-OLDEST (+ ``dropped`` counter + rate-limited WARN):
  fresh data beats stale data. The replay provider is deterministic, so for it the producer
  blocks (backpressure) instead of dropping.
- Supervisor-wrapped providers never raise. A bare provider that raises (connect/subscribe/
  stream) is recorded as DEGRADED and its producer stops; the pipeline and the app carry on.
- One consumer task does everything else, sequentially. Persistence is batched (size or time
  based, never per bar); a failed batch is kept and retried (upserts are idempotent).
- Features run on each closed 1m EQUITY bar, but only once the market and sector benchmark
  bars of the same minute exist (providers deliver the symbols of one minute in arbitrary
  order). If a benchmark bar never shows, the equity is evaluated as soon as a later minute
  is seen, so a missing benchmark delays evaluation by at most one minute. Frames handed to
  the engine are truncated to the evaluated bar (strictly causal).
- The feature engine runs in a worker thread so a long replay cannot starve the API.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import time
from collections import deque
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from typing import Any, Literal, Protocol

import polars as pl
from pydantic import BaseModel, Field

from app.market.aggregation import BarAggregator
from app.market.calendar import NY, MarketCalendar
from app.market.providers.base import MarketDataProvider
from app.market.providers.failover import BarDeduper, FailoverSelector
from app.market.settings import MarketSettings
from app.market.shock.detector import MarketShockDetector, ShockDecision
from app.market.shock.events import build_shock_event
from app.market.types import (
    Bar,
    DataMode,
    FeatureStatus,
    Interval,
    ProviderHealth,
    ProviderName,
    ProviderState,
    ShockAssessment,
    ShockLevel,
    SymbolFeatures,
)
from app.market.universe import Universe
from app.repositories.market import MarketBarRepository
from app.schemas.event import EventCreate

logger = logging.getLogger("echo.market.pipeline")

EventSink = Callable[[EventCreate], Awaitable[None]]
BarWriter = Callable[[Sequence[Bar]], Awaitable[int]]
Overflow = Literal["drop_oldest", "block"]

FRAME_SCHEMA: dict[str, Any] = {
    "timestamp": pl.Datetime("us", "UTC"),
    "open": pl.Float64,
    "high": pl.Float64,
    "low": pl.Float64,
    "close": pl.Float64,
    "volume": pl.Float64,
    "vwap": pl.Float64,
    "trade_count": pl.Int64,
}
_ONE_MIN = timedelta(minutes=1)
_STOP = object()  # queue wake-up sentinel (never counted, never persisted)
_WARN_EVERY_S = 30.0
_MAX_BUFFER = 50_000  # bars kept while the database is unavailable
_MAX_FAILED_EVENTS = 100
_LIVE_PROVIDERS = frozenset({ProviderName.MASSIVE, ProviderName.ALPACA})

_LEVEL_STATE = {
    ShockLevel.NONE: "NORMAL",
    ShockLevel.WATCH: "WATCH",
    ShockLevel.SHOCK: "SHOCK",
    ShockLevel.SEVERE: "SEVERE",
}


class _EngineLike(Protocol):
    def compute(self, symbol: str, frames: dict[str, pl.DataFrame]) -> SymbolFeatures: ...


class _DetectorLike(Protocol):
    def evaluate(self, features: SymbolFeatures) -> ShockDecision: ...


class PipelineStatus(BaseModel):
    mode: DataMode
    providers: list[ProviderHealth]
    active_provider: ProviderName | None = None
    queue_depth: int = 0
    queue_capacity: int = 0
    dropped: int = 0
    subscribed_symbols: list[str] = Field(default_factory=list)
    last_observation_at: datetime | None = None
    replay_finished: bool = False


@dataclass
class _SymbolBuf:
    frame: pl.DataFrame | None = None
    rows: list[tuple[Any, ...]] = field(default_factory=list)
    last_ts: datetime | None = None


_RESERVED_LOG_KEYS = frozenset(logging.LogRecord("", 0, "", 0, "", (), None).__dict__) | {
    "message",
    "asctime",
}


def log_event(log_level: int, event: str, /, **fields: Any) -> None:
    """Structured log: ``operation`` carries the event name; fields are also in the message.

    ``log_level`` and ``event`` are positional-only so a field may be called ``level``; field
    names that collide with ``LogRecord`` attributes are kept in the message but not in ``extra``.
    """
    text = " ".join(f"{k}={v}" for k, v in fields.items() if v is not None)
    extra: dict[str, Any] = {"operation": event}
    extra.update({k: v for k, v in fields.items() if k not in _RESERVED_LOG_KEYS})
    logger.log(log_level, f"{event} {text}".strip(), extra=extra)


def _to_row(bar: Bar) -> tuple[Any, ...]:
    return (
        bar.timestamp,
        bar.open,
        bar.high,
        bar.low,
        bar.close,
        bar.volume,
        bar.vwap,
        bar.trade_count,
    )


class MarketPipeline:
    def __init__(
        self,
        provider: MarketDataProvider,
        universe: Universe,
        settings: MarketSettings,
        session_factory: Callable[[], Any] | None,
        event_sink: EventSink | None,
        *,
        fallback: MarketDataProvider | None = None,
        feature_engine: _EngineLike | None = None,
        detector: _DetectorLike | None = None,
        calendar: MarketCalendar | None = None,
        bar_writer: BarWriter | None = None,
        batch_size: int = 500,
        flush_interval_s: float = 2.0,
        monitor_interval_s: float = 1.0,
        pending_grace_s: float = 10.0,
        overflow: Overflow | None = None,
        evaluate_from: datetime | None = None,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        if batch_size < 1:
            raise ValueError("batch_size must be >= 1")
        self.provider = provider
        self.fallback = fallback
        self._providers: list[MarketDataProvider] = [provider] + (
            [fallback] if fallback is not None else []
        )
        self._universe = universe
        self._settings = settings
        self._session_factory = session_factory
        self._event_sink = event_sink
        self._bar_writer = bar_writer
        self._calendar = calendar or MarketCalendar()
        self._batch_size = batch_size
        self._flush_interval = flush_interval_s
        self._monitor_interval = monitor_interval_s
        self._pending_grace = pending_grace_s
        self._clock = clock
        # Bars older than this are baseline only (ingested/persisted, never evaluated). Replay
        # warm-up sessions use it: the feature engine costs ~0.1 s per call.
        self._evaluate_from = evaluate_from
        self._overflow: Overflow = overflow or (
            "block" if provider.name == ProviderName.REPLAY else "drop_oldest"
        )
        self._queue: asyncio.Queue[Any] = asyncio.Queue(maxsize=settings.echo_market_queue_size)
        self.dropped = 0
        self._dropped_unlogged = 0

        self._selector: FailoverSelector | None = (
            FailoverSelector(provider.name, fallback.name) if fallback is not None else None
        )
        self._deduper = BarDeduper()
        self._aggregator = BarAggregator((Interval.M5, Interval.M15))
        self._engine_obj: _EngineLike | None = feature_engine
        self._detector: _DetectorLike = detector or MarketShockDetector(settings.shock)

        self._buf: dict[str, _SymbolBuf] = {}
        self._pending: list[tuple[str, datetime, float]] = []  # (symbol, bar ts, wall)
        self._max_ts: datetime | None = None
        self._buffer: list[Bar] = []
        self._last_flush = clock()
        self._flush_retry_at = 0.0
        self._failed_events: deque[EventCreate] = deque(maxlen=_MAX_FAILED_EVENTS)

        self.latest_features: dict[str, SymbolFeatures] = {}
        self.latest_assessments: dict[str, ShockAssessment] = {}
        self.latest_prices: dict[str, tuple[float, datetime]] = {}
        self._session_first: dict[str, tuple[date, datetime, float]] = {}
        self.last_observation_at: datetime | None = None
        self._subscribed: list[str] = []

        self._failed_providers: dict[ProviderName, str] = {}
        self._last_state: dict[ProviderName, ProviderState] = {}
        self._last_malformed: dict[ProviderName, int] = {}
        self._rl_last: dict[str, float] = {}

        self._tasks: list[asyncio.Task[None]] = []
        self._consumer: asyncio.Task[None] | None = None
        self._monitor_task: asyncio.Task[None] | None = None
        self._producers_left = 0
        self._producers_done = False
        self._stopping = False
        self._started = False
        self.finished = False
        self.stats: dict[str, int] = {
            "received": 0,
            "accepted": 0,
            "ignored": 0,
            "aggregated": 0,
            "writes": 0,
            "persisted": 0,
            "write_failures": 0,
            "evaluated": 0,
            "events_emitted": 0,
            "sink_failures": 0,
            "errors": 0,
        }

    # ------------------------------------------------------------------ lifecycle

    def start(self) -> None:
        """Create producer/consumer/monitor tasks (needs a running loop). Idempotent."""
        if self._started:
            return
        self._started = True
        self._producers_left = len(self._providers)
        for p in self._providers:
            self._tasks.append(
                asyncio.create_task(self._produce(p), name=f"market-produce-{p.name}")
            )
        self._consumer = asyncio.create_task(self._consume(), name="market-consume")
        self._monitor_task = asyncio.create_task(self._monitor(), name="market-monitor")

    async def run(self) -> None:
        """Start and wait until the stream(s) end or ``stop()`` is called. Never raises
        provider errors."""
        self.start()
        assert self._consumer is not None
        try:
            await asyncio.wait({self._consumer})
        except asyncio.CancelledError:
            await asyncio.shield(self.stop(drain_s=2.0))  # never leak background tasks
            raise
        await self._cancel_background()

    async def stop(self, drain_s: float = 10.0) -> None:
        """Stop producers, drain the queue, flush persistence, cancel everything."""
        self._stopping = True
        await self._cancel_background(include_producers=True)
        for p in self._providers:  # bare providers have no supervisor to disconnect them
            with contextlib.suppress(Exception):
                await p.disconnect()
        self._wake()
        if self._consumer is not None and not self._consumer.done():
            _, pending = await asyncio.wait({self._consumer}, timeout=drain_s)
            if pending:
                self._consumer.cancel()
                await asyncio.gather(self._consumer, return_exceptions=True)
        with contextlib.suppress(Exception):
            await self._flush(force=True)  # nothing buffered may be lost, even if drain timed out
            await self._retry_events()
        self.finished = True
        self._observe_health()

    async def _cancel_background(self, include_producers: bool = True) -> None:
        tasks = ([self._monitor_task] if self._monitor_task else []) + (
            list(self._tasks) if include_producers else []
        )
        for t in tasks:
            t.cancel()
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)

    def _wake(self) -> None:
        with contextlib.suppress(asyncio.QueueFull):
            self._queue.put_nowait(_STOP)

    # ------------------------------------------------------------------ producer

    async def _produce(self, provider: MarketDataProvider) -> None:
        name = provider.name
        stream: Any = None
        try:
            try:
                await provider.connect()
                await provider.subscribe(self._universe.symbols())
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                self._mark_failed(name, "connect/subscribe", exc)
                return
            if not self._subscribed:
                self._subscribed = list(self._universe.symbols())
            log_event(
                logging.INFO,
                "subscription_started",
                provider=name.value,
                count=len(self._universe.symbols()),
                state=self._health_of(provider).state.value,
            )
            stream = provider.stream()
            async for bar in stream:
                await self._enqueue(bar)
                if self._overflow == "block":
                    await asyncio.sleep(0)
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # bare provider failure: degrade, keep the app alive
            self._mark_failed(name, "stream", exc)
        finally:
            aclose = getattr(stream, "aclose", None)
            if aclose is not None:
                with contextlib.suppress(Exception, asyncio.CancelledError):
                    await aclose()
            self._producers_left -= 1
            if self._producers_left <= 0:
                self._producers_done = True
                self._wake()

    def _mark_failed(self, name: ProviderName, where: str, exc: BaseException) -> None:
        self._failed_providers[name] = f"{where}: {type(exc).__name__}: {exc}"
        log_event(
            logging.ERROR,
            "provider_degraded",
            provider=name.value,
            error=self._failed_providers[name],
        )

    async def _enqueue(self, bar: Bar) -> None:
        self.stats["received"] += 1
        if self._overflow == "block":
            await self._queue.put(bar)
            return
        try:
            self._queue.put_nowait(bar)
        except asyncio.QueueFull:
            with contextlib.suppress(asyncio.QueueEmpty):
                if self._queue.get_nowait() is _STOP:  # drop the OLDEST (a wake-up is no bar)
                    self._queue.put_nowait(bar)
                    return
            self.dropped += 1
            self._dropped_unlogged += 1
            self._queue.put_nowait(bar)
            if self._rate_ok("queue_overflow"):
                logger.warning(
                    "queue_overflow dropped_oldest count=%d total_dropped=%d capacity=%d",
                    self._dropped_unlogged,
                    self.dropped,
                    self._queue.maxsize,
                    extra={"operation": "queue_overflow", "count": self._dropped_unlogged},
                )
                self._dropped_unlogged = 0

    def _rate_ok(self, key: str) -> bool:
        now = self._clock()
        last = self._rl_last.get(key)
        if last is not None and now - last < _WARN_EVERY_S:
            return False
        self._rl_last[key] = now
        return True

    # ------------------------------------------------------------------ consumer

    async def _consume(self) -> None:
        try:
            while True:
                if (self._stopping or self._producers_done) and self._queue.empty():
                    break
                try:
                    item = await asyncio.wait_for(self._queue.get(), timeout=self._flush_interval)
                except TimeoutError:
                    await self._on_idle()
                    continue
                if item is _STOP:
                    continue
                try:
                    await self._process(item)
                except asyncio.CancelledError:
                    raise
                except Exception:
                    self.stats["errors"] += 1
                    if self._rate_ok("process_error"):
                        logger.exception(
                            "pipeline_error processing bar",
                            extra={"operation": "pipeline_error"},
                        )
                await self._flush()
        finally:
            await self._finalize()

    async def _on_idle(self) -> None:
        with contextlib.suppress(Exception):
            await self._resolve_pending()
        await self._flush()
        await self._retry_events()

    async def _finalize(self) -> None:
        try:
            await self._resolve_pending(final=True)
            if not self._stopping:  # natural end of stream: emit partial 5m/15m buckets
                for agg in self._aggregator.flush():
                    self._buffer.append(agg)
                    self.stats["aggregated"] += 1
            await self._flush(force=True)
            await self._retry_events()
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception(
                "pipeline_error during finalize", extra={"operation": "pipeline_error"}
            )
        finally:
            self.finished = True
            self._observe_health()

    async def _process(self, bar: Bar) -> None:
        if bar.interval != Interval.M1 or self._universe.entry(bar.symbol) is None:
            self.stats["ignored"] += 1
            return
        active = self._active_name()
        if bar.source != active and self._selector is not None:
            # A fallback bar while the primary may have just died: re-check health now instead
            # of waiting for the next monitor tick, so the first fallback bar is not lost.
            self._observe_health()
            active = self._active_name()
        if not self._deduper.accept(bar, active):
            return
        self.stats["accepted"] += 1
        self._ingest(bar)
        self._buffer.append(bar)
        for agg in self._aggregator.add(bar):
            self._buffer.append(agg)
            self.stats["aggregated"] += 1
        entry = self._universe.entry(bar.symbol)
        if (
            entry is not None
            and entry.role == "equity"
            and (self._evaluate_from is None or bar.timestamp >= self._evaluate_from)
        ):
            self._pending.append((bar.symbol, bar.timestamp, self._clock()))
        await self._resolve_pending()

    # ------------------------------------------------------------------ history

    def _ingest(self, bar: Bar) -> None:
        sym, ts = bar.symbol, bar.timestamp
        buf = self._buf.setdefault(sym, _SymbolBuf())
        buf.rows.append(_to_row(bar))
        if buf.last_ts is None or ts > buf.last_ts:
            buf.last_ts = ts
        if len(buf.rows) >= self._settings.features.history_bars:
            self._frame(sym)  # materialize so the row list stays bounded
        if self._max_ts is None or ts > self._max_ts:
            self._max_ts = ts
        if self.last_observation_at is None or ts > self.last_observation_at:
            self.last_observation_at = ts
        latest = self.latest_prices.get(sym)
        if latest is None or ts >= latest[1]:
            self.latest_prices[sym] = (bar.close, ts)
        d = ts.astimezone(NY).date()
        first = self._session_first.get(sym)
        if first is None or first[0] < d or (first[0] == d and ts < first[1]):
            self._session_first[sym] = (d, ts, bar.close)

    def _frame(self, symbol: str) -> pl.DataFrame | None:
        buf = self._buf.get(symbol)
        if buf is None:
            return None
        if buf.rows:
            new = pl.DataFrame(buf.rows, schema=FRAME_SCHEMA, orient="row")
            df = new if buf.frame is None else pl.concat([buf.frame, new])
            buf.frame = (
                df.unique(subset="timestamp", keep="last", maintain_order=True)
                .sort("timestamp")
                .tail(self._settings.features.history_bars)
            )
            buf.rows = []
        return buf.frame

    def history(self, symbol: str) -> pl.DataFrame | None:
        """Read-only copy-free view of the capped 1m history for ``symbol``."""
        return self._frame(symbol.upper())

    def _last_ts(self, symbol: str) -> datetime | None:
        buf = self._buf.get(symbol)
        return buf.last_ts if buf else None

    # ------------------------------------------------------------------ features / shocks

    @property
    def _engine(self) -> _EngineLike:
        if self._engine_obj is None:
            from app.market.features.engine import FeatureEngine  # lazy: sibling module

            self._engine_obj = FeatureEngine(self._universe, self._settings.features)
        return self._engine_obj

    async def _resolve_pending(self, final: bool = False) -> None:
        if not self._pending:
            return
        self._pending.sort(key=lambda p: (p[1], p[0]))
        keep: list[tuple[str, datetime, float]] = []
        ready: list[tuple[str, datetime]] = []
        now = self._clock()
        for sym, t, since in self._pending:
            mkt = self._universe.market_benchmark
            sec = self._universe.sector_benchmark_for(sym)
            caught_up = all((ts := self._last_ts(b)) is not None and ts >= t for b in (mkt, sec))
            stale = self._max_ts is not None and self._max_ts >= t + _ONE_MIN
            waited = now - since >= self._pending_grace
            if caught_up or stale or waited or final:
                ready.append((sym, t))
            else:
                keep.append((sym, t, since))
        self._pending = keep
        for sym, t in ready:
            try:
                await self._evaluate(sym, t)
            except asyncio.CancelledError:
                raise
            except Exception:
                self.stats["errors"] += 1
                if self._rate_ok("evaluate_error"):
                    logger.exception(
                        "pipeline_error evaluating %s",
                        sym,
                        extra={"operation": "pipeline_error"},
                    )

    def _frames_upto(self, symbol: str, t: datetime) -> dict[str, pl.DataFrame] | None:
        keys = [
            symbol,
            self._universe.market_benchmark,
            self._universe.sector_benchmark_for(symbol),
        ]
        frames: dict[str, pl.DataFrame] = {}
        for k in dict.fromkeys(keys):
            df = self._frame(k)
            if df is None or df.height == 0:
                return None  # own or benchmark bars do not exist yet
            if (last := self._last_ts(k)) is not None and last > t:
                df = df.filter(pl.col("timestamp") <= t)
            frames[k] = df
        return frames

    async def _evaluate(self, symbol: str, t: datetime) -> None:
        frames = self._frames_upto(symbol, t)
        if frames is None:
            return
        engine = self._engine
        features = await asyncio.to_thread(engine.compute, symbol, frames)
        decision = self._detector.evaluate(features)
        self.stats["evaluated"] += 1
        self.latest_features[symbol] = features
        self.latest_assessments[symbol] = decision.assessment
        if not decision.emit:
            return
        provider_name = self._active_name()
        try:
            event = build_shock_event(decision.assessment, features, provider_name)
        except ValueError as exc:
            logger.warning(
                "shock event not built symbol=%s error=%s",
                symbol,
                exc,
                extra={"operation": "shock_event_skipped"},
            )
            return
        log_event(
            logging.INFO,
            "market_shock_detected",
            provider=provider_name.value,
            symbol=symbol,
            timestamp=features.as_of.isoformat(),
            shock_score=round(decision.assessment.score, 4),
            level=decision.assessment.level.value,
        )
        self.stats["events_emitted"] += 1
        await self._emit(event)

    async def _emit(self, event: EventCreate) -> None:
        if self._event_sink is None:
            return
        try:
            await self._event_sink(event)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            self.stats["sink_failures"] += 1
            self._failed_events.append(event)  # deterministic id => retry is idempotent
            logger.warning(
                "event_sink_failed event_id=%s error=%s",
                event.id,
                exc,
                extra={"operation": "event_sink_failed", "event_id": event.id},
            )

    async def _retry_events(self) -> None:
        for _ in range(len(self._failed_events)):
            event = self._failed_events.popleft()
            await self._emit(event)

    # ------------------------------------------------------------------ persistence

    async def _write(self, bars: Sequence[Bar]) -> int:
        if self._bar_writer is not None:
            return await self._bar_writer(bars)
        assert self._session_factory is not None
        async with self._session_factory() as session:
            n = await MarketBarRepository(session).upsert_bars(bars)
            await session.commit()
            return n

    @property
    def _persist_enabled(self) -> bool:
        return self._bar_writer is not None or self._session_factory is not None

    async def _flush(self, force: bool = False) -> None:
        if not self._buffer:
            self._last_flush = self._clock()
            return
        if not self._persist_enabled:
            self._buffer.clear()
            return
        now = self._clock()
        if not force:
            if (
                len(self._buffer) < self._batch_size
                and now - self._last_flush < self._flush_interval
            ):
                return
            if now < self._flush_retry_at:
                return
        batch = list(self._buffer)
        try:
            await self._write(batch)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            self.stats["write_failures"] += 1
            self._flush_retry_at = self._clock() + max(self._flush_interval, 0.1)
            if len(self._buffer) > _MAX_BUFFER:
                del self._buffer[: len(self._buffer) - _MAX_BUFFER]
            if force or self._rate_ok("write_failed"):
                logger.warning(
                    "bar_write_failed count=%d buffered=%d error=%s",
                    len(batch),
                    len(self._buffer),
                    exc,
                    extra={"operation": "bar_write_failed", "count": len(batch)},
                )
            return
        del self._buffer[: len(batch)]
        self.stats["writes"] += 1
        self.stats["persisted"] += len(batch)
        self._last_flush = self._clock()

    # ------------------------------------------------------------------ health / status

    def _active_name(self) -> ProviderName:
        return self._selector.active if self._selector is not None else self.provider.name

    def _health_of(self, provider: MarketDataProvider) -> ProviderHealth:
        try:
            h = provider.health()
        except Exception as exc:
            h = ProviderHealth(
                provider=provider.name,
                state=ProviderState.DEGRADED,
                configured=True,
                mode=DataMode.REPLAY if provider.name == ProviderName.REPLAY else DataMode.LIVE,
                last_error=f"health check failed: {exc}",
            )
        err = self._failed_providers.get(provider.name)
        if err is not None and h.state in (ProviderState.CONNECTED, ProviderState.CONNECTING):
            h = h.model_copy(update={"state": ProviderState.DEGRADED, "last_error": err})
        return h

    def provider_healths(self) -> list[ProviderHealth]:
        return [self._health_of(p) for p in self._providers]

    def health_map(self) -> dict[ProviderName, ProviderHealth]:
        return {h.provider: h for h in self.provider_healths()}

    @property
    def active_provider(self) -> ProviderName | None:
        return self._active_name()

    @property
    def mode(self) -> DataMode:
        active = self._active_name()
        if active == ProviderName.REPLAY:
            return DataMode.REPLAY
        health = self.health_map().get(active)
        if (
            active in _LIVE_PROVIDERS
            and health is not None
            and health.state == ProviderState.CONNECTED
        ):
            return DataMode.LIVE
        return DataMode.OFFLINE

    @property
    def subscribed_symbols(self) -> list[str]:
        health = self.health_map().get(self._active_name())
        if health is not None and health.subscribed_symbols:
            return list(health.subscribed_symbols)
        return list(self._subscribed)

    @property
    def replay_finished(self) -> bool:
        return (
            self.finished
            and self.provider.name == ProviderName.REPLAY
            and self.provider.name not in self._failed_providers
            and bool(getattr(self.provider, "finished", False))
        )

    def queue_stats(self) -> dict[str, int]:
        return {
            "depth": self._queue.qsize(),
            "capacity": self._queue.maxsize,
            "dropped": self.dropped,
        }

    def status(self) -> PipelineStatus:
        q = self.queue_stats()
        return PipelineStatus(
            mode=self.mode,
            providers=self.provider_healths(),
            active_provider=self.active_provider,
            queue_depth=q["depth"],
            queue_capacity=q["capacity"],
            dropped=q["dropped"],
            subscribed_symbols=self.subscribed_symbols,
            last_observation_at=self.last_observation_at,
            replay_finished=self.replay_finished,
        )

    async def _monitor(self) -> None:
        while True:
            self._observe_health()
            await asyncio.sleep(self._monitor_interval)

    def _observe_health(self) -> None:
        """Poll provider health: drive failover and log STATE CHANGES only (never per tick)."""
        try:
            healths = self.health_map()
            if self._selector is not None:
                before = self._selector.active
                after = self._selector.update(healths)
                if after != before:
                    log_event(
                        logging.WARNING,
                        "provider_failover",
                        provider=after.value,
                        previous=before.value,
                        reason=self._selector.reason,
                    )
            for name, h in healths.items():
                prev = self._last_state.get(name)
                if prev != h.state:
                    self._last_state[name] = h.state
                    self._log_transition(name, prev, h)
                seen = self._last_malformed.get(name, 0)
                if h.malformed_messages > seen:
                    self._last_malformed[name] = h.malformed_messages
                    if self._rate_ok(f"malformed_{name.value}"):
                        log_event(
                            logging.WARNING,
                            "malformed_message",
                            provider=name.value,
                            count=h.malformed_messages,
                        )
        except Exception:
            logger.exception("health observation failed", extra={"operation": "monitor_error"})

    @staticmethod
    def _log_transition(name: ProviderName, prev: ProviderState | None, h: ProviderHealth) -> None:
        fields = {"provider": name.value, "state": h.state.value, "error": h.last_error}
        if h.state == ProviderState.CONNECTED:
            log_event(logging.INFO, "provider_connected", **fields)
            if prev == ProviderState.RECONNECTING:
                log_event(  # the supervisor re-subscribes on every successful reconnect
                    logging.INFO,
                    "subscription_started",
                    provider=name.value,
                    count=len(h.subscribed_symbols),
                    resubscribed=True,
                )
        elif h.state == ProviderState.RECONNECTING:
            log_event(
                logging.WARNING, "provider_reconnecting", attempts=h.reconnect_attempts, **fields
            )
        elif h.state == ProviderState.STALE:
            log_event(logging.WARNING, "provider_stale", **fields)
        elif h.state == ProviderState.DISCONNECTED and prev is not None:
            log_event(logging.INFO, "provider_disconnected", **fields)
        elif h.state in (ProviderState.DEGRADED, ProviderState.UNCONFIGURED):
            log_event(logging.WARNING, f"provider_{h.state.value.lower()}", **fields)

    # ------------------------------------------------------------------ facade helpers

    def latest_price(self, symbol: str) -> tuple[float, datetime] | None:
        return self.latest_prices.get(symbol.upper())

    def change_pct(self, symbol: str) -> float | None:
        sym = symbol.upper()
        last = self.latest_prices.get(sym)
        first = self._session_first.get(sym)
        if last is None or first is None or first[2] <= 0:
            return None
        if last[1].astimezone(NY).date() != first[0]:
            return None
        return (last[0] / first[2] - 1.0) * 100.0

    def state_of(self, symbol: str) -> str:
        sym = symbol.upper()
        entry = self._universe.entry(sym)
        if entry is None:
            return "NO_DATA"
        if entry.role != "equity":
            return "NORMAL" if sym in self.latest_prices else "NO_DATA"
        feats = self.latest_features.get(sym)
        assessment = self.latest_assessments.get(sym)
        if feats is None or assessment is None:
            return "WARMING_UP" if sym in self.latest_prices else "NO_DATA"
        if feats.overall_status != FeatureStatus.READY or not assessment.ready:
            return "WARMING_UP"
        return _LEVEL_STATE[assessment.level]
