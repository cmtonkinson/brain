"""Scaffold a new upgrade directory: ``make new-upgrade NAME=...``."""

from __future__ import annotations

import os
import re
from dataclasses import dataclass
from datetime import date
from pathlib import Path

from lib.core.upgrades.discovery import DIRECTORY_NAME_PATTERN

NAME_PATTERN = re.compile(r"^[a-z][a-z0-9_]*$")


class ScaffoldError(RuntimeError):
    """Raised when scaffolding inputs are invalid."""


@dataclass(frozen=True, slots=True)
class ScaffoldResult:
    """Paths created by a successful ``make new-upgrade`` invocation."""

    directory: Path
    upgrade_py: Path
    test_upgrade_py: Path


def scaffold_upgrade(
    *,
    name: str,
    upgrades_root: Path,
    today: date | None = None,
) -> ScaffoldResult:
    """Create a new ``YYYYMMDD_NNNN_<name>/`` directory with stub files."""
    if not NAME_PATTERN.match(name):
        raise ScaffoldError(
            f"invalid upgrade name '{name}'; must match {NAME_PATTERN.pattern}"
        )

    upgrades_root.mkdir(parents=True, exist_ok=True)
    today = today or date.today()
    date_prefix = today.strftime("%Y%m%d")
    counter = _next_counter_for_day(upgrades_root, date_prefix)
    upgrade_id = f"{date_prefix}_{counter:04d}"
    directory_name = f"{upgrade_id}_{name}"
    directory = upgrades_root / directory_name

    if directory.exists():
        raise ScaffoldError(f"target directory already exists: {directory}")

    directory.mkdir(parents=True, exist_ok=False)
    upgrade_py = directory / "upgrade.py"
    test_upgrade_py = directory / "test_upgrade.py"

    upgrade_py.write_text(_render_upgrade_template(upgrade_id=upgrade_id, name=name))
    os.chmod(upgrade_py, 0o644)
    test_upgrade_py.write_text(_render_test_template(upgrade_id=upgrade_id, name=name))
    os.chmod(test_upgrade_py, 0o644)

    return ScaffoldResult(
        directory=directory,
        upgrade_py=upgrade_py,
        test_upgrade_py=test_upgrade_py,
    )


def _next_counter_for_day(upgrades_root: Path, date_prefix: str) -> int:
    """Return the next 1-indexed counter for ``date_prefix`` in ``upgrades_root``."""
    if not upgrades_root.is_dir():
        return 1
    used: list[int] = []
    for child in upgrades_root.iterdir():
        if not child.is_dir():
            continue
        match = DIRECTORY_NAME_PATTERN.match(child.name)
        if match is None:
            continue
        full_id = match.group("id")
        if full_id.startswith(f"{date_prefix}_"):
            used.append(int(full_id.split("_", 1)[1]))
    return max(used) + 1 if used else 1


def _render_upgrade_template(*, upgrade_id: str, name: str) -> str:
    return f'''"""Upgrade {upgrade_id} {name}."""

from __future__ import annotations

from lib.core.upgrades.api import UpgradeContext

DESCRIPTION = "TODO: one-line summary of what this upgrade does"
PHASE = "post-services"  # or "pre-services"
INTERACTIVE = False
TIMEOUT_SECONDS = 300


def run(ctx: UpgradeContext) -> None:
    raise NotImplementedError("implement this upgrade")
'''


def _render_test_template(*, upgrade_id: str, name: str) -> str:
    return f'''"""Tests for upgrade {upgrade_id} {name}."""

from __future__ import annotations

import pytest

from lib.core.upgrades.api import load_sibling


def test_run_raises_until_implemented(upgrade_context):
    upgrade = load_sibling(__file__, "upgrade")
    with pytest.raises(NotImplementedError):
        upgrade.run(upgrade_context)
'''
