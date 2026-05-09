"""Worker Actor job-execution runtime helpers."""

from __future__ import annotations

from lib.sdk.calls import JobClaimResult
from lib.sdk.client import BrainClient
from lib.sdk.errors import BrainDependencyError, BrainDomainError, BrainTransportError
from lib.shared.logging import get_logger

_LOGGER = get_logger(__name__)


def run_execution(*, client: BrainClient, claim: JobClaimResult, channel: str) -> None:
    """Execute one claimed job and report the result back to the Job Service."""
    execution_id = claim.execution_id
    _LOGGER.info(
        "Executing job: execution_id=%s op_id=%s attempt=%d/%d",
        execution_id,
        claim.op_id,
        claim.attempt_number,
        claim.max_attempts,
    )
    try:
        client.invoke_op(
            op_id=claim.op_id,
            input_payload=claim.input_payload,
            actor=claim.actor,
            channel=channel,
            invocation_id=claim.trace_id,
            parent_invocation_id=claim.parent_envelope_id,
        )
        client.job_complete_execution(execution_id=execution_id)
        _LOGGER.info("Execution succeeded: execution_id=%s", execution_id)
    except BrainDependencyError as exc:
        _LOGGER.warning(
            "Execution failed (dependency, retryable): execution_id=%s error=%s",
            execution_id,
            exc,
        )
        safe_fail(
            client=client,
            execution_id=execution_id,
            error_message=str(exc),
            is_retryable=True,
        )
    except BrainDomainError as exc:
        _LOGGER.warning(
            "Execution failed (domain): execution_id=%s error=%s",
            execution_id,
            exc,
        )
        safe_fail(
            client=client,
            execution_id=execution_id,
            error_message=str(exc),
            is_retryable=False,
        )
    except BrainTransportError as exc:
        _LOGGER.warning(
            "Execution failed (transport, retryable): execution_id=%s error=%s",
            execution_id,
            exc,
        )
        safe_fail(
            client=client,
            execution_id=execution_id,
            error_message=str(exc),
            is_retryable=exc.retryable,
        )
    except Exception as exc:
        _LOGGER.exception(
            "Execution failed (unexpected): execution_id=%s", execution_id
        )
        safe_fail(
            client=client,
            execution_id=execution_id,
            error_message=f"unexpected error: {type(exc).__name__}: {exc}",
            is_retryable=False,
        )


def safe_fail(
    *, client: BrainClient, execution_id: str, error_message: str, is_retryable: bool
) -> None:
    """Report a failure result, swallowing any secondary transport errors."""
    try:
        client.job_fail_execution(
            execution_id=execution_id,
            error_message=error_message,
            is_retryable=is_retryable,
        )
    except (BrainTransportError, BrainDomainError) as exc:
        _LOGGER.warning(
            "Failed to report execution failure (transport): execution_id=%s: %s",
            execution_id,
            exc,
        )
    except Exception:
        _LOGGER.exception(
            "Failed to report execution failure: execution_id=%s", execution_id
        )


__all__ = ["run_execution", "safe_fail"]
