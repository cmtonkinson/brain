"""Health-check utilities for the Postgres shared substrate."""

from __future__ import annotations

from sqlalchemy import Engine, text


def ping(engine: Engine) -> bool:
    """Return True when the database can answer a trivial query."""
    try:
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        return True
    except Exception:
        return False
