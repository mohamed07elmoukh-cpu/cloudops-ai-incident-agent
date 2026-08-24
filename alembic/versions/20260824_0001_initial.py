"""Create incident, evidence, and remediation execution tables."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260824_0001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "incidents",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("source", sa.String(length=255), nullable=False),
        sa.Column("incident_type", sa.String(length=100), nullable=False),
        sa.Column(
            "severity",
            sa.Enum("LOW", "MEDIUM", "HIGH", "CRITICAL", name="severity", native_enum=False),
            nullable=False,
        ),
        sa.Column(
            "status",
            sa.Enum(
                "OPEN",
                "INVESTIGATING",
                "REMEDIATING",
                "VERIFYING",
                "RESOLVED",
                "FAILED",
                "ESCALATED",
                name="incident_status",
                native_enum=False,
            ),
            nullable=False,
        ),
        sa.Column("title", sa.String(length=255), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("detected_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("correlation_key", sa.String(length=255), nullable=False),
        sa.Column("remediation_attempted", sa.Boolean(), nullable=False),
        sa.Column("verification_failures", sa.Integer(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_incidents_incident_type", "incidents", ["incident_type"])
    op.create_index("ix_incidents_status", "incidents", ["status"])
    op.create_index("ix_incidents_correlation_key", "incidents", ["correlation_key"])
    op.create_index(
        "uq_incidents_open_correlation_key",
        "incidents",
        ["correlation_key"],
        unique=True,
        postgresql_where=sa.text("status = 'OPEN'"),
    )

    op.create_table(
        "evidence",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("incident_id", sa.Uuid(), nullable=False),
        sa.Column("metric_name", sa.String(length=255), nullable=False),
        sa.Column("metric_value", sa.Float(), nullable=False),
        sa.Column("threshold", sa.Float(), nullable=False),
        sa.Column("timestamp", sa.DateTime(timezone=True), nullable=False),
        sa.Column("raw_data", sa.JSON(), nullable=False),
        sa.ForeignKeyConstraint(["incident_id"], ["incidents.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_evidence_incident_id", "evidence", ["incident_id"])

    op.create_table(
        "remediation_executions",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("incident_id", sa.Uuid(), nullable=False),
        sa.Column("runbook_name", sa.String(length=255), nullable=False),
        sa.Column("status", sa.String(length=50), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("output", sa.JSON(), nullable=False),
        sa.Column("idempotency_key", sa.String(length=255), nullable=False),
        sa.ForeignKeyConstraint(["incident_id"], ["incidents.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("idempotency_key"),
    )
    op.create_index(
        "ix_remediation_executions_incident_id", "remediation_executions", ["incident_id"]
    )


def downgrade() -> None:
    op.drop_index("ix_remediation_executions_incident_id", table_name="remediation_executions")
    op.drop_table("remediation_executions")
    op.drop_index("ix_evidence_incident_id", table_name="evidence")
    op.drop_table("evidence")
    op.drop_index("uq_incidents_open_correlation_key", table_name="incidents")
    op.drop_index("ix_incidents_correlation_key", table_name="incidents")
    op.drop_index("ix_incidents_status", table_name="incidents")
    op.drop_index("ix_incidents_incident_type", table_name="incidents")
    op.drop_table("incidents")

