"""Upgrade 20260507_0001 relocate_signal_cli_state_to_xdg.

Moves signal-cli account state from the legacy repo-local path
(``<repo>/data/signal-cli``) to the XDG State directory
(``~/.local/state/brain/signal-cli``), consistent with how the upgrades
ledger is already stored. Updates ``.env`` so
``SIGNAL_CLI_CONFIG_DIR`` points to the new location.
"""

from __future__ import annotations

import re
import shutil
from pathlib import Path

from lib.core.upgrades.api import UpgradeContext

DESCRIPTION = "Relocate signal-cli state from ./data/ to ~/.local/state/brain/"
PHASE = "pre-services"
INTERACTIVE = False
TIMEOUT_SECONDS = 60

_ENV_KEY = "SIGNAL_CLI_CONFIG_DIR"
_ENV_LINE_RE = re.compile(r"^SIGNAL_CLI_CONFIG_DIR\s*=\s*(.+)$", re.MULTILINE)
_LEGACY_RELATIVE = "data/signal-cli"


def run(ctx: UpgradeContext) -> None:
    """Move signal-cli state and update .env to reference the new path."""
    legacy_dir = ctx.repo_root / _LEGACY_RELATIVE
    target_dir = ctx.state_dir / "signal-cli"
    env_path = ctx.repo_root / ".env"

    _migrate_data(ctx=ctx, legacy_dir=legacy_dir, target_dir=target_dir)
    _update_env_file(ctx=ctx, env_path=env_path, target_dir=target_dir)


def _migrate_data(
    *,
    ctx: UpgradeContext,
    legacy_dir: Path,
    target_dir: Path,
) -> None:
    """Copy signal-cli data from the legacy path to the XDG path."""
    if not legacy_dir.exists():
        ctx.logger.info(
            "legacy signal-cli directory does not exist; nothing to migrate: %s",
            legacy_dir,
        )
        return
    accounts_file = legacy_dir / "data" / "accounts.json"
    if not accounts_file.exists():
        ctx.logger.info(
            "no signal-cli account data found in legacy directory; skipping: %s",
            legacy_dir,
        )
        return
    if target_dir.exists() and any(target_dir.iterdir()):
        ctx.logger.info(
            "target directory already contains data; skipping migration: %s",
            target_dir,
        )
        return
    target_dir.mkdir(parents=True, exist_ok=True)
    for child in legacy_dir.iterdir():
        dest = target_dir / child.name
        if child.is_dir():
            shutil.copytree(child, dest, dirs_exist_ok=True)
        else:
            shutil.copy2(child, dest)
    ctx.logger.info(
        "migrated signal-cli state: %s -> %s",
        legacy_dir,
        target_dir,
    )


def _update_env_file(
    *,
    ctx: UpgradeContext,
    env_path: Path,
    target_dir: Path,
) -> None:
    """Rewrite SIGNAL_CLI_CONFIG_DIR in .env to use the XDG path."""
    if not env_path.exists():
        ctx.logger.info(".env not found; skipping env update: %s", env_path)
        return
    content = env_path.read_text(encoding="utf-8")
    match = _ENV_LINE_RE.search(content)
    if match is None:
        ctx.logger.info(
            "%s not found in .env; skipping env update",
            _ENV_KEY,
        )
        return
    current_value = match.group(1).strip()
    # Represent the target as ${HOME}-relative for portability.
    home = Path.home()
    try:
        relative = target_dir.relative_to(home)
        new_value = f"${{HOME}}/{relative}"
    except ValueError:
        new_value = str(target_dir)
    if current_value == new_value:
        ctx.logger.info("%s already set to %s; no change", _ENV_KEY, new_value)
        return
    updated = _ENV_LINE_RE.sub(f"{_ENV_KEY}={new_value}", content)
    env_path.write_text(updated, encoding="utf-8")
    ctx.logger.info(
        "updated .env: %s=%s (was: %s)",
        _ENV_KEY,
        new_value,
        current_value,
    )
