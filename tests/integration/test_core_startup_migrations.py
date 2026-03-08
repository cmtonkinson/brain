"""Integration tests for real startup migrations against transient Postgres."""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from packages.brain_core.migrations import (
    discover_service_migration_configs,
    run_startup_migrations,
)
from resources.substrates.postgres.config import resolve_postgres_settings
from tests.integration.helpers import real_provider_tests_enabled

pytest_plugins = ("tests.integration.fixtures",)


pytestmark = pytest.mark.skipif(
    not real_provider_tests_enabled(),
    reason="set BRAIN_RUN_INTEGRATION_REAL=1 to run real-provider integration tests",
)


def test_run_startup_migrations_executes_all_registered_service_configs(
    integration_settings,
) -> None:
    """Real startup migrations should load every checked-in service environment."""
    postgres_url = resolve_postgres_settings(integration_settings).url
    assert postgres_url != ""
    repo_root = Path(__file__).resolve().parents[2]
    expected = tuple(
        str(item) for item in discover_service_migration_configs(repo_root=repo_root)
    )

    previous = os.environ.get("BRAIN_RESOURCES_SUBSTRATE__POSTGRES__URL")
    os.environ["BRAIN_RESOURCES_SUBSTRATE__POSTGRES__URL"] = postgres_url
    try:
        result = run_startup_migrations(
            settings=integration_settings,
            repo_root=repo_root,
        )
    finally:
        if previous is None:
            os.environ.pop("BRAIN_RESOURCES_SUBSTRATE__POSTGRES__URL", None)
        else:
            os.environ["BRAIN_RESOURCES_SUBSTRATE__POSTGRES__URL"] = previous

    assert result.executed_alembic_configs == expected
