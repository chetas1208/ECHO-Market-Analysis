from __future__ import annotations

from datetime import UTC, date, datetime, timedelta

import pytest

from app.market.calendar import (
    NY,
    NYSE_EARLY_CLOSES,
    NYSE_HOLIDAYS,
    MarketCalendar,
    Session,
)

CAL = MarketCalendar()


def utc(*a: int) -> datetime:
    return datetime(*a, tzinfo=UTC)


def _nth(y: int, m: int, wd: int, n: int) -> date:
    d = date(y, m, 1)
    d += timedelta((wd - d.weekday()) % 7)
    return d + timedelta(7 * (n - 1))


def _last(y: int, m: int, wd: int) -> date:
    d = date(y + (m == 12), m % 12 + 1, 1) - timedelta(1)
    return d - timedelta((d.weekday() - wd) % 7)


def _easter(y: int) -> date:  # anonymous Gregorian algorithm
    a, b, c = y % 19, y // 100, y % 100
    d, e = b // 4, b % 4
    f = (b + 8) // 25
    g = (b - f + 1) // 3
    h = (19 * a + b - d - g + 15) % 30
    i, k = c // 4, c % 4
    ell = (32 + 2 * e + 2 * i - h - k) % 7
    m = (a + 11 * h + 22 * ell) // 451
    month = (h + ell - 7 * m + 114) // 31
    return date(y, month, (h + ell - 7 * m + 114) % 31 + 1)


def _obs(d: date) -> date:
    if d.weekday() == 5:
        return d - timedelta(1)
    if d.weekday() == 6:
        return d + timedelta(1)
    return d


def _rule_holidays(y: int) -> set[date]:
    return {
        _obs(date(y, 1, 1)),
        _nth(y, 1, 0, 3),
        _nth(y, 2, 0, 3),
        _easter(y) - timedelta(2),
        _last(y, 5, 0),
        _obs(date(y, 6, 19)),
        _obs(date(y, 7, 4)),
        _nth(y, 9, 0, 1),
        _nth(y, 11, 3, 4),
        _obs(date(y, 12, 25)),
    }


@pytest.mark.parametrize("year", [2025, 2026, 2027])
def test_embedded_holidays_match_rules(year: int) -> None:
    assert {h for h in NYSE_HOLIDAYS if h.year == year} == _rule_holidays(year)


def test_known_holiday_dates() -> None:
    assert date(2026, 4, 3) in NYSE_HOLIDAYS  # Good Friday 2026
    assert date(2026, 7, 3) in NYSE_HOLIDAYS  # July 4 on Saturday -> Friday
    assert date(2027, 6, 18) in NYSE_HOLIDAYS
    assert date(2027, 12, 24) in NYSE_HOLIDAYS


def test_early_closes_are_trading_days_and_expected() -> None:
    assert {
        date(2025, 7, 3),
        date(2025, 11, 28),
        date(2025, 12, 24),
        date(2026, 11, 27),
        date(2026, 12, 24),
        date(2027, 11, 26),
    } == NYSE_EARLY_CLOSES
    for d in NYSE_EARLY_CLOSES:
        assert CAL.is_trading_day(d)
        assert d.weekday() < 5


def test_session_boundaries_summer_edt() -> None:
    d = (2025, 7, 1)  # Tuesday, EDT (UTC-4)
    assert CAL.session_at(utc(*d, 7, 59)) is Session.CLOSED  # 03:59 ET
    assert CAL.session_at(utc(*d, 8, 0)) is Session.PREMARKET  # 04:00 ET
    assert CAL.session_at(utc(*d, 13, 29)) is Session.PREMARKET
    assert CAL.session_at(utc(*d, 13, 30)) is Session.REGULAR
    assert CAL.session_at(utc(*d, 19, 59)) is Session.REGULAR
    assert CAL.session_at(utc(*d, 20, 0)) is Session.AFTERHOURS
    assert CAL.session_at(utc(*d, 23, 59)) is Session.AFTERHOURS
    assert CAL.session_at(utc(2025, 7, 2, 0, 0)) is Session.CLOSED  # 20:00 ET


def test_accepts_non_utc_aware_input() -> None:
    ts = datetime(2025, 7, 1, 9, 30, tzinfo=NY)
    assert CAL.session_at(ts) is Session.REGULAR
    assert CAL.is_regular(ts) and CAL.expected_active(ts)


def test_weekend_closed() -> None:
    assert CAL.session_at(utc(2025, 7, 5, 15, 0)) is Session.CLOSED  # Saturday
    assert CAL.session_at(utc(2025, 7, 6, 15, 0)) is Session.CLOSED
    assert CAL.session_bounds(date(2025, 7, 5)) is None
    assert not CAL.is_trading_day(date(2025, 7, 6))


def test_holiday_closed_all_day() -> None:
    for h in (utc(2025, 12, 25, 15, 0), utc(2026, 4, 3, 15, 0), utc(2026, 7, 3, 15, 0)):
        assert CAL.session_at(h) is Session.CLOSED
        assert not CAL.expected_active(h)
    assert CAL.session_bounds(date(2025, 12, 25)) is None
    assert not CAL.is_trading_day(date(2026, 7, 3))


