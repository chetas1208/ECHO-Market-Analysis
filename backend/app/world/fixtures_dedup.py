"""Deterministic de-duplication / corroboration scenarios for the world-event pipeline.

Every event here is synthetic (``is_replay=True``, ``provider="replay"``, fictional publishers
such as "Replay Wire A", URLs on the reserved ``example.invalid`` TLD). No wall clock, no random:
each call to :func:`build_dedup_scenarios` returns fresh, equal objects.

Scenarios (keys are a stable contract):

- ``exact_duplicate``: the same Hormuz report twice (same provider_event_id, identical content).
- ``independent_sources``: one Hormuz event from 4 distinct publishers within 90 minutes.
- ``syndicated``: a "Replay Wire A" original plus 3 republications crediting Replay Wire A
  (via ``syndicated_from`` and/or a "(Replay Wire A)" attribution marker).
- ``aftershock``: Taiwan quake (10:00Z, M7.4) and a later aftershock (16:00Z, M6.1); distinct.
- ``update``: initial Taiwan quake report (09:00Z, no magnitude) and a later report of the same
  event (11:30Z) adding magnitude/importance and a new source.

``SCENARIO_EXPECTATIONS`` documents what a correct ingest pipeline should end up with after
feeding a scenario's events, in order, into an empty store.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from app.world.types import RawWorldEvent, SourceRef

PROVIDER = "replay"
_DAY = datetime(2026, 9, 16, 0, 0, tzinfo=UTC)


def _at(hour: int, minute: int = 0) -> datetime:
    return _DAY.replace(hour=hour, minute=minute)


def _slug(group: str) -> str:
    return group.replace("_", "-")


def _src(
    name: str,
    group: str,
    headline: str,
    published_at: datetime,
    identifier: str,
    *,
    syndicated_from: str | None = None,
    reliability: float | None = None,
    with_url: bool = True,
) -> SourceRef:
    return SourceRef(
        provider=PROVIDER,
        source_name=name,
        source_url=(
            f"https://{_slug(group)}.example.invalid/world/{identifier}" if with_url else None
        ),
        source_identifier=identifier,
        headline=headline,
        published_at=published_at,
        retrieved_at=published_at + timedelta(minutes=2),
        source_group=group,
        syndicated_from=syndicated_from,
        reliability=reliability,
    )


def _hormuz(
    event_id: str,
    headline: str,
    body: str,
    occurred_at: datetime,
    source: SourceRef,
) -> RawWorldEvent:
    return RawWorldEvent(
        provider=PROVIDER,
        provider_event_id=event_id,
        headline=headline,
        body=body,
        occurred_at=occurred_at,
        sources=[source],
        region="Middle East",
        entities=["Strait of Hormuz"],
        categories=["shipping", "geopolitics"],
        is_replay=True,
    )


def _exact_duplicate() -> list[RawWorldEvent]:
    t = _at(9, 0)
    headline = "Tanker traffic halted in Strait of Hormuz after naval standoff"
    first = _hormuz(
        "replay-hormuz-dup-001",
        headline,
        "Commercial tankers paused transit through the Strait of Hormuz on Wednesday "
        "as naval vessels confronted one another near the shipping lane.",
        t,
        _src("Replay Wire A", "replay_wire_a", headline, t, "hormuz-dup-001", reliability=0.9),
    )
    return [first, first.model_copy(deep=True)]


def _independent_sources() -> list[RawWorldEvent]:
    specs = [
        (
            "Replay Wire A",
            "replay_wire_a",
            _at(9, 0),
            "Tanker traffic halted in Strait of Hormuz after naval standoff",
            "Commercial tankers paused transit through the Strait of Hormuz as naval "
            "vessels confronted one another near the shipping lane.",
            0.9,
        ),
        (
            "Replay Daily",
            "replay_daily",
            _at(9, 20),
            "Naval standoff halts tanker traffic in the Strait of Hormuz",
            "Shipping through the Strait of Hormuz stopped after a standoff between "
            "naval vessels, according to harbour officials.",
            0.7,
        ),
        (
            "Replay Herald",
            "replay_herald",
            _at(9, 50),
            "Strait of Hormuz: tankers stop transit amid naval confrontation",
            "Oil tankers halted passage through the Strait of Hormuz on Wednesday as "
            "warships faced off, shipping brokers said.",
            0.6,
        ),
        (
            "Replay Wire B",
            "replay_wire_b",
            _at(10, 25),
            "Hormuz tanker traffic halted following naval standoff, brokers say",
            "Tanker traffic in the Strait of Hormuz was halted after a naval standoff, "
            "brokers told Replay Wire B.",
            0.85,
        ),
    ]
    events: list[RawWorldEvent] = []
    for i, (name, group, t, headline, body, reliability) in enumerate(specs, start=1):
        ident = f"hormuz-ind-{i:03d}"
        events.append(
            _hormuz(
                f"replay-{ident}",
                headline,
                body,
                t,
                _src(name, group, headline, t, ident, reliability=reliability),
            )
        )
    return events


def _syndicated() -> list[RawWorldEvent]:
    original_headline = "Tanker traffic halted in Strait of Hormuz after naval standoff"
    t0 = _at(9, 0)
    events = [
        _hormuz(
            "replay-hormuz-syn-001",
            original_headline,
            "Commercial tankers paused transit through the Strait of Hormuz as naval "
            "vessels confronted one another near the shipping lane.",
            t0,
            _src(
                "Replay Wire A",
                "replay_wire_a",
                original_headline,
                t0,
                "hormuz-syn-001",
                reliability=0.9,
            ),
        )
    ]
    # (name, group, minute offset, headline, byline/body attribution, syndicated_from field)
    copies = [
        (
            "Replay Daily",
            "replay_daily",
            15,
            f"{original_headline} (Replay Wire A)",
            "Commercial tankers paused transit through the Strait of Hormuz as naval "
            "vessels confronted one another near the shipping lane. (Replay Wire A)",
            "replay_wire_a",
        ),
        (
            "Replay Herald",
            "replay_herald",
            30,
            original_headline,
            "By Replay Wire A. Commercial tankers paused transit through the Strait of "
            "Hormuz as naval vessels confronted one another near the shipping lane.",
            "replay_wire_a",
        ),
        (
            "Replay Wire C",
            "replay_wire_c",
            45,
            f"{original_headline} (Replay Wire A)",
            "Commercial tankers paused transit through the Strait of Hormuz as naval "
            "vessels confronted one another near the shipping lane. (Replay Wire A)",
            None,  # attribution marker only; no structured syndicated_from
        ),
    ]
    for i, (name, group, minute, headline, body, synd) in enumerate(copies, start=2):
        t = t0 + timedelta(minutes=minute)
        ident = f"hormuz-syn-{i:03d}"
        events.append(
            _hormuz(
                f"replay-{ident}",
                headline,
                body,
                t,
                _src(name, group, headline, t, ident, syndicated_from=synd, reliability=0.6),
            )
        )
    return events


def _quake(
    event_id: str,
    headline: str,
    body: str,
    occurred_at: datetime,
    source: SourceRef,
    *,
    magnitude: dict[str, float] | None = None,
    provider_scores: dict[str, float] | None = None,
) -> RawWorldEvent:
    return RawWorldEvent(
        provider=PROVIDER,
        provider_event_id=event_id,
        headline=headline,
        body=body,
        occurred_at=occurred_at,
        sources=[source],
        country="Taiwan",
        region="East Asia",
        entities=["Taiwan"],
        categories=["natural_disaster", "earthquake"],
        magnitude=magnitude or {},
        provider_scores=provider_scores or {},
        is_replay=True,
    )


def _aftershock() -> list[RawWorldEvent]:
    t_main, t_after = _at(10, 0), _at(16, 0)
    main_headline = "Magnitude 7.4 earthquake strikes off eastern Taiwan"
    after_headline = "Magnitude 6.1 aftershock rattles eastern Taiwan"
    return [
        _quake(
            "replay-taiwan-quake-001",
            main_headline,
            "A powerful earthquake struck off the east coast of Taiwan, shaking Taipei "
            "and prompting inspections at semiconductor fabrication plants.",
            t_main,
            _src(
                "Replay Wire A",
                "replay_wire_a",
                main_headline,
                t_main,
                "quake-001",
                reliability=0.9,
            ),
            magnitude={"richter": 7.4},
        ),
        _quake(
            "replay-taiwan-quake-002",
            after_headline,
            "A strong aftershock followed hours after the main earthquake; officials said "
            "no new damage was reported.",
            t_after,
            _src(
                "Replay Daily",
                "replay_daily",
                after_headline,
                t_after,
                "quake-002",
                reliability=0.7,
            ),
            magnitude={"richter": 6.1},
        ),
    ]


def _update() -> list[RawWorldEvent]:
    t1, t2 = _at(9, 0), _at(11, 30)
    first_headline = "Earthquake strikes off eastern Taiwan"
    second_headline = "Earthquake strikes off eastern Taiwan, magnitude 7.4, fab checks under way"
    return [
        _quake(
            "replay-taiwan-upd-001",
            first_headline,
            "An earthquake was felt across eastern Taiwan. Authorities are assessing the "
            "strength and possible damage.",
            t1,
            _src(
                "Replay Wire A",
                "replay_wire_a",
                first_headline,
                t1,
                "quake-upd-001",
                reliability=0.9,
            ),
        ),
        _quake(
            "replay-taiwan-upd-002",
            second_headline,
            "The earthquake off eastern Taiwan measured magnitude 7.4, the seismology agency "
            "said; semiconductor plants began safety inspections and some production lines "
            "paused.",
            t2,
            _src(
                "Replay Herald",
                "replay_herald",
                second_headline,
                t2,
                "quake-upd-002",
                reliability=0.6,
            ),
            magnitude={"richter": 7.4},
            provider_scores={"importance": 0.9},
        ),
    ]


def build_dedup_scenarios() -> dict[str, list[RawWorldEvent]]:
    """Return fresh, deterministic scenario event lists, each in intended arrival order."""
    return {
        "exact_duplicate": _exact_duplicate(),
        "independent_sources": _independent_sources(),
        "syndicated": _syndicated(),
        "aftershock": _aftershock(),
        "update": _update(),
    }


# Expected end state after ingesting a scenario's events, in order, into an empty store.
#   canonical_events    distinct canonical events expected
#   min_sources / sources        expected source-row count (lower bound / exact), across canonicals
#   min_independent / independent  expected independent-source count (lower bound / exact),
#                                  summed across canonicals
#   syndicated          expected source rows classified as syndicated copies
SCENARIO_EXPECTATIONS: dict[str, dict[str, int]] = {
    # Same (provider, provider_event_id) and content: second ingest is a no-op duplicate.
    "exact_duplicate": {
        "canonical_events": 1,
        "min_sources": 1,
        "sources": 1,
        "min_independent": 1,
        "independent": 1,
        "syndicated": 0,
    },
    # One event, four distinct publishers -> four independent sources.
    "independent_sources": {
        "canonical_events": 1,
        "min_sources": 4,
        "sources": 4,
        "min_independent": 4,
        "independent": 4,
        "syndicated": 0,
    },
    # One event, four source rows, but only Replay Wire A is independent.
    "syndicated": {
        "canonical_events": 1,
        "min_sources": 4,
        "sources": 4,
        "min_independent": 1,
        "independent": 1,
        "syndicated": 3,
    },
    # Main quake and aftershock stay separate events, one source each.
    "aftershock": {
        "canonical_events": 2,
        "min_sources": 2,
        "sources": 2,
        "min_independent": 2,
        "independent": 2,
        "syndicated": 0,
    },
    # Later report merges into the same event and adds a new independent source.
    "update": {
        "canonical_events": 1,
        "min_sources": 2,
        "sources": 2,
        "min_independent": 2,
        "independent": 2,
        "syndicated": 0,
    },
}
