"""Skill test harness for unit and dry-run execution."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from skills.context import SkillContext
from skills.policy import DefaultPolicy
from skills.registry import SkillRegistryLoader
from skills.runtime import ExecutionResult, SkillRuntime
from skills.services import SkillServices, set_services


@dataclass(frozen=True)
class DryRunResult:
    dry_run: bool
    skill: str
    version: str
    inputs: dict[str, Any]
    side_effects: list[str]


class SkillTestHarness:
    def __init__(
        self,
        registry_path: Path,
        capabilities_path: Path,
        overlay_paths: list[Path] | None = None,
    ) -> None:
        self.registry = SkillRegistryLoader(
            base_path=registry_path,
            overlay_paths=overlay_paths or [],
            capability_path=capabilities_path,
        )
        self.registry.load()
        self.policy = DefaultPolicy()

    async def run(
        self,
        name: str,
        inputs: dict[str, Any],
        adapters: dict[str, Any],
        allow_capabilities: set[str],
        version: str | None = None,
        dry_run: bool = False,
        services: SkillServices | None = None,
    ) -> ExecutionResult | DryRunResult:
        context = SkillContext(allowed_capabilities=allow_capabilities)
        runtime = SkillRuntime(
            registry=self.registry,
            policy=self.policy,
            adapters=adapters,
        )
        skill = self.registry.get_skill(name, version)
        runtime._validate_schema(inputs, skill.definition.inputs_schema, "inputs")

        if services is not None:
            set_services(services)

        if dry_run:
            return DryRunResult(
                dry_run=True,
                skill=skill.definition.name,
                version=skill.definition.version,
                inputs=inputs,
                side_effects=list(skill.definition.side_effects),
            )

        return await runtime.execute(name, inputs, context, version=version)
