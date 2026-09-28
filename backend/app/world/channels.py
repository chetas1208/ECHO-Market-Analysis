"""Economic-channel extraction for world events (deterministic, rule-based, auditable).

A *channel* is a coarse economic transmission path. Its value is a **directional pressure
score in [-1, 1]** (-1 strong negative pressure on that channel, +1 strong positive, absent
= nothing identified). It is NOT an expected % price move and NOT a probability. E.g.
``oil_supply=-0.8`` means "strong downward pressure on oil supply", ``energy_prices=+0.7``
means "strong upward pressure on energy prices".

Method (no text model, no randomness, no clock):

1. Layer 1 - class prior: ``CLASS_PRIORS`` maps each ``EventClass`` to signed base pressures.
2. Layer 2 - evidence modifiers: ``EVIDENCE_RULES`` fire on canonical entity names/kinds, the
   resolved geo (chokepoint/country/region) or word-boundary keywords in headline/body. Each
   rule fires at most once per event and is gated to the event classes where it is meaningful
   (e.g. a passing mention of "chip" in a MACRO or OTHER event is not a supply shock).
3. Combine: per-channel sum of contributions, times a severity scale (``severity_hint``
   clamped to [0.3, 1.0] - the floor keeps low-severity events from erasing all direction),
   clamped to [-1, 1], values with |v| < 0.05 dropped, rounded to 0.05 steps (coarse on
   purpose: no fabricated precision).

Unavailable stays unavailable: a class with no prior and no evidence (``OTHER``, ``MACRO_EVENT``
without keywords) returns ``({}, {})`` - the extractor abstains. Central-bank mentions without a
stated direction (hike/cut) add nothing, since the sign would be invented.

Output evidence maps each returned channel to the rule ids that contributed, e.g.
``class:shipping_disruption``, ``entity:Strait of Hormuz``, ``geo:Strait of Hormuz``,
``keyword:semiconductor``. Only channels in ``CHANNELS`` are ever produced.

Entities are duck-typed (``.canonical``, ``.kind``); this module does not import entities.py.
"""

from __future__ import annotations

import math
import re
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from typing import Any

from app.world.types import EventClass

CHANNELS: tuple[str, ...] = (
    "oil_supply",
    "natural_gas_supply",
    "energy_prices",
    "shipping_capacity",
    "shipping_costs",
    "port_capacity",
    "semiconductor_supply",
    "compute_supply",
    "commodity_supply",
    "commodity_prices",
    "consumer_demand",
    "industrial_demand",
    "interest_rates",
    "credit_conditions",
    "regulatory_risk",
    "geopolitical_risk",
    "cybersecurity_risk",
    "infrastructure_availability",
    "global_trade",
)

SEVERITY_FLOOR = 0.3
MIN_ABS_VALUE = 0.05
_STEP = 0.05
_MAX_TEXT_CHARS = 20_000  # untrusted input: bound regex work

# Layer 1: class -> signed base pressure per channel at full severity (before scaling).
# Semantics: directional pressure, NOT a % move. Empty mapping = abstain on the prior.
CLASS_PRIORS: dict[EventClass, dict[str, float]] = {
    EventClass.GEOPOLITICAL_ESCALATION: {"geopolitical_risk": 0.6, "global_trade": -0.2},
    EventClass.MILITARY_CONFLICT: {
        "geopolitical_risk": 0.8,
        "global_trade": -0.3,
        "energy_prices": 0.2,
        "commodity_prices": 0.2,
    },
    EventClass.SANCTION: {"regulatory_risk": 0.5, "geopolitical_risk": 0.5, "global_trade": -0.3},
    EventClass.REGULATORY_EVENT: {"regulatory_risk": 0.6},
    EventClass.SHIPPING_DISRUPTION: {
        "shipping_capacity": -0.6,
        "shipping_costs": 0.5,
        "global_trade": -0.4,
    },
    EventClass.PORT_DISRUPTION: {
        "port_capacity": -0.7,
        "shipping_capacity": -0.3,
        "shipping_costs": 0.3,
        "global_trade": -0.3,
    },
    EventClass.ENERGY_SUPPLY_DISRUPTION: {
        "energy_prices": 0.6,
        "infrastructure_availability": -0.3,
    },
    EventClass.COMMODITY_SHOCK: {"commodity_supply": -0.5, "commodity_prices": 0.6},
    EventClass.NATURAL_DISASTER: {"infrastructure_availability": -0.4},
    EventClass.CYBER_INCIDENT: {"cybersecurity_risk": 0.7, "infrastructure_availability": -0.3},
    EventClass.INFRASTRUCTURE_OUTAGE: {"infrastructure_availability": -0.7},
    EventClass.TECHNOLOGY_SUPPLY_SHOCK: {"semiconductor_supply": -0.4, "compute_supply": -0.3},
    EventClass.MACRO_EVENT: {},  # direction only from evidence (rates, recession, ...)
    EventClass.OTHER: {},
}