def test_dst_open_utc_march_and_november() -> None:
    # US DST starts 2026-03-08: Fri Mar 6 EST (14:30Z), Mon Mar 9 EDT (13:30Z)
    assert CAL.session_bounds(date(2026, 3, 6)) == (utc(2026, 3, 6, 14, 30), utc(2026, 3, 6, 21, 0))
    assert CAL.session_bounds(date(2026, 3, 9)) == (utc(2026, 3, 9, 13, 30), utc(2026, 3, 9, 20, 0))
    # DST ends 2026-11-01: Fri Oct 30 EDT, Mon Nov 2 EST
    assert CAL.session_bounds(date(2026, 10, 30))[0] == utc(2026, 10, 30, 13, 30)
    assert CAL.session_bounds(date(2026, 11, 2)) == (
        utc(2026, 11, 2, 14, 30),
        utc(2026, 11, 2, 21, 0),
    )
    # session_at follows the same offsets
    assert CAL.session_at(utc(2026, 3, 9, 13, 30)) is Session.REGULAR
    assert CAL.session_at(utc(2026, 3, 6, 13, 30)) is Session.PREMARKET
    assert CAL.session_at(utc(2026, 11, 2, 14, 29)) is Session.PREMARKET
    assert CAL.session_at(utc(2026, 11, 2, 14, 30)) is Session.REGULAR


def test_half_day_close_1300_et() -> None:
    # Day after Thanksgiving 2025 (EST, UTC-5): close 13:00 ET = 18:00Z
    assert CAL.session_bounds(date(2025, 11, 28)) == (
        utc(2025, 11, 28, 14, 30),
        utc(2025, 11, 28, 18, 0),
    )
    assert CAL.session_at(utc(2025, 11, 28, 17, 59)) is Session.REGULAR
    assert CAL.session_at(utc(2025, 11, 28, 18, 0)) is Session.AFTERHOURS
    assert not CAL.expected_active(utc(2025, 11, 28, 19, 0))
    # July 3 2025 (EDT): close 17:00Z
    assert CAL.session_bounds(date(2025, 7, 3))[1] == utc(2025, 7, 3, 17, 0)
    # Normal day is 16:00 ET
    assert CAL.session_bounds(date(2025, 11, 26))[1] == utc(2025, 11, 26, 21, 0)


def test_minutes_since_open() -> None:
    assert CAL.minutes_since_open(utc(2025, 7, 1, 13, 30)) == 0
    assert CAL.minutes_since_open(utc(2025, 7, 1, 13, 30, 59)) == 0
    assert CAL.minutes_since_open(utc(2025, 7, 1, 14, 45)) == 75
    assert CAL.minutes_since_open(utc(2025, 7, 1, 19, 59)) == 389
    assert CAL.minutes_since_open(utc(2025, 7, 1, 13, 29)) is None  # premarket
    assert CAL.minutes_since_open(utc(2025, 7, 1, 20, 0)) is None  # afterhours
    assert CAL.minutes_since_open(utc(2025, 7, 5, 15, 0)) is None  # weekend
    # winter: 09:30 ET = 14:30Z
    assert CAL.minutes_since_open(utc(2026, 1, 6, 14, 31)) == 1


def test_next_open_across_weekend_and_holiday() -> None:
    # Friday after close -> Monday open (Jul 7 2025, EDT)
    assert CAL.next_open(utc(2025, 7, 4, 22, 0)) == utc(2025, 7, 7, 13, 30)
    # Fri Jan 16 2026 evening; Mon Jan 19 is MLK -> Tue Jan 20 14:30Z
    assert CAL.next_open(utc(2026, 1, 16, 23, 0)) == utc(2026, 1, 20, 14, 30)
    # Before today's open -> today's open
    assert CAL.next_open(utc(2025, 7, 1, 10, 0)) == utc(2025, 7, 1, 13, 30)
    # Exactly at open -> the next one (strictly after)
    assert CAL.next_open(utc(2025, 7, 1, 13, 30)) == utc(2025, 7, 2, 13, 30)
    # Mid-session -> next day
    assert CAL.next_open(utc(2025, 7, 1, 15, 0)) == utc(2025, 7, 2, 13, 30)
    # Across DST start: Fri Mar 6 2026 close -> Mon Mar 9 13:30Z
    assert CAL.next_open(utc(2026, 3, 6, 22, 0)) == utc(2026, 3, 9, 13, 30)
    # Result is UTC-aware
    assert CAL.next_open(utc(2025, 7, 5, 0, 0)).utcoffset() == timedelta(0)


def test_naive_datetime_raises() -> None:
    naive = datetime(2025, 7, 1, 14, 0)
    for fn in (
        CAL.session_at,
        CAL.is_regular,
        CAL.expected_active,
        CAL.minutes_since_open,
        CAL.next_open,
    ):
        with pytest.raises(ValueError):
            fn(naive)
