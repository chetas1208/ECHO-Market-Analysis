import random
from itertools import islice

from app.market.providers.backoff import Backoff, backoff_delays
from app.market.settings import ReconnectConfig


def _cfg(**kw) -> ReconnectConfig:
    return ReconnectConfig(**{"jitter": 0.0, **kw})


def test_growth_zero_jitter_exact():
    cfg = _cfg(base_delay_s=1.0, max_delay_s=60.0, factor=2.0)
    assert list(islice(backoff_delays(cfg), 6)) == [1.0, 2.0, 4.0, 8.0, 16.0, 32.0]


def test_cap_and_no_overflow():
    cfg = _cfg(base_delay_s=1.0, max_delay_s=60.0, factor=2.0)
    vals = list(islice(backoff_delays(cfg), 5000))
    assert vals[6:] == [60.0] * (5000 - 6)


def test_jitter_bounds_1000_draws():
    cfg = ReconnectConfig(base_delay_s=1.0, max_delay_s=60.0, factor=2.0, jitter=0.3)
    rng = random.Random(1)
    for n, d in enumerate(islice(backoff_delays(cfg, rng), 1000)):
        base = min(60.0, 1.0 * 2.0**n) if n < 100 else 60.0
        assert d >= 0.0
        assert base * 0.7 - 1e-9 <= d <= base * 1.3 + 1e-9
        assert d <= 60.0 * 1.3 + 1e-9


def test_jitter_actually_varies():
    cfg = ReconnectConfig(jitter=0.3)
    vals = list(islice(backoff_delays(cfg, random.Random(2)), 50))
    assert len(set(vals[-20:])) > 1


def test_deterministic_with_seed():
    cfg = ReconnectConfig(jitter=0.3)
    a = list(islice(backoff_delays(cfg, random.Random(42)), 30))
    b = list(islice(backoff_delays(cfg, random.Random(42)), 30))
    c = list(islice(backoff_delays(cfg, random.Random(43)), 30))
    assert a == b
    assert a != c


def test_never_negative_with_large_jitter():
    cfg = ReconnectConfig(jitter=5.0)
    assert all(d >= 0.0 for d in islice(backoff_delays(cfg, random.Random(3)), 1000))


def test_reset_restarts_sequence():
    b = Backoff(_cfg(base_delay_s=1.0, factor=2.0))
    assert [b.next(), b.next(), b.next()] == [1.0, 2.0, 4.0]
    b.reset()
    assert [b.next(), b.next()] == [1.0, 2.0]


def test_backoff_class_matches_generator_with_seed():
    cfg = ReconnectConfig(jitter=0.3)
    b = Backoff(cfg, random.Random(7))
    exp = list(islice(backoff_delays(cfg, random.Random(7)), 10))
    assert [b.next() for _ in range(10)] == exp
