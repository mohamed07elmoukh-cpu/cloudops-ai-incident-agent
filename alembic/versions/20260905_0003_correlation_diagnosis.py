"""Add multi-resource correlation and evidence-backed diagnosis fields."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260905_0003"
down_revision: str | None = "20260824_0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("incidents", sa.Column("correlation_group", sa.String(255), nullable=True))
    op.add_column("incidents", sa.Column("diagnosis_summary", sa.Text(), nullable=True))
    op.add_column("incidents", sa.Column("probable_root_cause", sa.Text(), nullable=True))
    op.add_column("incidents", sa.Column("diagnosis_confidence", sa.Float(), nullable=True))
    op.add_column(
        "incidents",
        sa.Column("diagnosis_evidence", sa.JSON(), nullable=False, server_default="[]"),
    )
    op.add_column("incidents", sa.Column("diagnosed_at", sa.DateTime(timezone=True)))
    op.create_index("ix_incidents_correlation_group", "incidents", ["correlation_group"])


def downgrade() -> None:
    op.drop_index("ix_incidents_correlation_group", table_name="incidents")
    op.drop_column("incidents", "diagnosed_at")
    op.drop_column("incidents", "diagnosis_evidence")
    op.drop_column("incidents", "diagnosis_confidence")
    op.drop_column("incidents", "probable_root_cause")
    op.drop_column("incidents", "diagnosis_summary")
    op.drop_column("incidents", "correlation_group")
