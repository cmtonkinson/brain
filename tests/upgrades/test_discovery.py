"""Discovery validation: directory naming, required metadata, ordering."""

from __future__ import annotations

import pytest

from lib.core.upgrades.discovery import (
    DEFAULT_PHASE,
    DEFAULT_TIMEOUT_SECONDS,
    DEFAULT_INTERACTIVE_TIMEOUT_SECONDS,
    DiscoveryError,
    discover_upgrades,
)


def test_discover_orders_lexicographically(make_upgrade, isolated_state_env):
    make_upgrade(upgrade_id="20260601_0001", slug="zebra")
    make_upgrade(upgrade_id="20260505_0002", slug="alpha")
    make_upgrade(upgrade_id="20260505_0001", slug="charlie")

    result = discover_upgrades(isolated_state_env["upgrades_dir"])

    assert [d.upgrade_id for d in result] == [
        "20260505_0001",
        "20260505_0002",
        "20260601_0001",
    ]


def test_discover_rejects_duplicate_id(make_upgrade, isolated_state_env):
    make_upgrade(upgrade_id="20260505_0001", slug="alpha")
    upgrades_dir = isolated_state_env["upgrades_dir"]
    duplicate = upgrades_dir / "20260505_0001_beta"
    duplicate.mkdir()
    (duplicate / "upgrade.py").write_text(
        'DESCRIPTION="dup"\nPHASE="post-services"\ndef run(ctx):\n    pass\n'
    )

    with pytest.raises(DiscoveryError, match="duplicate upgrade id"):
        discover_upgrades(upgrades_dir)


def test_discover_rejects_missing_upgrade_py(isolated_state_env):
    upgrades_dir = isolated_state_env["upgrades_dir"]
    (upgrades_dir / "20260505_0001_no_module").mkdir()

    with pytest.raises(DiscoveryError, match="missing upgrade.py"):
        discover_upgrades(upgrades_dir)


def test_discover_rejects_missing_description(make_upgrade, isolated_state_env):
    directory = make_upgrade(upgrade_id="20260505_0001", slug="x")
    (directory / "upgrade.py").write_text(
        'PHASE="post-services"\ndef run(ctx):\n    pass\n'
    )

    with pytest.raises(DiscoveryError, match="DESCRIPTION"):
        discover_upgrades(isolated_state_env["upgrades_dir"])


def test_discover_rejects_missing_run_callable(make_upgrade, isolated_state_env):
    directory = make_upgrade(upgrade_id="20260505_0001", slug="x")
    (directory / "upgrade.py").write_text('DESCRIPTION="x"\nPHASE="post-services"\n')

    with pytest.raises(DiscoveryError, match="run.*callable"):
        discover_upgrades(isolated_state_env["upgrades_dir"])


def test_discover_rejects_unknown_phase(make_upgrade, isolated_state_env):
    make_upgrade(upgrade_id="20260505_0001", slug="x", phase="middle-services")

    with pytest.raises(DiscoveryError, match="unknown PHASE"):
        discover_upgrades(isolated_state_env["upgrades_dir"])


def test_discover_rejects_directory_name_mismatch(isolated_state_env):
    upgrades_dir = isolated_state_env["upgrades_dir"]
    (upgrades_dir / "not-a-valid-upgrade-name").mkdir()

    with pytest.raises(DiscoveryError, match="does not match"):
        discover_upgrades(upgrades_dir)


def test_discover_skips_underscore_and_dot_dirs(isolated_state_env):
    upgrades_dir = isolated_state_env["upgrades_dir"]
    (upgrades_dir / "_run-2026-05-05.log").mkdir()
    (upgrades_dir / ".cache").mkdir()

    result = discover_upgrades(upgrades_dir)

    assert result == ()


def test_discover_default_phase_and_timeouts(make_upgrade, isolated_state_env):
    directory = make_upgrade(upgrade_id="20260505_0001", slug="x")
    # Strip PHASE/INTERACTIVE/TIMEOUT_SECONDS to exercise defaults.
    (directory / "upgrade.py").write_text('DESCRIPTION="x"\ndef run(ctx):\n    pass\n')
    interactive_dir = make_upgrade(
        upgrade_id="20260505_0002", slug="y", interactive=True
    )
    # Drop explicit TIMEOUT_SECONDS for the interactive case too.
    (interactive_dir / "upgrade.py").write_text(
        'DESCRIPTION="y"\nPHASE="pre-services"\nINTERACTIVE=True\n'
        "def run(ctx):\n    pass\n"
    )

    result = discover_upgrades(isolated_state_env["upgrades_dir"])

    by_id = {d.upgrade_id: d for d in result}
    assert by_id["20260505_0001"].phase == DEFAULT_PHASE
    assert by_id["20260505_0001"].timeout_seconds == DEFAULT_TIMEOUT_SECONDS
    assert by_id["20260505_0001"].interactive is False
    assert by_id["20260505_0002"].interactive is True
    assert by_id["20260505_0002"].timeout_seconds == DEFAULT_INTERACTIVE_TIMEOUT_SECONDS


def test_discover_returns_empty_when_root_missing(tmp_path):
    assert discover_upgrades(tmp_path / "does_not_exist") == ()
