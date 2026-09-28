"""Pure tests for app.world.channels (no DB, no network)."""

from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import UTC, datetime

import pytest

from app.world.channels import CHANNELS, CLASS_PRIORS, EVIDENCE_RULES, extract_channels
from app.world.types import EventClass, GeoInfo, RawWorldEvent

T0 = datetime(2026, 9, 16, 9, 0, tzinfo=UTC)

EXPECTED_VOCAB = (
    "oil_supply, natural_gas_supply, energy_prices, shipping_capacity, shipping_costs, "
    "port_capacity, semiconductor_supply, compute_supply, commodity_supply, commodity_prices, "
    "consumer_demand, industrial_demand, interest_rates, credit_conditions, regulatory_risk, "
    "geopolitical_risk, cybersecurity_risk, infrastructure_availability, global_trade"
)


@dataclass
class Ent:
    canonical: str
    kind: str = "other"
    raw: str = ""


def raw(headline: str, body: str | None = None, **kw) -> RawWorldEvent:
    return RawWorldEvent(provider="replay", headline=headline, body=body, occurred_at=T0, **kw)


def run(cls, headline="Synthetic event", ents=(), geo=None, hint=1.0, body=None, **kw):
    return extract_channels(cls, list(ents), geo or GeoInfo(), raw(headline, body, **kw), hint)


def test_vocabulary_exact():
    assert tuple(EXPECTED_VOCAB.split(", ")) == CHANNELS
    assert len(set(CHANNELS)) == len(CHANNELS) == 19


def test_tables_only_use_vocabulary_and_cover_all_classes():
    assert set(CLASS_PRIORS) == set(EventClass)
    for table in [*CLASS_PRIORS.values(), *(r.contributions for r in EVIDENCE_RULES)]:
        assert set(table) <= set(CHANNELS)
        assert all(-1 <= v <= 1 for v in table.values())


def test_hormuz_shipping_disruption():
    ch, ev = run(
        EventClass.SHIPPING_DISRUPTION,
        "Tanker traffic halted in Strait of Hormuz",
        ents=[Ent("Strait of Hormuz", "infrastructure")],
        geo=GeoInfo(chokepoint="Strait of Hormuz", resolved=True),
    )
    assert ch["oil_supply"] < 0
    assert ch["energy_prices"] > 0
    assert ch["shipping_costs"] > 0
    assert ch["shipping_capacity"] < 0
    assert ch["global_trade"] < 0
    assert "class:shipping_disruption" in ev["shipping_capacity"]
    assert "entity:Strait of Hormuz" in ev["oil_supply"]
    assert set(ev) == set(ch)
    assert all(ev[k] for k in ev)


def test_hormuz_from_geo_only_and_from_keyword_only():
    ch, ev = run(EventClass.GEOPOLITICAL_ESCALATION, geo=GeoInfo(chokepoint="Strait of Hormuz"))
    assert ch["oil_supply"] < 0 and "geo:Strait of Hormuz" in ev["oil_supply"]
    ch, ev = run(EventClass.MILITARY_CONFLICT, "Clashes near the Persian Gulf")
    assert ch["oil_supply"] < 0 and "keyword:persian gulf" in ev["oil_supply"]


def test_suez_bab_el_mandeb():
    ch, _ = run(
        EventClass.SHIPPING_DISRUPTION,
        ents=[Ent("Bab el-Mandeb", "infrastructure")],
    )
    assert ch["shipping_capacity"] < 0 and ch["global_trade"] < 0 and ch["shipping_costs"] > 0
    ch2, _ = run(EventClass.SHIPPING_DISRUPTION, ents=[Ent("Suez Canal", "infrastructure")])
    assert ch2["shipping_capacity"] <= ch["shipping_capacity"] or ch2["shipping_capacity"] < 0


def test_quake_taiwan_semiconductors():
    ch, ev = run(
        EventClass.NATURAL_DISASTER,
        "Magnitude 7.4 earthquake strikes Taiwan",
        ents=[Ent("Taiwan", "country")],
        magnitude={"richter": 7.4},
    )
    assert ch["semiconductor_supply"] < 0
    assert ch["compute_supply"] < 0
    assert ch["infrastructure_availability"] < 0
    assert "entity:Taiwan" in ev["semiconductor_supply"]


def test_semiconductor_keyword_without_taiwan():
    ch, ev = run(EventClass.NATURAL_DISASTER, "Fire halts chip fab output")
    assert ch["semiconductor_supply"] < 0
    assert any(e.startswith("keyword:") for e in ev["semiconductor_supply"])


def test_chip_word_in_macro_or_other_does_not_fire():
    assert run(EventClass.OTHER, "Chip shortage of poker chips")[0] == {}
    assert run(EventClass.MACRO_EVENT, "Semiconductor makers report earnings")[0] == {}


def test_cloud_outage_and_cyber():
    ch, _ = run(EventClass.INFRASTRUCTURE_OUTAGE, "Major AWS outage", ents=[Ent("AWS", "company")])
    assert ch["infrastructure_availability"] < 0
    assert "cybersecurity_risk" not in ch
    ch, ev = run(EventClass.INFRASTRUCTURE_OUTAGE, "Cloud outage blamed on ransomware attack")
    assert ch["cybersecurity_risk"] > 0 and ch["infrastructure_availability"] < 0
    assert "keyword:ransomware" in ev["cybersecurity_risk"]
    ch, ev = run(EventClass.CYBER_INCIDENT, "Data breach at retailer")
    assert ch["cybersecurity_risk"] > 0
    assert "class:cyber_incident" in ev["cybersecurity_risk"]


