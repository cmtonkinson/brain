"""Shared helpers for integration tests."""

from __future__ import annotations

import os


def real_provider_tests_enabled() -> bool:
    """Return True when real-provider integration tests are explicitly enabled."""
    raw = os.getenv("BRAIN_RUN_INTEGRATION_REAL", "").strip().lower()
    return raw in {"1", "true", "yes", "on"}
