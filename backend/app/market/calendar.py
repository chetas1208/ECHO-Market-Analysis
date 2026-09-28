"""NYSE trading calendar (America/New_York, DST-safe via zoneinfo).

Holidays and early closes are embedded for 2025-2027 (NYSE published schedule /
rules: weekend holidays are observed Fri/Mon, except that none is observed for a
Saturday Jan 1). Dates outside the embedded years are treated as plain weekdays
with regular hours (no holiday knowledge) -- ``covers_year`` reports coverage.

Sessions (ET): PREMARKET 04:00-09:30, REGULAR 09:30-16:00 (13:00 on early-close
days), AFTERHOURS from the close until 20:00, otherwise CLOSED. Weekends and full
holidays are CLOSED all day.
"""

from __future__ import annotations

from datetime import UTC, date, datetime, time, timedelta
from enum import StrEnum
from zoneinfo import ZoneInfo

NY = ZoneInfo("America/New_York")

PREMARKET_START = time(4, 0)
REGULAR_OPEN = time(9, 30)
REGULAR_CLOSE = time(16, 0)
EARLY_CLOSE = time(13, 0)
AFTERHOURS_END = time(20, 0)

# Full-day closures.
NYSE_HOLIDAYS: frozenset[date] = frozenset(
    {
        # 2025
        date(2025, 1, 1),  # New Year's Day
        date(2025, 1, 20),  # Martin Luther King Jr. Day
        date(2025, 2, 17),  # Presidents' Day
        date(2025, 4, 18),  # Good Friday
        date(2025, 5, 26),  # Memorial Day
        date(2025, 6, 19),  # Juneteenth
        date(2025, 7, 4),  # Independence Day
        date(2025, 9, 1),  # Labor Day
        date(2025, 11, 27),  # Thanksgiving
        date(2025, 12, 25),  # Christmas
        # 2026
        date(2026, 1, 1),
        date(2026, 1, 19),
        date(2026, 2, 16),
        date(2026, 4, 3),
        date(2026, 5, 25),
        date(2026, 6, 19),
        date(2026, 7, 3),  # Independence Day observed (Jul 4 is Saturday)
        date(2026, 9, 7),
        date(2026, 11, 26),
        date(2026, 12, 25),
        # 2027
        date(2027, 1, 1),
        date(2027, 1, 18),
        date(2027, 2, 15),
        date(2027, 3, 26),
        date(2027, 5, 31),
        date(2027, 6, 18),  # Juneteenth observed (Jun 19 is Saturday)
        date(2027, 7, 5),  # Independence Day observed (Jul 4 is Sunday)
        date(2027, 9, 6),
        date(2027, 11, 25),
        date(2027, 12, 24),  # Christmas observed (Dec 25 is Saturday)
    }
)

# 13:00 ET closes.
NYSE_EARLY_CLOSES: frozenset[date] = frozenset(
    {
        date(2025, 7, 3),
        date(2025, 11, 28),  # day after Thanksgiving
        date(2025, 12, 24),
        date(2026, 11, 27),
        date(2026, 12, 24),
        date(2027, 11, 26),
    }
)

COVERED_YEARS = frozenset({2025, 2026, 2027})


class Session(StrEnum):
    CLOSED = "CLOSED"
    PREMARKET = "PREMARKET"
    REGULAR = "REGULAR"
    AFTERHOURS = "AFTERHOURS"


def _et(ts: datetime) -> datetime:
    if ts.tzinfo is None or ts.utcoffset() is None:
        raise ValueError("timestamp must be timezone-aware")
    return ts.astimezone(NY)


def _local(d: date, t: time) -> datetime:
    """Aware ET datetime for date+time (zoneinfo resolves the DST offset)."""
    return datetime.combine(d, t, tzinfo=NY)


class MarketCalendar:
    """NYSE calendar. Stateless; all inputs must be tz-aware (naive -> ValueError)."""

    def covers_year(self, year: int) -> bool:
        return year in COVERED_YEARS

    def is_trading_day(self, d: date) -> bool:
        return d.weekday() < 5 and d not in NYSE_HOLIDAYS

    def is_early_close(self, d: date) -> bool:
        return self.is_trading_day(d) and d in NYSE_EARLY_CLOSES

    def _close_time(self, d: date) -> time:
        return EARLY_CLOSE if d in NYSE_EARLY_CLOSES else REGULAR_CLOSE

    def session_bounds(self, d: date) -> tuple[datetime, datetime] | None:
        """UTC (open, close) of the regular session, or None on holiday/weekend."""
        if not self.is_trading_day(d):
            return None
        open_ = _local(d, REGULAR_OPEN).astimezone(UTC)
        close = _local(d, self._close_time(d)).astimezone(UTC)
        return open_, close

    def session_at(self, ts: datetime) -> Session:
        local = _et(ts)
        d = local.date()
        if not self.is_trading_day(d):
            return Session.CLOSED
        t = local.time()
        if t < PREMARKET_START or t >= AFTERHOURS_END:
            return Session.CLOSED
        if t < REGULAR_OPEN:
            return Session.PREMARKET
        if t < self._close_time(d):
            return Session.REGULAR
        return Session.AFTERHOURS

    def is_regular(self, ts: datetime) -> bool:
        return self.session_at(ts) is Session.REGULAR

    def expected_active(self, ts: datetime) -> bool:
        """True when market data is expected to be flowing (regular session only)."""
        return self.is_regular(ts)

    def minutes_since_open(self, ts: datetime) -> int | None:
        """Whole minutes since the regular open; None outside the regular session."""
        if not self.is_regular(ts):
            return None
        bounds = self.session_bounds(_et(ts).date())
        assert bounds is not None
        return int((ts.astimezone(UTC) - bounds[0]).total_seconds() // 60)

    def next_open(self, ts: datetime) -> datetime:
        """First regular-session open strictly after ``ts`` (UTC)."""
        now_utc = _et(ts).astimezone(UTC)
        d = _et(ts).date()
        for _ in range(15):  # longest run of closed days is far below this
            bounds = self.session_bounds(d)
            if bounds is not None and bounds[0] > now_utc:
                return bounds[0]
            d += timedelta(days=1)
        raise RuntimeError("no trading day found")  # pragma: no cover
