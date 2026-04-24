"""Shared Language recovery primitives used by Agent and Subagent loops.

Owns the policy on which Language errors are retryable, how the provider
profile fallback sequence is ordered, and how long to back off between
provider-level retries.
"""

from __future__ import annotations

from lib.sdk.errors import (
    BrainDependencyError,
    BrainInternalError,
    BrainSdkError,
    BrainTransportError,
)


_LMS_LANGUAGE_OPERATIONS: frozenset[str] = frozenset(
    {"lms.chat", "lms.chat_with_tools"}
)
"""Operation names that identify Language Service calls for recovery classification."""

LMS_PROVIDER_RETRY_DELAYS_SECONDS: tuple[float, ...] = (0.5, 1.0)
"""Per-attempt back-off durations for provider-level Language retries."""

LMS_RECOVERY_NOTICE_DELAY_THRESHOLD_SECONDS: float = 1.0
"""Cumulative retry delay above which a recovery notice may surface."""

INVALID_TOOL_CALL_REPAIR_ATTEMPTS: int = 3
"""How many times the loop will reissue a turn to repair invalid tool calls."""

INVALID_TOOL_CALL_RETRY_INSTRUCTION: str = (
    "A prior response attempted to call tool names that were not in the "
    "currently advertised tool list. Each turn starts with a minimal "
    "advertised set — the discovery tools (`search_tools`, `get_tool_info`) "
    "and any always-on tools — and any other tool you saw in earlier turns "
    "or inside discovery results is currently unavailable. On this response: "
    "(1) if you already know the exact tool id you need, call "
    '`get_tool_info(tool_id="<id>")` so the runtime advertises it on the '
    "next hop, then invoke it; (2) if you do not know the id yet, call "
    '`search_tools(query="<concept>")` first; (3) only emit tool calls '
    "whose exact names appear in the tool definitions for THIS hop."
)


def language_recovery_profile_sequence(initial_profile: str) -> tuple[str, ...]:
    """Return the ordered profile fallback sequence for one turn.

    The sequence preserves the initially requested profile as the first
    attempt then steps to neighbours so a transient provider-side issue
    on one model can cleanly fall over to another.
    """
    if initial_profile == "quick":
        candidates = ("quick", "standard", "deep")
    elif initial_profile == "deep":
        candidates = ("deep", "standard", "quick")
    else:
        candidates = ("standard", "quick", "deep")
    return tuple(dict.fromkeys(candidates))


def should_retry_language_failure(exc: BrainSdkError) -> bool:
    """Return True when one Language failure should trigger local recovery attempts."""
    if isinstance(exc, BrainDependencyError):
        return any(detail.retryable for detail in exc.details)
    if isinstance(exc, BrainTransportError):
        return _is_retryable_language_transport_failure(exc)
    if isinstance(exc, BrainInternalError):
        return _is_retryable_language_internal_failure(exc)
    return False


def should_notify_operator_of_language_recovery(exc: BrainSdkError) -> bool:
    """Return True when one Language failure warrants a visible in-progress notice."""
    return isinstance(exc, (BrainDependencyError, BrainTransportError)) and (
        should_retry_language_failure(exc)
    )


def is_retryable_language_throttle(exc: BrainDependencyError) -> bool:
    """Return True when one Language dependency failure represents provider throttling."""
    if exc.operation not in _LMS_LANGUAGE_OPERATIONS:
        return False
    if not any(detail.retryable for detail in exc.details):
        return False
    message = str(exc).lower()
    throttle_tokens = ("rate limit", "rate_limit", "throttle", "too many requests")
    return any(token in message for token in throttle_tokens)


def is_retryable_language_timeout(exc: BrainDependencyError) -> bool:
    """Return True when one Language dependency failure represents timeout exhaustion."""
    if exc.operation not in _LMS_LANGUAGE_OPERATIONS:
        return False
    if not any(detail.retryable for detail in exc.details):
        return False
    message = str(exc).lower()
    timeout_tokens = ("timed out", "timeout", "readtimeout")
    return any(token in message for token in timeout_tokens)


def is_retryable_language_transport_timeout(exc: BrainTransportError) -> bool:
    """Return True when one Language transport failure represents timeout exhaustion."""
    if exc.operation not in _LMS_LANGUAGE_OPERATIONS:
        return False
    if not exc.retryable:
        return False
    message = str(exc).lower()
    timeout_tokens = ("timed out", "timeout", "readtimeout")
    return any(token in message for token in timeout_tokens)


def _is_retryable_language_transport_failure(exc: BrainTransportError) -> bool:
    """Return True when one Language transport failure merits another whole-turn try."""
    if exc.operation not in _LMS_LANGUAGE_OPERATIONS:
        return False
    return exc.retryable or exc.status_code >= 500 or exc.status_code == 429


def _is_retryable_language_internal_failure(exc: BrainInternalError) -> bool:
    """Return True when one Language internal failure is marked as recoverable."""
    if exc.operation not in _LMS_LANGUAGE_OPERATIONS:
        return False
    return any(detail.retryable for detail in exc.details)


__all__ = [
    "INVALID_TOOL_CALL_REPAIR_ATTEMPTS",
    "INVALID_TOOL_CALL_RETRY_INSTRUCTION",
    "LMS_PROVIDER_RETRY_DELAYS_SECONDS",
    "LMS_RECOVERY_NOTICE_DELAY_THRESHOLD_SECONDS",
    "is_retryable_language_throttle",
    "is_retryable_language_timeout",
    "is_retryable_language_transport_timeout",
    "language_recovery_profile_sequence",
    "should_notify_operator_of_language_recovery",
    "should_retry_language_failure",
]
