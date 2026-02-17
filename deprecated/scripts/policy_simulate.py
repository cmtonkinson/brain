"""Simulate policy evaluation without executing side effects."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from skills.policy import DefaultPolicy, PolicyContext
from skills.registry import OpRegistryLoader, SkillRegistryLoader
from skills.registry_schema import AutonomyLevel

PRECEDENCE_ORDER = [
    "channel_allow_deny",
    "actor_allow_deny",
    "capability_allow_deny",
    "autonomy_ceiling",
    "policy_tags",
    "rate_limits",
]


def _parse_autonomy(value: str | None) -> AutonomyLevel | None:
    """Parse an autonomy string into an enum."""
    if value is None:
        return None
    return AutonomyLevel(value)


def _load_entry(
    kind: str,
    name: str,
    version: str | None,
    skill_registry_path: Path,
    op_registry_path: Path,
    capabilities_path: Path,
    skill_overlays: list[Path],
    op_overlays: list[Path],
):
    """Load a skill or op entry from registries."""
    if kind == "skill":
        registry = SkillRegistryLoader(
            base_path=skill_registry_path,
            overlay_paths=skill_overlays,
            capability_path=capabilities_path,
            op_registry_path=op_registry_path,
        )
        registry.load()
        return registry.get_skill(name, version)
    if kind == "op":
        registry = OpRegistryLoader(
            base_path=op_registry_path,
            overlay_paths=op_overlays,
            capability_path=capabilities_path,
        )
        registry.load()
        return registry.get_op(name, version)
    raise ValueError(f"unknown kind: {kind}")


def simulate_policy_decision(
    *,
    kind: str,
    name: str,
    version: str | None,
    actor: str | None,
    channel: str | None,
    allowed_capabilities: set[str] | None,
    max_autonomy: AutonomyLevel | None,
    confirmed: bool,
    dry_run: bool,
    skill_registry_path: Path,
    op_registry_path: Path,
    capabilities_path: Path,
    skill_overlays: list[Path],
    op_overlays: list[Path],
) -> dict[str, Any]:
    """Return a policy decision payload for simulation purposes."""
    entry = _load_entry(
        kind,
        name,
        version,
        skill_registry_path,
        op_registry_path,
        capabilities_path,
        skill_overlays,
        op_overlays,
    )
    allowed_caps = allowed_capabilities or set(entry.definition.capabilities)
    context = PolicyContext(
        actor=actor,
        channel=channel,
        allowed_capabilities=allowed_caps,
        max_autonomy=max_autonomy,
        confirmed=confirmed,
        dry_run=dry_run,
    )
    decision = DefaultPolicy().evaluate(entry, context)
    return {
        "decision": decision.allowed,
        "reasons": decision.reasons,
        "metadata": decision.metadata,
        "precedence_order": PRECEDENCE_ORDER,
    }


def _parse_args() -> argparse.Namespace:
    """Parse CLI arguments for policy simulation."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--kind", choices=["skill", "op"], required=True)
    parser.add_argument("--name", required=True)
    parser.add_argument("--version", default=None)
    parser.add_argument("--actor", default=None)
    parser.add_argument("--channel", default=None)
    parser.add_argument("--confirmed", action="store_true")
    parser.add_argument("--max-autonomy", default=None)
    parser.add_argument("--allowed-capabilities", default="")
    parser.add_argument("--skill-registry", default="config/skill-registry.json")
    parser.add_argument("--op-registry", default="config/op-registry.json")
    parser.add_argument("--capabilities", default="config/capabilities.json")
    return parser.parse_args()


def main() -> None:
    """Run policy simulation and print JSON output."""
    args = _parse_args()
    skill_overlays = [
        Path("config/skill-registry.local.yml"),
        Path("~/.config/brain/skill-registry.local.yml").expanduser(),
    ]
    op_overlays = [
        Path("config/op-registry.local.yml"),
        Path("~/.config/brain/op-registry.local.yml").expanduser(),
    ]
    allowed_caps = (
        set(filter(None, args.allowed_capabilities.split(",")))
        if args.allowed_capabilities
        else None
    )
    payload = simulate_policy_decision(
        kind=args.kind,
        name=args.name,
        version=args.version,
        actor=args.actor,
        channel=args.channel,
        allowed_capabilities=allowed_caps,
        max_autonomy=_parse_autonomy(args.max_autonomy),
        confirmed=args.confirmed,
        dry_run=True,
        skill_registry_path=Path(args.skill_registry),
        op_registry_path=Path(args.op_registry),
        capabilities_path=Path(args.capabilities),
        skill_overlays=skill_overlays,
        op_overlays=op_overlays,
    )
    print(json.dumps(payload, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
