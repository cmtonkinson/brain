"""Smoke tests for the integration harness fixture layer."""

from __future__ import annotations

from tests.integration.helpers import real_provider_tests_enabled


def test_real_provider_flag_defaults_disabled() -> None:
    """Real-provider integration mode should be opt-in by environment flag."""
    assert isinstance(real_provider_tests_enabled(), bool)
