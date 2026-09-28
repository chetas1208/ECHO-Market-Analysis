"""canonical_events

Revision ID: 0001
Revises:
Create Date: 2026-09-20
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE canonical_events (
            id                text PRIMARY KEY,
            timestamp         timestamptz NOT NULL,
            source_type       text NOT NULL,
            event_type        text NOT NULL,
            title             text NOT NULL,
            summary           text,
            entities          jsonb NOT NULL DEFAULT '[]'::jsonb,
            companies         jsonb NOT NULL DEFAULT '[]'::jsonb,
            locations         jsonb NOT NULL DEFAULT '[]'::jsonb,
            economic_channels jsonb NOT NULL DEFAULT '{}'::jsonb,
            severity          numeric NOT NULL,
            novelty           numeric NOT NULL,
            corroboration     numeric NOT NULL,
            confidence        numeric NOT NULL,
            source_refs       jsonb NOT NULL DEFAULT '[]'::jsonb,
            metadata          jsonb NOT NULL DEFAULT '{}'::jsonb,
            is_mock           boolean NOT NULL DEFAULT false,
            created_at        timestamptz NOT NULL DEFAULT now(),
            ingested_at       timestamptz NOT NULL DEFAULT now(),
            CONSTRAINT ck_canonical_events_id_format CHECK (id ~ '^evt_[a-z0-9_]+$'),
            CONSTRAINT ck_canonical_events_source_type
                CHECK (source_type IN ('WORLD', 'MARKET', 'FINANCIAL')),
            CONSTRAINT ck_canonical_events_title_nonempty CHECK (length(btrim(title)) > 0),
            CONSTRAINT ck_canonical_events_entities_array
                CHECK (jsonb_typeof(entities) = 'array'),
            CONSTRAINT ck_canonical_events_companies_array
                CHECK (jsonb_typeof(companies) = 'array'),
            CONSTRAINT ck_canonical_events_locations_array
                CHECK (jsonb_typeof(locations) = 'array'),
            CONSTRAINT ck_canonical_events_economic_channels_object
                CHECK (jsonb_typeof(economic_channels) = 'object'),
            CONSTRAINT ck_canonical_events_source_refs_array
                CHECK (jsonb_typeof(source_refs) = 'array'),
            CONSTRAINT ck_canonical_events_metadata_object
                CHECK (jsonb_typeof(metadata) = 'object'),
            CONSTRAINT ck_canonical_events_severity_unit CHECK (severity BETWEEN 0 AND 1),
            CONSTRAINT ck_canonical_events_novelty_unit CHECK (novelty BETWEEN 0 AND 1),
            CONSTRAINT ck_canonical_events_corroboration_unit
                CHECK (corroboration BETWEEN 0 AND 1),
            CONSTRAINT ck_canonical_events_confidence_unit CHECK (confidence BETWEEN 0 AND 1)
        )
        """
    )
    op.execute("CREATE INDEX ix_canonical_events_timestamp ON canonical_events (timestamp)")
    op.execute("CREATE INDEX ix_canonical_events_source_type ON canonical_events (source_type)")
    op.execute("CREATE INDEX ix_canonical_events_event_type ON canonical_events (event_type)")


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS canonical_events")
