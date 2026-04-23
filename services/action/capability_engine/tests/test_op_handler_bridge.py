"""Unit tests for generic Op handler bridge."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import pytest
from pydantic import BaseModel, ConfigDict

from lib.shared.envelope import EnvelopeMeta, new_meta, EnvelopeKind
from lib.shared.envelope.envelope import Envelope
from lib.shared.envelope.payload import Payload
from lib.shared.errors import not_found_error
from services.action.capability_engine.domain import CapabilityExecutionResponse
from services.action.capability_engine.op_handler_bridge import (
    OpHandlerBridgeError,
    build_op_handler,
)
from services.action.policy_service.domain import (
    CapabilityInvocationRequest,
    CapabilityPolicyInput,
    InvocationPolicyInput,
)


class _Item(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    name: str
    value: int


def _success_envelope(meta: EnvelopeMeta, payload: Any) -> Envelope:
    return Envelope(
        metadata=meta,
        payload=Payload(value=payload),
        errors=[],
    )


def _failure_envelope(meta: EnvelopeMeta) -> Envelope:
    return Envelope(
        metadata=meta,
        payload=None,
        errors=[not_found_error("thing not found")],
    )


class _FakeService:
    """Fake service with keyword-only methods returning Envelope."""

    def greet(self, *, meta: EnvelopeMeta, name: str) -> Envelope:
        return _success_envelope(meta, _Item(name=name, value=42))

    def echo_bool(self, *, meta: EnvelopeMeta, flag: bool) -> Envelope:
        return _success_envelope(meta, flag)

    def current_datetime(self, *, meta: EnvelopeMeta) -> Envelope:
        return _success_envelope(meta, datetime(2026, 3, 3, 12, 0, 0, tzinfo=UTC))

    def list_items(self, *, meta: EnvelopeMeta, prefix: str) -> Envelope:
        items = [_Item(name=f"{prefix}-1", value=1), _Item(name=f"{prefix}-2", value=2)]
        return _success_envelope(meta, items)

    def no_args(self, *, meta: EnvelopeMeta) -> Envelope:
        return _success_envelope(meta, True)

    def optional_param(
        self, *, meta: EnvelopeMeta, required: str, optional: str = "default"
    ) -> Envelope:
        return _success_envelope(meta, _Item(name=required, value=len(optional)))

    def fail_method(self, *, meta: EnvelopeMeta, key: str) -> Envelope:
        return _failure_envelope(meta)


def _components(service: object, component_id: str = "svc") -> dict[str, object]:
    return {component_id: service}


def _request(
    meta: EnvelopeMeta, payload: dict[str, Any]
) -> CapabilityInvocationRequest:
    return CapabilityInvocationRequest(
        metadata=meta,
        capability=CapabilityPolicyInput(
            capability_id="test-op",
            kind="op",
            version="1.0.0",
        ),
        invocation=InvocationPolicyInput(
            actor="operator",
            source="agent",
            channel="signal",
            invocation_id="inv-1",
        ),
        input_payload=payload,
    )


class _StubRuntime:
    def invoke_nested(self, *, capability_id: str, input_payload: dict[str, Any]):
        return CapabilityExecutionResponse(output=None)


def _meta() -> EnvelopeMeta:
    return new_meta(kind=EnvelopeKind.COMMAND, source="test", principal="operator")


def test_resolves_service_and_method() -> None:
    handler = build_op_handler(
        call_target="svc.greet", components=_components(_FakeService())
    )
    meta = _meta()
    result = handler(_request(meta, {"name": "world"}), _StubRuntime())
    assert result.output == {"name": "world", "value": 42}


def test_passes_meta_from_request_metadata() -> None:
    calls: list[EnvelopeMeta] = []

    class _Recorder:
        def ping(self, *, meta: EnvelopeMeta) -> Envelope:
            calls.append(meta)
            return _success_envelope(meta, True)

    handler = build_op_handler(
        call_target="svc.ping", components=_components(_Recorder())
    )
    meta = _meta()
    handler(_request(meta, {}), _StubRuntime())
    assert calls[0] is meta


def test_passes_input_payload_as_kwargs() -> None:
    handler = build_op_handler(
        call_target="svc.greet", components=_components(_FakeService())
    )
    result = handler(_request(_meta(), {"name": "test"}), _StubRuntime())
    assert result.output is not None
    assert result.output["name"] == "test"


def test_rejects_unknown_keys() -> None:
    handler = build_op_handler(
        call_target="svc.greet", components=_components(_FakeService())
    )
    with pytest.raises(ValueError, match="unknown input keys"):
        handler(_request(_meta(), {"name": "ok", "extra": "bad"}), _StubRuntime())


def test_rejects_missing_required_keys() -> None:
    handler = build_op_handler(
        call_target="svc.greet", components=_components(_FakeService())
    )
    with pytest.raises(ValueError, match="missing required input keys"):
        handler(_request(_meta(), {}), _StubRuntime())


def test_allows_optional_params_omitted() -> None:
    handler = build_op_handler(
        call_target="svc.optional_param", components=_components(_FakeService())
    )
    result = handler(_request(_meta(), {"required": "hello"}), _StubRuntime())
    assert result.output is not None
    assert result.output["name"] == "hello"
    assert result.output["value"] == len("default")


def test_unwraps_pydantic_model_payload() -> None:
    handler = build_op_handler(
        call_target="svc.greet", components=_components(_FakeService())
    )
    result = handler(_request(_meta(), {"name": "model"}), _StubRuntime())
    assert result.output == {"name": "model", "value": 42}


def test_unwraps_list_payload() -> None:
    handler = build_op_handler(
        call_target="svc.list_items", components=_components(_FakeService())
    )
    result = handler(_request(_meta(), {"prefix": "x"}), _StubRuntime())
    assert result.output is not None
    assert len(result.output["items"]) == 2
    assert result.output["items"][0]["name"] == "x-1"


def test_unwraps_bool_payload() -> None:
    handler = build_op_handler(
        call_target="svc.echo_bool", components=_components(_FakeService())
    )
    result = handler(_request(_meta(), {"flag": True}), _StubRuntime())
    assert result.output == {"result": True}


def test_unwraps_datetime_payload_as_isoformat_string() -> None:
    handler = build_op_handler(
        call_target="svc.current_datetime", components=_components(_FakeService())
    )
    result = handler(_request(_meta(), {}), _StubRuntime())
    assert result.output == {"result": "2026-03-03T12:00:00+00:00"}


def test_passes_through_structured_errors() -> None:
    handler = build_op_handler(
        call_target="svc.fail_method", components=_components(_FakeService())
    )
    with pytest.raises(OpHandlerBridgeError) as exc_info:
        handler(_request(_meta(), {"key": "missing"}), _StubRuntime())
    assert len(exc_info.value.errors) == 1
    assert exc_info.value.errors[0].message == "thing not found"


def test_raises_for_missing_component() -> None:
    with pytest.raises(ValueError, match="component not found"):
        build_op_handler(call_target="missing.method", components={})


def test_raises_for_missing_method() -> None:
    with pytest.raises(ValueError, match="method.*not found"):
        build_op_handler(
            call_target="svc.nonexistent", components=_components(_FakeService())
        )


def test_validates_call_target_format() -> None:
    with pytest.raises(ValueError, match="invalid call_target format"):
        build_op_handler(call_target="no_dot", components={})

    with pytest.raises(ValueError, match="invalid call_target format"):
        build_op_handler(call_target=".method", components={})


def test_no_args_method_works_with_empty_payload() -> None:
    handler = build_op_handler(
        call_target="svc.no_args", components=_components(_FakeService())
    )
    result = handler(_request(_meta(), {}), _StubRuntime())
    assert result.output == {"result": True}
