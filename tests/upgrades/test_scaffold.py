"""Scaffolder behavior: input validation, counter selection, file rendering."""

from __future__ import annotations

import os
import stat
from datetime import date

import pytest

from lib.core.upgrades.scaffold import ScaffoldError, scaffold_upgrade


def test_scaffold_creates_both_files(tmp_path):
    upgrades_root = tmp_path / "upgrades"

    result = scaffold_upgrade(
        name="alpha",
        upgrades_root=upgrades_root,
        today=date(2026, 5, 5),
    )

    assert result.upgrade_py.is_file()
    assert result.test_upgrade_py.is_file()
    assert result.directory.name == "20260505_0001_alpha"
    text = result.upgrade_py.read_text()
    assert "DESCRIPTION" in text
    assert 'PHASE = "post-services"' in text
    assert "def run(ctx: UpgradeContext) -> None:" in text


def test_scaffold_picks_next_counter_for_today(tmp_path):
    upgrades_root = tmp_path / "upgrades"
    today = date(2026, 5, 5)

    first = scaffold_upgrade(name="alpha", upgrades_root=upgrades_root, today=today)
    second = scaffold_upgrade(name="beta", upgrades_root=upgrades_root, today=today)
    other_day = scaffold_upgrade(
        name="gamma", upgrades_root=upgrades_root, today=date(2026, 6, 1)
    )

    assert first.directory.name == "20260505_0001_alpha"
    assert second.directory.name == "20260505_0002_beta"
    assert other_day.directory.name == "20260601_0001_gamma"


@pytest.mark.parametrize(
    "name",
    [
        "",
        "1starts-with-digit",
        "Has-Capitals",
        "kebab-case",
        "with space",
        "ends_with_underscore_",  # actually allowed by regex; keep for parametrize size
    ][:-1],
)
def test_scaffold_rejects_invalid_name(tmp_path, name):
    with pytest.raises(ScaffoldError):
        scaffold_upgrade(name=name, upgrades_root=tmp_path / "upgrades")


def test_scaffold_does_not_make_executable(tmp_path):
    """Upgrade modules are imported, not executed; no need for the +x bit."""
    upgrades_root = tmp_path / "upgrades"

    result = scaffold_upgrade(
        name="alpha", upgrades_root=upgrades_root, today=date(2026, 5, 5)
    )

    mode = os.stat(result.upgrade_py).st_mode
    assert not (mode & stat.S_IXUSR)


def test_scaffold_skips_malformed_existing_dirs(tmp_path):
    upgrades_root = tmp_path / "upgrades"
    upgrades_root.mkdir()
    (upgrades_root / "not_a_real_upgrade").mkdir()

    result = scaffold_upgrade(
        name="alpha", upgrades_root=upgrades_root, today=date(2026, 5, 5)
    )

    # Counter starts at 0001 because the malformed sibling didn't match the pattern.
    assert result.directory.name == "20260505_0001_alpha"
