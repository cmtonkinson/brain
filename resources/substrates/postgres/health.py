"""Health-check utilities for the Postgres shared substrate."""

from __future__ import annotations

from sqlalchemy import Engine, text


def ping(engine: Engine, *, timeout_seconds: float = 1.0) -> bool:
    """Return True when the database can answer a trivial query quickly."""
    timeout_ms = max(1, int(timeout_seconds * 1000))
    try:
        with engine.connect() as conn:
            conn.execute(
                text("SELECT set_config('statement_timeout', :timeout_value, false)"),
                {"timeout_value": f"{timeout_ms}ms"},
            )
            conn.execute(text("SELECT 1"))
        return True
    except Exception:
        return False
