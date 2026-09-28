"""Deterministic replay scenarios for the market pipeline (no network, no wall clock).

Universe: NVDA, AMD (equities), SOXX (sector benchmark), SPY (market benchmark).
Sessions: 6 PRIOR regular sessions (2026-09-08 .. 2026-09-15, Labor Day 09-07 skipped) followed by
a 7th "shock day" (2026-09-16). All 7 days are generated from one ``random.Random(1234)`` stream, so
``build_shock_scenario()`` is bit-identical to ``build_normal_scenario()`` except for the injected
NVDA move (SOXX / SPY / AMD are untouched and later NVDA bars continue from the shocked level).

Each session is 390 one-minute bars, 09:30-16:00 ET = 13:30Z-20:00Z (EDT). Prior sessions give the
time-of-day volume baseline its >=5 sessions. Volume follows a U-shaped seasonality
(open/close ~4x midday) with lognormal noise. Returns are log returns:
``spy ~ N(0, 4e-4)``, ``soxx = 1.2*spy + N(0, 4e-4)``, ``stock = 1.0*soxx + N(0, 5e-4)`` (~8e-4).

Shock: NVDA's ``shock_bars`` (5) consecutive 1m bars starting at minute ``shock_at_minute`` of the
shock day sum to exactly ``ln(1 + magnitude)`` (log return), with volume x``volume_multiple``.
``expected_shock_at`` is the START timestamp of the 5th such bar, i.e. the first 1m bar at which
the 5-bar return is complete.
"""

from __future__ import annotations

import math
import random
from datetime import UTC, date, datetime, timedelta

from pydantic import BaseModel

from app.market.types import Bar, Interval, ProviderName

SEED = 1234
SESSION_MINUTES = 390
SHOCK_BARS = 5
SHOCK_SYMBOL = "NVDA"
UNIVERSE_SYMBOLS: list[str] = ["NVDA", "AMD", "SOXX", "SPY"]

PRIOR_SESSION_DATES: list[date] = [
    date(2026, 9, 8),
    date(2026, 9, 9),
    date(2026, 9, 10),
    date(2026, 9, 11),
    date(2026, 9, 14),
    date(2026, 9, 15),
]
SHOCK_DAY: date = date(2026, 9, 16)

_OPEN_UTC = (13, 30)  # 09:30 EDT
_START_PRICE = {"NVDA": 180.0, "AMD": 160.0, "SOXX": 300.0, "SPY": 650.0}
_BASE_VOLUME = {"NVDA": 60_000.0, "AMD": 35_000.0, "SOXX": 9_000.0, "SPY": 80_000.0}
_SPY_VOL = 0.0004
_SOXX_BETA, _SOXX_IDIO = 1.2, 0.0004
_STOCK_BETA, _STOCK_IDIO = 1.0, 0.0005
_GAP_SIGMA = {"NVDA": 0.002, "AMD": 0.002, "SOXX": 0.0015, "SPY": 0.001}
_VOLUME_NOISE_SIGMA = 0.25
_SHOCK_NOISE_SIGMA = 0.0003
_AFTERMATH_BARS = 10
_ORDER = sorted(UNIVERSE_SYMBOLS)  # per-minute emission order => (timestamp, symbol) ordering


class ShockScenario(BaseModel):
    bars: list[Bar]
    shock_symbol: str
    expected_shock_at: datetime | None  # None for the normal (no-shock) scenario
    universe_symbols: list[str]
    description: str = ""


def _session_open(d: date) -> datetime:
    return datetime(d.year, d.month, d.day, _OPEN_UTC[0], _OPEN_UTC[1], tzinfo=UTC)


def _seasonality(minute: int) -> float:
    """U-shaped volume multiplier: 4.0 at open/close, ~1.0 midday."""
    return 1.0 + 3.0 * (math.exp(-minute / 30.0) + math.exp(-(SESSION_MINUTES - 1 - minute) / 30.0))


