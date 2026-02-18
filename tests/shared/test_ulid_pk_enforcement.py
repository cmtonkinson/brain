"""Repository-wide checks enforcing ULID BYTEA primary-key conventions."""

from __future__ import annotations

import sys
from pathlib import Path
import re

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))


def test_no_integer_uuid_or_text_primary_keys_in_service_schemas_or_migrations() -> None:
    """Reject int/uuid/text PK definitions in service schema + migration files."""
    root = Path("services")
    targets = list(root.rglob("data/schema.py")) + list(root.rglob("migrations/versions/*.py"))

    disallowed_patterns = [
        r'Column\("id",\s*Integer\b',
        r'sa\.Column\("id",\s*sa\.Integer\b',
        r'Column\("id",\s*String\b',
        r'sa\.Column\("id",\s*sa\.String\b',
        r'Column\("id",\s*UUID\b',
        r'sa\.Column\("id",\s*sa\.UUID\b',
        r'Column\("id",[^)]*autoincrement\s*=\s*True',
        r'sa\.Column\("id",[^)]*autoincrement\s*=\s*True',
    ]

    offenders: list[str] = []
    for target in targets:
        content = target.read_text(encoding="utf-8")
        for pattern in disallowed_patterns:
            if re.search(pattern, content):
                offenders.append(f"{target}: matches disallowed PK pattern '{pattern}'")
                break

    assert not offenders, "\n".join(offenders)


def test_primary_key_uses_postgres_bytea_and_length_check() -> None:
    """Ensure canonical BYTEA(16)-equivalent conventions are present."""
    schema_file = Path("services/state/embedding_authority/data/schema.py")
    migration_file = Path(
        "services/state/embedding_authority/migrations/versions/20260218_0001_create_embedding_audit_log.py"
    )

    schema = schema_file.read_text(encoding="utf-8")
    migration = migration_file.read_text(encoding="utf-8")

    assert "ulid_primary_key_column(" in schema
    assert "ck_embedding_audit_log_id_ulid_16" in schema
    assert "ck_embedding_audit_log_id_ulid_16" in schema

    assert "postgresql.BYTEA()" in migration
    assert "octet_length(id) =" in migration
    assert "ck_embedding_audit_log_id_ulid_16" in migration
