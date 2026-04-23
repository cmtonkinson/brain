"""Tests for SDK environment context assembly."""

from __future__ import annotations

from types import SimpleNamespace

from lib.sdk.environment import assemble_environment_context
from lib.sdk.errors import BrainDependencyError


class _FakeClient:
    def __init__(self) -> None:
        self.calls: list[dict[str, object]] = []

    def invoke_capability(self, **kwargs: object) -> object:
        self.calls.append(kwargs)
        if kwargs["capability_id"] == "broken-capability":
            raise BrainDependencyError(
                message="dependency down",
                operation="capabilities.invoke",
            )
        return SimpleNamespace(output={"value": kwargs["input_payload"]})


def test_assemble_environment_context_invokes_configured_capabilities() -> None:
    """Environment context assembly should preserve ordered capability outputs."""
    client = _FakeClient()

    context, diagnostics = assemble_environment_context(
        client=client,
        entries=(
            {
                "capability_id": "demo-context",
                "input_payload": {"scope": "today"},
            },
        ),
        actor="operator",
        channel="signal",
    )

    assert diagnostics == ()
    assert len(context.items) == 1
    assert context.items[0].capability_id == "demo-context"
    assert context.items[0].tag_name == "demo-context"
    assert context.items[0].output == {"value": {"scope": "today"}}
    assert client.calls[0]["actor"] == "operator"
    assert client.calls[0]["channel"] == "signal"


def test_assemble_environment_context_omits_failed_capabilities() -> None:
    """Failed environment capabilities should be omitted with diagnostics."""
    context, diagnostics = assemble_environment_context(
        client=_FakeClient(),
        entries=("broken-capability", "current-datetime"),
        actor="operator",
        channel="signal",
    )

    assert [item.capability_id for item in context.items] == ["current-datetime"]
    assert len(diagnostics) == 1
    assert diagnostics[0].capability_id == "broken-capability"
    assert diagnostics[0].error_type == "BrainDependencyError"
