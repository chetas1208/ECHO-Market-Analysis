"""Pure tests for app.world.taxonomy (no DB, no network)."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from app.world.taxonomy import (
    CATEGORY_GROUP,
    CLASS_LABELS,
    CLASS_PRIORITY,
    OTHER_CERTAINTY,
    classify,
)
from app.world.types import EventClass, RawWorldEvent

E = EventClass
T0 = datetime(2026, 9, 16, 9, 0, tzinfo=UTC)
GROUPS = {"geopolitics", "energy", "supply_chain", "technology", "macro", "other"}


def ev(headline: str, body: str | None = None, categories: list[str] | None = None):
    return RawWorldEvent(
        provider="replay",
        headline=headline,
        body=body,
        occurred_at=T0,
        categories=categories or [],
    )


HEADLINES: dict[EventClass, list[str]] = {
    E.SHIPPING_DISRUPTION: [
        "Iranian naval forces seize tanker in Strait of Hormuz",
        "Houthi drone hits container ship, carriers reroute around Red Sea",
        "Freight rates jump as shipping lanes disrupted by blockade",
    ],
    E.PORT_DISRUPTION: [
        "Port closure in Rotterdam halts container handling",
        "Strike at Port of Los Angeles paralyses terminals",
        "Dockworkers walk out, port congestion worsens",
    ],
    E.ENERGY_SUPPLY_DISRUPTION: [
        "Pipeline attack forces shutdown of key oil export route",
        "Refinery fire halts output at Gulf coast plant",
        "Oil field shutdown cuts supply after sabotage",
        "OPEC+ agrees to deepen production cuts",
    ],
    E.TECHNOLOGY_SUPPLY_SHOCK: [
        "New export controls tighten chip shipments to China",
        "Chip shortage hits automakers as foundry capacity stays constrained",
    ],
    E.INFRASTRUCTURE_OUTAGE: [
        "Major cloud outage takes down thousands of websites",
        "Data center downtime disrupts payment processing for hours",
        "Widespread power blackout hits the capital",
    ],
    E.CYBER_INCIDENT: [
        "Ransomware attack cripples hospital network",
        "Bank confirms data breach exposing customer records",
        "State-linked cyberattack targets energy firms",
    ],
    E.NATURAL_DISASTER: [
        "Magnitude 7.4 earthquake strikes off Taiwan coast",
        "Typhoon makes landfall, floods southern provinces",
        "Wildfire forces mass evacuations in California",
    ],
    E.SANCTION: [
        "US announces new sanctions on Russian oil exporters",
        "EU weighs embargo on energy imports",
        "OFAC adds shipping firms to blacklist",
    ],
    E.MILITARY_CONFLICT: [
        "Missile strikes hit eastern city as troops advance",
        "Airstrikes intensify across the border region",
        "Artillery shelling reported near the frontline",
    ],
    E.GEOPOLITICAL_ESCALATION: [
        "Tensions escalate as ambassador is expelled",
        "Diplomatic crisis deepens after border dispute",
        "Standoff continues as leaders trade ultimatums",
    ],
    E.COMMODITY_SHOCK: [
        "Copper prices surge to record high",
        "Wheat plunges as harvest estimates jump",
        "Commodity price shock rattles metals markets",
    ],
    E.MACRO_EVENT: [
        "Fed holds rates steady in latest rate decision",
        "US CPI accelerates in latest inflation report",
        "Jobs report shows unemployment rate ticking up",
    ],
    E.REGULATORY_EVENT: [
        "Regulators propose new tariffs on imported steel",
        "Antitrust lawsuit targets dominant search firm",
        "Government bans sale of unlicensed apps",
    ],
}


def _cases() -> list[tuple[EventClass, str]]:
    return [(cls, h) for cls, hs in HEADLINES.items() for h in hs]


@pytest.mark.parametrize(("expected", "headline"), _cases())
def test_headline_classes(expected: EventClass, headline: str) -> None:
    cls, certainty, evidence = classify(ev(headline))
    assert cls is expected, (headline, cls, evidence)
    assert 0.25 <= certainty <= 0.95
    assert evidence


def test_every_class_except_other_has_two_headlines() -> None:
    covered = {c for c, hs in HEADLINES.items() if len(hs) >= 2}
    assert covered == set(EventClass) - {E.OTHER}


def test_no_match_is_other() -> None:
    cls, certainty, evidence = classify(ev("Local bakery introduces sourdough range"))
    assert (cls, certainty, evidence) == (E.OTHER, OTHER_CERTAINTY, [])
    assert OTHER_CERTAINTY == 0.2


def test_provider_category_alone_classifies() -> None:
    cls, certainty, evidence = classify(ev("Update from region", categories=["Cyber-Attack"]))
    assert cls is E.CYBER_INCIDENT
    assert certainty == pytest.approx(0.65)
    assert evidence == ["category:cyber attack"]


def test_weak_category_alone_does_not_classify() -> None:
    assert classify(ev("Company opens new office", categories=["energy", "Markets"]))[0] is E.OTHER


def test_category_segments_and_separators() -> None:
    assert classify(ev("Quiet day", categories=["world/natural_disaster"]))[0] is (
        E.NATURAL_DISASTER
    )
    assert classify(ev("Quiet day", categories=["category:sanctions"]))[0] is E.SANCTION


def test_certainty_higher_with_category_and_multiple_hits() -> None:
    kw_only = classify(ev("Pipeline attack forces shutdown of oil terminal"))[1]
    kw_multi = classify(
        ev("Pipeline attack forces shutdown", body="Force majeure declared; refinery offline.")
    )[1]
    with_cat = classify(
        ev(
            "Pipeline attack forces shutdown",
            body="Force majeure declared; refinery offline.",
            categories=["energy supply"],
        )
    )[1]
    single = classify(ev("Pipeline attack"))[1]
    assert single <= kw_only <= kw_multi < with_cat <= 0.95


def test_category_plus_keywords_beats_keyword_only_same_text() -> None:
    text = "Earthquake shakes region, magnitude 6.8"
    assert classify(ev(text, categories=["earthquake"]))[1] > classify(ev(text))[1]


def test_weak_category_boosts_matching_class() -> None:
    base = classify(ev("Tensions escalate along border"))[1]
    boosted = classify(ev("Tensions escalate along border", categories=["geopolitics"]))[1]
    assert boosted > base


def test_headline_weighs_more_than_body() -> None:
    _, c_head, _ = classify(ev("Ransomware hits hospital"))
    _, c_body, _ = classify(ev("Hospital reports problem", body="Ransomware suspected"))
    assert c_head > c_body


def test_ambiguous_tie_break_is_deterministic() -> None:
    # "drone strike" (military) + "refinery ... struck" (energy): tie -> fixed priority.
    h = "Drone strike hits refinery"
    results = {(c, k, tuple(e)) for c, k, e in (classify(ev(h)) for _ in range(50))}
    assert len(results) == 1
    cls = results.pop()[0]
    assert cls is E.ENERGY_SUPPLY_DISRUPTION
    assert CLASS_PRIORITY.index(E.ENERGY_SUPPLY_DISRUPTION) < CLASS_PRIORITY.index(
        E.MILITARY_CONFLICT
    )


def test_tie_break_independent_of_category_order() -> None:
    a = classify(ev("Quiet day", categories=["sanctions", "cyber"]))
    b = classify(ev("Quiet day", categories=["cyber", "sanctions"]))
    assert a[0] is b[0] is E.CYBER_INCIDENT
    assert a[1] == b[1]


def test_evidence_deterministic_order_and_deduped() -> None:
    out = classify(ev("Ransomware attack, ransomware again", body="A cyberattack. Hackers."))
    assert out == classify(
        ev("Ransomware attack, ransomware again", body="A cyberattack. Hackers.")
    )
    assert len(out[2]) == len(set(out[2]))


def test_hormuz_needs_context() -> None:
    assert classify(ev("Delegation visits Strait of Hormuz museum"))[0] is E.OTHER
    assert classify(ev("Strait of Hormuz naval blockade fears grow"))[0] is (E.SHIPPING_DISRUPTION)


def test_word_boundary_portfolio_not_port() -> None:
    assert classify(ev("Fund closes portfolio review, strike price set"))[0] is E.OTHER
    assert classify(ev("Portugal shuts down transport report strike"))[0] is E.OTHER
    assert classify(ev("Airstrike closes portfolio"))[0] is not E.PORT_DISRUPTION
    assert classify(ev("Support desk closed after shutdown"))[0] is E.OTHER


def test_word_boundary_substrings_do_not_match() -> None:
    for text in (
        "Warranty extended on new appliances",  # 'war'
        "Bankruptcy filing by retailer",  # 'ban'
        "Reported earnings beat estimates",  # 'port' inside 'reported'
        "Hackathon winners announced",  # 'hack'
        "Cloudy skies expected",  # 'cloud'
        "Federation of clubs meets",  # 'fed'
    ):
        assert classify(ev(text))[0] is E.OTHER, text


def test_trade_war_is_not_military() -> None:
    assert classify(ev("Trade war fears weigh on stocks"))[0] is not E.MILITARY_CONFLICT
    assert classify(ev("War breaks out along the border"))[0] is E.MILITARY_CONFLICT


def test_case_insensitive_and_whitespace() -> None:
    a = classify(ev("RANSOMWARE   ATTACK\n\tHITS  HOSPITAL"))
    b = classify(ev("ransomware attack hits hospital"))
    assert a == b
    assert classify(ev("STRAIT   OF\nHORMUZ tanker seized"))[0] is E.SHIPPING_DISRUPTION
    assert classify(ev("cyber-attack on ministry"))[0] is E.CYBER_INCIDENT
    assert classify(ev("Cyber attack on ministry"))[0] is E.CYBER_INCIDENT


def test_body_only_match() -> None:
    cls, certainty, _ = classify(ev("Breaking news update", body="A magnitude 6.5 earthquake"))
    assert cls is E.NATURAL_DISASTER
    assert certainty < 0.6


def test_very_long_text_is_fast_and_safe() -> None:
    body = "earthquake " * 500_000 + "a" * 1_000_000
    cls, certainty, evidence = classify(ev("x" * 100_000, body=body))
    assert cls is E.NATURAL_DISASTER
    assert 0.25 <= certainty <= 0.95
    assert len(evidence) <= 16
    pathological = "expels " + "the " * 100_000 + "ambassador"
    classify(ev("news", body=pathological))
    classify(ev(" ".join(["port"] * 50_000), body="\n" * 100_000))


def test_unicode_and_odd_text() -> None:
    assert classify(ev("réport on the économie"))[0] is E.OTHER
    assert classify(ev("répport closure"))[0] is E.OTHER  # accent before 'port' blocks match
    fullwidth = "".join(chr(ord(c) + 0xFEE0) for c in "Ransomware")
    assert classify(ev(f"{fullwidth} attack"))[0] is E.CYBER_INCIDENT  # NFKC
    assert classify(ev("地震 earthquake 🌋 strikes"))[0] is E.NATURAL_DISASTER
    assert classify(ev("‮\x00 ransomware ​"))[0] is E.CYBER_INCIDENT
    assert classify(ev("İstanbul port closure"))[0] is E.PORT_DISRUPTION
    assert classify(ev("'; DROP TABLE events; -- <script>alert(1)</script>"))[0] is E.OTHER


def test_malicious_categories_do_not_break() -> None:
    raw = ev("Quiet day", categories=["", "   ", "x" * 10_000, "\x00", "🌋", "a:b:c", "sanctions"])
    assert classify(raw)[0] is E.SANCTION
    many = ev("Quiet day", categories=["noise"] * 5_000 + ["sanctions"])
    assert classify(many)[0] is E.OTHER  # beyond the category cap; still safe


def test_evidence_terms_for_winner_only() -> None:
    cls, _, evidence = classify(ev("Iranian naval forces seize tanker in Strait of Hormuz"))
    assert cls is E.SHIPPING_DISRUPTION
    assert "strait of hormuz" in evidence
    assert "tanker" in evidence


def test_labels_and_groups_cover_every_class() -> None:
    assert set(CLASS_LABELS) == set(EventClass)
    assert set(CATEGORY_GROUP) == set(EventClass)
    assert set(CATEGORY_GROUP.values()) <= GROUPS
    assert all(isinstance(v, str) and v for v in CLASS_LABELS.values())
    assert set(CLASS_PRIORITY) == set(EventClass)
    assert len(CLASS_PRIORITY) == len(set(CLASS_PRIORITY))
    assert CATEGORY_GROUP[E.OTHER] == "other"
    assert {"geopolitics", "energy", "supply_chain", "technology", "macro"} <= set(
        CATEGORY_GROUP.values()
    )
