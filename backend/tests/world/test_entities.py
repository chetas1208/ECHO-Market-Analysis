"""Entity normalization/extraction: pure, deterministic, no DB/network."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest
import yaml

from app.world import entities as ent
from app.world.entities import COMPANY_TICKERS, extract_entities, normalize_entity
from app.world.types import RawWorldEvent

UNIVERSE = Path(__file__).resolve().parents[2] / "config" / "universe.yaml"


def _raw(headline: str, **kw) -> RawWorldEvent:
    return RawWorldEvent(
        provider="replay",
        headline=headline,
        occurred_at=datetime(2026, 9, 16, 9, 0, tzinfo=UTC),
        **kw,
    )


def _canon(raw: RawWorldEvent) -> list[str]:
    return [e.canonical for e in extract_entities(raw)]


# ---------------------------------------------------------------- alias collapse


@pytest.mark.parametrize(
    ("name", "canonical", "kind"),
    [
        ("US", "United States", "country"),
        ("U.S.", "United States", "country"),
        ("USA", "United States", "country"),
        ("U.S.A.", "United States", "country"),
        ("United States", "United States", "country"),
        ("united states of america", "United States", "country"),
        ("the US", "United States", "country"),
        ("UK", "United Kingdom", "country"),
        ("UAE", "United Arab Emirates", "country"),
        ("Russian Federation", "Russia", "country"),
        ("ROC", "Taiwan", "country"),
        ("Republic of China", "Taiwan", "country"),
        ("Türkiye", "Turkey", "country"),
        ("NVIDIA", "NVIDIA", "company"),
        ("Nvidia Corp.", "NVIDIA", "company"),
        ("NVIDIA Corporation", "NVIDIA", "company"),
        ("nvidia corp", "NVIDIA", "company"),
        ("NVIDIA CORP", "NVIDIA", "company"),
        ("$NVDA", "NVIDIA", "company"),
        ("TSMC", "TSMC", "company"),
        ("Taiwan Semiconductor", "TSMC", "company"),
        ("Taiwan Semiconductor Manufacturing Co., Ltd.", "TSMC", "company"),
        ("JPMorgan Chase & Co.", "JPMorgan Chase", "company"),
        ("Brent", "crude oil", "commodity"),
        ("WTI", "crude oil", "commodity"),
        ("Brent crude", "crude oil", "commodity"),
        ("LNG", "liquefied natural gas", "commodity"),
        ("Strait of Hormuz", "Strait of Hormuz", "infrastructure"),
        ("Hormuz", "Strait of Hormuz", "infrastructure"),
        ("Bab-el-Mandeb", "Bab el-Mandeb", "infrastructure"),
        ("Bab al-Mandab", "Bab el-Mandeb", "infrastructure"),
        ("Port of Shanghai", "Port of Shanghai", "infrastructure"),
        ("TSMC fabs", "TSMC fabs", "infrastructure"),
        ("Middle East", "Middle East", "region"),
        ("South China Sea", "South China Sea", "region"),
        ("OPEC", "OPEC", "organization"),
        ("Opec", "OPEC", "organization"),
        ("NATO", "NATO", "organization"),
        ("Fed", "Federal Reserve", "organization"),
    ],
)
def test_alias_collapse(name: str, canonical: str, kind: str) -> None:
    e = normalize_entity(name)
    assert e is not None
    assert (e.canonical, e.kind) == (canonical, kind)
    assert e.raw == name


def test_pronoun_never_normalizes() -> None:
    assert normalize_entity("us") is None
    assert normalize_entity("Us") is None
    assert normalize_entity("fed") is None


def test_alias_tables_are_large_enough_and_unambiguous() -> None:
    by_kind: dict[str, set[str]] = {}
    for a in ent._ALIASES:
        by_kind.setdefault(a.kind, set()).add(a.canonical)
    assert len(by_kind["country"]) >= 60
    assert {"region", "commodity", "infrastructure", "organization", "company", "city"} <= set(
        by_kind
    )
    # every alias key resolves to exactly one canonical (module raises at import otherwise)
    for a in ent._ALIASES:
        if a.text not in ent._STRICT:
            hit = normalize_entity(a.text)
            assert hit is not None and hit.canonical == a.canonical, a.text


# ---------------------------------------------------------------- ticker map


def test_ticker_map_covers_universe() -> None:
    universe = yaml.safe_load(UNIVERSE.read_text(encoding="utf-8"))
    equities = {s["symbol"] for s in universe["symbols"] if s["role"] == "equity"}
    assert set(COMPANY_TICKERS.values()) == equities
    assert len(set(COMPANY_TICKERS.values())) == len(COMPANY_TICKERS)
    assert COMPANY_TICKERS["NVIDIA"] == "NVDA"
    assert COMPANY_TICKERS["TSMC"] == "TSM"


def test_every_tracked_company_normalizes_by_name_and_ticker() -> None:
    for company, ticker in COMPANY_TICKERS.items():
        by_name = normalize_entity(company)
        assert by_name is not None and by_name.kind == "company"
        assert by_name.canonical == company
        by_ticker = normalize_entity(ticker)
        assert by_ticker is not None
        if ticker == "LNG":
            # LNG means liquefied natural gas, never Cheniere
            assert by_ticker.canonical == "liquefied natural gas"
        else:
            assert by_ticker.canonical == company


def test_company_scan_with_suffixes_and_aliases() -> None:
    raw = _raw("Nvidia Corp. and Taiwan Semiconductor Manufacturing Co. rally; Exxon, Google slip")
    assert _canon(raw) == ["NVIDIA", "TSMC", "ExxonMobil", "Alphabet"]


def test_ambiguous_words_are_case_sensitive() -> None:
    # apple (fruit), meta-analysis, intel (lowercase), jordan/chad as names
    assert _canon(_raw("apple prices; meta analysis; military intel; chad and jordan talk")) == []
    assert _canon(_raw("Apple and Meta report; Jordan and Chad")) == [
        "Apple",
        "Meta Platforms",
        "Jordan",
        "Chad",
    ]


# ---------------------------------------------------------------- pronoun 'us' guard


def test_pronoun_us_is_not_united_states() -> None:
    assert _canon(_raw("Tell us what happened; let us know and give us time")) == []
    assert _canon(_raw("Officials gave us the numbers", body="Between us and them, nothing.")) == []
    # all-caps headline: bare US is ambiguous and ignored
    assert _canon(_raw("WHAT THEY TOLD US ABOUT BRENT")) == ["crude oil"]
    assert "United States" not in _canon(_raw("WHAT THEY TOLD US ABOUT THE FUTURE"))


@pytest.mark.parametrize(
    "headline",
    [
        "US sanctions hit exporters",
        "Trade talks between US and China",
        "U.S. Treasury tightens rules",
        "New US-China tariffs",
        "United States warns Iran",
        "USA imposes curbs",
    ],
)
def test_united_states_forms_match(headline: str) -> None:
    assert "United States" in _canon(_raw(headline))


def test_us_and_pronoun_in_same_sentence() -> None:
    assert _canon(_raw("Tell us why the US acted")) == ["United States"]


def test_dotted_us_matches_even_in_all_caps() -> None:
    assert "United States" in _canon(_raw("U.S. SANCTIONS ON IRAN"))


# ---------------------------------------------------------------- longest match


def test_strait_of_hormuz_beats_hormuz() -> None:
    es = extract_entities(_raw("Tanker seized in the Strait of Hormuz"))
    assert [(e.canonical, e.raw) for e in es] == [("Strait of Hormuz", "Strait of Hormuz")]
    lone = extract_entities(_raw("Traffic through Hormuz slows"))
    assert [(e.canonical, e.raw) for e in lone] == [("Strait of Hormuz", "Hormuz")]


def test_longest_alias_wins_over_contained_shorter_ones() -> None:
    assert _canon(_raw("Tensions rise in the Taiwan Strait")) == ["Taiwan Strait"]
    assert _canon(_raw("Vessels avoid the South China Sea")) == ["South China Sea"]
    assert _canon(_raw("Delays at the Port of Shanghai")) == ["Port of Shanghai"]
    assert _canon(_raw("Taiwan Semiconductor Manufacturing Company guides higher")) == ["TSMC"]
    assert _canon(_raw("Quake near TSMC fabs")) == ["TSMC fabs"]
    assert _canon(_raw("Attack in the Gulf of Aden, off Yemen")) == ["Gulf of Aden", "Yemen"]
    assert _canon(_raw("Bank of America lifts Brent forecast")) == ["Bank of America", "crude oil"]


def test_hyphen_and_case_variants_in_text() -> None:
    assert _canon(_raw("Houthi drones near bab-el-mandeb")) == ["Houthis", "Bab el-Mandeb"]
    assert _canon(_raw("Asia-Pacific and Asia Pacific markets")) == ["Asia-Pacific"]


def test_word_boundaries() -> None:
    assert _canon(_raw("Iranian officials; Indiana; Omaha; Suezanne; Chinatown")) == []


# ---------------------------------------------------------------- unknown kept, never invented


def test_unknown_provider_entities_kept_as_other() -> None:
    raw = _raw("Local firm halts output", entities=["Acme  Frobnicator Ltd", "  ", "OPEC"])
    es = extract_entities(raw)
    assert [(e.canonical, e.kind, e.raw) for e in es] == [
        ("Acme Frobnicator Ltd", "other", "Acme Frobnicator Ltd"),
        ("OPEC", "organization", "OPEC"),
    ]
    assert normalize_entity("Acme Frobnicator") is None


def test_unknown_provider_fields_use_field_kind_and_iso2_resolves() -> None:
    es = extract_entities(_raw("Report", country="TW", region="Zzyzx Basin", city="Tarapoto"))
    assert [(e.canonical, e.kind) for e in es] == [
        ("Taiwan", "country"),
        ("Zzyzx Basin", "region"),
        ("Tarapoto", "city"),
    ]
    only = extract_entities(_raw("Report", country="Freedonia"))
    assert [(e.canonical, e.kind) for e in only] == [("Freedonia", "country")]


def test_nothing_invented_from_plain_text() -> None:
    assert _canon(_raw("Quarterly results beat expectations, shares rise")) == []


# ---------------------------------------------------------------- order + de-dupe


def test_provider_entities_first_then_headline_then_body() -> None:
    raw = _raw(
        "Iran threatens Strait of Hormuz shipping",
        body="OPEC+ and Brent react; Japan imports at risk near Hormuz.",
        entities=["Brent", "OPEC"],
        country="Iran",
        region="Persian Gulf",
        city="Dubai",
    )
    assert _canon(raw) == [
        "crude oil",
        "OPEC",
        "Iran",
        "Persian Gulf",
        "Dubai",
        "Strait of Hormuz",
        "OPEC+",
        "Japan",
    ]


def test_dedupe_keeps_first_occurrence_and_provider_raw() -> None:
    raw = _raw(
        "Hormuz closure: US Navy, U.S. allies and the United States respond",
        body="Strait of Hormuz again; US again",
        entities=["strait of hormuz"],
    )
    es = extract_entities(raw)
    assert [e.canonical for e in es] == ["Strait of Hormuz", "United States"]
    assert es[0].raw == "strait of hormuz"
    assert es[1].raw == "US"


def test_ordering_is_stable_and_deterministic() -> None:
    raw = _raw(
        "Suez Canal, Panama Canal and Taiwan Strait delays hit copper and wheat",
        body="Japan, Germany and Brazil exposed; Nvidia and AMD warn",
        entities=["Zeta Corp", "Alpha Widgets"],
    )
    first = extract_entities(raw)
    for _ in range(5):
        assert extract_entities(raw) == first
    assert [e.canonical for e in first] == [
        "Zeta Corp",
        "Alpha Widgets",
        "Suez Canal",
        "Panama Canal",
        "Taiwan Strait",
        "copper",
        "wheat",
        "Japan",
        "Germany",
        "Brazil",
        "NVIDIA",
        "AMD",
    ]


def test_body_only_scan_and_none_body() -> None:
    assert _canon(_raw("Update", body="Shipping through the Suez Canal resumed")) == ["Suez Canal"]
    assert _canon(_raw("Update", body=None)) == []


# ---------------------------------------------------------------- empty input


def test_empty_input() -> None:
    assert normalize_entity("") is None
    assert normalize_entity("   ") is None
    assert normalize_entity("$") is None
    assert extract_entities(_raw("x")) == []
    assert extract_entities(_raw("Nothing to see", body="")) == []
    assert extract_entities(_raw("x", entities=["", "  "], country=" ", region="", city="")) == []
