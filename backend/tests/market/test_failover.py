from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from app.market.providers.failover import BarDeduper, FailoverSelector
from app.market.types import (
    Bar,
    DataMode,
    Interval,
    ProviderHealth,
    ProviderName,
    ProviderState,
)

P, F = ProviderName.MASSIVE, ProviderName.ALPACA
T0 = datetime(2025, 3, 3, 15, 0, tzinfo=UTC)


def h(name: ProviderName, state: ProviderState) -> ProviderHealth:
    return ProviderHealth(provider=name, state=state, configured=True, mode=DataMode.LIVE)


def snap(p: ProviderState, f: ProviderState | None = ProviderState.CONNECTED):
    out = {P: h(P, p)}
    if f is not None:
        out[F] = h(F, f)
    return out


C, D, S = ProviderState.CONNECTED, ProviderState.DEGRADED, ProviderState.STALE
R, U = ProviderState.RECONNECTING, ProviderState.UNCONFIGURED


def bar(sym="NVDA", ts=T0, source=P, interval=Interval.M1) -> Bar:
    return Bar(
        symbol=sym, timestamp=ts, interval=interval, open=1, high=1, low=1, close=1,
        volume=1, source=source,
    )  # fmt: skip


def test_primary_healthy_stays_primary():
    s = FailoverSelector(P, F)
    for _ in range(5):
        assert s.update(snap(C)) == P
    assert s.switches == 0 and s.reason == "primary healthy"


@pytest.mark.parametrize("bad", [D, S, R, U, ProviderState.DISCONNECTED])
def test_fail_over_when_primary_unhealthy(bad):
    s = FailoverSelector(P, F)
    assert s.update(snap(bad)) == F
    assert s.switches == 1 and "fallback" in s.reason


def test_neither_healthy_stays_on_primary():
    s = FailoverSelector(P, F)
    assert s.update(snap(S, S)) == P
    assert s.switches == 0 and "no healthy fallback" in s.reason
    # missing fallback health entry counts as unhealthy
    assert s.update({P: h(P, R)}) == P


def test_no_flapping_before_recovery_threshold():
    s = FailoverSelector(P, F, recover_after_healthy_updates=3)
    s.update(snap(S))
    assert s.active == F
    # primary flaps healthy/unhealthy: streak resets, never switches back
    for state in (C, C, S, C, C, D, C):
        assert s.update(snap(state)) == F
    assert s.switches == 1


def test_recover_after_n_consecutive_healthy():
    s = FailoverSelector(P, F, recover_after_healthy_updates=3)
    s.update(snap(S))
    assert s.update(snap(C)) == F
    assert s.update(snap(C)) == F
    assert s.update(snap(C)) == P
    assert s.switches == 2
    # stays put afterwards
    assert s.update(snap(C)) == P and s.switches == 2


def test_fallback_dies_while_active_returns_to_primary():
    s = FailoverSelector(P, F, recover_after_healthy_updates=5)
    s.update(snap(S))
    assert s.update(snap(C, S)) == P  # fallback unhealthy, primary healthy -> use primary
    s2 = FailoverSelector(P, F)
    s2.update(snap(S))
    assert s2.update(snap(S, S)) == P  # neither healthy -> primary


def test_replay_only_config_no_fallback():
    s = FailoverSelector(ProviderName.REPLAY)
    rp = ProviderName.REPLAY
    assert s.update({rp: h(rp, C)}) == rp
    assert s.update({rp: h(rp, S)}) == rp
    assert s.update({}) == rp
    assert s.switches == 0 and "no fallback" in s.reason


def test_selector_validation():
    with pytest.raises(ValueError):
        FailoverSelector(P, P)
    with pytest.raises(ValueError):
        FailoverSelector(P, F, recover_after_healthy_updates=0)


def test_first_accepted_duplicate_rejected():
    d = BarDeduper()
    assert d.accept(bar(), P) is True
    assert d.accept(bar(), P) is False
    assert d.accept(bar(ts=T0 + timedelta(minutes=1)), P) is True
    assert d.accept(bar(sym="AMD"), P) is True
    assert d.accept(bar(interval=Interval.M5), P) is True


def test_duplicate_across_providers_after_failover():
    d = BarDeduper()
    assert d.accept(bar(source=P), P) is True
    # failover: fallback becomes active and redelivers the same key -> dropped
    assert d.accept(bar(source=F), F) is False
    # a key the old primary never delivered is accepted from the new active
    assert d.accept(bar(ts=T0 + timedelta(minutes=1), source=F), F) is True


def test_non_active_provider_dropped_and_not_recorded():
    d = BarDeduper()
    assert d.accept(bar(source=F), P) is False  # fallback not active
    assert len(d) == 0
    assert d.accept(bar(source=P), P) is True  # primary still accepted afterwards
    assert d.dropped_non_active == 1


def test_eviction_bounded_lru():
    d = BarDeduper(max_keys=3)
    for i in range(10):
        assert d.accept(bar(ts=T0 + timedelta(minutes=i)), P) is True
        assert len(d) <= 3
    # oldest evicted -> accepted again; newest still remembered
    assert d.accept(bar(ts=T0), P) is True
    assert d.accept(bar(ts=T0 + timedelta(minutes=9)), P) is False


def test_lru_refresh_on_duplicate_hit():
    d = BarDeduper(max_keys=2)
    a, b, c = (bar(ts=T0 + timedelta(minutes=i)) for i in range(3))
    d.accept(a, P)
    d.accept(b, P)
    assert d.accept(a, P) is False  # refresh a
    d.accept(c, P)  # evicts b, not a
    assert d.accept(a, P) is False
    assert d.accept(b, P) is True
