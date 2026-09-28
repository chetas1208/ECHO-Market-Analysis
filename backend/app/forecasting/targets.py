"""Target construction for cumulative abnormal returns.

Targets are only for training/evaluation. Feature builders never call this module during
realtime inference. A target uses subsequent available trading sessions, so weekends and
holidays are skipped naturally rather than treated as zero-return sessions.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import UTC, date, datetime

from app.forecasting.types import FORECAST_HORIZONS
from app.market.calendar import NY, MarketCalendar
from app.market.types import Bar


class TargetConstructionError(ValueError):
    """Raised when target inputs are incomplete or violate the information boundary."""


@dataclass(frozen=True)
class TargetPoint:
    horizon: str
    trading_days: int
    target_timestamp: datetime
    cumulative_abnormal_return: float


def _utc(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise TargetConstructionError("timestamps must be timezone-aware")
    return value.astimezone(UTC)


def _validate_bars(bars: list[Bar]) -> None:
    for bar in bars:
        _utc(bar.timestamp)
        if not math.isfinite(bar.close) or bar.close <= 0:
            raise TargetConstructionError("target bars must have finite positive closes")


def _session_closes(
    bars: list[Bar], *, after: datetime | None = None
) -> list[tuple[date, datetime, float]]:
    grouped: dict[date, tuple[datetime, float]] = {}
    after_utc = _utc(after) if after is not None else None
    for bar in sorted(bars, key=lambda item: (_utc(item.timestamp), item.source.value)):
        timestamp = _utc(bar.timestamp)
        if after_utc is not None and timestamp <= after_utc:
            continue
        session = timestamp.astimezone(NY).date()
        if not MarketCalendar().is_trading_day(session):
            continue
        existing = grouped.get(session)
        if existing is None or timestamp >= existing[0]:
            grouped[session] = (timestamp, float(bar.close))
    return [(day, timestamp, close) for day, (timestamp, close) in sorted(grouped.items())]


def _close_at_or_before(bars: list[Bar], timestamp: datetime) -> float | None:
    timestamp = _utc(timestamp)
    eligible = [bar for bar in bars if _utc(bar.timestamp) <= timestamp]
    if not eligible:
        return None
    return float(max(eligible, key=lambda item: _utc(item.timestamp)).close)


def _log_return(start: float | None, end: float | None) -> float | None:
    if start is None or end is None or start <= 0 or end <= 0:
        return None
    value = math.log(end / start)
    return value if math.isfinite(value) else None


def build_car_targets(
    *,
    asset_bars: list[Bar],
    market_bars: list[Bar],
    sector_bars: list[Bar],
    issuance_timestamp: datetime,
    data_cutoff_at: datetime,
    beta_market: float | None,
    beta_sector: float | None,
) -> dict[str, TargetPoint]:
    """Build CAR targets for 1D/2D/5D/10D/20D using future bars only.

    ``r_asset - beta_market*r_market - beta_sector*r_sector`` is accumulated from
    the issuance close to the close of the requested trading session. The caller must
    provide betas estimated from history strictly before issuance.
    """

    issuance = _utc(issuance_timestamp)
    cutoff = _utc(data_cutoff_at)
    if cutoff < issuance:
        raise TargetConstructionError("target cutoff cannot precede issuance")
    all_bars = [*asset_bars, *market_bars, *sector_bars]
    _validate_bars(all_bars)
    if beta_market is None or beta_sector is None:
        raise TargetConstructionError("market and sector betas are required for CAR targets")

    asset_start = _close_at_or_before(asset_bars, issuance)
    market_start = _close_at_or_before(market_bars, issuance)
    sector_start = _close_at_or_before(sector_bars, issuance)
    if asset_start is None or market_start is None or sector_start is None:
        raise TargetConstructionError("a pre-issuance close is required for CAR targets")

    asset_future = _session_closes(asset_bars, after=issuance)
    market_future = dict(
        (day, (timestamp, close))
        for day, timestamp, close in _session_closes(market_bars, after=issuance)
    )
    sector_future = dict(
        (day, (timestamp, close))
        for day, timestamp, close in _session_closes(sector_bars, after=issuance)
    )
    output: dict[str, TargetPoint] = {}
    for horizon, days in FORECAST_HORIZONS.items():
        if len(asset_future) < days:
            continue
        session, target_timestamp, asset_close = asset_future[days - 1]
        market_value = market_future.get(session)
        sector_value = sector_future.get(session)
        if market_value is None or sector_value is None:
            continue
        asset_return = _log_return(asset_start, asset_close)
        market_return = _log_return(market_start, market_value[1])
        sector_return = _log_return(sector_start, sector_value[1])
        if asset_return is None or market_return is None or sector_return is None:
            continue
        car = asset_return - beta_market * market_return - beta_sector * sector_return
        if math.isfinite(car):
            output[horizon] = TargetPoint(horizon, days, target_timestamp, car)
    return output


def future_session_timestamps(
    bars: list[Bar], issuance_timestamp: datetime, horizons: dict[str, int] | None = None
) -> dict[str, datetime]:
    """Resolve horizon timestamps from available trading sessions."""

    sessions = _session_closes(bars, after=issuance_timestamp)
    result: dict[str, datetime] = {}
    for horizon, days in (horizons or FORECAST_HORIZONS).items():
        if len(sessions) >= days:
            result[horizon] = sessions[days - 1][1]
    return result
