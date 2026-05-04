"""Integration tests for Software Service Postgres-backed repositories.

These tests exercise the SQL persistence path against a real, ephemeral
Postgres container. They are gated on ``BRAIN_RUN_INTEGRATION_REAL=1`` so
the unit-test gate stays fast and Docker-free.
"""

from __future__ import annotations

import subprocess
from datetime import UTC, datetime
from pathlib import Path

import pytest

from lib.shared.envelope import EnvelopeKind, new_meta
from lib.shared.ids import generate_ulid_str
from resources.adapters.coding.adapter import (
    CodingTaskHandle,
    CodingTaskLogs,
    CodingTaskResult,
    CodingTaskSpec,
    CodingTaskStatusSnapshot,
    ExecutorHealthStatus,
    ExecutorId,
    ExecutorInfo,
    TaskPhase,
    TerminationReason,
)
from services.effect.software.config import SoftwareServiceSettings
from services.effect.software.data.repository import (
    PostgresTaskRepository,
    PostgresWorkspaceRepository,
)
from services.effect.software.data.runtime import SoftwarePostgresRuntime
from services.effect.software.domain import Task, TaskStatus, Workspace
from services.effect.software.implementation import DefaultSoftwareService
from tests.integration.helpers import real_provider_tests_enabled

pytest_plugins = ("tests.integration.fixtures",)


pytestmark = pytest.mark.skipif(
    not real_provider_tests_enabled(),
    reason="set BRAIN_RUN_INTEGRATION_REAL=1 to run real-provider integration tests",
)


def _meta():
    """Build valid envelope metadata for tests."""
    return new_meta(kind=EnvelopeKind.COMMAND, source="test", principal="operator")


def _settings(staging_root: Path) -> SoftwareServiceSettings:
    """Build deterministic Software Service settings for integration tests."""
    return SoftwareServiceSettings(
        staging_root=str(staging_root),
        # These integration tests run on the host rather than inside the
        # brain-core container, so fixture repos live under ``tmp_path``.
        # Setting ``workspace_root`` to ``/`` preserves the production
        # registration flow while letting absolute fixture paths resolve.
        workspace_root="/",
        default_branch_prefix="brain/software/",
        default_executor=ExecutorId.CLAUDE_CODE,
        default_max_wallclock_seconds=30,
        default_test_command="true",
        commit_author_name="Brain",
        commit_author_email="brain@local",
    )


def _git(cwd: Path, *args: str) -> None:
    """Run ``git`` against ``cwd`` and raise on non-zero exit."""
    subprocess.run(
        ["git", *args],
        check=True,
        capture_output=True,
        text=True,
        cwd=str(cwd),
    )


@pytest.fixture
def fixture_repo(tmp_path: Path) -> Path:
    """Create one fresh git working tree for integration tests."""
    repo = tmp_path / "fixture-repo"
    repo.mkdir()
    _git(repo, "init", "-q", "-b", "main")
    _git(repo, "config", "user.email", "fixture@local")
    _git(repo, "config", "user.name", "Fixture")
    (repo / "README.md").write_text("hello\n")
    _git(repo, "add", "README.md")
    _git(repo, "commit", "-q", "-m", "initial")
    return repo


@pytest.fixture
def staging_root(tmp_path: Path) -> Path:
    """Yield a per-test staging root."""
    root = tmp_path / "staging"
    root.mkdir()
    return root


class _StubAdapter:
    """Minimal adapter that runs a deterministic shell-script executor.

    The "executor" mutates the worktree to ensure that the Software
    Service exercises the test-step + commit branches end-to-end.
    """

    def __init__(self, *, mutator) -> None:
        self._mutator = mutator
        self._handle: CodingTaskHandle | None = None
        self._collected = False

    def health(self) -> ExecutorHealthStatus:
        return ExecutorHealthStatus(ready=True, executors=())

    def list_executors(self) -> tuple[ExecutorInfo, ...]:
        return ()

    def run_task(self, *, spec: CodingTaskSpec) -> CodingTaskHandle:
        if callable(self._mutator):
            self._mutator(Path(spec.worktree_path))
        self._handle = CodingTaskHandle(
            handle_id=f"handle-{spec.task_id}",
            task_id=spec.task_id,
            container_id=f"container-{spec.task_id}",
            started_at=datetime.now(UTC),
        )
        return self._handle

    def poll(self, *, handle: CodingTaskHandle) -> CodingTaskStatusSnapshot:
        return CodingTaskStatusSnapshot(
            handle_id=handle.handle_id,
            phase=TaskPhase.SUCCEEDED,
            last_observed_at=datetime.now(UTC),
            exit_code=0,
        )

    def cancel(self, *, handle: CodingTaskHandle) -> None:
        return None

    def logs(self, *, handle: CodingTaskHandle) -> CodingTaskLogs:
        return CodingTaskLogs(handle_id=handle.handle_id, stdout=b"", stderr=b"")

    def collect(self, *, handle: CodingTaskHandle) -> CodingTaskResult:
        self._collected = True
        return CodingTaskResult(
            handle_id=handle.handle_id,
            task_id=handle.task_id,
            phase=TaskPhase.SUCCEEDED,
            exit_code=0,
            elapsed_seconds=0.05,
            termination_reason=TerminationReason.EXECUTOR_EXITED,
        )

    def list_owned(self) -> tuple[CodingTaskHandle, ...]:
        return () if self._handle is None else (self._handle,)

    def resolve_workspace_host_path(self, *, workspace_path: str) -> str | None:
        """Mirror the path through unchanged so tests pass the bind-mount gate."""
        return workspace_path


