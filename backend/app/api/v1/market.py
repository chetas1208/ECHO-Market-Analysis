"""Market data API: feed status, symbol board, bars, features, recent shocks."""

import math
from collections.abc import Sequence
from datetime import UTC, datetime
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Query, Request
from fastapi.exceptions import RequestValidationError
from pydantic import AfterValidator

from app.api.deps import SessionDep
from app.core.errors import NotFoundError
from app.market.types import (
    Bar,
    DataMode,
    FeatureStatus,
    Interval,
    ProviderHealth,
    ProviderName,
    ShockAssessment,
    SymbolFeatures,
)
from app.market.universe import Universe, get_universe
from app.repositories.market import MAX_BARS_LIMIT, MarketBarRepository
from app.repositories.market_bar_window import bars_ending_at
from app.repositories.market_events import MarketEventRepository
from app.schemas.common import ErrorResponse
from app.schemas.event import Event
from app.schemas.market import (
    BarOut,
    BarsResponse,
    FeaturesResponse,
    MarketStatus,
    QueueStats,
    ShocksResponse,
    SymbolRow,
    SymbolsResponse,
)

router = APIRouter(prefix="/market", tags=["market"])

_ERRORS = {
    404: {"model": ErrorResponse, "description": "Unknown symbol"},
    422: {"model": ErrorResponse, "description": "Validation error"},
}

DEFAULT_BARS_LIMIT = 300
# Rows fetched per requested bar so de-duplication across sources can still fill the limit.
_SOURCE_FANOUT = len(ProviderName)


class OfflineRuntime:
    """Stand-in used when the app has no market runtime: OFFLINE, nothing subscribed."""

    mode = DataMode.OFFLINE
    active_provider: ProviderName | None = None
    last_observation_at: datetime | None = None
    replay_finished = False
    session = "CLOSED"

    def provider_healths(self) -> list[ProviderHealth]:
        return []

    @property
    def subscribed_symbols(self) -> list[str]:
        return []

    def queue_stats(self) -> dict[str, int]:
        return {"depth": 0, "capacity": 0, "dropped": 0}

    def latest_features(self, symbol: str) -> SymbolFeatures | None:
        return None

    def latest_assessment(self, symbol: str) -> ShockAssessment | None:
        return None

    def latest_price(self, symbol: str) -> tuple[float, datetime] | None:
        return None

    def change_pct(self, symbol: str) -> float | None:
        return None

    def state_of(self, symbol: str) -> str:
        return "NO_DATA"


_OFFLINE = OfflineRuntime()


def get_runtime(request: Request) -> Any:
    return getattr(request.app.state, "market_runtime", None) or _OFFLINE


def get_universe_dep() -> Universe:
    return get_universe()


def get_bar_repository(session: SessionDep) -> MarketBarRepository:
    return MarketBarRepository(session)


def get_market_event_repository(session: SessionDep) -> MarketEventRepository:
    return MarketEventRepository(session)


RuntimeDep = Annotated[Any, Depends(get_runtime)]
UniverseDep = Annotated[Universe, Depends(get_universe_dep)]
BarRepoDep = Annotated[MarketBarRepository, Depends(get_bar_repository)]
MarketEventRepoDep = Annotated[MarketEventRepository, Depends(get_market_event_repository)]


