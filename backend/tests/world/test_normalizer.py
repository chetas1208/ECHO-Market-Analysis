from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from app.world import geo as geo_mod
from app.world.channels import CHANNELS
from app.world.fingerprint import EventKey, geo_location_key, is_same_event
from app.world.fixtures import WORLD_FIXTURES
from app.world.fixtures_dedup import build_dedup_scenarios
from app.world.normalizer import NormalizationError, normalize, to_event_key
from app.world.settings import WorldSettings
from app.world.text.analyzer import TextAnalysis
from app.world.types import EventClass, GeoInfo, RawWorldEvent, SourceRef

NOW = datetime(2026, 9, 16, 12, 0, tzinfo=UTC)
SETTINGS = WorldSettings()


def _raw(**kw) -> RawWorldEvent:
    base = {
        "provider": "replay",
        "headline": "Strait of Hormuz shipping halted after tanker attack",
        "occurred_at": datetime(2026, 9, 16, 9, 0, tzinfo=UTC),
    }
    base.update(kw)
    return RawWorldEvent(**base)


def _norm(raw, **kw):
    return normalize(raw, now=NOW, settings=SETTINGS, **kw)


class FakeAnalyzer:
    def __init__(self) -> None:
        self.calls: list[str] = []

    def analyze(self, text: str):
        self.calls.append(text)
        return TextAnalysis(label="positive", scores={"positive": 0.9}, model="fake")


@pytest.mark.parametrize("key", sorted(WORLD_FIXTURES))
def test_every_fixture_matches_expectations(key: str) -> None:
    fx = WORLD_FIXTURES[key]
    n = _norm(fx.raw)
    assert n.event_class == fx.expected_class, (key, n.event_class, n.metadata["matched_terms"])
    for ch, sign in fx.expected_channels.items():
        assert ch in n.economic_channels, (key, ch, n.economic_channels)
        assert n.economic_channels[ch] * sign > 0, (key, ch, n.economic_channels[ch])
    if fx.expected_country is not None:
        assert n.geo.country == fx.expected_country, (key, n.geo)
    s = n.scores
    assert s is not None
    for v in (s.severity, s.novelty, s.corroboration, s.confidence):
        assert 0.0 <= v <= 1.0
    for ch, v in n.economic_channels.items():
        assert ch in CHANNELS
        assert -1.0 <= v <= 1.0
    assert set(n.channel_evidence) == set(n.economic_channels)
    assert n.metadata["channel_evidence"] == n.channel_evidence
    assert n.sources == list(fx.raw.sources) and n.sources
    assert n.text_sentiment is None
    assert n.metadata["is_replay"] is True
    assert n.metadata["provider"] == "replay"
    assert n.metadata["provider_event_id"] == fx.raw.provider_event_id
    assert "not probabilities" in n.metadata["score_semantics"]
    for k in (
        "classification_certainty",
        "matched_terms",
        "severity_components",
        "corroboration_components",
        "confidence_components",
    ):
        assert k in n.metadata
    assert s.novelty == 1.0
    assert s.components["novelty"] == {"note": "pipeline recomputes with history"}
    assert len(n.fingerprint) == 40


@pytest.mark.parametrize("key", sorted(WORLD_FIXTURES))
def test_deterministic(key: str) -> None:
    raw = WORLD_FIXTURES[key].raw
    assert _norm(raw) == _norm(raw)
    assert _norm(raw).fingerprint == _norm(raw.model_copy(deep=True)).fingerprint


@pytest.mark.parametrize("key", ["hormuz", "taiwan_quake", "sanction"])
def test_fingerprint_location_key_equals_geo_location_key(key: str) -> None:
    n = _norm(WORLD_FIXTURES[key].raw)
    assert geo_location_key(n.geo) == geo_mod.location_key(n.geo)


def test_location_keys_agree_for_hormuz_quake_unresolved() -> None:
    hormuz = GeoInfo(chokepoint="Strait of Hormuz", resolved=True)
    quake = GeoInfo(country="TW", country_name="Taiwan", city="Hualien", resolved=True)
    unresolved = GeoInfo()
    for g in (hormuz, quake, unresolved):
        assert geo_location_key(g) == geo_mod.location_key(g)
    assert geo_location_key(None) == "unknown"


def test_missing_location_never_raises() -> None:
    n = _norm(_raw(headline="Unspecified disruption reported", sources=[]))
    assert n.geo.resolved is False
    assert n.geo.country is None and n.geo.latitude is None
    assert geo_location_key(n.geo) == "unknown"


def test_no_sources_synthesizes_nothing() -> None:
    n = _norm(_raw(sources=[]))
    assert n.sources == []
    assert n.scores is not None
    assert n.scores.corroboration == 0.0
    ref = WORLD_FIXTURES["hormuz"].raw
    with_src = _norm(ref)
    assert with_src.scores is not None
    assert n.scores.confidence <= with_src.scores.confidence
    assert n.scores.confidence <= 0.95


def test_missing_text_gives_no_summary() -> None:
    n = _norm(_raw(body=None))
    assert n.summary is None
    n2 = _norm(_raw(body="   \n\t "))
    assert n2.summary is None


