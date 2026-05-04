"""Grandfather-writer behavior: enumeration, sentinel, atomicity, refusal."""

from __future__ import annotations

import os

import pytest

from lib.core.upgrades.ledger import (
    LEDGER_SCHEMA_VERSION,
    ZERO_SHA_SENTINEL,
    Ledger,
    ledger_path,
    now_utc_iso,
    read_ledger,
    write_ledger,
)
from lib.setup.ledger_init import (
    LedgerAlreadyExistsError,
    write_grandfathered_ledger,
)


def test_grandfathers_every_current_upgrade_dir(isolated_install_env, make_upgrade_dir):
    make_upgrade_dir(upgrade_id="20260505_0001", slug="alpha", phase="pre-services")
    make_upgrade_dir(upgrade_id="20260505_0002", slug="beta")
    make_upgrade_dir(upgrade_id="20260601_0001", slug="gamma")

    ledger = write_grandfathered_ledger(
        upgrades_root=isolated_install_env["upgrades_dir"]
    )

    assert len(ledger.applied) == 3
    on_disk = read_ledger()
    assert {e.upgrade_id for e in on_disk.applied} == {
        "20260505_0001",
        "20260505_0002",
        "20260601_0001",
    }
    assert all(e.grandfathered for e in on_disk.applied)


def test_sets_installed_at_and_uses_consistent_applied_at(
    isolated_install_env, make_upgrade_dir
):
    make_upgrade_dir(upgrade_id="20260505_0001", slug="alpha")
    timestamp = now_utc_iso()

    ledger = write_grandfathered_ledger(
        upgrades_root=isolated_install_env["upgrades_dir"],
        installed_at=timestamp,
    )

    assert ledger.installed_at == timestamp
    assert ledger.applied[0].applied_at == timestamp


def test_uses_zero_sha_sentinel_for_grandfathered(
    isolated_install_env, make_upgrade_dir
):
    make_upgrade_dir(upgrade_id="20260505_0001", slug="alpha")

    ledger = write_grandfathered_ledger(
        upgrades_root=isolated_install_env["upgrades_dir"]
    )

    assert ledger.applied[0].module_sha256 == ZERO_SHA_SENTINEL
    assert ledger.applied[0].duration_seconds == 0.0


def test_writes_to_overrideable_path(isolated_install_env, make_upgrade_dir, tmp_path):
    make_upgrade_dir(upgrade_id="20260505_0001", slug="alpha")
    target = tmp_path / "alt-ledger.json"

    write_grandfathered_ledger(
        upgrades_root=isolated_install_env["upgrades_dir"],
        ledger_target=target,
    )

    assert target.exists()


def test_refuses_to_overwrite_existing_ledger(isolated_install_env, make_upgrade_dir):
    make_upgrade_dir(upgrade_id="20260505_0001", slug="alpha")
    write_ledger(
        Ledger(
            schema_version=LEDGER_SCHEMA_VERSION,
            installed_at=now_utc_iso(),
            applied=[],
        )
    )

    with pytest.raises(LedgerAlreadyExistsError, match="refusing to overwrite"):
        write_grandfathered_ledger(upgrades_root=isolated_install_env["upgrades_dir"])


def test_writes_atomically(isolated_install_env, make_upgrade_dir, monkeypatch):
    make_upgrade_dir(upgrade_id="20260505_0001", slug="alpha")

    real_replace = os.replace

    def boom(src, dst, *args, **kwargs):
        raise RuntimeError("simulated crash mid-replace")

    monkeypatch.setattr("lib.core.upgrades.ledger.os.replace", boom)

    with pytest.raises(RuntimeError, match="simulated crash"):
        write_grandfathered_ledger(upgrades_root=isolated_install_env["upgrades_dir"])

    monkeypatch.setattr("lib.core.upgrades.ledger.os.replace", real_replace)
    # No half-written ledger remains.
    assert not ledger_path().exists()


def test_empty_upgrades_tree_yields_empty_applied(isolated_install_env):
    ledger = write_grandfathered_ledger(
        upgrades_root=isolated_install_env["upgrades_dir"]
    )

    assert ledger.applied == []
    assert read_ledger().applied == []


def test_grandfathered_entries_are_ignored_by_apply_pending(
    isolated_install_env, make_upgrade_dir
):
    """Sanity bridge: after grandfathering, the runner sees nothing pending."""
    from lib.core.upgrades.runner import list_pending

    make_upgrade_dir(upgrade_id="20260505_0001", slug="alpha")
    make_upgrade_dir(upgrade_id="20260505_0002", slug="beta")
    write_grandfathered_ledger(upgrades_root=isolated_install_env["upgrades_dir"])

    pending = list_pending(repo_root=isolated_install_env["tmp_path"])

    assert pending == ()