_EC = EventClass
# Classes where a physical/political disruption reading of an entity mention is sensible.
_DISRUPTIVE = frozenset(_EC) - {_EC.REGULATORY_EVENT, _EC.MACRO_EVENT, _EC.OTHER}
_GEO_ENERGY = frozenset(
    {_EC.MILITARY_CONFLICT, _EC.GEOPOLITICAL_ESCALATION, _EC.SANCTION, _EC.ENERGY_SUPPLY_DISRUPTION}
)


def _rx(pattern: str) -> re.Pattern[str]:
    return re.compile(pattern, re.IGNORECASE)


@dataclass(frozen=True)
class Rule:
    """One evidence modifier. Fires once per event; ``classes=None`` means any class."""

    rule_id: str
    contributions: dict[str, float]
    pattern: re.Pattern[str] | None = None
    kinds: frozenset[str] = frozenset()  # entity kinds that also trigger the rule
    exclude: re.Pattern[str] | None = None  # canonical names never triggering the kind match
    classes: frozenset[EventClass] | None = None


_OIL = r"oil|crude(?: oil)?|brent|wti|petroleum|refiner(?:y|ies)|oil fields?|opec\+?"
_GAS = r"natural gas|lng|liquefied natural gas|gas pipelines?|nord stream|ttf"

