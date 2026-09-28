"""Serializable event/market cases used by the historical replay engine."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from app.forecasting.simulator import SimulationPoint
from app.market.types import Bar, Interval, ProviderName


def _utc(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("case timestamps must be timezone-aware")
    return value.astimezone(UTC)


@dataclass(frozen=True)
class BacktestCase:
    event_id: str
    event_group: str
    event_class: str
    symbol: str
    sector: str
    event_timestamp: datetime
    data_cutoff_at: datetime
    decision_timestamp: datetime
    graph_exposure: float | None
    graph_confidence: float | None
    event_confidence: float | None
    cause_score: float | None
    cause_direction: float | None
    observed_residual: float | None
    residual_z: float | None
    sector_residual_z: float | None
    volume_z: float | None
    response_state: str | None
    forecast: SimulationPoint
    bars: tuple[Bar, ...] = field(default_factory=tuple)
    hedge_bars: tuple[Bar, ...] = field(default_factory=tuple)
    market_fresh: bool = True
    already_priced: bool | None = None

    def __post_init__(self) -> None:
        event = _utc(self.event_timestamp)
        cutoff = _utc(self.data_cutoff_at)
        decision = _utc(self.decision_timestamp)
        if cutoff > decision or event > cutoff:
            raise ValueError("event and cutoff must be available before the decision")
        if _utc(self.forecast.target_timestamp) <= decision:
            raise ValueError("forecast target must be after the decision")
        if not self.event_id.strip() or not self.symbol.strip():
            raise ValueError("event_id and symbol are required")
        for bar in (*self.bars, *self.hedge_bars):
            if _utc(bar.timestamp) <= decision:
                raise ValueError("bars used for execution must be strictly after decision")

    @property
    def case_key(self) -> str:
        return f"{self.event_id}:{self.symbol.upper()}:{_utc(self.decision_timestamp).isoformat()}"

    def as_dict(self) -> dict[str, Any]:
        return {
            "event_id": self.event_id,
            "event_group": self.event_group,
            "event_class": self.event_class,
            "symbol": self.symbol.upper(),
            "sector": self.sector,
            "event_timestamp": _utc(self.event_timestamp).isoformat(),
            "data_cutoff_at": _utc(self.data_cutoff_at).isoformat(),
            "decision_timestamp": _utc(self.decision_timestamp).isoformat(),
            "graph_exposure": self.graph_exposure,
            "graph_confidence": self.graph_confidence,
            "event_confidence": self.event_confidence,
            "cause_score": self.cause_score,
            "cause_direction": self.cause_direction,
            "observed_residual": self.observed_residual,
            "residual_z": self.residual_z,
            "sector_residual_z": self.sector_residual_z,
            "volume_z": self.volume_z,
            "response_state": self.response_state,
            "forecast": self.forecast.__dict__,
            "market_fresh": self.market_fresh,
            "already_priced": self.already_priced,
            "bars": [bar.model_dump(mode="json") for bar in self.bars],
        }


@dataclass(frozen=True)
class CaseSplit:
    train: tuple[BacktestCase, ...]
    validation: tuple[BacktestCase, ...]
    test: tuple[BacktestCase, ...]
    diagnostics: dict[str, Any]


def chronological_case_split(
    cases: list[BacktestCase], *, train_fraction: float = 0.6, validation_fraction: float = 0.2
) -> CaseSplit:
    """Split complete event groups in time order; random splitting is impossible here."""

    if not cases:
        raise ValueError("cases cannot be empty")
    if not 0 < train_fraction < 1 or not 0 <= validation_fraction < 1:
        raise ValueError("split fractions are invalid")
    if train_fraction + validation_fraction >= 1:
        raise ValueError("split must leave a test period")
    groups: dict[str, datetime] = {}
    for case in cases:
        groups[case.event_group] = min(
            groups.get(case.event_group, _utc(case.event_timestamp)),
            _utc(case.event_timestamp),
        )
    ordered_groups = [
        name for name, _ in sorted(groups.items(), key=lambda item: (item[1], item[0]))
    ]
    count = len(ordered_groups)
    train_end = max(1, min(count - 2 if count >= 3 else count, int(count * train_fraction)))
    validation_end = max(train_end, min(count - 1, train_end + int(count * validation_fraction)))
    train_groups = set(ordered_groups[:train_end])
    validation_groups = set(ordered_groups[train_end:validation_end])
    test_groups = set(ordered_groups[validation_end:])
    if count >= 3 and (not validation_groups or not test_groups):
        train_groups = set(ordered_groups[:-2])
        validation_groups = {ordered_groups[-2]}
        test_groups = {ordered_groups[-1]}
    train = tuple(case for case in cases if case.event_group in train_groups)
    validation = tuple(case for case in cases if case.event_group in validation_groups)
    test = tuple(case for case in cases if case.event_group in test_groups)
    return CaseSplit(
        train=train,
        validation=validation,
        test=test,
        diagnostics={
            "event_groups": count,
            "chronological": True,
            "train_groups": sorted(train_groups),
            "validation_groups": sorted(validation_groups),
            "test_groups": sorted(test_groups),
        },
    )


def dataset_hash(cases: list[BacktestCase]) -> str:
    encoded = json.dumps(
        [case.as_dict() for case in sorted(cases, key=lambda item: item.case_key)],
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    ).encode()
    return hashlib.sha256(encoded).hexdigest()


def parse_bar(value: dict[str, Any]) -> Bar:
    return Bar(
        symbol=str(value["symbol"]),
        timestamp=datetime.fromisoformat(str(value["timestamp"])),
        interval=Interval(value.get("interval", "1m")),
        open=float(value["open"]),
        high=float(value["high"]),
        low=float(value["low"]),
        close=float(value["close"]),
        volume=float(value.get("volume", 0)),
        source=ProviderName(value.get("source", "replay")),
        vwap=value.get("vwap"),
        trade_count=value.get("trade_count"),
    )


def load_jsonl(path: Path) -> list[BacktestCase]:
    """Load only explicit cases; no hidden future joins or silent row dropping."""
    cases: list[BacktestCase] = []
    for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip():
            continue
        try:
            value = json.loads(line)
            forecast = SimulationPoint(**value["forecast"])
            cases.append(
                BacktestCase(
                    **{
                        **value,
                        "forecast": forecast,
                        "bars": tuple(parse_bar(item) for item in value.get("bars", [])),
                        "hedge_bars": tuple(
                            parse_bar(item) for item in value.get("hedge_bars", [])
                        ),
                    }
                )
            )
        except (KeyError, TypeError, ValueError) as exc:
            raise ValueError(f"invalid backtest dataset line {line_number}: {exc}") from exc
    if not cases:
        raise ValueError("backtest dataset is empty")
    return cases


def fixture_cases() -> list[BacktestCase]:
    """Small deterministic smoke dataset; never a production performance claim."""
    start = datetime(2025, 1, 2, 14, 30, tzinfo=UTC)
    cases: list[BacktestCase] = []
    for index in range(18):
        timestamp = start + timedelta(days=index)
        direction = 1.0 if index % 3 else -1.0
        outcome_direction = -direction if index % 6 == 0 else direction
        symbol = "NVDA" if index % 2 else "AMD"
        price = 100.0 + index
        open_price = price + outcome_direction * 0.1
        close_price = price + outcome_direction * 1.0
        bars = tuple(
            [
                Bar(
                    symbol=symbol,
                    timestamp=timestamp + timedelta(minutes=1 + minute),
                    interval=Interval.M1,
                    open=open_price,
                    high=max(open_price, close_price) + 0.2,
                    low=min(open_price, close_price) - 0.2,
                    close=close_price,
                    volume=1000,
                    source=ProviderName.REPLAY,
                )
                for minute in range(5)
            ]
            + [
                Bar(
                    symbol=symbol,
                    timestamp=timestamp + timedelta(days=1),
                    interval=Interval.M1,
                    open=open_price,
                    high=max(open_price, close_price) + 0.2,
                    low=min(open_price, close_price) - 0.2,
                    close=close_price,
                    volume=1000,
                    source=ProviderName.REPLAY,
                )
            ]
        )
        cases.append(
            BacktestCase(
                event_id=f"fixture_{index:03d}",
                event_group=f"fixture_{index:03d}",
                event_class="EARNINGS",
                symbol=symbol,
                sector="technology",
                event_timestamp=timestamp,
                data_cutoff_at=timestamp,
                decision_timestamp=timestamp,
                graph_exposure=0.65 * direction,
                graph_confidence=0.80,
                event_confidence=0.85,
                cause_score=0.75,
                cause_direction=direction,
                observed_residual=0.001 * direction,
                residual_z=0.4 * direction,
                sector_residual_z=0.3 * direction,
                volume_z=1.5,
                response_state="CONFIRMED",
                forecast=SimulationPoint(
                    horizon="1D",
                    target_timestamp=timestamp + timedelta(days=1),
                    q10=-0.012 if direction < 0 else -0.004,
                    q50=0.012 * direction,
                    q90=0.024 if direction > 0 else 0.004,
                    probability_positive=0.72 if direction > 0 else 0.28,
                    risk=0.01,
                ),
                bars=bars,
            )
        )
    return cases
