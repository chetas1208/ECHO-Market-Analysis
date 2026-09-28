"""Persistence for Day 3 world-event tables. All SQL for them lives here.

The repository never commits; the caller owns the transaction. Untrusted text (payload
excerpts, error strings) is bound as parameters only and has NUL characters stripped, which
Postgres text cannot store. Scores are heuristic values in [0, 1], not probabilities.
"""

from collections.abc import Iterable, Mapping, Sequence
from datetime import datetime
from typing import Any

from sqlalchemy import func, select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import (
    CanonicalEvent,
    EventFingerprint,
    EventRelationship,
    EventRevision,
    EventSource,
    WorldIngestError,
)

MAX_RECENT_FINGERPRINTS = 500
MAX_PAYLOAD_EXCERPT_CHARS = 500
MAX_ERROR_CHARS = 2000

_SOURCE_COLUMNS = frozenset(
    {
        "provider",
        "source_name",
        "source_group",
        "source_url",
        "source_identifier",
        "headline",
        "published_at",
        "retrieved_at",
        "is_independent",
        "syndicated_from",
        "reliability",
        "content_hash",
        "metadata",
    }
)


def _clean(text: str, limit: int) -> str:
    return text.replace("\x00", "")[:limit]


class WorldRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    # -- event_sources ---------------------------------------------------------------------

    async def add_source(self, event_id: str, ref_row: Mapping[str, Any]) -> bool:
        """Append a source; True if inserted, False if (event_id, content_hash) already exists.

        ``ref_row`` keys are the event_sources columns (``metadata`` accepted for the JSON
        column). Unknown keys raise ``ValueError`` rather than being silently dropped.
        """
        unknown = set(ref_row) - _SOURCE_COLUMNS
        if unknown:
            raise ValueError(f"unknown event_sources fields: {sorted(unknown)}")
        values = {k: v for k, v in ref_row.items() if k != "metadata"}
        values["metadata_"] = dict(ref_row.get("metadata") or {})
        stmt = (
            insert(EventSource)
            .values(event_id=event_id, **values)
            .on_conflict_do_nothing(constraint="uq_event_sources_event_id_content_hash")
            .returning(EventSource.id)
        )
        return (await self.session.execute(stmt)).scalar_one_or_none() is not None

    async def list_sources(self, event_id: str) -> list[EventSource]:
        """Sources for an event, oldest first (stable by id)."""
        rows = await self.session.execute(
            select(EventSource).where(EventSource.event_id == event_id).order_by(EventSource.id)
        )
        return list(rows.scalars().all())

    async def find_by_provider_event_id(self, provider: str, source_identifier: str) -> str | None:
        """Event id already holding a source with this provider-side identifier (earliest)."""
        row = await self.session.execute(
            select(EventSource.event_id)
            .where(
                EventSource.provider == provider, EventSource.source_identifier == source_identifier
            )
            .order_by(EventSource.id)
            .limit(1)
        )
        return row.scalar_one_or_none()

    async def find_by_content_hash(self, content_hash: str) -> str | None:
        """Return the event already holding a source with this content hash."""
        row = await self.session.execute(
            select(EventSource.event_id)
            .where(EventSource.content_hash == content_hash)
            .order_by(EventSource.id)
            .limit(1)
        )
        return row.scalar_one_or_none()

    async def find_by_raw_content_hash(self, content_hash: str) -> str | None:
        """Return an event whose source metadata records the raw payload hash."""
        row = await self.session.execute(
            select(EventSource.event_id)
            .where(EventSource.metadata_.contains({"raw_content_hash": content_hash}))
            .order_by(EventSource.id)
            .limit(1)
        )
        return row.scalar_one_or_none()

    # -- event_fingerprints ----------------------------------------------------------------

    async def upsert_fingerprint(
        self,
        event_id: str,
        *,
        fingerprint: str,
        event_class: str,
        location_key: str,
        time_bucket: int,
        entity_keys: Iterable[str],
        tokens: Iterable[str],
        occurred_at: datetime,
    ) -> None:
        values = {
            "fingerprint": fingerprint,
            "event_class": event_class,
            "location_key": location_key,
            "time_bucket": time_bucket,
            "entity_keys": sorted(entity_keys),
            "tokens": sorted(tokens),
            "occurred_at": occurred_at,
        }
        stmt = insert(EventFingerprint).values(event_id=event_id, **values)
        stmt = stmt.on_conflict_do_update(index_elements=[EventFingerprint.event_id], set_=values)
        await self.session.execute(stmt)

    async def recent_fingerprints(
        self, since: datetime, limit: int = MAX_RECENT_FINGERPRINTS
    ) -> list[EventFingerprint]:
        """Fingerprints with occurred_at >= ``since``, newest first; ``limit`` clamped to 1..500."""
        bounded = max(1, min(int(limit), MAX_RECENT_FINGERPRINTS))
        rows = await self.session.execute(
            select(EventFingerprint)
            .where(EventFingerprint.occurred_at >= since)
            .order_by(EventFingerprint.occurred_at.desc(), EventFingerprint.event_id.asc())
            .limit(bounded)
        )
        return list(rows.scalars().all())

    # -- event_revisions (append-only) ----------------------------------------------------

    async def add_revision(
        self, event_id: str, revision: int, snapshot: Mapping[str, Any], reason: str
    ) -> None:
        """Append a revision snapshot. A duplicate (event_id, revision) raises IntegrityError."""
        await self.session.execute(
            insert(EventRevision).values(
                event_id=event_id, revision=revision, snapshot=dict(snapshot), reason=reason
            )
        )

    async def list_revisions(self, event_id: str) -> list[EventRevision]:
        rows = await self.session.execute(
            select(EventRevision)
            .where(EventRevision.event_id == event_id)
            .order_by(EventRevision.revision)
        )
        return list(rows.scalars().all())

    # -- world_ingest_errors ---------------------------------------------------------------

    async def record_ingest_error(
        self,
        *,
        provider: str,
        error: str,
        payload_hash: str | None = None,
        payload_excerpt: str | None = None,
    ) -> int:
        """Dead-letter a rejected payload. The excerpt is capped at 500 characters."""
        excerpt = (
            None if payload_excerpt is None else _clean(payload_excerpt, MAX_PAYLOAD_EXCERPT_CHARS)
        )
        row = await self.session.execute(
            insert(WorldIngestError)
            .values(
                provider=_clean(provider, MAX_ERROR_CHARS),
                error=_clean(error, MAX_ERROR_CHARS),
                payload_hash=payload_hash,
                payload_excerpt=excerpt,
            )
            .returning(WorldIngestError.id)
        )
        return row.scalar_one()

    # -- canonical_events: the ONLY mutation path ------------------------------------------

    async def update_event_scores(
        self,
        event_id: str,
        *,
        severity: float,
        novelty: float,
        corroboration: float,
        confidence: float,
        economic_channels: Mapping[str, float],
        source_count: int,
        independent_source_count: int,
        revision: int,
    ) -> bool:
        """Update score/derived columns of an event and stamp ``updated_at``.

        Touches ONLY these columns (plus ``updated_at``); title, timestamp, entities, source
        refs etc. are never modified. Returns False when the event does not exist.
        """
        stmt = (
            update(CanonicalEvent)
            .where(CanonicalEvent.id == event_id)
            .values(
                severity=severity,
                novelty=novelty,
                corroboration=corroboration,
                confidence=confidence,
                economic_channels=dict(economic_channels),
                source_count=source_count,
                independent_source_count=independent_source_count,
                revision=revision,
                updated_at=func.clock_timestamp(),
            )
            .returning(CanonicalEvent.id)
            .execution_options(synchronize_session=False)
        )
        return (await self.session.execute(stmt)).scalar_one_or_none() is not None

    # -- event_relationships (stub: no attribution logic) ----------------------------------

    async def add_relationship(
        self,
        source_event_id: str,
        target_event_id: str,
        relationship_type: str,
        confidence: float,
    ) -> bool:
        """Idempotent on (source, target, type); True if inserted."""
        stmt = (
            insert(EventRelationship)
            .values(
                source_event_id=source_event_id,
                target_event_id=target_event_id,
                relationship_type=relationship_type,
                confidence=confidence,
            )
            .on_conflict_do_nothing(constraint="uq_event_relationships_pair_type")
            .returning(EventRelationship.id)
        )
        return (await self.session.execute(stmt)).scalar_one_or_none() is not None

    async def list_relationships(self, event_id: str) -> Sequence[EventRelationship]:
        rows = await self.session.execute(
            select(EventRelationship)
            .where(
                (EventRelationship.source_event_id == event_id)
                | (EventRelationship.target_event_id == event_id)
            )
            .order_by(EventRelationship.id)
        )
        return list(rows.scalars().all())
