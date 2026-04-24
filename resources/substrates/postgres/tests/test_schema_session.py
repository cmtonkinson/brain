"""Tests for ServiceSchemaSessionProvider schema pinning and validation."""

from __future__ import annotations

import pytest

from resources.substrates.postgres.schema_session import ServiceSchemaSessionProvider


class _FakeSession:
    """Minimal session double capturing execute calls."""

    def __init__(self) -> None:
        self.statements: list[str] = []

    def execute(self, statement, *args, **kwargs) -> None:
        self.statements.append(str(statement))

    def commit(self) -> None:
        pass

    def rollback(self) -> None:
        pass

    def close(self) -> None:
        pass


def _make_factory(session: _FakeSession):
    """Return a callable that acts as a sessionmaker returning the given session."""

    def factory() -> _FakeSession:
        return session

    return factory


def test_schema_session_provider_sets_search_path() -> None:
    """Session context manager should emit SET LOCAL search_path before yielding."""
    fake_session = _FakeSession()
    factory = _make_factory(fake_session)
    provider = ServiceSchemaSessionProvider(session_factory=factory, schema="my_schema")

    with provider.session() as db:
        assert db is fake_session

    assert any("my_schema" in s for s in fake_session.statements)
    assert any("search_path" in s for s in fake_session.statements)


def test_schema_session_provider_exposes_schema_name() -> None:
    """The schema property should return the name the provider was constructed with."""
    factory = _make_factory(_FakeSession())
    provider = ServiceSchemaSessionProvider(session_factory=factory, schema="svc_x")
    assert provider.schema == "svc_x"


def test_schema_validation_rejects_empty() -> None:
    """Empty schema name should raise ValueError before any state is set."""
    with pytest.raises(ValueError, match="required"):
        ServiceSchemaSessionProvider(
            session_factory=_make_factory(_FakeSession()), schema=""
        )


def test_schema_validation_rejects_hyphen() -> None:
    """Schema names with hyphens should be rejected to prevent SQL injection."""
    with pytest.raises(ValueError, match="alphanumeric"):
        ServiceSchemaSessionProvider(
            session_factory=_make_factory(_FakeSession()), schema="bad-schema"
        )


def test_schema_validation_rejects_semicolon() -> None:
    """Schema names with semicolons should be rejected to prevent SQL injection."""
    with pytest.raises(ValueError, match="alphanumeric"):
        ServiceSchemaSessionProvider(
            session_factory=_make_factory(_FakeSession()), schema="x; DROP TABLE y"
        )


def test_schema_validation_accepts_underscores() -> None:
    """Schema names with underscores should be accepted."""
    factory = _make_factory(_FakeSession())
    provider = ServiceSchemaSessionProvider(
        session_factory=factory, schema="svc_my_schema_1"
    )
    assert provider.schema == "svc_my_schema_1"
