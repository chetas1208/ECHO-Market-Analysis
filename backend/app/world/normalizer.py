"""Compose the world-event pipeline stages into one ``NormalizedWorldEvent`` (pure, no I/O).

Stages: classify -> extract_entities -> normalize_geo -> score_severity ->
extract_channels(severity_hint=severity) -> classify_independence -> event_fingerprint ->
corroboration -> confidence.  Novelty is NOT computed here (it needs history): it defaults to
1.0 and the ingest pipeline recomputes it against recent events.

Rules
- Never invent data: no location -> unresolved ``GeoInfo``; no sources -> ``sources=[]`` and
  corroboration 0.0 (confidence reflects it); no body -> ``summary=None``.
- Only an empty headline or a naive timestamp raises :class:`NormalizationError`.
- Text is untrusted: ``title``/``summary`` are plain text with control characters removed; no
  markup is interpreted here and the frontend renders text only.
- The optional financial text analyzer runs ONLY when ``is_financial_text`` gates the text in
  (company/market text), never for geopolitical/disaster text. Its output goes in
  ``text_sentiment`` and never influences severity/channels/class.
- Deterministic: ``now`` is passed in; no clock, no randomness.
- All scores are HEURISTIC in [0,1], not probabilities; channels are directional pressure in
  [-1, 1], not expected % moves.
"""

from __future__ import annotations

import unicodedata
from datetime import datetime
from typing import Any

from app.world.channels import extract_channels
from app.world.entities import extract_entities
from app.world.fingerprint import (
    EventKey,
    entity_keys,
    event_fingerprint,
    geo_location_key,
    text_tokens,
)
from app.world.geo import normalize_geo
from app.world.scoring.confidence import score_confidence
from app.world.scoring.corroboration import score_corroboration
from app.world.scoring.severity import score_severity
from app.world.settings import WorldSettings
from app.world.sources import classify_independence
from app.world.taxonomy import classify
from app.world.text.analyzer import is_financial_text
from app.world.types import EventScores, NormalizedWorldEvent, RawWorldEvent

TITLE_MAX = 300
SUMMARY_MAX = 600
NOVELTY_NOTE = "pipeline recomputes with history"
SCORE_SEMANTICS = (
    "severity/novelty/corroboration/confidence are heuristic scores in [0,1], not probabilities; "
    "economic channels are directional pressure in [-1,1], not expected price moves"
)


class NormalizationError(ValueError):
    """Raw event cannot be normalized (empty headline / naive timestamp)."""


def _plain(text: str | None, limit: int) -> str:
    """Strip control/format chars, collapse whitespace, truncate to ``limit`` characters."""
    if not text:
        return ""
    cleaned = "".join(
        " " if ch.isspace() else ch
        for ch in str(text)
        if ch.isspace() or unicodedata.category(ch) not in ("Cc", "Cf", "Cs", "Co", "Cn")
    )
    return " ".join(cleaned.split())[:limit].strip()


def _analyze_text(text_analyzer: Any, text: str) -> dict[str, Any] | None:
    try:
        result = text_analyzer.analyze(text)
    except Exception:  # analyzers must not raise, but a bad one must not break ingest
        return None
    if result is None:
        return None
    if hasattr(result, "model_dump"):
        return dict(result.model_dump(mode="json"))
    return dict(result) if isinstance(result, dict) else None


def normalize(
    raw: RawWorldEvent,
    *,
    now: datetime,
    settings: WorldSettings,
    text_analyzer: Any = None,
) -> NormalizedWorldEvent:
    """Normalize one provider-agnostic raw event. Raises only :class:`NormalizationError`."""
    if not isinstance(raw.headline, str):
        raise NormalizationError("headline must be a string")
    title = _plain(raw.headline, TITLE_MAX)
    if not title:
        raise NormalizationError("headline is empty")
    if raw.occurred_at is None or raw.occurred_at.tzinfo is None:
        raise NormalizationError("occurred_at must be timezone-aware")
    if now is None or now.tzinfo is None:
        raise NormalizationError("now must be timezone-aware")
    summary = _plain(raw.body, SUMMARY_MAX) or None

    event_class, certainty, matched_terms = classify(raw)
    entities = extract_entities(raw)
    geo = normalize_geo(raw, entities)
    severity, sev_components = score_severity(event_class, entities, geo, raw, settings.severity)
    channels, channel_evidence = extract_channels(event_class, entities, geo, raw, severity)

    sources = list(raw.sources)
    independence = classify_independence(sources)
    corroboration, corr_components = score_corroboration(
        sources, independence, settings.corroboration
    )

    reliabilities = [s.reliability for s in sources if s.reliability is not None]
    reliability_mean = sum(reliabilities) / len(reliabilities) if reliabilities else None
    has_text = summary is not None
    confidence, conf_components = score_confidence(
        classification_certainty=certainty,
        geo_resolved=geo.resolved,
        entity_count=len(entities),
        corroboration=corroboration,
        source_reliability_mean=reliability_mean,
        has_text=has_text,
    )

    fingerprint = event_fingerprint(event_class, entities, geo, raw.occurred_at, settings.dedup)

    text_sentiment: dict[str, Any] | None = None
    if text_analyzer is not None and is_financial_text(f"{raw.headline} {raw.body or ''}"):
        text_sentiment = _analyze_text(text_analyzer, f"{title}. {summary or ''}".strip())

    scores = EventScores(
        severity=severity,
        novelty=1.0,
        corroboration=corroboration,
        confidence=confidence,
        components={
            "severity": sev_components,
            "novelty": {"note": NOVELTY_NOTE},
            "corroboration": corr_components,
            "confidence": conf_components,
        },
    )
    metadata: dict[str, Any] = {
        "classification_certainty": certainty,
        "matched_terms": list(matched_terms),
        "provider": raw.provider,
        "provider_event_id": raw.provider_event_id,
        "is_replay": raw.is_replay,
        "severity_components": sev_components,
        "corroboration_components": corr_components,
        "confidence_components": conf_components,
        "channel_evidence": channel_evidence,
        "score_semantics": SCORE_SEMANTICS,
        "normalized_at": now.isoformat(),
    }
    return NormalizedWorldEvent(
        event_class=event_class,
        title=title,
        summary=summary,
        occurred_at=raw.occurred_at,
        geo=geo,
        entities=entities,
        economic_channels=channels,
        channel_evidence=channel_evidence,
        sources=sources,
        fingerprint=fingerprint,
        scores=scores,
        text_sentiment=text_sentiment,
        metadata=metadata,
    )


def to_event_key(n: NormalizedWorldEvent) -> EventKey:
    """Build the ``EventKey`` used by ``is_same_event`` / novelty from a normalized event."""
    return EventKey(
        event_class=n.event_class,
        entity_keys=entity_keys(n.entities),
        location_key=geo_location_key(n.geo),
        occurred_at=n.occurred_at,
        tokens=text_tokens(n.title),
    )
