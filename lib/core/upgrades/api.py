"""Public surface for upgrade authors: ``UpgradeContext`` and ``load_sibling``."""

from __future__ import annotations

import importlib.util
import logging
import sys
from dataclasses import dataclass
from pathlib import Path
from types import ModuleType


@dataclass(frozen=True, slots=True)
class UpgradeContext:
    """Runtime context handed to an upgrade's ``run(ctx)`` callable.

    Constructed by the subprocess entrypoint (``lib.core.upgrades.execute``)
    from environment variables set by the runner. Authors should treat all
    paths as already-existing directories.
    """

    upgrade_id: str
    slug: str
    phase: str
    interactive: bool
    repo_root: Path
    config_dir: Path
    state_dir: Path
    cache_dir: Path
    log_dir: Path
    logger: logging.Logger


def load_sibling(upgrade_file: str | Path, name: str) -> ModuleType:
    """Load a sibling ``.py`` module from the same upgrade directory.

    ``upgrade_file`` should be ``__file__`` from inside ``upgrade.py``.
    ``name`` is the module name without the ``.py`` extension. Returns the
    imported module. Raises ``FileNotFoundError`` if the sibling is missing.
    """
    sibling_path = Path(upgrade_file).resolve().parent / f"{name}.py"
    if not sibling_path.exists():
        raise FileNotFoundError(
            f"sibling module '{name}.py' not found at {sibling_path}"
        )
    upgrade_dir_name = sibling_path.parent.name
    module_name = f"_brain_upgrade.{upgrade_dir_name}.{name}"
    spec = importlib.util.spec_from_file_location(module_name, sibling_path)
    if spec is None or spec.loader is None:
        raise ImportError(f"could not load module spec for {sibling_path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module
