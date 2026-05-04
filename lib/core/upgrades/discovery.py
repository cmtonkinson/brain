"""Discover upgrade directories and extract their metadata."""

from __future__ import annotations

import importlib.util
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from types import ModuleType
from typing import Any

DIRECTORY_NAME_PATTERN = re.compile(r"^(?P<id>\d{8}_\d{4})_(?P<slug>[a-z][a-z0-9_]*)$")
ALLOWED_PHASES = ("pre-services", "post-services")
DEFAULT_PHASE = "post-services"
DEFAULT_TIMEOUT_SECONDS = 300
DEFAULT_INTERACTIVE_TIMEOUT_SECONDS = 1800


class DiscoveryError(RuntimeError):
    """Raised when an upgrade directory or module fails validation."""


@dataclass(frozen=True, slots=True)
class UpgradeDescriptor:
    """Static description of one upgrade on disk."""

    upgrade_id: str
    slug: str
    directory: Path
    upgrade_py: Path
    description: str
    phase: str
    interactive: bool
    timeout_seconds: int


def discover_upgrades(upgrades_root: Path) -> tuple[UpgradeDescriptor, ...]:
    """Return all upgrade descriptors under ``upgrades_root`` in lex order.

    Raises ``DiscoveryError`` on duplicate ids, malformed directory names,
    missing ``upgrade.py``, missing required metadata, or unknown phase.
    """
    if not upgrades_root.is_dir():
        return ()

    descriptors: list[UpgradeDescriptor] = []
    seen_ids: dict[str, Path] = {}

    candidate_dirs = sorted(p for p in upgrades_root.iterdir() if p.is_dir())
    for directory in candidate_dirs:
        if directory.name.startswith("_") or directory.name.startswith("."):
            continue
        match = DIRECTORY_NAME_PATTERN.match(directory.name)
        if match is None:
            raise DiscoveryError(
                f"upgrade directory name does not match "
                f"YYYYMMDD_NNNN_<snake_case_slug>: {directory.name}"
            )
        upgrade_id = match.group("id")
        slug = match.group("slug")

        if upgrade_id in seen_ids:
            raise DiscoveryError(
                f"duplicate upgrade id '{upgrade_id}' "
                f"({seen_ids[upgrade_id].name} and {directory.name})"
            )
        seen_ids[upgrade_id] = directory

        upgrade_py = directory / "upgrade.py"
        if not upgrade_py.is_file():
            raise DiscoveryError(
                f"upgrade directory '{directory.name}' is missing upgrade.py"
            )

        metadata = _extract_metadata(upgrade_py)
        descriptors.append(
            UpgradeDescriptor(
                upgrade_id=upgrade_id,
                slug=slug,
                directory=directory,
                upgrade_py=upgrade_py,
                description=metadata["description"],
                phase=metadata["phase"],
                interactive=metadata["interactive"],
                timeout_seconds=metadata["timeout_seconds"],
            )
        )

    return tuple(descriptors)


def load_upgrade_module(upgrade_py: Path) -> ModuleType:
    """Import ``upgrade.py`` via importlib with a unique synthetic module name."""
    module_name = f"_brain_upgrade_module.{upgrade_py.parent.name}"
    spec = importlib.util.spec_from_file_location(module_name, upgrade_py)
    if spec is None or spec.loader is None:
        raise DiscoveryError(f"could not load module spec for {upgrade_py}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module


def _extract_metadata(upgrade_py: Path) -> dict[str, Any]:
    """Import the upgrade module and validate its module-level metadata."""
    module = load_upgrade_module(upgrade_py)

    description = getattr(module, "DESCRIPTION", None)
    if not isinstance(description, str) or not description.strip():
        raise DiscoveryError(
            f"upgrade '{upgrade_py.parent.name}' missing required "
            "DESCRIPTION (non-empty str)"
        )

    run_callable = getattr(module, "run", None)
    if not callable(run_callable):
        raise DiscoveryError(
            f"upgrade '{upgrade_py.parent.name}' missing required run(ctx) callable"
        )

    phase = getattr(module, "PHASE", DEFAULT_PHASE)
    if phase not in ALLOWED_PHASES:
        raise DiscoveryError(
            f"upgrade '{upgrade_py.parent.name}' has unknown PHASE "
            f"'{phase}'; expected one of {ALLOWED_PHASES}"
        )

    interactive = bool(getattr(module, "INTERACTIVE", False))
    default_timeout = (
        DEFAULT_INTERACTIVE_TIMEOUT_SECONDS if interactive else DEFAULT_TIMEOUT_SECONDS
    )
    timeout_seconds = int(getattr(module, "TIMEOUT_SECONDS", default_timeout))
    if timeout_seconds <= 0:
        raise DiscoveryError(
            f"upgrade '{upgrade_py.parent.name}' has non-positive "
            f"TIMEOUT_SECONDS={timeout_seconds}"
        )

    return {
        "description": description.strip(),
        "phase": phase,
        "interactive": interactive,
        "timeout_seconds": timeout_seconds,
    }