def test_summary_truncated_and_control_chars_stripped() -> None:
    body = "line one\x00\x07\nline two " + "x" * 1000
    n = _norm(_raw(body=body))
    assert n.summary is not None
    assert len(n.summary) <= 600
    assert all(ord(c) >= 32 for c in n.summary)
    assert n.summary.startswith("line one line two")


def test_title_stripped_and_truncated() -> None:
    n = _norm(_raw(headline="  " + "Oil tanker attack " * 40 + "  "))
    assert len(n.title) <= 300
    assert n.title == n.title.strip()


def test_malicious_headline_stays_plain_text() -> None:
    head = "<script>alert(1)</script>\x1b[31m Robert'); DROP TABLE events;-- tanker attack Hormuz"
    n = _norm(_raw(headline=head, body="<img src=x onerror=alert(1)>"))
    assert "<script>alert(1)</script>" in n.title
    assert "\x1b" not in n.title
    assert isinstance(n.title, str) and n.summary == "<img src=x onerror=alert(1)>"


def test_financial_headline_triggers_analyzer_geopolitical_does_not() -> None:
    fake = FakeAnalyzer()
    fin = _raw(
        headline="NVIDIA beats earnings estimates as quarterly revenue jumps",
        body="The company raised its revenue guidance and shares rose.",
    )
    n = _norm(fin, text_analyzer=fake)
    assert len(fake.calls) == 1
    assert n.text_sentiment is not None and n.text_sentiment["label"] == "positive"

    fake2 = FakeAnalyzer()
    geo_ev = _raw(headline="Missile strike escalates border conflict between two states")
    n2 = _norm(geo_ev, text_analyzer=fake2)
    assert fake2.calls == []
    assert n2.text_sentiment is None
    quake = _norm(WORLD_FIXTURES["taiwan_quake"].raw, text_analyzer=fake2)
    assert fake2.calls == [] and quake.text_sentiment is None


def test_analyzer_none_or_failing_is_tolerated() -> None:
    class Boom:
        def analyze(self, text: str):
            raise RuntimeError("x")

    class Nothing:
        def analyze(self, text: str):
            return None

    fin = _raw(headline="Apple earnings beat estimates, shares rise")
    assert _norm(fin, text_analyzer=Boom()).text_sentiment is None
    assert _norm(fin, text_analyzer=Nothing()).text_sentiment is None
    assert _norm(fin).text_sentiment is None


def test_empty_headline_raises() -> None:
    raw = RawWorldEvent.model_construct(
        provider="replay",
        headline="   ",
        occurred_at=NOW,
        body=None,
        sources=[],
        entities=[],
        categories=[],
        magnitude={},
        provider_scores={},
        is_replay=True,
        provider_event_id=None,
        country=None,
        region=None,
        city=None,
        latitude=None,
        longitude=None,
    )
    with pytest.raises(NormalizationError):
        _norm(raw)
    with pytest.raises(ValueError):  # pydantic rejects it earlier for validated construction
        _raw(headline="  ")


def test_naive_time_raises() -> None:
    raw = _raw().model_copy(update={"occurred_at": datetime(2026, 9, 16, 9, 0)})
    with pytest.raises(NormalizationError):
        _norm(raw)
    with pytest.raises(NormalizationError):
        normalize(_raw(), now=datetime(2026, 9, 16, 12, 0), settings=SETTINGS)


def test_independent_sources_raise_corroboration() -> None:
    scenarios = build_dedup_scenarios()
    one = _norm(scenarios["independent_sources"][0])
    many = [_norm(e) for e in scenarios["independent_sources"]]
    assert one.scores is not None
    assert all(m.scores is not None for m in many)
    assert max(m.scores.corroboration for m in many if m.scores) >= one.scores.corroboration


def test_to_event_key_and_same_event() -> None:
    n = _norm(WORLD_FIXTURES["hormuz"].raw)
    key = to_event_key(n)
    assert isinstance(key, EventKey)
    assert key.event_class == n.event_class
    assert key.location_key == geo_mod.location_key(n.geo)
    assert key.tokens and key.occurred_at == n.occurred_at
    same, score, _ = is_same_event(
        key, to_event_key(_norm(WORLD_FIXTURES["hormuz"].raw)), SETTINGS.dedup
    )
    assert same and score == 1.0
    other = to_event_key(_norm(WORLD_FIXTURES["cyber_incident"].raw))
    assert not is_same_event(key, other, SETTINGS.dedup)[0]


def test_aftershock_stays_distinct_after_normalization() -> None:
    a, b = build_dedup_scenarios()["aftershock"][:2]
    ka, kb = to_event_key(_norm(a)), to_event_key(_norm(b))
    assert not is_same_event(ka, kb, SETTINGS.dedup)[0]


def test_source_refs_preserved() -> None:
    ref = SourceRef(
        provider="replay",
        source_name="Replay Wire A",
        retrieved_at=NOW - timedelta(minutes=5),
        reliability=0.8,
    )
    n = _norm(_raw(sources=[ref]))
    assert n.sources == [ref]
    assert n.event_class != EventClass.OTHER