def _generate(
    *,
    shock_at_minute: int | None,
    magnitude: float,
    volume_multiple: float,
) -> list[Bar]:
    rng = random.Random(SEED)
    shock_rng = random.Random(SEED + 1)  # separate stream: keeps the main draws aligned
    shock_ret: list[float] = []
    if shock_at_minute is not None:
        target = math.log1p(magnitude)
        noise = [shock_rng.gauss(0.0, _SHOCK_NOISE_SIGMA) for _ in range(SHOCK_BARS)]
        mean = sum(noise) / SHOCK_BARS
        shock_ret = [target / SHOCK_BARS + (n - mean) for n in noise]

    price = dict(_START_PRICE)
    bars: list[Bar] = []
    days = [*PRIOR_SESSION_DATES, SHOCK_DAY]
    vol_mu = -(_VOLUME_NOISE_SIGMA**2) / 2.0  # lognormal with mean 1

    for day in days:
        is_shock_day = day == SHOCK_DAY and shock_at_minute is not None
        open_ts = _session_open(day)
        gaps = {s: rng.gauss(0.0, _GAP_SIGMA[s]) for s in _ORDER}
        for minute in range(SESSION_MINUTES):
            ts = open_ts + timedelta(minutes=minute)
            spy_r = rng.gauss(0.0, _SPY_VOL)
            soxx_r = _SOXX_BETA * spy_r + rng.gauss(0.0, _SOXX_IDIO)
            nvda_r = _STOCK_BETA * soxx_r + rng.gauss(0.0, _STOCK_IDIO)
            amd_r = _STOCK_BETA * soxx_r + rng.gauss(0.0, _STOCK_IDIO)
            rets = {"SPY": spy_r, "SOXX": soxx_r, "NVDA": nvda_r, "AMD": amd_r}
            vol_mult = dict.fromkeys(_ORDER, 1.0)
            if is_shock_day:
                assert shock_at_minute is not None
                k = minute - shock_at_minute
                if 0 <= k < SHOCK_BARS:
                    rets[SHOCK_SYMBOL] = shock_ret[k]
                    vol_mult[SHOCK_SYMBOL] = volume_multiple
                elif SHOCK_BARS <= k < SHOCK_BARS + _AFTERMATH_BARS:
                    decay = 1.0 - (k - SHOCK_BARS) / _AFTERMATH_BARS
                    vol_mult[SHOCK_SYMBOL] = 1.0 + 2.0 * decay
            for sym in _ORDER:
                vol_noise = math.exp(rng.gauss(vol_mu, _VOLUME_NOISE_SIGMA))
                wick_hi, wick_lo = rng.random(), rng.random()
                o = price[sym] * math.exp(gaps[sym]) if minute == 0 else price[sym]
                c = o * math.exp(rets[sym])
                wick = abs(rets[sym]) * 0.5 + 0.0002
                h = max(o, c) * (1.0 + wick * wick_hi)
                lo = min(o, c) * (1.0 - wick * wick_lo)
                volume = float(
                    round(_BASE_VOLUME[sym] * _seasonality(minute) * vol_noise * vol_mult[sym])
                )
                bars.append(
                    Bar(
                        symbol=sym,
                        timestamp=ts,
                        interval=Interval.M1,
                        open=o,
                        high=h,
                        low=lo,
                        close=c,
                        volume=volume,
                        vwap=(o + h + lo + c) / 4.0,
                        trade_count=int(volume // 80),
                        source=ProviderName.REPLAY,
                    )
                )
                price[sym] = c
    return bars


def build_normal_scenario() -> ShockScenario:
    """7 sessions of normal 1m bars for every symbol; no abnormal move anywhere."""
    bars = _generate(shock_at_minute=None, magnitude=0.0, volume_multiple=1.0)
    return ShockScenario(
        bars=bars,
        shock_symbol=SHOCK_SYMBOL,
        expected_shock_at=None,
        universe_symbols=list(UNIVERSE_SYMBOLS),
        description="Normal replay: 6 prior sessions + 1 normal session, no shock.",
    )


def build_shock_scenario(
    shock_at_minute: int = 150,
    magnitude: float = -0.045,
    volume_multiple: float = 8.0,
) -> ShockScenario:
    """Normal scenario plus a NVDA-only abnormal move on the 7th session.

    ``shock_at_minute`` = minute-of-session (0 = 09:30 ET) of the FIRST shocked bar; the move
    spans 5 consecutive 1m bars and sums to ``ln(1 + magnitude)``.
    """
    if not 1 <= shock_at_minute <= SESSION_MINUTES - SHOCK_BARS:
        raise ValueError(f"shock_at_minute must be in [1, {SESSION_MINUTES - SHOCK_BARS}]")
    if not -1.0 < magnitude < 1.0 or magnitude == 0.0:
        raise ValueError("magnitude must be a non-zero simple return in (-1, 1)")
    if volume_multiple < 1.0:
        raise ValueError("volume_multiple must be >= 1")
    bars = _generate(
        shock_at_minute=shock_at_minute, magnitude=magnitude, volume_multiple=volume_multiple
    )
    expected = _session_open(SHOCK_DAY) + timedelta(minutes=shock_at_minute + SHOCK_BARS - 1)
    return ShockScenario(
        bars=bars,
        shock_symbol=SHOCK_SYMBOL,
        expected_shock_at=expected,
        universe_symbols=list(UNIVERSE_SYMBOLS),
        description=(
            f"{SHOCK_SYMBOL} {magnitude:+.1%} over {SHOCK_BARS} 1m bars on volume x"
            f"{volume_multiple:g} at minute {shock_at_minute} of {SHOCK_DAY}; "
            "SOXX/SPY/AMD unaffected."
        ),
    )
