"""Pipeline-skill handler bridge for declarative capability chaining."""

from __future__ import annotations

from services.action.capability_engine.domain import (
    CapabilityExecutionResponse,
    SkillCapabilityManifest,
)
from services.action.capability_engine.registry import (
    CapabilityHandler,
    CapabilityRegistry,
    CapabilityRuntime,
)
from services.action.policy_service.domain import CapabilityInvocationRequest


def build_pipeline_skill_handler(
    *,
    manifest: SkillCapabilityManifest,
    registry: CapabilityRegistry,
) -> CapabilityHandler:
    """Build one runtime handler for a declarative pipeline skill."""
    if manifest.kind != "pipeline_skill":
        raise ValueError(
            f"pipeline handler requires pipeline_skill manifest: {manifest.capability_id}"
        )

    steps = []
    for entry in manifest.pipeline:
        step = registry._pipeline_step(entry)
        step_manifest = registry.resolve_manifest(capability_id=step.capability)
        if step_manifest is None:
            raise ValueError(
                "pipeline step manifest not found for "
                f"{manifest.capability_id}: {step.capability}"
            )
        steps.append((step, step_manifest))

    def handler(
        request: CapabilityInvocationRequest,
        runtime: CapabilityRuntime,
    ) -> CapabilityExecutionResponse:
        current_payload = registry.project_pipeline_payload(
            payload=request.input_payload,
            consumer_schema=registry._pipeline_step_input_schema(
                step=steps[0][0],
                consumer_schema=steps[0][1].input_schema,
            ),
        )
        final_step_output = None

        for index, (_step, step_manifest) in enumerate(steps):
            result = runtime.invoke_nested(
                capability_id=step_manifest.capability_id,
                input_payload=current_payload,
            )
            final_step_output = result.output
            if index == len(steps) - 1:
                continue
            next_step, next_manifest = steps[index + 1]
            current_payload = registry.project_pipeline_payload(
                payload=result.output,
                consumer_schema=registry._pipeline_step_input_schema(
                    step=next_step,
                    consumer_schema=next_manifest.input_schema,
                ),
            )

        if manifest.output_schema is None:
            final_output = None
        else:
            final_output = registry.project_pipeline_payload(
                payload=final_step_output,
                consumer_schema=manifest.output_schema,
            )
        return CapabilityExecutionResponse(output=final_output)

    return handler
