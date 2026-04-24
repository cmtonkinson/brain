"""Logic op handler bridge for loading execute.py entrypoints."""

from __future__ import annotations

from collections.abc import Callable, Mapping
import inspect
from pathlib import Path
from typing import Any

from services.effect.execution.domain import OpExecutionResponse
from services.effect.execution.op_handler_bridge import (
    invoke_call_target,
    normalize_handler_output,
)
from services.effect.execution.registry import (
    OpHandler,
    OpRuntime,
)
from services.reason.policy.domain import OpInvocationRequest


def build_logic_op_handler(
    *,
    op_id: str,
    package_dir: Path,
    entrypoint: str,
    components: Mapping[str, object],
) -> OpHandler:
    """Build a logic op handler from one package entrypoint module."""
    execute = _load_execute_function(
        op_id=op_id,
        package_dir=package_dir,
        entrypoint=entrypoint,
    )
    signature = inspect.signature(execute)
    accepted_parameters = tuple(signature.parameters.values())

    def handler(
        request: OpInvocationRequest,
        runtime: OpRuntime,
    ) -> OpExecutionResponse:
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
            op_id=op_id,
            accepted_parameters=accepted_parameters,
            request=request,
            runtime=runtime,
            invoke_call_target_fn=_invoke_call_target,
        )
        result = execute(**kwargs)
        if isinstance(result, OpExecutionResponse):
            return result
        return OpExecutionResponse(output=normalize_handler_output(result))

    return handler


def _load_execute_function(
    *,
    op_id: str,
    package_dir: Path,
    entrypoint: str,
) -> Callable[..., Any]:
    """Load and validate the callable ``execute`` symbol for one logic op."""
    entrypoint_path = package_dir / entrypoint
    source = entrypoint_path.read_text(encoding="utf-8")
    globals_dict = {
        "__builtins__": __builtins__,
        "__file__": str(entrypoint_path),
        "__name__": f"brain_op_{op_id.replace('-', '_')}",
        "__package__": None,
    }
    exec(compile(source, str(entrypoint_path), "exec"), globals_dict)
    execute = globals_dict.get("execute")
    if not callable(execute):
        raise ValueError(f"logic op entrypoint must export callable execute(): {op_id}")
    return execute


def _build_execute_kwargs(
    *,
    op_id: str,
    accepted_parameters: tuple[inspect.Parameter, ...],
    request: OpInvocationRequest,
    runtime: OpRuntime,
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
                "logic op execute() only supports positional-or-keyword or "
                f"keyword-only parameters: {op_id}"
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
            f"unsupported logic op execute() parameter {parameter.name!r}: {op_id}"
        )
    return kwargs
