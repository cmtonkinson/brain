"""Pipeline op handler bridge for declarative op chaining."""

from __future__ import annotations

from services.effect.execution.domain import (
    OpExecutionResponse,
    CompoundOpManifest,
)
from services.effect.execution.registry import (
    OpHandler,
    OpRegistry,
    OpRuntime,
)
from services.reason.policy.domain import OpInvocationRequest


def build_pipeline_op_handler(
    *,
    manifest: CompoundOpManifest,
    registry: OpRegistry,
) -> OpHandler:
    """Build one runtime handler for a declarative pipeline op."""
    if manifest.kind != "pipeline":
        raise ValueError(
            f"pipeline handler requires pipeline manifest: {manifest.op_id}"
        )

    steps = []
    for entry in manifest.pipeline:
        step = registry.pipeline_step(entry)
        step_manifest = registry.resolve_manifest(op_id=step.op)
        if step_manifest is None:
            raise ValueError(
                f"pipeline step manifest not found for {manifest.op_id}: {step.op}"
            )
        steps.append((step, step_manifest))

    def handler(
        request: OpInvocationRequest,
        runtime: OpRuntime,
    ) -> OpExecutionResponse:
        current_payload = registry.project_pipeline_payload(
            payload=request.input_payload,
            consumer_schema=registry.pipeline_step_input_schema(
                step=steps[0][0],
                consumer_schema=steps[0][1].input_schema,
            ),
        )
        final_step_output = None

        for index, (_step, step_manifest) in enumerate(steps):
            result = runtime.invoke_nested(
                op_id=step_manifest.op_id,
                input_payload=current_payload,
            )
            final_step_output = result.output
            if index == len(steps) - 1:
                continue
            next_step, next_manifest = steps[index + 1]
            current_payload = registry.project_pipeline_payload(
                payload=result.output,
                consumer_schema=registry.pipeline_step_input_schema(
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
        return OpExecutionResponse(output=final_output)

    return handler
