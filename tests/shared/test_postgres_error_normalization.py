"""Tests for Postgres exception normalization into shared error taxonomy."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from packages.brain_shared.errors import codes
from resources.substrates.postgres.errors import normalize_postgres_error


def test_normalize_unique_violation_maps_to_conflict() -> None:
    """Unique key failures should map to conflict/already-exists semantics."""

    class UniqueViolation(Exception):
        """Synthetic unique-violation exception."""

    error = normalize_postgres_error(UniqueViolation("duplicate key value violates unique constraint"))
    assert error.category.value == "conflict"
    assert error.code == codes.ALREADY_EXISTS


def test_normalize_operational_errors_map_to_retryable_dependency() -> None:
    """Operational/timeout failures should be retryable dependency errors."""

    class OperationalError(Exception):
        """Synthetic operational exception."""

    error = normalize_postgres_error(OperationalError("connection timeout"))
    assert error.category.value == "dependency"
    assert error.retryable is True


def test_normalize_programming_errors_map_to_non_retryable_dependency() -> None:
    """Interface/programming failures should be non-retryable dependency errors."""

    class ProgrammingError(Exception):
        """Synthetic programming exception."""

    error = normalize_postgres_error(ProgrammingError("bad SQL"))
    assert error.category.value == "dependency"
    assert error.retryable is False


def test_normalize_unknown_exception_maps_to_internal() -> None:
    """Unexpected failures should map to internal/unexpected semantics."""
    error = normalize_postgres_error(RuntimeError("boom"))
    assert error.category.value == "internal"
    assert error.code == codes.UNEXPECTED_EXCEPTION
