"""Tests for shared op-tool builder and turn-state mechanics."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from lib.agent.tools import build_op_tools, op_error_payload
from lib.agent.turn_state import (
    DefaultTurnState,
    MAX_PENDING_INVOCATIONS,
    PendingInvocation,
)
from lib.sdk.calls import OpDescriptor
from lib.sdk.errors import (
    BrainInternalError,
    BrainNotFoundError,
    BrainPolicyError,
    SdkErrorDetail,
)

_DEMO_DESCRIPTOR = OpDescriptor(
    op_id="demo-tool",
    kind="native",
    version="1.0.0",
    summary="Do the thing.",
    input_schema={"type": "object", "properties": {"value": {"type": "string"}}},
    output_schema={"ok": "boolean"},
    effect="read",
    approval="never",
    required_ops=(),
)

_APPROVAL_DESCRIPTOR = OpDescriptor(
    op_id="vault-move-path",
    kind="native",
    version="1.0.0",
    summary="Move one file or directory path.",
    input_schema={"type": "object"},
    output_schema={"type": "object"},
    effect="read",
    approval="always",
    required_ops=(),
)


class _FakeInvokeResult:
    def __init__(self, output: object) -> None:
        self.output = output


class _SuccessClient:
    def __init__(self) -> None:
        self.calls: list[tuple[str, dict[str, object], str, str, str, str, str]] = []

    def invoke_op(
        self,
        *,
        op_id: str,
        input_payload: dict[str, object],
        actor: str,
        channel: str,
        reply_to_proposal_token: str = "",
        reaction_to_proposal_token: str = "",
        message_text: str = "",
        parent_invocation_id: str = "",
        **_kwargs: object,
    ):
        self.calls.append(
            (
                op_id,
                input_payload,
                actor,
                channel,
                reply_to_proposal_token,
                reaction_to_proposal_token,
                message_text,
            )
        )
        return _FakeInvokeResult(output={"ok": True})


# ---------------------------------------------------------------------------
# Context-invoke path (with OpInvocationContext)
# ---------------------------------------------------------------------------


def test_context_invoke_routes_through_sdk_client() -> None:
    """Op tool wrappers should route calls through Brain SDK with trace metadata."""
    client = _SuccessClient()
    turn_state = DefaultTurnState(
        actor="operator",
        channel="signal",
        message_text="tok-123 approved",
    )
    tools = build_op_tools(
        client=client,
        descriptors=(_DEMO_DESCRIPTOR,),
        invocation_context=turn_state,
    )
    result = tools[0].function(value="x")
    assert result == {"ok": True}
    assert client.calls == [
        (
            "demo-tool",
            {"value": "x"},
            "operator",
            "signal",
            "",
            "",
            "tok-123 approved",
        )
    ]


def test_context_invoke_strips_extra_properties() -> None:
    """Agent-only context properties should be stripped before forwarding."""
    client = _SuccessClient()
    turn_state = DefaultTurnState(
        actor="operator", channel="signal", strip_keys=frozenset({"call_mode"})
    )
    tools = build_op_tools(
        client=client,
        descriptors=(_DEMO_DESCRIPTOR,),
        invocation_context=turn_state,
    )
    tools[0].function(value="x", call_mode="decide")
    assert client.calls[0][1] == {"value": "x"}


def test_context_invoke_returns_policy_denial_payload() -> None:
    """Policy denials should return structured tool data, not raise."""

    class _PolicyClient:
        def invoke_op(self, **_kwargs):
            raise BrainPolicyError(
                message="ops.invoke domain failure: policy denied",
                operation="ops.invoke",
                details=(
                    SdkErrorDetail(
                        code="permission_denied",
                        message="policy denied",
                        category="policy",
                        metadata={
                            "proposal_token": "tok-123",
                            "reason_codes": "approval_required",
                        },
                    ),
                ),
            )

    turn_state = DefaultTurnState(actor="operator", channel="signal")
    tools = build_op_tools(
        client=_PolicyClient(),
        descriptors=(_APPROVAL_DESCRIPTOR,),
        invocation_context=turn_state,
    )
    result = tools[0].function(source_path="old.md", target_path="new.md")
    assert result["error"] == "policy_denied"
    assert result["proposal_token"] == "tok-123"
    assert result["reason_codes"] == ["approval_required"]
    assert "tok-123" in turn_state.pending_invocations


def test_context_invoke_returns_not_found_payload() -> None:
    """Not-found domain failures should return structured tool data."""

    class _NotFoundClient:
        def invoke_op(self, **_kwargs):
            raise BrainNotFoundError(
                message="ops.invoke domain failure: Not Found",
                operation="ops.invoke",
                details=(
                    SdkErrorDetail(
                        code="NOT_FOUND",
                        message="Not Found",
                        category="not_found",
                        metadata={"path": "missing.md"},
                    ),
                ),
            )

    turn_state = DefaultTurnState(actor="operator", channel="signal")
    tools = build_op_tools(
        client=_NotFoundClient(),
        descriptors=(_DEMO_DESCRIPTOR,),
        invocation_context=turn_state,
    )
    result = tools[0].function(value="x")
    assert result["error"] == "not_found"
    assert result["details"][0]["code"] == "NOT_FOUND"


def test_context_invoke_returns_internal_error_payload() -> None:
    """Internal failures should return structured tool data."""

    class _InternalClient:
        def invoke_op(self, **_kwargs):
            raise BrainInternalError(
                message="ops.invoke domain failure: internal fault",
                operation="ops.invoke",
                details=(
                    SdkErrorDetail(
                        code="INTERNAL", message="internal fault", category="internal"
                    ),
                ),
            )

    turn_state = DefaultTurnState(actor="operator", channel="signal")
    tools = build_op_tools(
        client=_InternalClient(),
        descriptors=(_DEMO_DESCRIPTOR,),
        invocation_context=turn_state,
    )
    result = tools[0].function(value="x")
    assert result["error"] == "internal_error"


# ---------------------------------------------------------------------------
# Direct-invoke path (no OpInvocationContext — headless)
# ---------------------------------------------------------------------------


def test_direct_invoke_routes_through_sdk_client() -> None:
    """Headless op tools should route calls through Brain SDK directly."""
    client = _SuccessClient()
    tools = build_op_tools(
        client=client,
        descriptors=(_DEMO_DESCRIPTOR,),
        actor="subagent",
        channel="worker",
    )
    result = tools[0].function(value="x")
    assert result == {"ok": True}
    assert client.calls[0][:4] == ("demo-tool", {"value": "x"}, "subagent", "worker")


def test_direct_invoke_returns_not_found_payload() -> None:
    """Headless tools should also return structured error payloads."""

    class _NotFoundClient:
        def invoke_op(self, **_kwargs):
            raise BrainNotFoundError(
                message="Not Found",
                operation="ops.invoke",
                details=(
                    SdkErrorDetail(
                        code="NOT_FOUND", message="Not Found", category="not_found"
                    ),
                ),
            )

    tools = build_op_tools(
        client=_NotFoundClient(),
        descriptors=(_DEMO_DESCRIPTOR,),
        actor="subagent",
        channel="worker",
    )
    result = tools[0].function(value="x")
    assert result["error"] == "not_found"


# ---------------------------------------------------------------------------
# Schema handling
# ---------------------------------------------------------------------------


def test_uses_descriptor_input_schema() -> None:
    """Tool schema should come from the op descriptor, not be generated."""
    tools = build_op_tools(
        client=_SuccessClient(),
        descriptors=(
            OpDescriptor(
                op_id="vault-get-file",
                kind="native",
                version="1.0.0",
                summary="Read one markdown file by path.",
                input_schema={
                    "type": "object",
                    "properties": {"file_path": {"type": "string"}},
                    "required": ["file_path"],
                    "additionalProperties": False,
                },
                output_schema={"type": "object"},
                effect="read",
                approval="never",
                required_ops=(),
            ),
        ),
        actor="operator",
        channel="signal",
    )
    assert tools[0].tool_def.parameters_json_schema == {
        "type": "object",
        "properties": {"file_path": {"type": "string"}},
        "required": ["file_path"],
        "additionalProperties": False,
    }


def test_extra_input_properties_merged_into_schema() -> None:
    """Extra agent-context properties should appear in the tool schema."""
    tools = build_op_tools(
        client=_SuccessClient(),
        descriptors=(_DEMO_DESCRIPTOR,),
        actor="operator",
        channel="signal",
        extra_input_properties={"call_mode": {"type": "string"}},
    )
    schema = tools[0].tool_def.parameters_json_schema
    assert "call_mode" in schema.get("properties", {})


# ---------------------------------------------------------------------------
# op_error_payload
# ---------------------------------------------------------------------------


def test_op_error_payload_shape() -> None:
    """op_error_payload should return the canonical error dict shape."""
    exc = BrainNotFoundError(
        message="Not Found",
        operation="ops.invoke",
        details=(
            SdkErrorDetail(
                code="NOT_FOUND",
                message="nf",
                category="not_found",
                metadata={"k": "v"},
            ),
        ),
    )
    payload = op_error_payload(error="not_found", op_id="demo", exc=exc)
    assert payload["error"] == "not_found"
    assert payload["op_id"] == "demo"
    assert payload["details"][0]["metadata"] == {"k": "v"}


# ---------------------------------------------------------------------------
# Turn state: pending invocations
# ---------------------------------------------------------------------------


def test_prune_expired_pending_invocations() -> None:
    """Expired invocations should be evicted by prune."""
    ts = DefaultTurnState()
    now = datetime(2025, 1, 1, tzinfo=UTC)
    ts.pending_invocations = {
        "expired": PendingInvocation(
            proposal_token="expired",
            op_id="op-a",
            input_payload={},
            actor="operator",
            channel="signal",
            approval="always",
            reason_codes=(),
            created_at=now - timedelta(minutes=10),
            expires_at=now - timedelta(minutes=1),
        ),
        "active": PendingInvocation(
            proposal_token="active",
            op_id="op-b",
            input_payload={},
            actor="operator",
            channel="signal",
            approval="always",
            reason_codes=(),
            created_at=now,
            expires_at=now + timedelta(hours=1),
        ),
    }
    ts.prune_pending_invocations(now=now)
    assert "expired" not in ts.pending_invocations
    assert "active" in ts.pending_invocations


def test_remember_pending_invocation_evicts_overflow() -> None:
    """Overflow beyond MAX_PENDING_INVOCATIONS should evict oldest."""
    ts = DefaultTurnState(actor="operator", channel="signal")
    now = datetime(2025, 1, 1, tzinfo=UTC)
    for i in range(MAX_PENDING_INVOCATIONS):
        ts.pending_invocations[f"tok-{i:04d}"] = PendingInvocation(
            proposal_token=f"tok-{i:04d}",
            op_id="op-a",
            input_payload={},
            actor="operator",
            channel="signal",
            approval="always",
            reason_codes=(),
            created_at=now + timedelta(seconds=i),
        )
    ts.remember_pending_invocation(
        proposal_token="tok-new",
        op_id="op-b",
        input_payload={},
        approval="always",
        reason_codes=(),
        now=now + timedelta(hours=1),
    )
    assert "tok-new" in ts.pending_invocations
    assert len(ts.pending_invocations) <= MAX_PENDING_INVOCATIONS


def test_proposal_token_for_retry_matches_stored() -> None:
    """Matching pending invocation should return proposal tokens."""
    now = datetime(2025, 1, 1, tzinfo=UTC)
    ts = DefaultTurnState(
        actor="operator",
        channel="signal",
        reply_to_proposal_token="tok-reply",
        pending_invocations={
            "tok-reply": PendingInvocation(
                proposal_token="tok-reply",
                op_id="op-a",
                input_payload={"x": 1},
                actor="operator",
                channel="signal",
                approval="always",
                reason_codes=(),
                created_at=now,
            ),
        },
    )
    reply, reaction = ts.proposal_token_for_retry(op_id="op-a", input_payload={"x": 1})
    assert reply == "tok-reply"
    assert reaction == ""


def test_proposal_token_for_retry_rejects_mismatch() -> None:
    """Mismatched op_id or payload should not return tokens."""
    now = datetime(2025, 1, 1, tzinfo=UTC)
    ts = DefaultTurnState(
        actor="operator",
        channel="signal",
        reply_to_proposal_token="tok-reply",
        pending_invocations={
            "tok-reply": PendingInvocation(
                proposal_token="tok-reply",
                op_id="op-a",
                input_payload={"x": 1},
                actor="operator",
                channel="signal",
                approval="always",
                reason_codes=(),
                created_at=now,
            ),
        },
    )
    reply, reaction = ts.proposal_token_for_retry(op_id="op-b", input_payload={"x": 1})
    assert reply == ""
    assert reaction == ""
