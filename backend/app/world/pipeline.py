"""World provider to canonical-event ingestion.

This module is the persistence boundary for world intelligence. Provider payloads never cross
into it; only ``RawWorldEvent`` values are accepted. All matching and score calculations are
deterministic, while the caller owns the database session and transaction.
"""

from __future__ import annotations

import hashlib
import json
import logging
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

from app.repositories.events import EventRepository
from app.repositories.world import WorldRepository
from app.schemas.event import SourceType
from app.world.fingerprint import (
    EventKey,
    entity_keys,
    geo_location_key,
    is_same_event,
    text_tokens,
    time_bucket,
)
from app.world.normalizer import NormalizationError, normalize, to_event_key
from app.world.scoring.confidence import score_confidence
from app.world.scoring.corroboration import score_corroboration
from app.world.scoring.novelty import score_novelty
from app.world.settings import WorldSettings
from app.world.sources import SourceIndependence, classify_independence, source_group
from app.world.types import NormalizedWorldEvent, RawWorldEvent, SourceRef

logger = logging.getLogger("echo.world.pipeline")


@dataclass(frozen=True)
class IngestResult:
    action: str
    event_id: str | None = None
    source_added: bool = False
    corroboration_before: float | None = None
    corroboration_after: float | None = None
    reason: str | None = None


def _hash(value: Any) -> str:
    encoded = json.dumps(value, sort_keys=True, default=str, separators=(",", ":"))
    return hashlib.sha256(encoded.encode("utf-8", errors="replace")).hexdigest()


def _raw_hash(raw: RawWorldEvent) -> str:
    return _hash(raw.model_dump(mode="json", exclude={"is_replay"}))


def _source_hash(ref: SourceRef, raw_hash: str) -> str:
    if ref.source_identifier:
        return _hash({"provider": ref.provider, "identifier": ref.source_identifier})
    return _hash({"raw": raw_hash, "headline": ref.headline, "url": ref.source_url})


def _source_row(ref: SourceRef, content_hash: str) -> dict[str, Any]:
    return {
        "provider": ref.provider.strip() or "unknown",
        "source_name": ref.source_name.strip() or "unknown",
        "source_group": ref.source_group or source_group(ref.source_name, ref.source_url),
        "source_url": ref.source_url,
        "source_identifier": ref.source_identifier,
        "headline": ref.headline,
        "published_at": ref.published_at,
        "retrieved_at": ref.retrieved_at,
        "is_independent": True,
        "syndicated_from": ref.syndicated_from,
        "reliability": ref.reliability,
        "content_hash": content_hash,
        "metadata": dict(ref.metadata),
    }


def _refs_from_rows(rows: list[Any]) -> list[SourceRef]:
    return [
        SourceRef(
            provider=row.provider,
            source_name=row.source_name,
            source_url=row.source_url,
            source_identifier=row.source_identifier,
            headline=row.headline,
            published_at=row.published_at,
            retrieved_at=row.retrieved_at,
            source_group=row.source_group,
            syndicated_from=row.syndicated_from,
            reliability=row.reliability,
            metadata=dict(row.metadata_ or {}),
        )
        for row in rows
    ]


def _independence_map(refs: list[SourceRef]) -> list[SourceIndependence]:
    return classify_independence(refs)


def _snapshot(event: Any) -> dict[str, Any]:
    return {
        "revision": event.revision,
        "severity": event.severity,
        "novelty": event.novelty,
        "corroboration": event.corroboration,
        "confidence": event.confidence,
        "economic_channels": dict(event.economic_channels or {}),
        "source_count": event.source_count,
        "independent_source_count": event.independent_source_count,
        "updated_at": event.updated_at.isoformat() if event.updated_at else None,
    }