def _require_aware(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("must be timezone-aware: include a UTC offset or 'Z'")
    return value.astimezone(UTC)


AwareDatetime = Annotated[datetime, AfterValidator(_require_aware)]


def _finite(value: float | None) -> float | None:
    if value is None or not math.isfinite(value):
        return None
    return float(value)


def _known_symbol(universe: Universe, symbol: str) -> str:
    normalized = symbol.strip().upper()
    if universe.entry(normalized) is None:
        raise NotFoundError(f"Symbol '{symbol}' is not in the market universe")
    return normalized


def _reported_mode(runtime: Any) -> DataMode:
    """Replay/mock data must never be reported as LIVE, whatever the runtime claims."""
    mode = DataMode(runtime.mode)
    if mode == DataMode.LIVE and runtime.active_provider == ProviderName.REPLAY:
        return DataMode.REPLAY
    return mode


@router.get("/status", response_model=MarketStatus)
async def market_status(runtime: RuntimeDep) -> MarketStatus:
    stats = runtime.queue_stats() or {}
    return MarketStatus(
        mode=_reported_mode(runtime),
        providers=list(runtime.provider_healths()),
        active_provider=runtime.active_provider,
        subscribed_symbols=list(runtime.subscribed_symbols),
        last_observation_at=runtime.last_observation_at,
        queue=QueueStats(
            depth=int(stats.get("depth", 0)),
            capacity=int(stats.get("capacity", 0)),
            dropped=int(stats.get("dropped", 0)),
        ),
        replay_finished=bool(runtime.replay_finished),
        session=str(runtime.session),
    )


def _symbol_row(runtime: Any, entry: Any) -> SymbolRow:
    symbol = entry.symbol
    price = runtime.latest_price(symbol)
    features: SymbolFeatures | None = runtime.latest_features(symbol)
    assessment: ShockAssessment | None = runtime.latest_assessment(symbol)
    return SymbolRow(
        symbol=symbol,
        group=entry.group,
        role=entry.role,
        sector_benchmark=entry.sector_benchmark,
        price=_finite(price[0]) if price else None,
        change_pct=_finite(runtime.change_pct(symbol)),
        as_of=price[1] if price else None,
        state=runtime.state_of(symbol),
        shock_score=_finite(assessment.score) if assessment else None,
        volume_z=_finite(features.volume_z.value) if features else None,
        return_5m=_finite(features.ret_5m.value) if features else None,
        sector_residual=_finite(features.sector_residual.value) if features else None,
        direction=assessment.direction.value if assessment and assessment.direction else None,
    )


@router.get("/symbols", response_model=SymbolsResponse)
async def market_symbols(runtime: RuntimeDep, universe: UniverseDep) -> SymbolsResponse:
    return SymbolsResponse(items=[_symbol_row(runtime, e) for e in universe.entries])


def dedupe_bars(bars: Sequence[Bar], preferred: ProviderName | None) -> list[Bar]:
    """One bar per timestamp: the preferred source if present, else the first alphabetically."""
    chosen: dict[datetime, Bar] = {}
    for bar in bars:
        current = chosen.get(bar.timestamp)
        if current is None or _source_rank(bar, preferred) < _source_rank(current, preferred):
            chosen[bar.timestamp] = bar
    return [chosen[ts] for ts in sorted(chosen)]


def _source_rank(bar: Bar, preferred: ProviderName | None) -> tuple[int, str]:
    return (0 if bar.source == preferred else 1, bar.source.value)


@router.get(
    "/bars/{symbol}",
    response_model=BarsResponse,
    responses={404: _ERRORS[404], 422: _ERRORS[422]},
)
async def market_bars(
    symbol: str,
    runtime: RuntimeDep,
    universe: UniverseDep,
    repo: BarRepoDep,
    interval: Interval = Interval.M1,
    start: Annotated[AwareDatetime | None, Query()] = None,
    end: Annotated[AwareDatetime | None, Query()] = None,
    limit: Annotated[int, Query(ge=1, le=MAX_BARS_LIMIT)] = DEFAULT_BARS_LIMIT,
) -> BarsResponse:
    """Ascending bars, one per timestamp; without ``start`` the newest ``limit`` bars."""
    sym = _known_symbol(universe, symbol)
    if start is not None and end is not None and start > end:
        raise RequestValidationError(
            [{"type": "value_error", "loc": ("query", "start"), "msg": "start must be <= end"}]
        )
    fetch = min(MAX_BARS_LIMIT, limit * _SOURCE_FANOUT)
    if start is not None:
        rows = await repo.get_bars(sym, interval, start=start, end=end, limit=fetch)
        bars = dedupe_bars(rows, runtime.active_provider)[:limit]
    else:
        if end is None:
            rows = await repo.load_recent(sym, interval, fetch)
        else:
            rows = await bars_ending_at(repo.session, sym, interval, end, fetch)
        bars = dedupe_bars(rows, runtime.active_provider)[-limit:]
    return BarsResponse(
        symbol=sym,
        interval=interval.value,
        items=[BarOut.model_validate(b, from_attributes=True) for b in bars],
    )


@router.get(
    "/features/{symbol}",
    response_model=FeaturesResponse,
    responses={404: _ERRORS[404]},
)
async def market_features(
    symbol: str, runtime: RuntimeDep, universe: UniverseDep
) -> FeaturesResponse:
    sym = _known_symbol(universe, symbol)
    features: SymbolFeatures | None = runtime.latest_features(sym)
    assessment: ShockAssessment | None = runtime.latest_assessment(sym)
    if features is None:
        return FeaturesResponse(
            symbol=sym,
            as_of=None,
            overall_status=FeatureStatus.UNAVAILABLE,
            market_benchmark=universe.market_benchmark,
            sector_benchmark=universe.sector_benchmark_for(sym),
            assessment=assessment,
        )
    return FeaturesResponse(**features.model_dump(), assessment=assessment)


@router.get("/shocks", response_model=ShocksResponse, responses={422: _ERRORS[422]})
async def market_shocks(
    repo: MarketEventRepoDep,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
) -> ShocksResponse:
    events = await repo.list_market_shocks(limit)
    return ShocksResponse(items=[Event.model_validate(e) for e in events])
