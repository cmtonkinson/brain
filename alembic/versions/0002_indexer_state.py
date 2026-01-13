"""Add indexer state tables.

Revision ID: 0002_indexer_state
Revises: 0001_initial
Create Date: 2026-01-13 00:00:00.000000

"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = "0002_indexer_state"
down_revision = "0001_initial"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "indexed_notes",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("path", sa.String(length=1000), nullable=False),
        sa.Column("collection", sa.String(length=200), nullable=False),
        sa.Column("content_hash", sa.String(length=64), nullable=False),
        sa.Column("modified_at", sa.DateTime(), nullable=True),
        sa.Column("chunk_count", sa.Integer(), nullable=False),
        sa.Column("last_indexed_at", sa.DateTime(), nullable=True),
        sa.UniqueConstraint("collection", "path", name="uq_indexed_notes_collection_path"),
    )
    op.create_table(
        "indexed_chunks",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("note_id", sa.Integer(), nullable=False),
        sa.Column("chunk_index", sa.Integer(), nullable=False),
        sa.Column("qdrant_id", sa.String(length=64), nullable=False),
        sa.Column("chunk_chars", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(["note_id"], ["indexed_notes.id"]),
        sa.UniqueConstraint("note_id", "chunk_index", name="uq_indexed_chunks_note_chunk"),
    )
    op.create_index(
        "ix_indexed_chunks_note_id",
        "indexed_chunks",
        ["note_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_indexed_chunks_note_id", table_name="indexed_chunks")
    op.drop_table("indexed_chunks")
    op.drop_table("indexed_notes")
