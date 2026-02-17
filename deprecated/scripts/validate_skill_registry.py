#!/usr/bin/env python3
"""Validate skill registry and overlays."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from skills.registry_schema import OpRegistry, SkillRegistry
from skills.registry_validation import (
    RegistryIndex,
    load_json,
    validate_overlay_file,
    validate_op_registry_file,
    validate_registry_file,
)


def _parse_args() -> argparse.Namespace:
    """Parse CLI arguments for registry validation."""
    parser = argparse.ArgumentParser(description="Validate skill registry files.")
    parser.add_argument(
        "--registry",
        type=Path,
        default=Path("config/skill-registry.json"),
        help="Path to the base registry (required).",
    )
    parser.add_argument(
        "--op-registry",
        type=Path,
        default=Path("config/op-registry.json"),
        help="Path to the op registry (required).",
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
    parser.add_argument(
        "--op-overlay",
        type=Path,
        action="append",
        default=[],
        help="Op overlay file path (can be repeated).",
    )
    return parser.parse_args()


def main() -> int:
    """Run registry validation and return a process exit code."""
    args = _parse_args()

    if not args.registry.exists():
        print(f"Registry file not found: {args.registry}", file=sys.stderr)
        return 2
    if not args.op_registry.exists():
        print(f"Op registry file not found: {args.op_registry}", file=sys.stderr)
        return 2

    errors = []
    errors.extend(
        validate_registry_file(args.registry, args.capabilities, op_registry_path=args.op_registry)
    )
    errors.extend(validate_op_registry_file(args.op_registry, args.capabilities))

    registry_index = None
    op_index = None
    if not errors:
        registry = SkillRegistry.model_validate(load_json(args.registry))
        registry_index = RegistryIndex.from_registry(registry)
        op_registry = OpRegistry.model_validate(load_json(args.op_registry))
        op_index = RegistryIndex.from_op_registry(op_registry)

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

    op_overlays = args.op_overlay
    if not op_overlays:
        op_overlays = [
            Path("config/op-registry.local.yml"),
            Path("~/.config/brain/op-registry.local.yml").expanduser(),
        ]

    for overlay_path in op_overlays:
        if not overlay_path.exists():
            continue
        errors.extend(validate_overlay_file(overlay_path, op_index, entry_label="op"))

    if errors:
        for error in errors:
            print(f"ERROR: {error}", file=sys.stderr)
        return 1

    print("Skill registry validation passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
