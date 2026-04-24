"""add foreign key constraints to all ULID reference columns"""

from __future__ import annotations

from alembic import op

from services.reason.job.data.runtime import job_postgres_schema

# revision identifiers, used by Alembic.
revision = "20260424_0003"
down_revision = "20260420_0002"
branch_labels = None
depends_on = None


def _schema() -> str:
    """Resolve canonical Job Service-owned schema name."""
    return job_postgres_schema()


_FK_DEFINITIONS: list[tuple[str, str, str, str, str]] = [
    # (constraint_name, source_table, source_column, target_table, ondelete)
    ("fk_jobs_job_intent_id", "jobs", "job_intent_id", "job_intents", "RESTRICT"),
    (
        "fk_job_intents_superseded_by_id",
        "job_intents",
        "superseded_by_id",
        "job_intents",
        "SET NULL",
    ),
    ("fk_executions_job_id", "executions", "job_id", "jobs", "RESTRICT"),
    (
        "fk_executions_job_intent_id",
        "executions",
        "job_intent_id",
        "job_intents",
        "RESTRICT",
    ),
    (
        "fk_job_mutation_audits_job_id",
        "job_mutation_audits",
        "job_id",
        "jobs",
        "RESTRICT",
    ),
    (
        "fk_execution_audits_execution_id",
        "execution_audits",
        "execution_id",
        "executions",
        "RESTRICT",
    ),
    ("fk_execution_audits_job_id", "execution_audits", "job_id", "jobs", "RESTRICT"),
    (
        "fk_predicate_evaluations_job_id",
        "predicate_evaluations",
        "job_id",
        "jobs",
        "RESTRICT",
    ),
    (
        "fk_review_items_review_output_id",
        "review_items",
        "review_output_id",
        "review_outputs",
        "RESTRICT",
    ),
    ("fk_review_items_job_id", "review_items", "job_id", "jobs", "RESTRICT"),
]


def upgrade() -> None:
    """Add foreign key constraints to all ULID reference columns."""
    schema = _schema()
    for name, source, column, target, ondelete in _FK_DEFINITIONS:
        op.create_foreign_key(
            name,
            source,
            target,
            [column],
            ["id"],
            source_schema=schema,
            referent_schema=schema,
            ondelete=ondelete,
        )


def downgrade() -> None:
    """Remove foreign key constraints."""
    schema = _schema()
    for name, source, _column, _target, _ondelete in reversed(_FK_DEFINITIONS):
        op.drop_constraint(name, source, schema=schema, type_="foreignkey")