# Layer 2: evidence modifiers (order is the evidence order; keep stable).
EVIDENCE_RULES: tuple[Rule, ...] = (
    Rule(
        "hormuz",
        {
            "oil_supply": -0.8,
            "energy_prices": 0.7,
            "shipping_costs": 0.7,
            "shipping_capacity": -0.6,
        },
        _rx(r"\b(?:strait of hormuz|hormuz|persian gulf)\b"),
        classes=_DISRUPTIVE,
    ),
    Rule(
        "red_sea_suez",
        {"shipping_capacity": -0.5, "shipping_costs": 0.5, "global_trade": -0.4},
        _rx(r"\b(?:suez(?: canal)?|bab[ -]el[ -]mandeb|bab al[ -]mandab|red sea)\b"),
        classes=_DISRUPTIVE,
    ),
    Rule(
        "panama_canal",
        {"shipping_capacity": -0.4, "shipping_costs": 0.4, "global_trade": -0.3},
        _rx(r"\bpanama canal\b"),
        classes=_DISRUPTIVE,
    ),
    Rule(
        "taiwan_strait",
        {"shipping_capacity": -0.3, "global_trade": -0.3},
        _rx(r"\btaiwan strait\b"),
        classes=_DISRUPTIVE,
    ),
    Rule(
        "taiwan",
        {"semiconductor_supply": -0.5, "compute_supply": -0.3},
        _rx(r"\b(?:taiwan|taipei|hsinchu)\b"),
        classes=_DISRUPTIVE,
    ),
    Rule(
        "tsmc",
        {"semiconductor_supply": -0.7, "compute_supply": -0.5},
        _rx(r"\btsmc\b"),
        classes=_DISRUPTIVE | {_EC.REGULATORY_EVENT},
    ),
    Rule(
        "semiconductor_terms",
        {"semiconductor_supply": -0.6, "compute_supply": -0.4},
        _rx(r"\b(?:semiconductors?|chips?|chipmakers?|foundr(?:y|ies)|wafers?|fabs?)\b"),
        classes=_DISRUPTIVE | {_EC.REGULATORY_EVENT},
    ),
    Rule(
        "compute_terms",
        {"compute_supply": -0.5},
        _rx(r"\b(?:gpus?|ai accelerators?|ai chips?|hbm)\b"),
        classes=_DISRUPTIVE | {_EC.REGULATORY_EVENT},
    ),
    Rule(
        "cloud_datacenter",
        {"infrastructure_availability": -0.6, "compute_supply": -0.2},
        _rx(
            r"\b(?:aws|amazon web services|azure|google cloud|gcp|cloudflare|"
            r"data ?cent(?:er|re)s?|cloud)\b"
        ),
        classes=frozenset({_EC.INFRASTRUCTURE_OUTAGE, _EC.NATURAL_DISASTER}),
    ),
    Rule(
        "cyber_terms",
        {"cybersecurity_risk": 0.5},
        _rx(
            r"\b(?:ransomware|malware|cyber ?attacks?|cyber ?incidents?|hack(?:ed|ers?|ing)|"
            r"data breach(?:es)?|ddos|zero-day)\b"
        ),
        classes=frozenset(_EC) - {_EC.CYBER_INCIDENT},
    ),
    Rule(
        "sanction_energy",
        {"commodity_supply": -0.3, "energy_prices": 0.2},
        _rx(rf"\b(?:{_OIL}|{_GAS})\b"),
        classes=frozenset({_EC.SANCTION}),
    ),
    Rule(
        "oil",
        {"oil_supply": -0.4, "energy_prices": 0.4},
        _rx(rf"\b(?:{_OIL})\b"),
        classes=_DISRUPTIVE - {_EC.COMMODITY_SHOCK},
    ),
    Rule(
        "oil_price_shock",
        {"energy_prices": 0.5},
        _rx(rf"\b(?:{_OIL})\b"),
        classes=frozenset({_EC.COMMODITY_SHOCK}),
    ),
    Rule(
        "natural_gas",
        {"natural_gas_supply": -0.5, "energy_prices": 0.4},
        _rx(rf"\b(?:{_GAS})\b"),
        classes=_DISRUPTIVE,
    ),
    Rule(
        "commodity_entity",
        {"commodity_supply": -0.3, "commodity_prices": 0.3},
        None,
        kinds=frozenset({"commodity"}),
        exclude=_rx(rf"^(?:{_OIL}|{_GAS}|oil|gas)$"),
        classes=_DISRUPTIVE,
    ),
    Rule(
        "gulf_producers",
        {"oil_supply": -0.3, "energy_prices": 0.3},
        _rx(r"\b(?:iran|iraq|kuwait|saudi arabia|united arab emirates|qatar|libya)\b"),
        classes=_GEO_ENERGY,
    ),
    Rule(
        "russia_ukraine",
        {"natural_gas_supply": -0.2, "commodity_supply": -0.2, "energy_prices": 0.2},
        _rx(r"\b(?:russia|ukraine)\b"),
        classes=_GEO_ENERGY,
    ),
    Rule(
        "port_terms",
        {"port_capacity": -0.3},
        _rx(r"\b(?:port of [a-z]+|seaports?|container terminals?|dockworkers?|longshore\w*)\b"),
        classes=_DISRUPTIVE,
    ),
    Rule(
        "trade_restrictions",
        {"regulatory_risk": 0.4, "global_trade": -0.3},
        _rx(
            r"\b(?:tariffs?|trade war|import dut(?:y|ies)|export controls?|export bans?|"
            r"embargo(?:es)?|entity list)\b"
        ),
        classes=frozenset(_EC) - {_EC.OTHER},
    ),
    Rule(
        "rates_hawkish",
        {"interest_rates": 0.5, "credit_conditions": -0.3},
        _rx(
            r"\b(?:rate hikes?|(?:raises?|raised|hikes?|hiked|lifts?) "
            r"(?:benchmark |interest |policy )?rates?|hawkish|quantitative tightening)\b"
        ),
    ),
    Rule(
        "rates_dovish",
        {"interest_rates": -0.5, "credit_conditions": 0.3},
        _rx(
            r"\b(?:rate cuts?|(?:cuts?|lowers?|lowered|slash(?:es|ed)?) "
            r"(?:benchmark |interest |policy )?rates?|dovish|quantitative easing|"
            r"monetary easing)\b"
        ),
    ),
    Rule(
        "credit_stress",
        {"credit_conditions": -0.6},
        _rx(
            r"\b(?:bank failures?|bank run|credit crunch|banking crisis|debt default|"
            r"sovereign default|liquidity crisis)\b"
        ),
    ),
    Rule(
        "demand_slump",
        {"consumer_demand": -0.4, "industrial_demand": -0.3},
        _rx(r"\b(?:recession|economic contraction|gdp contraction|economic slowdown)\b"),
    ),
)


def _validate_tables() -> None:
    known = set(CHANNELS)
    tables: list[dict[str, float]] = list(CLASS_PRIORS.values())
    tables.extend(r.contributions for r in EVIDENCE_RULES)
    for table in tables:
        for ch, v in table.items():
            if ch not in known or not -1.0 <= v <= 1.0:
                raise ValueError(f"invalid channel table entry {ch}={v}")
    if set(CLASS_PRIORS) != set(EventClass):
        raise ValueError("CLASS_PRIORS must cover every EventClass")
    if len({r.rule_id for r in EVIDENCE_RULES}) != len(EVIDENCE_RULES):
        raise ValueError("duplicate rule id")