def test_sanctions_on_energy_entity():
    ch, ev = run(
        EventClass.SANCTION,
        "New sanctions target crude oil exports",
        ents=[Ent("crude oil", "commodity"), Ent("Russia", "country")],
    )
    assert ch["regulatory_risk"] > 0 and ch["geopolitical_risk"] > 0
    assert ch["commodity_supply"] < 0
    assert ch["oil_supply"] < 0 and ch["energy_prices"] > 0
    assert "class:sanction" in ev["regulatory_risk"]


def test_sanction_without_commodity_has_no_commodity_supply():
    ch, _ = run(
        EventClass.SANCTION, "Sanctions on shell companies", ents=[Ent("Iceland", "country")]
    )
    assert "commodity_supply" not in ch and "oil_supply" not in ch


def test_commodity_kind_entity():
    ch, ev = run(
        EventClass.COMMODITY_SHOCK, "Copper supply squeezed", ents=[Ent("copper", "commodity")]
    )
    assert ch["commodity_prices"] > 0 and ch["commodity_supply"] < 0
    assert "entity:copper" in ev["commodity_prices"]


def test_rates_direction():
    hike, _ = run(EventClass.MACRO_EVENT, "Fed raises interest rates by 25 basis points")
    assert hike["interest_rates"] > 0 and hike["credit_conditions"] < 0
    cut, _ = run(EventClass.MACRO_EVENT, "ECB announces rate cut")
    assert cut["interest_rates"] < 0 and cut["credit_conditions"] > 0
    # central bank named, no direction -> abstain
    assert (
        run(EventClass.MACRO_EVENT, "Fed meets this week", ents=[Ent("Federal Reserve")])[0] == {}
    )


def test_other_without_evidence_abstains():
    assert run(EventClass.OTHER, "Local festival draws crowds") == ({}, {})
    assert run(EventClass.MACRO_EVENT, "Quarterly review published") == ({}, {})


def test_unknown_class_value_abstains():
    ch, ev = extract_channels("not_a_class", [], GeoInfo(), raw("x"), 0.9)  # type: ignore[arg-type]
    assert (ch, ev) == ({}, {})


def test_deterministic():
    args = dict(
        headline="Tanker attack in Strait of Hormuz",
        ents=[Ent("Strait of Hormuz", "infrastructure"), Ent("Iran", "country")],
        geo=GeoInfo(chokepoint="Strait of Hormuz"),
        hint=0.7,
    )
    assert run(EventClass.SHIPPING_DISRUPTION, **args) == run(
        EventClass.SHIPPING_DISRUPTION, **args
    )


@pytest.mark.parametrize("cls", list(EventClass))
@pytest.mark.parametrize("hint", [-5.0, 0.0, 0.1, 0.5, 1.0, 7.0, math.inf, -math.inf, math.nan])
def test_bounds_keys_and_rounding_for_any_input(cls, hint):
    ents = [
        Ent("Strait of Hormuz", "infrastructure"),
        Ent("Taiwan", "country"),
        Ent("crude oil", "commodity"),
        Ent("AWS", "company"),
        Ent("Russia", "country"),
    ]
    text = (
        "Hormuz Suez tariffs ransomware semiconductor chips LNG oil port of Rotterdam "
        "Fed raises rates rate cut recession bank failure gpu cloud outage embargo"
    )
    ch, ev = run(cls, text, ents=ents, geo=GeoInfo(chokepoint="Strait of Hormuz"), hint=hint)
    assert set(ch) <= set(CHANNELS)
    assert set(ev) == set(ch)
    for k, v in ch.items():
        assert -1.0 <= v <= 1.0
        assert abs(v) >= 0.05
        assert v == round(v, 2)
        assert round(v / 0.05, 6) == round(v / 0.05)  # coarse 0.05 steps
        assert ev[k]


def test_severity_scaling_monotone():
    ents = [Ent("Strait of Hormuz", "infrastructure")]
    prev: dict[str, float] = {}
    for hint in [0.0, 0.3, 0.4, 0.55, 0.7, 0.85, 1.0]:
        ch, _ = run(EventClass.SHIPPING_DISRUPTION, "Tanker hit", ents=ents, hint=hint)
        for k, v in ch.items():
            if k in prev:
                assert abs(v) >= abs(prev[k]) - 1e-9
                assert (v > 0) == (prev[k] > 0)
        assert set(prev) <= set(ch)  # channels never vanish as severity rises
        prev = ch


def test_severity_floor():
    a, _ = run(EventClass.NATURAL_DISASTER, hint=0.0)
    b, _ = run(EventClass.NATURAL_DISASTER, hint=0.3)
    assert a == b and a["infrastructure_availability"] == -0.1


def test_low_values_dropped():
    # only a weak prior: -0.2 * 0.3 = -0.06 -> kept; ensure anything under 0.05 would be dropped
    ch, _ = run(EventClass.GEOPOLITICAL_ESCALATION, hint=0.0)
    assert "global_trade" in ch  # 0.06 -> quantized 0.05
    assert all(abs(v) >= 0.05 for v in ch.values())


def test_duck_typed_and_malformed_inputs_do_not_raise():
    class Bare:
        pass

    ch, ev = extract_channels(EventClass.OTHER, [Bare(), None, Ent("")], None, None, 0.5)  # type: ignore[list-item]
    assert (ch, ev) == ({}, {})
