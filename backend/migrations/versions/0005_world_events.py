"""world events: sources, fingerprints, revisions, relationships, ingest errors

Revision ID: 0005
Revises: 0004
Create Date: 2026-09-21

Day 3 (World Monitor + Event Intelligence). Additive only; 0001-0004 are untouched.

- event_sources: one row per piece of evidence for an event. UNIQUE (event_id, content_hash)
  makes source appends idempotent. FK to canonical_events is ON DELETE RESTRICT, so an event
  with evidence can never be deleted.
- event_fingerprints: dedup index (one row per event).
- event_revisions: append-only history of prior event state. Same enforcement as the forecast
  ledger (0002/0004): BEFORE UPDATE/DELETE row trigger + BEFORE TRUNCATE statement trigger,
  ENABLE ALWAYS so a superuser's ``session_replication_role = replica`` cannot bypass them.
  The trigger function ``echo_forbid_ledger_mutation()`` is owned by 0002 and reused here.
- event_relationships: table only (no attribution logic yet).
- world_ingest_errors: dead-letter log for rejected provider payloads (excerpt <= 500 chars).
- canonical_events: revision / updated_at / source_count / independent_source_count, and an
  index on severity. Existing rows get the defaults (1 / NULL / 1 / 1).

Scores are heuristic values in [0, 1]; they are not probabilities.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0005"
down_revision: str | None = "0004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

REVISIONS_TRIGGERS = ("trg_event_revisions_immutable_row", "trg_event_revisions_immutable_truncate")


def upgrade() -> None:
    # --- canonical_events additions ------------------------------------------------------
    op.execute(
        """
        ALTER TABLE canonical_events
            ADD COLUMN revision                 integer     NOT NULL DEFAULT 1,
            ADD COLUMN updated_at               timestamptz,
            ADD COLUMN source_count             integer     NOT NULL DEFAULT 1,
            ADD COLUMN independent_source_count integer     NOT NULL DEFAULT 1,
            ADD CONSTRAINT ck_canonical_events_revision_positive CHECK (revision >= 1),
            ADD CONSTRAINT ck_canonical_events_source_count_nonneg CHECK (source_count >= 0),
            ADD CONSTRAINT ck_canonical_events_independent_source_count_nonneg
                CHECK (independent_source_count >= 0)
        """
    )
    op.execute("CREATE INDEX ix_canonical_events_severity ON canonical_events (severity)")

    # --- event_sources ---------------------------------------------------------------------
    op.execute(
        """
        CREATE TABLE event_sources (
            id                bigserial PRIMARY KEY,
            event_id          text NOT NULL,
            provider          text NOT NULL,
            source_name       text NOT NULL,
            source_group      text,
            source_url        text,
            source_identifier text,
            headline          text,
            published_at      timestamptz,
            retrieved_at      timestamptz NOT NULL,
            is_independent    boolean NOT NULL,
            syndicated_from   text,
            reliability       numeric,
            content_hash      text NOT NULL,
            metadata          jsonb NOT NULL DEFAULT '{}'::jsonb,
            created_at        timestamptz NOT NULL DEFAULT now(),
            CONSTRAINT fk_event_sources_event_id_canonical_events
                FOREIGN KEY (event_id) REFERENCES canonical_events (id) ON DELETE RESTRICT,
            CONSTRAINT ck_event_sources_provider_nonempty CHECK (length(btrim(provider)) > 0),
            CONSTRAINT ck_event_sources_content_hash_nonempty
                CHECK (length(btrim(content_hash)) > 0),
            CONSTRAINT ck_event_sources_reliability_unit
                CHECK (reliability IS NULL OR reliability BETWEEN 0 AND 1),
            CONSTRAINT ck_event_sources_metadata_object CHECK (jsonb_typeof(metadata) = 'object'),
            CONSTRAINT uq_event_sources_event_id_content_hash UNIQUE (event_id, content_hash)
        )
        """
    )
    op.execute("CREATE INDEX ix_event_sources_event_id ON event_sources (event_id)")
    op.execute(
        "CREATE INDEX ix_event_sources_provider_source_identifier "
        "ON event_sources (provider, source_identifier)"
    )

    # --- event_fingerprints ----------------------------------------------------------------
    op.execute(
        """
        CREATE TABLE event_fingerprints (
            event_id     text PRIMARY KEY,
            fingerprint  text NOT NULL,
            event_class  text NOT NULL,
            location_key text NOT NULL,
            time_bucket  bigint NOT NULL,
            entity_keys  jsonb NOT NULL,
            tokens       jsonb NOT NULL,
            occurred_at  timestamptz NOT NULL,
            CONSTRAINT fk_event_fingerprints_event_id_canonical_events
                FOREIGN KEY (event_id) REFERENCES canonical_events (id) ON DELETE RESTRICT,
            CONSTRAINT ck_event_fingerprints_entity_keys_array
                CHECK (jsonb_typeof(entity_keys) = 'array'),
            CONSTRAINT ck_event_fingerprints_tokens_array CHECK (jsonb_typeof(tokens) = 'array')
        )
        """
    )
    op.execute("CREATE INDEX ix_event_fingerprints_fingerprint ON event_fingerprints (fingerprint)")
    op.execute(
        "CREATE INDEX ix_event_fingerprints_occurred_at_desc "
        "ON event_fingerprints (occurred_at DESC)"
    )

    # --- event_revisions (append-only) ----------------------------------------------------
    op.execute(
        """
        CREATE TABLE event_revisions (
            id         bigserial PRIMARY KEY,
            event_id   text NOT NULL,
            revision   integer NOT NULL,
            snapshot   jsonb NOT NULL,
            reason     text NOT NULL,
            created_at timestamptz NOT NULL DEFAULT now(),
            CONSTRAINT fk_event_revisions_event_id_canonical_events
                FOREIGN KEY (event_id) REFERENCES canonical_events (id) ON DELETE RESTRICT,
            CONSTRAINT ck_event_revisions_revision_positive CHECK (revision >= 1),
            CONSTRAINT ck_event_revisions_snapshot_object CHECK (jsonb_typeof(snapshot) = 'object'),
            CONSTRAINT uq_event_revisions_event_id_revision UNIQUE (event_id, revision)
        )
        """
    )
    op.execute(
        """
        CREATE TRIGGER trg_event_revisions_immutable_row
            BEFORE UPDATE OR DELETE ON event_revisions
            FOR EACH ROW EXECUTE FUNCTION echo_forbid_ledger_mutation()
        """
    )
    op.execute(
        """
        CREATE TRIGGER trg_event_revisions_immutable_truncate
            BEFORE TRUNCATE ON event_revisions
            FOR EACH STATEMENT EXECUTE FUNCTION echo_forbid_ledger_mutation()
        """
    )
    for trigger in REVISIONS_TRIGGERS:
        op.execute(f"ALTER TABLE event_revisions ENABLE ALWAYS TRIGGER {trigger}")

    # --- event_relationships (table only; no attribution logic yet) -----------------------
    op.execute(
        """
        CREATE TABLE event_relationships (
            id                bigserial PRIMARY KEY,
            source_event_id   text NOT NULL,
            target_event_id   text NOT NULL,
            relationship_type text NOT NULL,
            confidence        numeric NOT NULL,
            created_at        timestamptz NOT NULL DEFAULT now(),
            CONSTRAINT fk_event_relationships_source_event_id_canonical_events
                FOREIGN KEY (source_event_id) REFERENCES canonical_events (id) ON DELETE RESTRICT,
            CONSTRAINT fk_event_relationships_target_event_id_canonical_events
                FOREIGN KEY (target_event_id) REFERENCES canonical_events (id) ON DELETE RESTRICT,
            CONSTRAINT ck_event_relationships_relationship_type
                CHECK (relationship_type IN ('RELATED', 'POSSIBLE_CAUSE', 'REACTION_TO')),
            CONSTRAINT ck_event_relationships_confidence_unit CHECK (confidence BETWEEN 0 AND 1),
            CONSTRAINT ck_event_relationships_no_self_reference
                CHECK (source_event_id <> target_event_id),
            CONSTRAINT uq_event_relationships_pair_type
                UNIQUE (source_event_id, target_event_id, relationship_type)
        )
        """
    )
    op.execute(
        "CREATE INDEX ix_event_relationships_target_event_id "
        "ON event_relationships (target_event_id)"
    )

    # --- world_ingest_errors (dead letter) -------------------------------------------------
    op.execute(
        """
        CREATE TABLE world_ingest_errors (
            id              bigserial PRIMARY KEY,
            provider        text NOT NULL,
            error           text NOT NULL,
            payload_hash    text,
            payload_excerpt text,
            created_at      timestamptz NOT NULL DEFAULT now(),
            CONSTRAINT ck_world_ingest_errors_payload_excerpt_max
                CHECK (payload_excerpt IS NULL OR char_length(payload_excerpt) <= 500)
        )
        """
    )
    op.execute("CREATE INDEX ix_world_ingest_errors_created_at ON world_ingest_errors (created_at)")


def downgrade() -> None:
    # Dropping the tables drops their triggers, indexes and constraints. The shared trigger
    # function echo_forbid_ledger_mutation() belongs to 0002 and is left in place.
    op.execute("DROP TABLE IF EXISTS world_ingest_errors")
    op.execute("DROP TABLE IF EXISTS event_relationships")
    op.execute("DROP TABLE IF EXISTS event_revisions")
    op.execute("DROP TABLE IF EXISTS event_fingerprints")
    op.execute("DROP TABLE IF EXISTS event_sources")
    op.execute("DROP INDEX IF EXISTS ix_canonical_events_severity")
    op.execute(
        """
        ALTER TABLE canonical_events
            DROP CONSTRAINT IF EXISTS ck_canonical_events_independent_source_count_nonneg,
            DROP CONSTRAINT IF EXISTS ck_canonical_events_source_count_nonneg,
            DROP CONSTRAINT IF EXISTS ck_canonical_events_revision_positive,
            DROP COLUMN IF EXISTS independent_source_count,
            DROP COLUMN IF EXISTS source_count,
            DROP COLUMN IF EXISTS updated_at,
            DROP COLUMN IF EXISTS revision
        """
    )
