"""Subcommand dispatcher for ``bin/install``."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from lib.setup.wizard import InstallError, run_install


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="install", description="Install or reconfigure Brain."
    )
    parser.add_argument(
        "--reconfigure",
        action="store_true",
        help="Re-walk the wizard against an already-configured install.",
    )
    args = parser.parse_args(argv)

    repo_root = Path(__file__).resolve().parents[2]
    config_dir = _resolve_config_dir()

    try:
        run_install(
            repo_root=repo_root,
            config_dir=config_dir,
            reconfigure=args.reconfigure,
        )
    except InstallError as exc:
        print(str(exc), file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        print("\naborted", file=sys.stderr)
        return 130
    return 0


def _resolve_config_dir() -> Path:
    import os

    override = os.getenv("BRAIN_CONFIG_DIR", "").strip()
    if override:
        return Path(override).expanduser().resolve()
    return Path.home() / ".config" / "brain"


if __name__ == "__main__":
    sys.exit(main())
