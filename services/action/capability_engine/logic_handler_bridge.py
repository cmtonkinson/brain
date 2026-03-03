"""Logic-skill handler bridge for loading execute.py entrypoints."""

from __future__ import annotations

from collections.abc import Callable, Mapping
import inspect
from pathlib import Path
from typing import Any

from pydantic import BaseModel

from services.action.capability_engine.domain import CapabilityExecutionResponse
from services.action.capability_engine.op_handler_bridge import invoke_call_target
from services.action.capability_engine.registry import (
    CapabilityHandler,
    CapabilityRuntime,
)
from services.action.policy_service.domain import CapabilityInvocationRequest


def build_logic_skill_handler(
    *,
    capability_id: str,
    package_dir: Path,
    entrypoint: str,
    components: Mapping[str, object],
) -> CapabilityHandler:
    """Build a logic-skill handler from one package entrypoint module."""
    execute = _load_execute_function(
        capability_id=capability_id,
        package_dir=package_dir,
        entrypoint=entrypoint,
    )
    signature = inspect.signature(execute)
    accepted_parameters = tuple(signature.parameters.values())

    def handler(
        request: CapabilityInvocationRequest,
        runtime: CapabilityRuntime,
    ) -> CapabilityExecutionResponse:
        def _invoke_call_target(
            *,
            call_target: str,
            input_payload: Mapping[str, Any],
        ) -> Any:
            return invoke_call_target(
                call_target=call_target,
                components=components,
                meta=request.metadata,
                input_payload=input_payload,
            )

        kwargs = _build_execute_kwargs(
            capability_id=capability_id,
            accepted_parameters=accepted_parameters,
            request=request,
            runtime=runtime,
            invoke_call_target_fn=_invoke_call_target,
        )
        result = execute(**kwargs)
        if isinstance(result, CapabilityExecutionResponse):
            return result
        return CapabilityExecutionResponse(output=_normalize_output(result))

    return handler


def _load_execute_function(
    *,
    capability_id: str,
    package_dir: Path,
    entrypoint: str,
) -> Callable[..., Any]:
    """Load and validate the callable ``execute`` symbol for one skill."""
    entrypoint_path = package_dir / entrypoint
    source = entrypoint_path.read_text(encoding="utf-8")
    globals_dict = {
        "__builtins__": __builtins__,
        "__file__": str(entrypoint_path),
        "__name__": f"brain_capability_{capability_id.replace('-', '_')}",
        "__package__": None,
    }
    exec(compile(source, str(entrypoint_path), "exec"), globals_dict)
    execute = globals_dict.get("execute")
    if not callable(execute):
        raise ValueError(
            f"logic skill entrypoint must export callable execute(): {capability_id}"
        )
    return execute


def _build_execute_kwargs(
    *,
    capability_id: str,
    accepted_parameters: tuple[inspect.Parameter, ...],
    request: CapabilityInvocationRequest,
    runtime: CapabilityRuntime,
    invoke_call_target_fn: Callable[..., Any],
) -> dict[str, Any]:
    """Map supported execute() parameter names onto runtime values."""
    kwargs: dict[str, Any] = {}
    for parameter in accepted_parameters:
        if parameter.kind not in (
            inspect.Parameter.POSITIONAL_OR_KEYWORD,
            inspect.Parameter.KEYWORD_ONLY,
        ):
            raise ValueError(
                "logic skill execute() only supports positional-or-keyword or "
                f"keyword-only parameters: {capability_id}"
            )
        if parameter.name == "request":
            kwargs[parameter.name] = request
            continue
        if parameter.name == "input_payload":
            kwargs[parameter.name] = request.input_payload
            continue
        if parameter.name == "runtime":
            kwargs[parameter.name] = runtime
            continue
        if parameter.name == "invoke_call_target":
            kwargs[parameter.name] = invoke_call_target_fn
            continue
        raise ValueError(
            f"unsupported logic skill execute() parameter {parameter.name!r}: "
            f"{capability_id}"
        )
    return kwargs


def _normalize_output(value: Any) -> dict[str, Any] | None:
    """Convert a logic skill return value into normalized CES output."""
    if value is None:
        return None
    if isinstance(value, dict):
        return value
    if isinstance(value, bool):
        return {"result": value}
    if isinstance(value, BaseModel):
        return value.model_dump(mode="json")
    if isinstance(value, list):
        return {
            "items": [
                item.model_dump(mode="json") if isinstance(item, BaseModel) else item
                for item in value
            ]
        }
    if isinstance(value, tuple):
        return {
            "items": [
                item.model_dump(mode="json") if isinstance(item, BaseModel) else item
                for item in value
            ]
        }
    return {"result": value}
