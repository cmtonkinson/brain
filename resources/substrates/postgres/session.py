"""Session lifecycle helpers for shared Postgres substrate access."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager

from sqlalchemy import Engine
from sqlalchemy.orm import Session, sessionmaker


def create_session_factory(engine: Engine) -> sessionmaker[Session]:
    """Create a session factory bound to the provided SQLAlchemy engine."""
    return sessionmaker(bind=engine, autoflush=False, autocommit=False, expire_on_commit=False)


@contextmanager
def transactional_session(session_factory: sessionmaker[Session]) -> Iterator[Session]:
    """Yield a session and enforce commit/rollback semantics."""
    session = session_factory()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()
