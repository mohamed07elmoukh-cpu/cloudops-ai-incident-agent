"""Add webhook publication and worker event idempotence tables."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260824_0002"
down_revision: str | None = "20260824_0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "processed_events",
        sa.Column("event_id", sa.Uuid(), nullable=False),
        sa.Column("event_type", sa.String(length=100), nullable=False),
        sa.Column("processed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("incident_id", sa.Uuid(), nullable=True),
        sa.Column("status", sa.String(length=50), nullable=False),
        sa.Column("trace_id", sa.Uuid(), nullable=False),
        sa.ForeignKeyConstraint(["incident_id"], ["incidents.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("event_id"),
    )
    op.create_index("ix_processed_events_incident_id", "processed_events", ["incident_id"])
    op.create_index("ix_processed_events_trace_id", "processed_events", ["trace_id"])

    op.create_table(
        "published_events",
        sa.Column("event_id", sa.Uuid(), nullable=False),
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("trace_id", sa.Uuid(), nullable=False),
        sa.Column("message_id", sa.String(length=255), nullable=False),
        sa.PrimaryKeyConstraint("event_id"),
    )
    op.create_index("ix_published_events_trace_id", "published_events", ["trace_id"])


def downgrade() -> None:
    op.drop_index("ix_published_events_trace_id", table_name="published_events")
    op.drop_table("published_events")
    op.drop_index("ix_processed_events_trace_id", table_name="processed_events")
    op.drop_index("ix_processed_events_incident_id", table_name="processed_events")
    op.drop_table("processed_events")

