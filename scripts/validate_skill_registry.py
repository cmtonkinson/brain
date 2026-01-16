#!/usr/bin/env python3
"""Validate skill registry and overlays."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from skills.registry_schema import SkillRegistry
from skills.registry_validation import (
    RegistryIndex,
    load_json,
    validate_overlay_file,
    validate_registry_file,
)


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Validate skill registry files.")
    parser.add_argument(
        "--registry",
        type=Path,
        default=Path("config/skill-registry.json"),
        help="Path to the base registry (required).",
    )
    parser.add_argument(
        "--capabilities",
        type=Path,
        default=Path("config/capabilities.json"),
        help="Path to the capability list.",
    )
    parser.add_argument(
        "--overlay",
        type=Path,
        action="append",
        default=[],
        help="Overlay file path (can be repeated).",
    )
    return parser.parse_args()


def main() -> int:
    args = _parse_args()

    if not args.registry.exists():
        print(f"Registry file not found: {args.registry}", file=sys.stderr)
        return 2

    errors = []
    errors.extend(validate_registry_file(args.registry, args.capabilities))

    registry_index = None
    if not errors:
        registry = SkillRegistry.model_validate(load_json(args.registry))
        registry_index = RegistryIndex.from_registry(registry)

    overlays = args.overlay
    if not overlays:
        overlays = [
            Path("config/skill-registry.local.yml"),
            Path("~/.config/brain/skill-registry.local.yml").expanduser(),
        ]

    for overlay_path in overlays:
        if not overlay_path.exists():
            continue
        errors.extend(validate_overlay_file(overlay_path, registry_index))

    if errors:
        for error in errors:
            print(f"ERROR: {error}", file=sys.stderr)
        return 1

    print("Skill registry validation passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
