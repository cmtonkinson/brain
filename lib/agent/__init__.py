"""Shared agent runtime primitives for actors/assistant and actors/subagent.

This package owns the canonical PydanticAI tool-loop, the inference-request
builder, the Language recovery policy, and the headless loop driver that every
Brain agent runtime shares. The operator-facing Agent
(``actors/assistant/main.py``) layers Recall context assembly, approval gating,
and operator-recovery notifications on top of these primitives; the
headless Subagent Actor consumes them directly via :func:`run` to drive
single-prompt invocations to completion against the same machinery.
"""

from __future__ import annotations

from lib.agent.cancellation import (
    CancelDecision,
    CancelReason,
    CancellationError,
    TurnSummary,
)
from lib.agent.inference_request import (
    build_inference_request,
)
from lib.agent.loop import LoopResult, run
from lib.agent.recovery import (
    INVALID_TOOL_CALL_REPAIR_ATTEMPTS,
    INVALID_TOOL_CALL_RETRY_INSTRUCTION,
    LMS_PROVIDER_RETRY_DELAYS_SECONDS,
    LMS_RECOVERY_NOTICE_DELAY_THRESHOLD_SECONDS,
    is_retryable_language_throttle,
    is_retryable_language_timeout,
    is_retryable_language_transport_timeout,
    language_recovery_profile_sequence,
    should_notify_operator_of_language_recovery,
    should_retry_language_failure,
)
from lib.shared.observability import set_current_span_attributes, set_span_attributes
from lib.agent.tool_model import (
    AgentToolModel,
    OperatorIntermediateTextNotifier,
    OperatorRecoveryNotifier,
    call_with_optional_meta,
)
from lib.agent.tools import (
    OpInvocationContext,
    build_op_tools,
    build_op_tools_from_descriptors,
    op_error_payload,
    parse_optional_iso_datetime,
)
from lib.agent.toolset import build_brain_toolset, filtered_brain_toolset
from lib.agent.turn_state import (
    DefaultTurnState,
    GET_TOOL_INFO_TOOL_NAME,
    MAX_PENDING_INVOCATIONS,
    PendingInvocation,
    SEARCH_TOOLS_TOOL_NAME,
    TurnState,
)

__all__ = [
    "AgentToolModel",
    "CancelDecision",
    "CancelReason",
    "CancellationError",
    "DefaultTurnState",
    "GET_TOOL_INFO_TOOL_NAME",
    "INVALID_TOOL_CALL_REPAIR_ATTEMPTS",
    "MAX_PENDING_INVOCATIONS",
    "INVALID_TOOL_CALL_RETRY_INSTRUCTION",
    "LMS_PROVIDER_RETRY_DELAYS_SECONDS",
    "LMS_RECOVERY_NOTICE_DELAY_THRESHOLD_SECONDS",
    "LoopResult",
    "OperatorIntermediateTextNotifier",
    "OperatorRecoveryNotifier",
    "PendingInvocation",
    "SEARCH_TOOLS_TOOL_NAME",
    "TurnState",
    "TurnSummary",
    "OpInvocationContext",
    "build_brain_toolset",
    "build_inference_request",
    "build_op_tools",
    "build_op_tools_from_descriptors",
    "call_with_optional_meta",
    "filtered_brain_toolset",
    "op_error_payload",
    "parse_optional_iso_datetime",
    "is_retryable_language_throttle",
    "is_retryable_language_timeout",
    "is_retryable_language_transport_timeout",
    "language_recovery_profile_sequence",
    "run",
    "set_current_span_attributes",
    "set_span_attributes",
    "should_notify_operator_of_language_recovery",
    "should_retry_language_failure",
]
