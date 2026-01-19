"""Store normalized routing envelopes for fail-closed queue entries.

Revision ID: 0015_attention_fail_closed_envelopes
Revises: 0014_attention_decision_records
Create Date: 2026-02-02 00:00:00.000000
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = "0015_attention_fail_closed_envelopes"
down_revision = "0014_attention_decision_records"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Add normalized envelope fields and backfill existing rows."""
    op.add_column(
        "attention_fail_closed_queue",
        sa.Column("actor", sa.String(length=200), nullable=True),
    )
    op.add_column(
        "attention_fail_closed_queue",
        sa.Column("signal_reference", sa.String(length=500), nullable=True),
    )
    op.add_column(
        "attention_fail_closed_queue",
        sa.Column("envelope_version", sa.String(length=50), nullable=True),
    )
    op.add_column(
        "attention_fail_closed_queue",
        sa.Column("signal_type", sa.String(length=200), nullable=True),
    )
    op.add_column(
        "attention_fail_closed_queue",
        sa.Column("urgency", sa.Float(), nullable=True),
    )
    op.add_column(
        "attention_fail_closed_queue",
        sa.Column("channel_cost", sa.Float(), nullable=True),
    )
    op.add_column(
        "attention_fail_closed_queue",
        sa.Column("content_type", sa.String(length=200), nullable=True),
    )
    op.add_column(
        "attention_fail_closed_queue",
        sa.Column("correlation_id", sa.String(length=200), nullable=True),
    )
    op.add_column(
        "attention_fail_closed_queue",
        sa.Column("routing_intent", sa.String(length=50), nullable=True),
    )
    op.add_column(
        "attention_fail_closed_queue",
        sa.Column("envelope_timestamp", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "attention_fail_closed_queue",
        sa.Column("deadline", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "attention_fail_closed_queue",
        sa.Column("previous_severity", sa.Integer(), nullable=True),
    )
    op.add_column(
        "attention_fail_closed_queue",
        sa.Column("current_severity", sa.Integer(), nullable=True),
    )
    op.add_column(
        "attention_fail_closed_queue",
        sa.Column("authorization_autonomy_level", sa.String(length=50), nullable=True),
    )
    op.add_column(
        "attention_fail_closed_queue",
        sa.Column("authorization_approval_status", sa.String(length=50), nullable=True),
    )
    op.add_column(
        "attention_fail_closed_queue",
        sa.Column("notification_version", sa.String(length=50), nullable=True),
    )
    op.add_column(
        "attention_fail_closed_queue",
        sa.Column("notification_origin_signal", sa.String(length=500), nullable=True),
    )
    op.add_column(
        "attention_fail_closed_queue",
        sa.Column("notification_confidence", sa.Float(), nullable=True),
    )

    op.create_table(
        "attention_fail_closed_provenance_inputs",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "queue_id",
            sa.Integer(),
            sa.ForeignKey("attention_fail_closed_queue.id"),
            nullable=False,
        ),
        sa.Column("input_type", sa.String(length=200), nullable=False),
        sa.Column("reference", sa.String(length=500), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_table(
        "attention_fail_closed_policy_tags",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "queue_id",
            sa.Integer(),
            sa.ForeignKey("attention_fail_closed_queue.id"),
            nullable=False,
        ),
        sa.Column("tag", sa.String(length=200), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=True),
    )

    connection = op.get_bind()
    queue = sa.table(
        "attention_fail_closed_queue",
        sa.column("id", sa.Integer()),
        sa.column("source_component", sa.String()),
        sa.column("from_number", sa.String()),
        sa.column("to_number", sa.String()),
        sa.column("channel", sa.String()),
        sa.column("message", sa.Text()),
        sa.column("queued_at", sa.DateTime(timezone=True)),
        sa.column("signal_reference", sa.String()),
    )
    provenance = sa.table(
        "attention_fail_closed_provenance_inputs",
        sa.column("queue_id", sa.Integer()),
        sa.column("input_type", sa.String()),
        sa.column("reference", sa.String()),
        sa.column("description", sa.Text()),
        sa.column("created_at", sa.DateTime(timezone=True)),
    )

    rows = connection.execute(
        sa.select(
            queue.c.id,
            queue.c.source_component,
            queue.c.from_number,
            queue.c.to_number,
            queue.c.channel,
            queue.c.message,
            queue.c.queued_at,
            queue.c.signal_reference,
        )
    ).mappings()

    for row in rows:
        signal_reference = row["signal_reference"] or f"fail_closed:{row['id']}"
        queued_at = row["queued_at"]
        connection.execute(
            queue.update()
            .where(queue.c.id == row["id"])
            .values(
                actor=row["source_component"],
                signal_reference=signal_reference,
                envelope_version="1.0.0",
                signal_type="signal.reply",
                urgency=0.9,
                channel_cost=0.1,
                content_type="message",
                correlation_id=signal_reference,
                routing_intent="DELIVER",
                envelope_timestamp=queued_at,
                notification_version="1.0.0",
                notification_origin_signal=signal_reference,
                notification_confidence=0.9,
            )
        )
        connection.execute(
            provenance.insert().values(
                queue_id=row["id"],
                input_type="fail_closed_queue",
                reference=signal_reference,
                description="Recovered from fail-closed queue.",
                created_at=queued_at,
            )
        )


def downgrade() -> None:
    """Remove normalized envelope columns and tables."""
    op.drop_table("attention_fail_closed_policy_tags")
    op.drop_table("attention_fail_closed_provenance_inputs")

    op.drop_column("attention_fail_closed_queue", "notification_confidence")
    op.drop_column("attention_fail_closed_queue", "notification_origin_signal")
    op.drop_column("attention_fail_closed_queue", "notification_version")
    op.drop_column("attention_fail_closed_queue", "authorization_approval_status")
    op.drop_column("attention_fail_closed_queue", "authorization_autonomy_level")
    op.drop_column("attention_fail_closed_queue", "current_severity")
    op.drop_column("attention_fail_closed_queue", "previous_severity")
    op.drop_column("attention_fail_closed_queue", "deadline")
    op.drop_column("attention_fail_closed_queue", "envelope_timestamp")
    op.drop_column("attention_fail_closed_queue", "routing_intent")
    op.drop_column("attention_fail_closed_queue", "correlation_id")
    op.drop_column("attention_fail_closed_queue", "content_type")
    op.drop_column("attention_fail_closed_queue", "channel_cost")
    op.drop_column("attention_fail_closed_queue", "urgency")
    op.drop_column("attention_fail_closed_queue", "signal_type")
    op.drop_column("attention_fail_closed_queue", "envelope_version")
    op.drop_column("attention_fail_closed_queue", "signal_reference")
    op.drop_column("attention_fail_closed_queue", "actor")
