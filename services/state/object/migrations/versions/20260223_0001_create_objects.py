"""create object tables"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa

from lib.shared.ids import ulid_domain_type
from services.state.object.data.runtime import object_postgres_schema

# revision identifiers, used by Alembic.
revision = "20260223_0001"
down_revision = None
branch_labels = None
depends_on = None


def _schema() -> str:
    """Resolve canonical Object-owned schema name."""
    return object_postgres_schema()


def upgrade() -> None:
    """Create Object authoritative schema objects."""
    schema = _schema()

    op.create_table(
        "objects",
        sa.Column("id", ulid_domain_type(schema), primary_key=True, nullable=False),
        sa.Column("object_key", sa.String(length=128), nullable=False),
        sa.Column("digest_algorithm", sa.String(length=32), nullable=False),
        sa.Column("digest_version", sa.String(length=16), nullable=False),
        sa.Column("digest_hex", sa.String(length=64), nullable=False),
        sa.Column("extension", sa.String(length=32), nullable=False),
        sa.Column(
            "content_type", sa.String(length=256), nullable=False, server_default=""
        ),
        sa.Column("size_bytes", sa.Integer(), nullable=False),
        sa.Column(
            "original_filename",
            sa.String(length=512),
            nullable=False,
            server_default="",
        ),
        sa.Column(
            "source_uri", sa.String(length=1024), nullable=False, server_default=""
        ),
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
        sa.UniqueConstraint("object_key", name="uq_objects_object_key"),
        sa.UniqueConstraint(
            "digest_version",
            "digest_algorithm",
            "digest_hex",
            name="uq_objects_digest_identity",
        ),
        sa.CheckConstraint(
            "char_length(digest_hex) = 64", name="ck_objects_digest_len"
        ),
        sa.CheckConstraint("size_bytes >= 0", name="ck_objects_size_nonnegative"),
        schema=schema,
    )


def downgrade() -> None:
    """Drop Object authoritative schema objects."""
    op.drop_table("objects", schema=_schema())
