"""create commitment service tables"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from packages.brain_shared.ids.constants import ULID_DOMAIN_NAME
from services.control.commitment.data.runtime import commitment_postgres_schema

revision = "20260418_0001"
down_revision = None
branch_labels = None
depends_on = None


def _schema() -> str:
    """Resolve canonical Commitment Service-owned schema name."""
    return commitment_postgres_schema()


def _ulid_domain(schema: str) -> postgresql.DOMAIN:
    """Return schema-local ``ulid_bin`` domain reference."""
    return postgresql.DOMAIN(
        name=ULID_DOMAIN_NAME,
        data_type=postgresql.BYTEA(),
        schema=schema,
        create_type=False,
    )


def upgrade() -> None:
    """Create Commitment Service authoritative schema objects."""
    schema = _schema()

    op.create_table(
        "commitments",
        sa.Column("id", _ulid_domain(schema), primary_key=True, nullable=False),
        sa.Column("description", sa.String(length=512), nullable=False),
        sa.Column("state", sa.String(length=32), nullable=False),
        sa.Column("provenance_reference", sa.String(length=255), nullable=True),
        sa.Column("ingestion_id", sa.String(length=255), nullable=True),
        sa.Column("source", sa.String(length=128), nullable=True),
        sa.Column("due_by", sa.DateTime(timezone=True), nullable=True),
        sa.Column("due_timezone", sa.String(length=64), nullable=True),
        sa.Column("importance", sa.Integer(), nullable=False),
        sa.Column("effort_provided", sa.Integer(), nullable=False),
        sa.Column("effort_inferred", sa.Integer(), nullable=True),
        sa.Column("urgency", sa.Integer(), nullable=False),
        sa.Column("last_progress_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_modified_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("ever_missed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("presented_for_review_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("reviewed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        schema=schema,
    )
    op.create_index("ix_commitments_state", "commitments", ["state"], schema=schema)
    op.create_index("ix_commitments_due_by", "commitments", ["due_by"], schema=schema)

    op.create_table(
        "commitment_progress",
        sa.Column("id", _ulid_domain(schema), primary_key=True, nullable=False),
        sa.Column("commitment_id", sa.LargeBinary(length=16), nullable=False),
        sa.Column("provenance_reference", sa.String(length=255), nullable=True),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("summary", sa.String(length=512), nullable=False),
        sa.Column("snippet", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        schema=schema,
    )
    op.create_index(
        "ix_commitment_progress_commitment_id",
        "commitment_progress",
        ["commitment_id"],
        schema=schema,
    )

    op.create_table(
        "commitment_transitions",
        sa.Column("id", _ulid_domain(schema), primary_key=True, nullable=False),
        sa.Column("commitment_id", sa.LargeBinary(length=16), nullable=False),
        sa.Column("from_state", sa.String(length=32), nullable=False),
        sa.Column("to_state", sa.String(length=32), nullable=False),
        sa.Column("actor", sa.String(length=32), nullable=False),
        sa.Column("reason", sa.Text(), nullable=True),
        sa.Column("confidence", sa.Float(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        schema=schema,
    )
    op.create_index(
        "ix_commitment_transitions_commitment_id",
        "commitment_transitions",
        ["commitment_id"],
        schema=schema,
    )
    op.create_index(
        "ix_commitment_transitions_to_state",
        "commitment_transitions",
        ["to_state"],
        schema=schema,
    )

    op.create_table(
        "creation_proposals",
        sa.Column("id", _ulid_domain(schema), primary_key=True, nullable=False),
        sa.Column("description", sa.String(length=512), nullable=False),
        sa.Column("provenance_reference", sa.String(length=255), nullable=True),
        sa.Column("ingestion_id", sa.String(length=255), nullable=True),
        sa.Column("source", sa.String(length=128), nullable=True),
        sa.Column("due_by", sa.DateTime(timezone=True), nullable=True),
        sa.Column("due_timezone", sa.String(length=64), nullable=True),
        sa.Column("importance", sa.Integer(), nullable=False),
        sa.Column("effort_provided", sa.Integer(), nullable=False),
        sa.Column("effort_inferred", sa.Integer(), nullable=True),
        sa.Column("requested_by", sa.String(length=32), nullable=False),
        sa.Column("confidence", sa.Float(), nullable=True),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("decided_by", sa.String(length=255), nullable=True),
        sa.Column("decision_reason", sa.Text(), nullable=True),
        sa.Column("created_commitment_id", sa.String(length=26), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column("decided_at", sa.DateTime(timezone=True), nullable=True),
        schema=schema,
    )
    op.create_index(
        "ix_creation_proposals_status",
        "creation_proposals",
        ["status"],
        schema=schema,
    )

    op.create_table(
        "transition_proposals",
        sa.Column("id", _ulid_domain(schema), primary_key=True, nullable=False),
        sa.Column("commitment_id", sa.LargeBinary(length=16), nullable=False),
        sa.Column("from_state", sa.String(length=32), nullable=False),
        sa.Column("to_state", sa.String(length=32), nullable=False),
        sa.Column("requested_by", sa.String(length=32), nullable=False),
        sa.Column("confidence", sa.Float(), nullable=True),
        sa.Column("threshold", sa.Float(), nullable=False),
        sa.Column("reason", sa.Text(), nullable=True),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("decided_by", sa.String(length=255), nullable=True),
        sa.Column("decision_reason", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column("decided_at", sa.DateTime(timezone=True), nullable=True),
        schema=schema,
    )
    op.create_index(
        "ix_transition_proposals_commitment_id",
        "transition_proposals",
        ["commitment_id"],
        schema=schema,
    )
    op.create_index(
        "ix_transition_proposals_status",
        "transition_proposals",
        ["status"],
        schema=schema,
    )

    op.create_table(
        "review_runs",
        sa.Column("id", _ulid_domain(schema), primary_key=True, nullable=False),
        sa.Column("since_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("run_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("delivered_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("notification_reference", sa.String(length=255), nullable=True),
        sa.Column("completed_count", sa.Integer(), nullable=False),
        sa.Column("missed_count", sa.Integer(), nullable=False),
        sa.Column("modified_count", sa.Integer(), nullable=False),
        sa.Column("no_due_date_count", sa.Integer(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        schema=schema,
    )

    op.create_table(
        "review_items",
        sa.Column("id", _ulid_domain(schema), primary_key=True, nullable=False),
        sa.Column("review_run_id", sa.LargeBinary(length=16), nullable=False),
        sa.Column("commitment_id", sa.LargeBinary(length=16), nullable=False),
        sa.Column("category", sa.String(length=32), nullable=False),
        sa.Column("message", sa.Text(), nullable=False),
        sa.Column("presented_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("reviewed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        schema=schema,
    )
    op.create_index(
        "ix_review_items_review_run_id",
        "review_items",
        ["review_run_id"],
        schema=schema,
    )

    op.create_table(
        "commitment_job_links",
        sa.Column("id", _ulid_domain(schema), primary_key=True, nullable=False),
        sa.Column("commitment_id", sa.LargeBinary(length=16), nullable=False),
        sa.Column("job_id", sa.String(length=26), nullable=True),
        sa.Column("job_timezone", sa.String(length=64), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("linked_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("unlinked_at", sa.DateTime(timezone=True), nullable=True),
        sa.UniqueConstraint(
            "commitment_id", name="uq_commitment_job_links_commitment_id"
        ),
        schema=schema,
    )


def downgrade() -> None:
    """Drop Commitment Service authoritative schema objects."""
    schema = _schema()
    op.drop_table("commitment_job_links", schema=schema)
    op.drop_index(
        "ix_review_items_review_run_id", table_name="review_items", schema=schema
    )
    op.drop_table("review_items", schema=schema)
    op.drop_table("review_runs", schema=schema)
    op.drop_index(
        "ix_transition_proposals_status",
        table_name="transition_proposals",
        schema=schema,
    )
    op.drop_index(
        "ix_transition_proposals_commitment_id",
        table_name="transition_proposals",
        schema=schema,
    )
    op.drop_table("transition_proposals", schema=schema)
    op.drop_index(
        "ix_creation_proposals_status", table_name="creation_proposals", schema=schema
    )
    op.drop_table("creation_proposals", schema=schema)
    op.drop_index(
        "ix_commitment_transitions_to_state",
        table_name="commitment_transitions",
        schema=schema,
    )
    op.drop_index(
        "ix_commitment_transitions_commitment_id",
        table_name="commitment_transitions",
        schema=schema,
    )
    op.drop_table("commitment_transitions", schema=schema)
    op.drop_index(
        "ix_commitment_progress_commitment_id",
        table_name="commitment_progress",
        schema=schema,
    )
    op.drop_table("commitment_progress", schema=schema)
    op.drop_index("ix_commitments_due_by", table_name="commitments", schema=schema)
    op.drop_index("ix_commitments_state", table_name="commitments", schema=schema)
    op.drop_table("commitments", schema=schema)
