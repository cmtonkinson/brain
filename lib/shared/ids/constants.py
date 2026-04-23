"""Shared ULID and PostgreSQL-domain constants.

This module centralizes scalar values used across ULID helpers, schema
bootstrap, and SQLAlchemy domain references so all schema-aware code relies on
one canonical naming source.
"""

ULID_DOMAIN_NAME = "ulid_bin"