_validate_tables()


def _scale(severity_hint: Any) -> float:
    try:
        s = float(severity_hint)
    except (TypeError, ValueError):
        return SEVERITY_FLOOR
    if math.isnan(s):
        return SEVERITY_FLOOR
    return min(1.0, max(SEVERITY_FLOOR, s))


def _entity_pairs(entities: Iterable[Any] | None) -> list[tuple[str, str]]:
    out: list[tuple[str, str]] = []
    for e in entities or ():
        canonical = getattr(e, "canonical", None)
        if isinstance(canonical, str) and canonical.strip():
            kind = getattr(e, "kind", "")
            out.append((canonical.strip(), kind.lower() if isinstance(kind, str) else ""))
    return out


def _str_items(values: Any) -> list[str]:
    if isinstance(values, str):
        return [values]
    if isinstance(values, Sequence):
        return [v for v in values if isinstance(v, str)]
    return []


def _text_of(raw: Any) -> str:
    parts: list[str] = []
    headline = getattr(raw, "headline", None)
    if isinstance(headline, str):
        parts.append(headline)
    body = getattr(raw, "body", None)
    if isinstance(body, str):
        parts.append(body)
    parts.extend(_str_items(getattr(raw, "categories", None)))
    parts.extend(_str_items(getattr(raw, "entities", None)))
    return "\n".join(parts)[:_MAX_TEXT_CHARS]


def _match_rule(
    rule: Rule,
    entities: list[tuple[str, str]],
    geo_fields: list[str],
    text: str,
) -> str | None:
    """Return the evidence id if the rule fires (entity > geo > keyword), else None."""
    for canonical, kind in entities:
        if rule.pattern is not None and rule.pattern.search(canonical):
            return f"entity:{canonical}"
        if kind in rule.kinds and not (rule.exclude and rule.exclude.search(canonical)):
            return f"entity:{canonical}"
    if rule.pattern is not None:
        for value in geo_fields:
            if rule.pattern.search(value):
                return f"geo:{value}"
        m = rule.pattern.search(text)
        if m:
            return f"keyword:{m.group(0).lower()}"
    return None


def _quantize(v: float) -> float:
    return round(round(v / _STEP) * _STEP, 2)


def extract_channels(
    event_class: EventClass,
    entities: Sequence[Any],
    geo: Any,
    raw: Any,
    severity_hint: float,
) -> tuple[dict[str, float], dict[str, list[str]]]:
    """Return ``(channels, evidence)``; see module docstring. Never raises on odd input."""
    try:
        cls = EventClass(event_class)
    except ValueError:
        cls = EventClass.OTHER

    sums: dict[str, float] = {}
    evidence: dict[str, list[str]] = {}

    def add(table: dict[str, float], rule_id: str) -> None:
        for ch, v in table.items():
            sums[ch] = sums.get(ch, 0.0) + v
            ids = evidence.setdefault(ch, [])
            if rule_id not in ids:
                ids.append(rule_id)

    add(CLASS_PRIORS.get(cls, {}), f"class:{cls.value}")

    ents = _entity_pairs(entities)
    geo_fields: list[str] = []
    for attr in ("chokepoint", "country_name", "region"):
        val = getattr(geo, attr, None)
        if isinstance(val, str) and val.strip():
            geo_fields.append(val.strip())
    text = _text_of(raw)

    for rule in EVIDENCE_RULES:
        if rule.classes is not None and cls not in rule.classes:
            continue
        hit = _match_rule(rule, ents, geo_fields, text)
        if hit is not None:
            add(rule.contributions, hit)
            for ch in rule.contributions:  # audit trail also names the rule that fired
                tag = f"rule:{rule.rule_id}"
                if tag not in evidence[ch]:
                    evidence[ch].append(tag)

    scale = _scale(severity_hint)
    channels: dict[str, float] = {}
    for ch in CHANNELS:
        if ch not in sums:
            continue
        v = max(-1.0, min(1.0, sums[ch] * scale))
        if abs(v) < MIN_ABS_VALUE:
            continue
        v = _quantize(v)
        if v != 0.0:
            channels[ch] = v
    return channels, {ch: evidence[ch] for ch in channels}
