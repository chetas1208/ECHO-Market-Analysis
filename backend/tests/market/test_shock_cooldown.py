import json
from datetime import UTC, datetime, timedelta

import pytest

from app.market.shock.cooldown import ShockCooldown
from app.market.types import ShockDirection as D
from app.market.types import ShockLevel as L

T0 = datetime(2026, 3, 2, 15, 0, tzinfo=UTC)


def _s(sec: float) -> datetime:
    return T0 + timedelta(seconds=sec)


def test_first_shock_emits():
    assert ShockCooldown(300).should_emit("NVDA", D.NEGATIVE, L.SHOCK, T0) is True


@pytest.mark.parametrize("level", [L.NONE, L.WATCH])
def test_non_eligible_levels_never_emit_or_change_state(level):
    c = ShockCooldown(300)
    assert c.should_emit("NVDA", D.NEGATIVE, level, T0) is False
    assert c.snapshot()["entries"] == []
    assert c.should_emit("NVDA", D.NEGATIVE, L.SHOCK, _s(1)) is True


def test_watch_does_not_disturb_existing_cooldown():
    c = ShockCooldown(300)
    assert c.should_emit("NVDA", D.NEGATIVE, L.SHOCK, T0)
    assert not c.should_emit("NVDA", D.NEGATIVE, L.WATCH, _s(400))
    assert c.snapshot()["entries"][0]["last_emit_at"] == T0.isoformat()


def test_none_direction_suppressed():
    assert ShockCooldown(300).should_emit("NVDA", None, L.SEVERE, T0) is False


def test_same_key_within_cooldown_suppressed():
    c = ShockCooldown(300)
    assert c.should_emit("NVDA", D.NEGATIVE, L.SHOCK, T0)
    assert not c.should_emit("NVDA", D.NEGATIVE, L.SHOCK, _s(60))
    assert not c.should_emit("NVDA", D.NEGATIVE, L.SHOCK, _s(299))


def test_severe_then_shock_within_cooldown_suppressed():
    c = ShockCooldown(300)
    assert c.should_emit("NVDA", D.NEGATIVE, L.SEVERE, T0)
    assert not c.should_emit("NVDA", D.NEGATIVE, L.SHOCK, _s(60))
    assert not c.should_emit("NVDA", D.NEGATIVE, L.SEVERE, _s(120))


def test_escalation_emits_and_updates_state():
    c = ShockCooldown(300)
    assert c.should_emit("NVDA", D.NEGATIVE, L.SHOCK, T0)
    assert c.should_emit("NVDA", D.NEGATIVE, L.SEVERE, _s(60))
    entry = c.snapshot()["entries"][0]
    assert entry["level"] == "severe" and entry["last_emit_at"] == _s(60).isoformat()
    # SHOCK now suppressed against the severe baseline; cooldown counts from escalation
    assert not c.should_emit("NVDA", D.NEGATIVE, L.SHOCK, _s(200))
    assert not c.should_emit("NVDA", D.NEGATIVE, L.SEVERE, _s(359))
    assert c.should_emit("NVDA", D.NEGATIVE, L.SHOCK, _s(360))


def test_emits_again_after_cooldown_elapsed():
    c = ShockCooldown(300)
    assert c.should_emit("NVDA", D.NEGATIVE, L.SHOCK, T0)
    assert c.should_emit("NVDA", D.NEGATIVE, L.SHOCK, _s(300))  # boundary inclusive
    assert not c.should_emit("NVDA", D.NEGATIVE, L.SHOCK, _s(500))
    assert c.should_emit("NVDA", D.NEGATIVE, L.SHOCK, _s(700))


def test_opposite_direction_independent():
    c = ShockCooldown(300)
    assert c.should_emit("NVDA", D.NEGATIVE, L.SHOCK, T0)
    assert c.should_emit("NVDA", D.POSITIVE, L.SHOCK, _s(10))
    assert not c.should_emit("NVDA", D.POSITIVE, L.SHOCK, _s(20))


def test_symbols_independent():
    c = ShockCooldown(300)
    assert c.should_emit("NVDA", D.NEGATIVE, L.SHOCK, T0)
    assert c.should_emit("AMD", D.NEGATIVE, L.SHOCK, _s(1))
    assert not c.should_emit("AMD", D.NEGATIVE, L.SHOCK, _s(2))


def test_out_of_order_suppressed_even_if_escalation():
    c = ShockCooldown(300)
    assert c.should_emit("NVDA", D.NEGATIVE, L.SHOCK, _s(100))
    assert not c.should_emit("NVDA", D.NEGATIVE, L.SHOCK, _s(50))
    assert not c.should_emit("NVDA", D.NEGATIVE, L.SEVERE, _s(50))
    assert c.snapshot()["entries"][0]["last_emit_at"] == _s(100).isoformat()


def test_deterministic_no_wall_clock():
    # far-past and far-future as_of behave purely relative to each other
    c = ShockCooldown(300)
    past = datetime(2001, 1, 1, tzinfo=UTC)
    assert c.should_emit("X", D.POSITIVE, L.SHOCK, past)
    assert not c.should_emit("X", D.POSITIVE, L.SHOCK, past + timedelta(seconds=10))
    assert c.should_emit("X", D.POSITIVE, L.SHOCK, datetime(2099, 1, 1, tzinfo=UTC))


def test_naive_as_of_rejected():
    with pytest.raises(ValueError):
        ShockCooldown(300).should_emit("X", D.POSITIVE, L.SHOCK, datetime(2026, 1, 1))


def test_negative_cooldown_rejected():
    with pytest.raises(ValueError):
        ShockCooldown(-1)


def test_reset_clears_state():
    c = ShockCooldown(300)
    c.should_emit("NVDA", D.NEGATIVE, L.SHOCK, T0)
    c.reset()
    assert c.snapshot()["entries"] == []
    assert c.should_emit("NVDA", D.NEGATIVE, L.SHOCK, _s(1))


def test_snapshot_json_serializable_and_sorted():
    c = ShockCooldown(300)
    c.should_emit("NVDA", D.NEGATIVE, L.SHOCK, T0)
    c.should_emit("AMD", D.POSITIVE, L.SEVERE, _s(5))
    snap = json.loads(json.dumps(c.snapshot()))
    assert snap["cooldown_seconds"] == 300
    assert [e["symbol"] for e in snap["entries"]] == ["AMD", "NVDA"]
    assert snap["entries"][1] == {
        "symbol": "NVDA",
        "direction": "negative",
        "level": "shock",
        "last_emit_at": T0.isoformat(),
    }
