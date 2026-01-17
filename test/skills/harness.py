"""Skill test harness for unit and dry-run execution."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from skills.context import SkillContext
from skills.policy import DefaultPolicy
from skills.registry import SkillRegistryLoader
from skills.registry_schema import SkillKind
from skills.runtime import ExecutionResult, SkillRuntime
from skills.services import SkillServices, set_services


@dataclass(frozen=True)
class DryRunResult:
    """Result payload for dry-run skill execution."""

    dry_run: bool
    skill: str
    version: str
    inputs: dict[str, Any]
    side_effects: list[str]


class SkillTestHarness:
    """Helper to execute skills in tests with consistent setup."""

    def __init__(
        self,
        registry_path: Path,
        capabilities_path: Path,
        overlay_paths: list[Path] | None = None,
        op_registry_path: Path | None = None,
    ) -> None:
        """Initialize the harness with registry paths."""
        self.registry = SkillRegistryLoader(
            base_path=registry_path,
            overlay_paths=overlay_paths or [],
            capability_path=capabilities_path,
            op_registry_path=op_registry_path,
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
        pipeline_step_results: dict[str, dict[str, Any]] | None = None,
    ) -> ExecutionResult | DryRunResult:
        """Run a skill or simulate its pipeline wiring in dry-run mode."""
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
            if skill.definition.kind == SkillKind.pipeline:
                _simulate_pipeline(skill.definition, inputs, pipeline_step_results or {})
            return DryRunResult(
                dry_run=True,
                skill=skill.definition.name,
                version=skill.definition.version,
                inputs=inputs,
                side_effects=list(skill.definition.side_effects),
            )

        return await runtime.execute(name, inputs, context, version=version)


def _simulate_pipeline(
    skill_definition: Any,
    inputs: dict[str, Any],
    step_results: dict[str, dict[str, Any]],
) -> None:
    """Simulate pipeline wiring for dry-run validation."""
    step_outputs: dict[str, dict[str, Any]] = {}
    for step in skill_definition.steps:
        resolved_inputs: dict[str, Any] = {}
        for input_name, source in step.inputs.items():
            resolved_inputs[input_name] = _resolve_pipeline_source(
                step.id, source, inputs, step_outputs
            )

        if step.id not in step_results:
            raise ValueError(f"missing dry-run output for step {step.id}")
        output_payload = step_results[step.id]
        step_outputs[step.id] = {
            output_name: output_payload.get(output_name)
            for output_name in step.outputs.keys()
        }


def _resolve_pipeline_source(
    step_id: str,
    source: str,
    inputs: dict[str, Any],
    step_outputs: dict[str, dict[str, Any]],
) -> Any:
    """Resolve a pipeline input source string to a concrete value."""
    if source.startswith("$inputs."):
        key = source.split(".", 1)[1]
        if key not in inputs:
            raise ValueError(f"pipeline step {step_id} missing input {key}")
        return inputs[key]

    if source.startswith("$step."):
        parts = source.split(".")
        if len(parts) < 3:
            raise ValueError(f"pipeline step {step_id} has invalid source {source}")
        source_step = parts[1]
        field = parts[2]
        if source_step not in step_outputs:
            raise ValueError(f"pipeline step {step_id} missing output from {source_step}")
        if field not in step_outputs[source_step]:
            raise ValueError(f"pipeline step {step_id} missing output field {field}")
        return step_outputs[source_step][field]

    raise ValueError(f"pipeline step {step_id} has invalid source {source}")
