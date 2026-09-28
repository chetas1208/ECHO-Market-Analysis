"""Deterministic event taxonomy: provider categories -> keyword/phrase rules -> OTHER.

`classify(raw)` returns ``(EventClass, classification_certainty, matched_evidence)``.

Method (no ML, no I/O, no clock, no randomness):

1. Provider categories/tags are normalised and looked up in an explicit table.
   * STRONG categories (e.g. "earthquake", "cyber attack", "sanctions") vote for a class by
     themselves (score +3.0).
   * WEAK categories (e.g. "energy", "geopolitics", "markets") are too generic to classify
     alone; they only corroborate a class that already has keyword evidence (+1.0).
2. Headline + body are scanned with word-boundary, case-insensitive rules. A rule is either a
   set of alternative anchor patterns, or an (anchors, contexts) pair that needs one of each
   (e.g. "strait of hormuz" AND tanker/naval/blockade). A rule that fires contributes at most
   once per event: 1.0 when its anchor is in the headline, 0.5 when only in the body.
3. The class with the highest total score wins; ties are broken by the fixed `CLASS_PRIORITY`
   (specific/causal classes before broad ones). No signal -> `EventClass.OTHER`, certainty 0.2.

Certainty is a HEURISTIC in [0.25, 0.95] for matched classes (never a probability):
``0.30 + 0.12 * min(keyword_score, 3) + 0.35 (strong category) + 0.10 (weak category)
- 0.10 (runner-up within 1.0 of the winner)``; explicit category plus several keyword hits
therefore scores highest. All input is untrusted: text is length-capped, Unicode-normalised
(NFKC), and every pattern is a simple bounded regex (no nested quantifiers).
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass

from app.world.types import EventClass, RawWorldEvent

E = EventClass

# Fixed tie-break order: earlier wins on equal score. Specific/causal classes first.
CLASS_PRIORITY: tuple[EventClass, ...] = (
    E.CYBER_INCIDENT,
    E.NATURAL_DISASTER,
    E.PORT_DISRUPTION,
    E.SHIPPING_DISRUPTION,
    E.ENERGY_SUPPLY_DISRUPTION,
    E.TECHNOLOGY_SUPPLY_SHOCK,
    E.INFRASTRUCTURE_OUTAGE,
    E.SANCTION,
    E.MILITARY_CONFLICT,
    E.GEOPOLITICAL_ESCALATION,
    E.COMMODITY_SHOCK,
    E.MACRO_EVENT,
    E.REGULATORY_EVENT,
    E.OTHER,
)

CLASS_LABELS: dict[EventClass, str] = {
    E.GEOPOLITICAL_ESCALATION: "Geopolitical escalation",
    E.MILITARY_CONFLICT: "Military conflict",
    E.SANCTION: "Sanctions",
    E.REGULATORY_EVENT: "Regulatory event",
    E.SHIPPING_DISRUPTION: "Shipping disruption",
    E.PORT_DISRUPTION: "Port disruption",
    E.ENERGY_SUPPLY_DISRUPTION: "Energy supply disruption",
    E.COMMODITY_SHOCK: "Commodity shock",
    E.NATURAL_DISASTER: "Natural disaster",
    E.CYBER_INCIDENT: "Cyber incident",
    E.INFRASTRUCTURE_OUTAGE: "Infrastructure outage",
    E.TECHNOLOGY_SUPPLY_SHOCK: "Technology supply shock",
    E.MACRO_EVENT: "Macro event",
    E.OTHER: "Other",
}

# UI filter groups: geopolitics | energy | supply_chain | technology | macro | other.
# Commodities are grouped with energy; natural disasters with supply chain (their main
# transmission route); regulation with macro (policy).
CATEGORY_GROUP: dict[EventClass, str] = {
    E.GEOPOLITICAL_ESCALATION: "geopolitics",
    E.MILITARY_CONFLICT: "geopolitics",
    E.SANCTION: "geopolitics",
    E.REGULATORY_EVENT: "macro",
    E.SHIPPING_DISRUPTION: "supply_chain",
    E.PORT_DISRUPTION: "supply_chain",
    E.ENERGY_SUPPLY_DISRUPTION: "energy",
    E.COMMODITY_SHOCK: "energy",
    E.NATURAL_DISASTER: "supply_chain",
    E.CYBER_INCIDENT: "technology",
    E.INFRASTRUCTURE_OUTAGE: "technology",
    E.TECHNOLOGY_SUPPLY_SHOCK: "technology",
    E.MACRO_EVENT: "macro",
    E.OTHER: "other",
}

OTHER_CERTAINTY = 0.2
_MAX_HEADLINE = 2_000
_MAX_BODY = 20_000
_MAX_CATEGORIES = 50
_MAX_CATEGORY_LEN = 100
_MAX_EVIDENCE = 16

_STRONG_CATEGORY_SCORE = 3.0
_WEAK_CATEGORY_SCORE = 1.0

# --------------------------------------------------------------------------------------
# Provider category / tag table (keys normalised: lowercase, separators -> single space)
# --------------------------------------------------------------------------------------

_STRONG_CATEGORIES: dict[str, EventClass] = {
    **dict.fromkeys(
        (
            "earthquake",
            "earthquakes",
            "natural disaster",
            "natural disasters",
            "disaster",
            "disasters",
            "wildfire",
            "wildfires",
            "flood",
            "floods",
            "hurricane",
            "typhoon",
            "cyclone",
            "tsunami",
            "volcano",
            "volcanic eruption",
            "severe weather",
            "extreme weather",
        ),
        E.NATURAL_DISASTER,
    ),
    **dict.fromkeys(
        (
            "cyber",
            "cyber attack",
            "cyberattack",
            "cyber incident",
            "cybersecurity",
            "cyber security",
            "ransomware",
            "data breach",
            "security breach",
            "hacking",
            "malware",
        ),
        E.CYBER_INCIDENT,
    ),
    **dict.fromkeys(
        ("sanction", "sanctions", "embargo", "export sanctions", "economic sanctions"),
        E.SANCTION,
    ),
    **dict.fromkeys(
        (
            "military",
            "military conflict",
            "armed conflict",
            "conflict",
            "war",
            "terrorism",
            "airstrike",
            "airstrikes",
        ),
        E.MILITARY_CONFLICT,
    ),
    **dict.fromkeys(
        (
            "geopolitical escalation",
            "escalation",
            "diplomatic crisis",
            "political unrest",
            "unrest",
        ),
        E.GEOPOLITICAL_ESCALATION,
    ),
    **dict.fromkeys(
        (
            "regulation",
            "regulatory",
            "regulatory event",
            "antitrust",
            "tariff",
            "tariffs",
            "trade policy",
        ),
        E.REGULATORY_EVENT,
    ),
    **dict.fromkeys(
        ("shipping", "shipping disruption", "maritime", "freight", "maritime security"),
        E.SHIPPING_DISRUPTION,
    ),
    **dict.fromkeys(
        ("port", "ports", "port disruption", "port closure", "port strike"),
        E.PORT_DISRUPTION,
    ),
    **dict.fromkeys(
        (
            "energy supply",
            "energy supply disruption",
            "energy disruption",
            "pipeline",
            "refinery",
            "oil supply",
            "gas supply",
        ),
        E.ENERGY_SUPPLY_DISRUPTION,
    ),
    **dict.fromkeys(
        ("commodity", "commodities", "commodity shock", "commodity prices"),
        E.COMMODITY_SHOCK,
    ),
    **dict.fromkeys(
        (
            "outage",
            "outages",
            "infrastructure outage",
            "internet outage",
            "service outage",
            "blackout",
            "power outage",
        ),
        E.INFRASTRUCTURE_OUTAGE,
    ),
    **dict.fromkeys(
        (
            "semiconductor",
            "semiconductors",
            "chips",
            "export controls",
            "technology supply",
            "chip shortage",
        ),
        E.TECHNOLOGY_SUPPLY_SHOCK,
    ),
    **dict.fromkeys(
        (
            "macro",
            "macroeconomics",
            "macro event",
            "monetary policy",
            "central bank",
            "central banks",
            "inflation",
            "interest rates",
            "economic data",
            "economic indicators",
            "employment",
        ),
        E.MACRO_EVENT,
    ),
}

# Generic tags: only reinforce a class that already has keyword evidence.
_WEAK_CATEGORIES: dict[str, EventClass] = {
    **dict.fromkeys(
        ("geopolitics", "geopolitical", "politics", "diplomacy", "international relations"),
        E.GEOPOLITICAL_ESCALATION,
    ),
    **dict.fromkeys(("security", "defense", "defence"), E.MILITARY_CONFLICT),
    **dict.fromkeys(("policy", "legal", "law", "trade", "government"), E.REGULATORY_EVENT),
    **dict.fromkeys(
        ("logistics", "supply chain", "transport", "transportation"), E.SHIPPING_DISRUPTION
    ),
    **dict.fromkeys(("energy", "oil", "gas", "oil and gas", "power"), E.ENERGY_SUPPLY_DISRUPTION),
    **dict.fromkeys(("metals", "agriculture", "markets"), E.COMMODITY_SHOCK),
    **dict.fromkeys(("weather", "environment"), E.NATURAL_DISASTER),
    **dict.fromkeys(("technology", "tech"), E.TECHNOLOGY_SUPPLY_SHOCK),
    **dict.fromkeys(("infrastructure", "internet"), E.INFRASTRUCTURE_OUTAGE),
    **dict.fromkeys(("economy", "economics", "finance"), E.MACRO_EVENT),
}

# --------------------------------------------------------------------------------------
# Keyword / phrase rules
# --------------------------------------------------------------------------------------


def _rx(pattern: str) -> re.Pattern[str]:
    """Compile with Unicode word boundaries on both ends (text is pre-lowercased)."""
    return re.compile(rf"(?<!\w)(?:{pattern})(?!\w)")


@dataclass(frozen=True)
class _Rule:
    anchors: re.Pattern[str]
    contexts: re.Pattern[str] | None = None


def _rule(anchors: str, contexts: str | None = None) -> _Rule:
    return _Rule(_rx(anchors), _rx(contexts) if contexts else None)


def _no_prefix(*words: str) -> str:
    """Negative lookbehinds so e.g. 'trade war' is not a military 'war'."""
    return "".join(f"(?<!{w} )" for w in words)


_SPIKE = (
    r"price spikes?|spikes?|spiking|surges?|surged|surging|soars?|soared|soaring|jumps?|jumped|"
    r"plunges?|plunged|plunging|crash(?:es|ed|ing)?|tumbles?|tumbled|plummets?|plummeted|"
    r"skyrockets?|skyrocketed|slumps?|slumped|record highs?|record lows?|rall(?:y|ies|ied)|"
    r"sell-?off|rout|shock|spike"
)

_RULES: dict[EventClass, tuple[_Rule, ...]] = {
    E.SHIPPING_DISRUPTION: (
        _rule(
            r"strait of hormuz|hormuz|suez canal|red sea|bab[ -]el[ -]mandeb|panama canal|"
            r"strait of malacca|malacca strait|black sea|gulf of aden",
            r"naval|navy|tankers?|blockad(?:e|es|ed|ing)|shipping|vessels?|cargo ships?|"
            r"container ships?|freighters?|maritime|closure|closed|seiz(?:e|es|ed|ure)|"
            r"rerout(?:e|es|ed|ing)|convoys?|transit",
        ),
        _rule(
            r"tankers?|cargo ships?|container ships?|freighters?|merchant (?:vessels?|ships?)|"
            r"bulk carriers?|vessels?",
            r"seiz(?:e|es|ed|ure)|hijack(?:s|ed|ing)?|attack(?:s|ed)?|struck|hit by|grounded|"
            r"stranded|collid(?:e|es|ed)|collision|rerout(?:e|es|ed|ing)|diverted|boarded|"
            r"blocked|sunk|detained|missiles?|drones?",
        ),
        _rule(
            r"shipping (?:disruptions?|lanes?|routes?|delays?|crisis|costs?|rates?|halts?)|"
            r"freight rates?|container rates?|(?:naval|maritime|sea) blockades?|blockade of|"
            r"maritime (?:disruptions?|security|chokepoints?)|chokepoints?"
        ),
    ),
    E.PORT_DISRUPTION: (
        _rule(
            r"port (?:closures?|shutdowns?|strikes?|congestion|blockades?|disruptions?|delays?|"
            r"workers?)|closure of (?:the )?port|dock ?workers?|longshoremen|stevedores?|"
            r"(?:ports?|harbou?rs?) (?:closed|shut)"
        ),
        _rule(
            r"ports?|seaports?|harbou?rs?|container terminals?",
            r"clos(?:e|es|ed|ure|ures|ing)|shut(?:s|ting)?[ -]?down|shutdowns?|shut|strikes?|"
            r"walkouts?|congestion|suspend(?:s|ed)?|halt(?:s|ed)?|blocked|blockade|paralys[ie]d?|"
            r"work stoppage|stoppage",
        ),
    ),
    E.ENERGY_SUPPLY_DISRUPTION: (
        _rule(
            r"pipelines?|refiner(?:y|ies)|oil ?fields?|gas ?fields?|"
            r"oil (?:terminals?|facilit(?:y|ies)|depots?|platforms?|rigs?|wells?|"
            r"export terminals?)|"
            r"(?:lng|gas|power) (?:terminals?|plants?|facilit(?:y|ies)|stations?)|nord stream|"
            r"petrochemical (?:plants?|complex(?:es)?)|storage tanks?",
            r"attack(?:s|ed)?|shut(?:s|ting)?[ -]?down|shutdowns?|explosions?|explod(?:e|es|ed)|"
            r"fires?|halt(?:s|ed)?|sabotag(?:e|ed)|drones?|strikes?|struck|offline|leaks?|"
            r"ruptures?|damag(?:e|ed|es)|suspend(?:s|ed)?|force majeure|disrupt(?:s|ed|ion|ions)?|"
            r"blasts?|closed|closure|curtail(?:s|ed|ment)?|blockade|hit by",
        ),
        _rule(
            r"(?:oil|gas|energy|fuel|crude|lng)[ -](?:supply )?"
            r"(?:disruptions?|shortages?|crisis|cuts?|crunch)|force majeure|"
            r"(?:production|output) cuts?|fuel shortages?"
        ),
        _rule(
            r"opec\+?",
            r"cuts?|cutting|reduc(?:e|es|ed|tion|tions)|output|production|quotas?|curbs?",
        ),
    ),
    E.TECHNOLOGY_SUPPLY_SHOCK: (
        _rule(
            r"export controls?|chip shortages?|semiconductor shortages?|chip supply|"
            r"semiconductor supply|gpu shortages?|memory shortages?|wafer shortages?|"
            r"chip (?:export )?(?:bans?|restrictions?|curbs|embargo)|entity list|"
            r"rare earths? (?:export|shortage)s?"
        ),
        _rule(
            r"chips?|semiconductors?|fabs?|foundr(?:y|ies)|wafers?|gpus?|tsmc|rare earths?|"
            r"chipmakers?|memory chips?",
            r"shortages?|export controls?|export restrictions?|restrictions?|"
            r"supply (?:disruption|crunch|cuts?)|shut(?:s|ting)?[ -]?down|shutdowns?|"
            r"halt(?:s|ed)?|curbs?|shortfalls?|constrain(?:ed|ts?)|allocation|bans?|banned|"
            r"licen[cs]e requirements?|suspend(?:s|ed)?",
        ),
    ),
    E.INFRASTRUCTURE_OUTAGE: (
        _rule(
            r"clouds?|data ?cent(?:er|re)s?|aws|amazon web services|azure|google cloud|gcp|"
            r"cloudflare|telecoms?|telecommunications?|internet|power grids?|"
            r"electric(?:al)? grids?|"
            r"payment (?:systems?|networks?|processors?)|air traffic control",
            r"outages?|down ?time|went down|goes down|going down|(?:is|are|was|were) down|"
            r"blackouts?|failures?|offline|disruptions?|service interruptions?|glitch(?:es)?|"
            r"degraded",
        ),
        _rule(
            r"(?:power|electricity) (?:outages?|blackouts?|cuts?)|blackouts?|"
            r"(?:major|widespread|global|massive|nationwide|large-scale|service) outages?|"
            r"grid failures?"
        ),
    ),
    E.CYBER_INCIDENT: (
        _rule(r"ransomware|malware|spyware|ddos|zero-day|phishing"),
        _rule(
            r"cyber[ -]?(?:attacks?|incidents?|espionage|intrusions?|crimes?|"
            r"security (?:incidents?|breach(?:es)?))"
        ),
        _rule(r"hack(?:s|ed|er|ers|ing)?|hacktivists?"),
        _rule(r"data (?:breach(?:es)?|leaks?)|security breach(?:es)?|data theft|stolen data"),
        _rule(
            r"breach(?:es|ed)?",
            r"data|customers?|security|networks?|systems?|hackers?|records|accounts|passwords|"
            r"credentials|personal information|users?",
        ),
        _rule(
            r"(?:systems?|networks?|servers?|files) (?:compromised|infiltrated|encrypted)|"
            r"exfiltrat(?:e|es|ed|ion)"
        ),
    ),
    E.NATURAL_DISASTER: (
        _rule(r"earthquakes?|quakes?|tremors?|aftershocks?|seismic"),
        _rule(r"magnitude \d|richter"),
        _rule(r"typhoons?|hurricanes?|cyclones?|tornado(?:es|s)?|storm surge|blizzards?"),
        _rule(r"tsunamis?|floods?|flooding|flash floods?|landslides?|mudslides?"),
        _rule(r"wildfires?|volcan(?:o|oes|ic)|eruptions?|droughts?|heat ?waves?"),
    ),
    E.SANCTION: (
        _rule(r"sanction(?:s|ed|ing)?"),
        _rule(r"embargo(?:es|ed)?"),
        _rule(
            r"ofac|asset freezes?|freez(?:e|es|ing) (?:of )?(?:\w+ )?assets|frozen assets|"
            r"blacklist(?:s|ed)?|price cap"
        ),
    ),
    E.MILITARY_CONFLICT: (
        _rule(
            r"missiles?|shelling|artillery|bombardment|bombing|bombed|warplanes?|fighter jets?|"
            r"rocket (?:attacks?|fire|barrage)"
        ),
        _rule(r"air ?strikes?|drone strikes?"),
        _rule(
            r"troops?|soldiers?|invasion|invad(?:e|es|ed|ing)|ground offensive|"
            r"military (?:operations?|offensive|campaign|strikes?|clashes?)|"
            r"front ?line|battlefield|casualties"
        ),
        _rule(
            _no_prefix(
                "trade",
                "price",
                "currency",
                "bidding",
                "culture",
                "talent",
                "streaming",
                "tech",
                "chip",
                "cold",
                "tariff",
            )
            + r"wars?|warfare|armed conflict|cease-?fire|truce"
        ),
    ),
    E.GEOPOLITICAL_ESCALATION: (
        _rule(r"escalat(?:e|es|ed|ing|ion)"),
        _rule(
            r"tensions?|stand-?offs?|brink of war|saber[ -]rattling|flashpoints?|ultimatum|"
            r"heightened tensions?"
        ),
        _rule(
            r"diplomatic (?:row|crisis|spat|tensions?|rift|standoff)|"
            r"(?:expels?|expelled|recalls?|recalled|summons?|summoned) (?:\w+ ){0,2}"
            r"(?:ambassadors?|diplomats?|envoys?)|coups?|unrest|"
            r"retaliat(?:e|es|ed|ion|ory)|border (?:disputes?|standoffs?|tensions?)|"
            r"territorial disputes?|nuclear (?:threats?|tests?)"
        ),
        _rule(
            r"military (?:drills?|exercises?|buildup|build-up)|war games|peace talks|"
            r"talks collapse"
        ),
    ),
    E.COMMODITY_SHOCK: (
        _rule(
            r"oil|crude(?: oil)?|brent|wti|natural gas|gas|gold|silver|copper|nickel|"
            r"alumin(?:i)?um|zinc|lithium|cobalt|uranium|iron ore|steel|wheat|corn|soybeans?|"
            r"rice|sugar|coffee|cocoa|cotton|palm oil|cattle|commodit(?:y|ies)|metals?|grains?|"
            r"fertili[sz]er|coal|lng|diesel|gasoline|jet fuel|rare earths?",
            _SPIKE,
        ),
        _rule(
            r"commodit(?:y|ies) (?:price )?(?:shocks?|spikes?|crash(?:es)?|rout|rally|surge|"
            r"slump|sell-?off)|price shocks?|"
            r"(?:energy|oil|gas|food|fuel|commodity|commodities|metal|grain) prices? "
            r"(?:spike|surge|soar|jump|plunge|crash|tumble|plummet|skyrocket|slump|collapse)"
            r"(?:s|d|ed|es|ing)?"
        ),
    ),
    E.MACRO_EVENT: (
        _rule(
            r"rate decisions?|interest rate (?:decisions?|hikes?|cuts?|rises?|increases?|moves?)|"
            r"rate (?:hikes?|cuts?)|fomc|monetary policy|hawkish|dovish"
        ),
        _rule(
            r"cpi|consumer price index|ppi|producer prices?|inflation(?: data| report| figures|"
            r" reading| print| rate| surges?| cools?| eases| accelerates| slows?)?|deflation"
        ),
        _rule(
            r"jobs report|non-?farm payrolls?|payrolls|unemployment rate|jobless claims|"
            r"employment (?:data|report)|job (?:gains|losses|growth)"
        ),
        _rule(
            r"gdp(?: growth| data| figures| report| contraction| contracts)?|recession|"
            r"economic (?:growth|contraction|data|slowdown)|retail sales|pmi|"
            r"industrial production|trade deficit"
        ),
        _rule(
            r"fed|federal reserve|ecb|european central bank|bank of england|boe|bank of japan|"
            r"boj|pboc|rbi|central banks?|treasury yields?|bond yields?",
            r"rates?|hik(?:e|es|ed|ing)|cuts?|holds?|raises?|decision|policy|inflation|"
            r"tighten(?:s|ing)?|easing|meeting|minutes|yield",
        ),
    ),
    E.REGULATORY_EVENT: (
        _rule(
            r"tariffs?|import dut(?:y|ies)|anti-?dumping|customs dut(?:y|ies)|"
            r"trade (?:barriers?|restrictions?)|quotas?"
        ),
        _rule(
            r"anti-?trust|competition (?:authority|commission|regulator|watchdog|probe|law)|"
            r"monopol(?:y|ies)|merger (?:review|blocked|probe)"
        ),
        _rule(
            r"regulat(?:ion|ions|or|ors|ory|e|es|ed|ing)|deregulat\w{0,10}|legislation|"
            r"rulemaking|new laws?|fined|lawsuits?|court ruling"
        ),
        _rule(r"bans?|banned|banning|prohibit(?:s|ed|ion)"),
    ),
}

_DASHES = re.compile(r"[\u2010-\u2015\u2212]")
_WS = re.compile(r"\s+")
_CATEGORY_SEP = re.compile(r"[_\-/:>|,;]+")


def _prep(text: str | None, cap: int) -> str:
    """Cap, NFKC-normalise, lowercase, unify dashes, collapse whitespace."""
    if not text:
        return ""
    s = unicodedata.normalize("NFKC", text[:cap]).lower()
    s = _DASHES.sub("-", s)
    return _WS.sub(" ", s).strip()


def _category_keys(raw_category: str) -> list[str]:
    """Normalised lookup keys for one provider tag: the whole tag, then its segments."""
    whole = _prep(raw_category[:_MAX_CATEGORY_LEN], _MAX_CATEGORY_LEN)
    keys: list[str] = []
    for candidate in (whole, *re.split(r"[:/>|,;]", whole)):
        norm = _WS.sub(" ", _CATEGORY_SEP.sub(" ", candidate)).strip()
        if norm and norm not in keys:
            keys.append(norm)
    return keys


def _scan_rule(rule: _Rule, headline: str, body: str) -> tuple[float, list[str]] | None:
    weight = 1.0
    m = rule.anchors.search(headline)
    if m is None:
        m = rule.anchors.search(body)
        weight = 0.5
    if m is None:
        return None
    terms = [m.group(0)]
    if rule.contexts is not None:
        c = rule.contexts.search(headline) or rule.contexts.search(body)
        if c is None:
            return None
        terms.append(c.group(0))
    return weight, terms


def classify(raw: RawWorldEvent) -> tuple[EventClass, float, list[str]]:
    """Return (event_class, classification_certainty in [0,1], matched evidence terms)."""
    headline = _prep(raw.headline, _MAX_HEADLINE)
    body = _prep(raw.body, _MAX_BODY)

    strong: dict[EventClass, list[str]] = {}
    weak: dict[EventClass, list[str]] = {}
    for raw_cat in raw.categories[:_MAX_CATEGORIES]:
        if not isinstance(raw_cat, str):
            continue
        for key in _category_keys(raw_cat):
            if key in _STRONG_CATEGORIES:
                strong.setdefault(_STRONG_CATEGORIES[key], []).append(f"category:{key}")
            elif key in _WEAK_CATEGORIES:
                weak.setdefault(_WEAK_CATEGORIES[key], []).append(f"category:{key}")

    kw_score: dict[EventClass, float] = {}
    kw_terms: dict[EventClass, list[str]] = {}
    for cls, rules in _RULES.items():
        for rule in rules:
            hit = _scan_rule(rule, headline, body)
            if hit is None:
                continue
            kw_score[cls] = kw_score.get(cls, 0.0) + hit[0]
            kw_terms.setdefault(cls, []).extend(hit[1])

    totals: dict[EventClass, float] = {}
    for cls in CLASS_PRIORITY:
        if cls is E.OTHER:
            continue
        kw = kw_score.get(cls, 0.0)
        total = kw
        if cls in strong:
            total += _STRONG_CATEGORY_SCORE
        if cls in weak and kw > 0:
            total += _WEAK_CATEGORY_SCORE
        if total > 0:
            totals[cls] = total

    if not totals:
        return E.OTHER, OTHER_CERTAINTY, []

    order = {cls: i for i, cls in enumerate(CLASS_PRIORITY)}
    ranked = sorted(totals, key=lambda c: (-totals[c], order[c]))
    winner = ranked[0]

    certainty = 0.30 + 0.12 * min(kw_score.get(winner, 0.0), 3.0)
    evidence: list[str] = []
    if winner in strong:
        certainty += 0.35
        evidence.extend(strong[winner])
    if winner in weak and kw_score.get(winner, 0.0) > 0:
        certainty += 0.10
        evidence.extend(weak[winner])
    if len(ranked) > 1 and totals[winner] - totals[ranked[1]] < 1.0:
        certainty -= 0.10
    certainty = round(min(0.95, max(0.25, certainty)), 4)

    evidence.extend(kw_terms.get(winner, []))
    deduped = list(dict.fromkeys(evidence))[:_MAX_EVIDENCE]
    return winner, certainty, deduped
