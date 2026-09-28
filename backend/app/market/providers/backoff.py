"""Exponential backoff with symmetric jitter for provider reconnects."""

from __future__ import annotations

import random
from collections.abc import Iterator

from app.market.settings import ReconnectConfig


def backoff_delays(cfg: ReconnectConfig, rng: random.Random | None = None) -> Iterator[float]:
    """Infinite delays: ``min(max, base * factor**n) * (1 + U(-jitter, +jitter))``.

    Result is clamped to ``[0, max_delay_s * (1 + jitter)]``. Deterministic for a seeded ``rng``.
    """
    rand = rng if rng is not None else random.Random()
    jitter = abs(cfg.jitter)
    ceiling = cfg.max_delay_s * (1.0 + jitter)
    raw = cfg.base_delay_s
    while True:
        base = min(cfg.max_delay_s, raw)
        delay = base * (1.0 + rand.uniform(-jitter, jitter))
        yield min(ceiling, max(0.0, delay))
        if raw < cfg.max_delay_s:  # stop growing once capped (avoids float overflow)
            raw *= cfg.factor


class Backoff:
    """Stateful wrapper: ``next()`` returns the next delay, ``reset()`` restarts the sequence."""

    def __init__(self, cfg: ReconnectConfig, rng: random.Random | None = None) -> None:
        self._cfg = cfg
        self._rng = rng
        self._it = backoff_delays(cfg, rng)

    def next(self) -> float:
        return next(self._it)

    def reset(self) -> None:
        self._it = backoff_delays(self._cfg, self._rng)