class WorldIngestPipeline:
    def __init__(
        self,
        session_factory: Callable[[], Any] | None,
        settings: WorldSettings,
        analyzer: Any = None,
        *,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self._session_factory = session_factory
        self._settings = settings
        self._analyzer = analyzer
        self._clock = clock or (lambda: datetime.now(UTC))
        self.counters: dict[str, int] = {
            "received": 0,
            "created": 0,
            "merged": 0,
            "duplicates": 0,
            "rejected": 0,
        }
        self.last_event_at: datetime | None = None

    async def ingest(self, raw: RawWorldEvent) -> IngestResult:
        self.counters["received"] += 1
        self.last_event_at = raw.occurred_at if raw.occurred_at else self.last_event_at
        now = self._clock()
        try:
            normalized = normalize(
                raw,
                now=now,
                settings=self._settings,
                text_analyzer=self._analyzer,
            )
        except (NormalizationError, ValueError, TypeError) as exc:
            self.counters["rejected"] += 1
            await self._dead_letter(raw, exc)
            return IngestResult("rejected", reason=str(exc)[:300])
        if self._session_factory is None:
            self.counters["rejected"] += 1
            return IngestResult("rejected", reason="database session unavailable")

        logger.info(
            "world_event_normalized",
            extra={
                "operation": "world_event_normalized",
                "provider": raw.provider,
                "fingerprint": normalized.fingerprint,
            },
        )
        async with self._session_factory() as session:
            world_repo = WorldRepository(session)
            event_repo = EventRepository(session)
            raw_hash = _raw_hash(raw)
            exact = await self._exact_event(world_repo, raw, raw_hash)
            if exact is not None:
                await session.rollback()
                self.counters["duplicates"] += 1
                return IngestResult(
                    "duplicate",
                    event_id=exact,
                    reason="provider identifier or content hash already seen",
                )

            recent_since = now - timedelta(hours=self._settings.novelty.lookback_hours)
            fingerprints = await world_repo.recent_fingerprints(recent_since)
            candidate = to_event_key(normalized)
            matched_id: str | None = None
            match_reason = ""
            for fp in fingerprints:
                other = EventKey(
                    event_class=fp.event_class,
                    entity_keys=frozenset(fp.entity_keys),
                    location_key=fp.location_key,
                    occurred_at=fp.occurred_at,
                    tokens=frozenset(fp.tokens),
                )
                same, _, reason = is_same_event(candidate, other, self._settings.dedup)
                if same:
                    matched_id, match_reason = fp.event_id, reason
                    break

            recent_keys = [
                EventKey(
                    event_class=fp.event_class,
                    entity_keys=frozenset(fp.entity_keys),
                    location_key=fp.location_key,
                    occurred_at=fp.occurred_at,
                    tokens=frozenset(fp.tokens),
                )
                for fp in fingerprints
            ]
            novelty, novelty_parts = score_novelty(
                candidate, recent_keys, self._settings.novelty, now
            )
            assert normalized.scores is not None
            normalized.scores.novelty = novelty
            normalized.scores.components["novelty"] = novelty_parts
            if matched_id:
                result = await self._merge(session, matched_id, normalized, raw_hash, match_reason)
                await session.commit()
                self.counters["merged"] += 1
                return result

            event_id = f"evt_world_{normalized.fingerprint}"
            values = _event_values(event_id, normalized, raw, now)
            created = await event_repo.insert(values)
            if created is None:
                await session.rollback()
                self.counters["duplicates"] += 1
                return IngestResult(
                    "duplicate", event_id=event_id, reason="canonical id already exists"
                )
            refs = normalized.sources
            independence = _independence_map(refs)
            for index, ref in enumerate(refs):
                row = _source_row(ref, _source_hash(ref, raw_hash))
                row["metadata"]["raw_content_hash"] = raw_hash
                row["is_independent"] = independence[index].independent
                row["syndicated_from"] = independence[index].syndicated_of or ref.syndicated_from
                await world_repo.add_source(event_id, row)
            await world_repo.upsert_fingerprint(
                event_id,
                fingerprint=normalized.fingerprint,
                event_class=normalized.event_class.value,
                location_key=geo_location_key(normalized.geo),
                time_bucket=time_bucket(normalized.occurred_at, self._settings.dedup),
                entity_keys=entity_keys(normalized.entities),
                tokens=text_tokens(normalized.title),
                occurred_at=normalized.occurred_at,
            )
            await session.commit()
            self.counters["created"] += 1
            logger.info(
                "event_persisted",
                extra={
                    "operation": "event_persisted",
                    "event_id": event_id,
                    "provider": raw.provider,
                },
            )
            return IngestResult(
                "created",
                event_id=event_id,
                source_added=bool(refs),
                corroboration_before=0.0,
                corroboration_after=normalized.scores.corroboration,
            )

    async def _exact_event(
        self, repo: WorldRepository, raw: RawWorldEvent, raw_hash: str
    ) -> str | None:
        if raw.provider_event_id:
            found = await repo.find_by_provider_event_id(raw.provider, raw.provider_event_id)
            if found:
                return found
        return await repo.find_by_raw_content_hash(raw_hash) or await repo.find_by_content_hash(
            raw_hash
        )

    async def _merge(
        self,
        session: Any,
        event_id: str,
        normalized: NormalizedWorldEvent,
        raw_hash: str,
        reason: str,
    ) -> IngestResult:
        event_repo = EventRepository(session)
        world_repo = WorldRepository(session)
        event = await event_repo.get(event_id)
        if event is None:
            return IngestResult("rejected", reason="candidate event disappeared")
        rows = await world_repo.list_sources(event_id)
        refs = _refs_from_rows(rows) + normalized.sources
        independence = _independence_map(refs)
        before = float(event.corroboration)
        added = False
        for index, ref in enumerate(normalized.sources, start=len(rows)):
            row = _source_row(ref, _source_hash(ref, raw_hash))
            row["metadata"]["raw_content_hash"] = raw_hash
            row["is_independent"] = independence[index].independent
            row["syndicated_from"] = independence[index].syndicated_of or ref.syndicated_from
            added = await world_repo.add_source(event_id, row) or added
        if not added:
            return IngestResult(
                "duplicate", event_id=event_id, reason="source evidence already persisted"
            )
        persisted_refs = _refs_from_rows(await world_repo.list_sources(event_id))
        persisted_independence = _independence_map(persisted_refs)
        corr, _corr_parts = score_corroboration(
            persisted_refs, persisted_independence, self._settings.corroboration
        )
        reliability = [r.reliability for r in persisted_refs if r.reliability is not None]
        confidence, _conf_parts = score_confidence(
            classification_certainty=normalized.metadata.get("classification_certainty"),
            geo_resolved=normalized.geo.resolved,
            entity_count=len(normalized.entities),
            corroboration=corr,
            source_reliability_mean=sum(reliability) / len(reliability) if reliability else None,
            has_text=bool(normalized.summary),
        )
        revision = max(1, int(event.revision)) + 1
        await world_repo.add_revision(event_id, revision, _snapshot(event), reason)
        await world_repo.update_event_scores(
            event_id,
            severity=max(
                float(event.severity),
                float(normalized.scores.severity if normalized.scores else event.severity),
            ),
            novelty=float(normalized.scores.novelty if normalized.scores else event.novelty),
            corroboration=corr,
            confidence=confidence,
            economic_channels=normalized.economic_channels,
            source_count=len(persisted_refs),
            independent_source_count=sum(1 for item in persisted_independence if item.independent),
            revision=revision,
        )
        await world_repo.upsert_fingerprint(
            event_id,
            fingerprint=normalized.fingerprint,
            event_class=normalized.event_class.value,
            location_key=geo_location_key(normalized.geo),
            time_bucket=time_bucket(normalized.occurred_at, self._settings.dedup),
            entity_keys=entity_keys(normalized.entities),
            tokens=text_tokens(normalized.title),
            occurred_at=normalized.occurred_at,
        )
        return IngestResult(
            "merged",
            event_id=event_id,
            source_added=True,
            corroboration_before=before,
            corroboration_after=corr,
            reason=reason,
        )

    async def _dead_letter(self, raw: RawWorldEvent, exc: Exception) -> None:
        if self._session_factory is None:
            return
        try:
            async with self._session_factory() as session:
                await WorldRepository(session).record_ingest_error(
                    provider=getattr(raw, "provider", "unknown"),
                    error=f"{type(exc).__name__}: {exc}",
                    payload_hash=_raw_hash(raw) if isinstance(raw, RawWorldEvent) else None,
                    payload_excerpt=getattr(raw, "headline", None),
                )
                await session.commit()
        except Exception:
            logger.exception(
                "world ingest dead-letter write failed", extra={"operation": "world_ingest_error"}
            )


def _event_values(
    event_id: str, n: NormalizedWorldEvent, raw: RawWorldEvent, now: datetime
) -> dict[str, Any]:
    scores = n.scores
    assert scores is not None
    return {
        "id": event_id,
        "timestamp": n.occurred_at,
        "source_type": SourceType.WORLD.value.upper(),
        "event_type": n.event_class.value,
        "title": n.title,
        "summary": n.summary,
        "entities": [e.canonical for e in n.entities],
        "companies": [e.canonical for e in n.entities if e.kind == "company"],
        "locations": [
            v for v in (n.geo.country_name, n.geo.region, n.geo.city, n.geo.chokepoint) if v
        ],
        "economic_channels": n.economic_channels,
        "severity": scores.severity,
        "novelty": scores.novelty,
        "corroboration": scores.corroboration,
        "confidence": scores.confidence,
        "source_refs": [ref.model_dump(mode="json") for ref in n.sources],
        # The ORM attribute is ``metadata_`` because ``metadata`` is reserved by
        # SQLAlchemy's declarative base. The database column remains ``metadata``.
        "metadata_": {
            **n.metadata,
            "fingerprint": n.fingerprint,
            "channel_evidence": n.channel_evidence,
            "text_sentiment": n.text_sentiment,
            "score_components": scores.components,
        },
        "is_mock": raw.is_replay,
        "revision": 1,
        "source_count": len(n.sources),
        "independent_source_count": sum(
            1 for item in _independence_map(n.sources) if item.independent
        ),
        "ingested_at": now,
    }
