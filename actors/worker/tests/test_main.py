"""Tests for Brain Worker Actor execution logic.

Test approach: BrainClient is replaced by a lightweight fake that records
calls and can be configured to raise on demand. No live Core connection is
required. The module-level signal handlers and poll loop (_main) are not
tested here — only the pure execution units (_run_execution, _safe_fail,
_resolve_heartbeat_path) and the utility helper _write_heartbeat.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from lib.sdk.calls import JobClaimResult
from lib.sdk.errors import (
    BrainDependencyError,
    BrainDomainError,
    BrainTransportError,
)
from actors.worker.main import (
    _HEARTBEAT_PATH,
    _resolve_heartbeat_path,
    _run_execution,
    _safe_fail,
    _write_heartbeat,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_claim(
    *,
    execution_id: str = "exec-001",
    job_id: str = "job-001",
    op_id: str = "test-cap",
    input_payload: dict[str, Any] | None = None,
    actor: str = "agent",
    trace_id: str = "trace-abc",
    parent_envelope_id: str = "env-xyz",
    attempt_number: int = 1,
    max_attempts: int = 3,
) -> JobClaimResult:
    """Return a minimal JobClaimResult for test use."""
    return JobClaimResult(
        execution_id=execution_id,
        job_id=job_id,
        op_id=op_id,
        input_payload=input_payload or {},
        actor=actor,
        trace_id=trace_id,
        parent_envelope_id=parent_envelope_id,
        attempt_number=attempt_number,
        max_attempts=max_attempts,
    )


@dataclass
class _Call:
    """One recorded method call on the fake client."""

    method: str
    kwargs: dict[str, Any]


class _FakeClient:
    """Minimal BrainClient stand-in that records calls and can raise on demand.

    Set `invoke_raises` or `fail_raises` to an exception instance to trigger
    that error when the corresponding method is called.
    """

    def __init__(
        self,
        *,
        invoke_raises: Exception | None = None,
        fail_raises: Exception | None = None,
    ) -> None:
        self.calls: list[_Call] = []
        self._invoke_raises = invoke_raises
        self._fail_raises = fail_raises

    def invoke_op(self, **kwargs: Any) -> None:
        """Record call; raise configured error when present."""
        self.calls.append(_Call(method="invoke_op", kwargs=kwargs))
        if self._invoke_raises is not None:
            raise self._invoke_raises

    def job_complete_execution(self, **kwargs: Any) -> None:
        """Record call."""
        self.calls.append(_Call(method="job_complete_execution", kwargs=kwargs))

    def job_fail_execution(self, **kwargs: Any) -> None:
        """Record call; raise configured error when present."""
        self.calls.append(_Call(method="job_fail_execution", kwargs=kwargs))
        if self._fail_raises is not None:
            raise self._fail_raises

    def _calls_for(self, method: str) -> list[_Call]:
        """Return all recorded calls for one method name."""
        return [c for c in self.calls if c.method == method]


# ---------------------------------------------------------------------------
# _run_execution — success path
# ---------------------------------------------------------------------------


def test_run_execution_success_invokes_op_then_completes() -> None:
    """Successful execution calls invoke_op then job_complete_execution."""
    client = _FakeClient()
    claim = _make_claim()

    _run_execution(client=client, claim=claim, channel="worker")

    invoke_calls = client._calls_for("invoke_op")
    complete_calls = client._calls_for("job_complete_execution")
    fail_calls = client._calls_for("job_fail_execution")

    assert len(invoke_calls) == 1
    assert len(complete_calls) == 1
    assert len(fail_calls) == 0


def test_run_execution_forwards_claim_fields_to_invoke() -> None:
    """Claim fields are forwarded verbatim to invoke_op."""
    client = _FakeClient()
    claim = _make_claim(
        op_id="my-cap",
        input_payload={"key": "value"},
        actor="agent",
        trace_id="trace-111",
        parent_envelope_id="env-222",
    )

    _run_execution(client=client, claim=claim, channel="worker")

    kwargs = client._calls_for("invoke_op")[0].kwargs
    assert kwargs["op_id"] == "my-cap"
    assert kwargs["input_payload"] == {"key": "value"}
    assert kwargs["actor"] == "agent"
    assert kwargs["channel"] == "worker"
    assert kwargs["invocation_id"] == "trace-111"
    assert kwargs["parent_invocation_id"] == "env-222"


def test_run_execution_forwards_execution_id_to_complete() -> None:
    """job_complete_execution receives the execution_id from the claim."""
    client = _FakeClient()
    claim = _make_claim(execution_id="exec-xyz")

    _run_execution(client=client, claim=claim, channel="worker")

    kwargs = client._calls_for("job_complete_execution")[0].kwargs
    assert kwargs["execution_id"] == "exec-xyz"


# ---------------------------------------------------------------------------
# _run_execution — failure paths
# ---------------------------------------------------------------------------


def test_run_execution_dependency_error_fails_retryable() -> None:
    """BrainDependencyError maps to a retryable job_fail_execution call."""
    exc = BrainDependencyError(message="dep down", operation="ops.invoke")
    client = _FakeClient(invoke_raises=exc)
    claim = _make_claim(execution_id="exec-dep")

    _run_execution(client=client, claim=claim, channel="worker")

    fail_calls = client._calls_for("job_fail_execution")
    assert len(fail_calls) == 1
    assert fail_calls[0].kwargs["execution_id"] == "exec-dep"
    assert fail_calls[0].kwargs["is_retryable"] is True
    assert len(client._calls_for("job_complete_execution")) == 0


def test_run_execution_domain_error_fails_non_retryable() -> None:
    """BrainDomainError maps to a non-retryable job_fail_execution call."""
    exc = BrainDomainError(message="domain boom", operation="ops.invoke")
    client = _FakeClient(invoke_raises=exc)
    claim = _make_claim(execution_id="exec-dom")

    _run_execution(client=client, claim=claim, channel="worker")

    fail_calls = client._calls_for("job_fail_execution")
    assert len(fail_calls) == 1
    assert fail_calls[0].kwargs["execution_id"] == "exec-dom"
    assert fail_calls[0].kwargs["is_retryable"] is False


def test_run_execution_transport_error_retryable_true() -> None:
    """BrainTransportError with retryable=True propagates that flag."""
    exc = BrainTransportError(
        message="timeout",
        operation="ops.invoke",
        status_code=503,
        retryable=True,
    )
    client = _FakeClient(invoke_raises=exc)
    claim = _make_claim()

    _run_execution(client=client, claim=claim, channel="worker")

    fail_calls = client._calls_for("job_fail_execution")
    assert len(fail_calls) == 1
    assert fail_calls[0].kwargs["is_retryable"] is True


def test_run_execution_transport_error_retryable_false() -> None:
    """BrainTransportError with retryable=False propagates that flag."""
    exc = BrainTransportError(
        message="bad request",
        operation="ops.invoke",
        status_code=400,
        retryable=False,
    )
    client = _FakeClient(invoke_raises=exc)
    claim = _make_claim()

    _run_execution(client=client, claim=claim, channel="worker")

    fail_calls = client._calls_for("job_fail_execution")
    assert len(fail_calls) == 1
    assert fail_calls[0].kwargs["is_retryable"] is False


def test_run_execution_unexpected_error_fails_non_retryable() -> None:
    """An untyped exception is caught and mapped to a non-retryable failure."""
    client = _FakeClient(invoke_raises=RuntimeError("oops"))
    claim = _make_claim(execution_id="exec-unk")

    _run_execution(client=client, claim=claim, channel="worker")

    fail_calls = client._calls_for("job_fail_execution")
    assert len(fail_calls) == 1
    assert fail_calls[0].kwargs["execution_id"] == "exec-unk"
    assert fail_calls[0].kwargs["is_retryable"] is False
    assert "RuntimeError" in fail_calls[0].kwargs["error_message"]


def test_run_execution_failure_message_contains_original_error() -> None:
    """The error message forwarded to job_fail_execution includes the original text."""
    exc = BrainDomainError(message="quota exceeded", operation="ops.invoke")
    client = _FakeClient(invoke_raises=exc)

    _run_execution(client=client, claim=_make_claim(), channel="worker")

    msg = client._calls_for("job_fail_execution")[0].kwargs["error_message"]
    assert "quota exceeded" in msg


# ---------------------------------------------------------------------------
# _safe_fail
# ---------------------------------------------------------------------------


def test_safe_fail_calls_job_fail_execution() -> None:
    """_safe_fail forwards all arguments to job_fail_execution."""
    client = _FakeClient()

    _safe_fail(
        client=client,
        execution_id="exec-sf",
        error_message="something went wrong",
        is_retryable=True,
    )

    fail_calls = client._calls_for("job_fail_execution")
    assert len(fail_calls) == 1
    assert fail_calls[0].kwargs["execution_id"] == "exec-sf"
    assert fail_calls[0].kwargs["error_message"] == "something went wrong"
    assert fail_calls[0].kwargs["is_retryable"] is True


def test_safe_fail_swallows_secondary_exception() -> None:
    """_safe_fail does not re-raise when job_fail_execution itself raises."""
    client = _FakeClient(
        fail_raises=BrainTransportError(
            message="core unreachable", operation="jobs.executions.fail", status_code=0
        )
    )

    # Must not raise.
    _safe_fail(
        client=client,
        execution_id="exec-sf2",
        error_message="original failure",
        is_retryable=False,
    )


# ---------------------------------------------------------------------------
# _write_heartbeat
# ---------------------------------------------------------------------------


def test_write_heartbeat_creates_file(tmp_path: Path) -> None:
    """_write_heartbeat touches the target file, creating parent dirs as needed."""
    target = tmp_path / "nested" / "dir" / "heartbeat"

    _write_heartbeat(target)

    assert target.exists()


def test_write_heartbeat_updates_existing_file(tmp_path: Path) -> None:
    """_write_heartbeat succeeds when the file already exists."""
    target = tmp_path / "heartbeat"
    target.touch()

    _write_heartbeat(target)

    assert target.exists()


# ---------------------------------------------------------------------------
# _resolve_heartbeat_path
# ---------------------------------------------------------------------------


def test_resolve_heartbeat_path_default(monkeypatch) -> None:
    """Returns the compiled-in default when the env var is absent."""
    monkeypatch.delenv("BRAIN_WORKER_HEARTBEAT_FILE", raising=False)

    assert _resolve_heartbeat_path() == _HEARTBEAT_PATH


def test_resolve_heartbeat_path_env_override(monkeypatch, tmp_path: Path) -> None:
    """Returns the env-var path when BRAIN_WORKER_HEARTBEAT_FILE is set."""
    custom = str(tmp_path / "custom-heartbeat")
    monkeypatch.setenv("BRAIN_WORKER_HEARTBEAT_FILE", custom)

    assert _resolve_heartbeat_path() == Path(custom)


def test_resolve_heartbeat_path_blank_env_uses_default(monkeypatch) -> None:
    """Falls back to the default when the env var is set to whitespace."""
    monkeypatch.setenv("BRAIN_WORKER_HEARTBEAT_FILE", "   ")

    assert _resolve_heartbeat_path() == _HEARTBEAT_PATH
