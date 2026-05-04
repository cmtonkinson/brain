"""Subprocess entrypoint: ``python -m lib.core.upgrades.execute <upgrade_dir>``.

Reads the BRAIN_* env contract, builds an ``UpgradeContext``, imports the
upgrade's ``upgrade.py``, and calls its ``run(ctx)`` callable. Exits 0 on
success or non-zero on any exception (with traceback to stderr).
"""

from __future__ import annotations

import logging
import os
import sys
import traceback
from pathlib import Path

from lib.core.upgrades.api import UpgradeContext
from lib.core.upgrades.discovery import load_upgrade_module


def main(argv: list[str] | None = None) -> int:
    args = list(argv if argv is not None else sys.argv[1:])
    if len(args) != 1:
        print(
            "usage: python -m lib.core.upgrades.execute <upgrade_directory>",
            file=sys.stderr,
        )
        return 2

    upgrade_dir = Path(args[0]).resolve()
    upgrade_py = upgrade_dir / "upgrade.py"
    if not upgrade_py.is_file():
        print(f"upgrade.py not found in {upgrade_dir}", file=sys.stderr)
        return 2

    try:
        ctx = _build_context(upgrade_dir)
    except KeyError as exc:
        print(f"missing required env var: {exc}", file=sys.stderr)
        return 2

    try:
        module = load_upgrade_module(upgrade_py)
    except Exception:
        traceback.print_exc()
        return 1

    run = getattr(module, "run", None)
    if not callable(run):
        print(
            f"upgrade.py at {upgrade_py} does not define a run(ctx) callable",
            file=sys.stderr,
        )
        return 2

    try:
        run(ctx)
    except SystemExit:
        raise
    except BaseException:
        traceback.print_exc()
        return 1
    return 0


def _build_context(upgrade_dir: Path) -> UpgradeContext:
    """Construct the UpgradeContext from BRAIN_* env vars."""
    env = os.environ
    upgrade_id = env["BRAIN_UPGRADE_ID"]
    slug = env["BRAIN_UPGRADE_SLUG"]
    phase = env["BRAIN_UPGRADE_PHASE"]
    interactive = env["BRAIN_UPGRADE_INTERACTIVE"] == "1"
    repo_root = Path(env["BRAIN_REPO_ROOT"])
    config_dir = Path(env["BRAIN_CONFIG_DIR"])
    state_dir = Path(env["BRAIN_STATE_DIR"])
    cache_dir = Path(env["BRAIN_CACHE_DIR"])
    log_dir = Path(env["BRAIN_LOG_DIR"])

    logger = logging.getLogger(f"brain.upgrade.{upgrade_id}")
    if not logger.handlers and not interactive:
        log_dir.mkdir(parents=True, exist_ok=True)
        handler = logging.FileHandler(log_dir / "upgrade.log", encoding="utf-8")
        handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
        logger.addHandler(handler)
        logger.setLevel(logging.INFO)

    return UpgradeContext(
        upgrade_id=upgrade_id,
        slug=slug,
        phase=phase,
        interactive=interactive,
        repo_root=repo_root,
        config_dir=config_dir,
        state_dir=state_dir,
        cache_dir=cache_dir,
        log_dir=log_dir,
        logger=logger,
    )


if __name__ == "__main__":
    sys.exit(main())
