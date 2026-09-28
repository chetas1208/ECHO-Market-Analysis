from datetime import UTC, datetime

from app.cause.cluster import detect_clusters
from app.cause.types import CauseConfig, ObservedShock


def _shock(symbol: str, minute: int, direction: str = "negative") -> ObservedShock:
    return ObservedShock(
        event_id=f"evt_{symbol.lower()}",
        symbol=symbol,
        timestamp=datetime(2026, 9, 20, 10, minute, tzinfo=UTC),
        direction=direction,
        residual_z=-2.0 if direction == "negative" else 2.0,
        volume_z=2.0,
    )


def test_related_synchronized_members_form_a_cluster() -> None:
    shocks = [_shock("NVDA", 0), _shock("AMD", 2), _shock("TSM", 4)]
    clusters = detect_clusters(
        shocks,
        {
            "NVDA": {"sector:semiconductors"},
            "AMD": {"sector:semiconductors"},
            "TSM": {"sector:semiconductors"},
        },
        CauseConfig(),
    )
    assert len(clusters) == 1
    assert clusters[0].cluster_key == "sector:semiconductors"
    assert clusters[0].direction == "NEGATIVE"
    assert clusters[0].members == ["NVDA", "AMD", "TSM"]


def test_unrelated_or_unsynchronized_moves_do_not_form_a_cluster() -> None:
    shocks = [_shock("NVDA", 0), _shock("AMD", 2), _shock("TSM", 20)]
    memberships = {
        "NVDA": {"sector:semiconductors"},
        "AMD": {"sector:semiconductors"},
        "TSM": {"sector:semiconductors"},
    }
    assert detect_clusters(shocks, memberships, CauseConfig()) == []
    assert (
        detect_clusters(
            [_shock("NVDA", 0), _shock("XOM", 1), _shock("DAL", 2)],
            {
                "NVDA": {"sector:semiconductors"},
                "XOM": {"sector:energy"},
                "DAL": {"sector:airlines"},
            },
            CauseConfig(),
        )
        == []
    )