def test_postgres_repositories_persist_full_run_task_lifecycle(
    migrated_integration_settings,
    fixture_repo: Path,
    staging_root: Path,
) -> None:
    """A full happy-path run_task should durably persist Workspace and Task rows."""
    runtime = SoftwarePostgresRuntime.from_settings(migrated_integration_settings)
    workspace_repo = PostgresWorkspaceRepository(runtime.schema_sessions)
    task_repo = PostgresTaskRepository(runtime.schema_sessions)
    adapter = _StubAdapter(
        mutator=lambda worktree: (worktree / "feature.txt").write_text("done\n")
    )
    service = DefaultSoftwareService(
        settings=_settings(staging_root=staging_root),
        adapter=adapter,
        workspace_repository=workspace_repo,
        task_repository=task_repo,
        poll_interval_seconds=0.0,
    )

    register = service.register_workspace(
        meta=_meta(),
        path=str(fixture_repo),
        default_executor=ExecutorId.CLAUDE_CODE,
        test_command="true",
        max_wallclock_seconds=30,
        branch_prefix="brain/code",
    )
    assert register.ok
    assert register.payload is not None
    workspace = register.payload.value

    fetched = workspace_repo.get_by_id(workspace_id=workspace.id)
    assert fetched is not None
    assert fetched.path == workspace.path

    run = service.run_task_sync(
        meta=_meta(), workspace_id=workspace.id, prompt="add feature"
    )
    assert run.ok, run.errors
    assert run.payload is not None
    task = run.payload.value
    assert task.status is TaskStatus.SUCCEEDED
    assert task.commit_sha is not None
    assert task.test_passed is True

    persisted = task_repo.get_by_id(task_id=task.id)
    assert persisted is not None
    assert persisted.commit_sha == task.commit_sha
    assert persisted.workspace_id == workspace.id


def test_postgres_workspace_repository_revoke_idempotency(
    migrated_integration_settings,
    fixture_repo: Path,
) -> None:
    """Revoking the same workspace twice should preserve the original timestamp."""
    runtime = SoftwarePostgresRuntime.from_settings(migrated_integration_settings)
    repo = PostgresWorkspaceRepository(runtime.schema_sessions)

    workspace = Workspace(
        id=generate_ulid_str(),
        path=str(fixture_repo) + "/idempotent",  # path uniqueness
        default_executor=ExecutorId.CLAUDE_CODE,
        test_command="true",
        max_wallclock_seconds=30,
        branch_prefix="brain/code",
        created_at=datetime.now(UTC),
        revoked_at=None,
    )
    repo.append(workspace=workspace)

    first = repo.mark_revoked(workspace_id=workspace.id, revoked_at=datetime.now(UTC))
    assert first.revoked_at is not None
    second = repo.mark_revoked(workspace_id=workspace.id, revoked_at=datetime.now(UTC))
    assert second.revoked_at == first.revoked_at


def test_postgres_task_repository_round_trips_terminal_row(
    migrated_integration_settings,
    fixture_repo: Path,
) -> None:
    """A terminal Task row should round-trip through the SQL layer unchanged."""
    runtime = SoftwarePostgresRuntime.from_settings(migrated_integration_settings)
    workspace_repo = PostgresWorkspaceRepository(runtime.schema_sessions)
    task_repo = PostgresTaskRepository(runtime.schema_sessions)

    workspace = Workspace(
        id=generate_ulid_str(),
        path=str(fixture_repo) + "/round_trip",
        default_executor=ExecutorId.CLAUDE_CODE,
        test_command="true",
        max_wallclock_seconds=30,
        branch_prefix="brain/code",
        created_at=datetime.now(UTC),
        revoked_at=None,
    )
    workspace_repo.append(workspace=workspace)

    task = Task(
        id=generate_ulid_str(),
        workspace_id=workspace.id,
        executor=ExecutorId.CLAUDE_CODE,
        branch="brain/code/test-roundtrip",
        prompt_object_ref="obj://prompt",
        status=TaskStatus.SUCCEEDED,
        commit_sha="abc123def456",
        test_passed=True,
        stdout_object_ref="obj://stdout",
        stderr_object_ref="obj://stderr",
        termination_reason=TerminationReason.EXECUTOR_EXITED,
        failure_detail=None,
        started_at=datetime.now(UTC),
        finished_at=datetime.now(UTC),
    )
    task_repo.append(task=task)

    persisted = task_repo.get_by_id(task_id=task.id)
    assert persisted is not None
    assert persisted.status is TaskStatus.SUCCEEDED
    assert persisted.commit_sha == "abc123def456"
    assert persisted.termination_reason is TerminationReason.EXECUTOR_EXITED
    assert persisted.test_passed is True
