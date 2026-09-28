from datetime import UTC, datetime

from app.world.fixtures import WORLD_FIXTURES
from app.world.normalizer import normalize
from app.world.pipeline import _event_values
from app.world.settings import WorldSettings


def test_normalized_world_event_uses_the_reserved_metadata_orm_attribute() -> None:
    fixture = WORLD_FIXTURES["hormuz"]
    now = datetime(2026, 9, 16, 10, 0, tzinfo=UTC)
    normalized = normalize(fixture.raw, now=now, settings=WorldSettings(_env_file=None))

    values = _event_values("evt_world_boundary_test", normalized, fixture.raw, now)

    assert "metadata_" in values
    assert "metadata" not in values
    assert values["metadata_"]["is_replay"] is True
