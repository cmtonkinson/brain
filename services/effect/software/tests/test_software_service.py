"""Behavior tests for the Software Service implementation.

These tests exercise the full :class:`DefaultSoftwareService` orchestration
loop against in-memory repositories and a deterministic mock Coding
Adapter that satisfies the Phase A Protocol.

A real, throwaway git repository is created via ``git init`` per test so
worktree creation, status inspection, and commit operations exercise the
actual ``git`` executable rather than a wrapper. ``tmp_path`` confines the
filesystem effects to the test's sandbox.
"""

from __future__ import annotations

import subprocess
from datetime import UTC, datetime
from pathlib import Path

import pytest

from lib.shared.envelope import EnvelopeKind, new_meta
from resources.adapters.coding.adapter import (
    CodingTaskHandle,
    CodingTaskLogs,
    CodingTaskNotFoundError,
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
    InMemoryTaskRepository,
    InMemoryWorkspaceRepository,
)
from services.effect.software.domain import Task, TaskStatus, Workspace
from services.effect.software.implementation import DefaultSoftwareService

# --------------------------------------------------------------------------
# Test fixtures and helpers
# --------------------------------------------------------------------------


def _meta():
    """Build valid envelope metadata for tests."""
    return new_meta(kind=EnvelopeKind.COMMAND, source="test", principal="operator")


def _settings(*, staging_root: Path) -> SoftwareServiceSettings:
    """Build deterministic Software Service settings for tests."""
    return SoftwareServiceSettings(
        staging_root=str(staging_root),
        # Tests run outside a Linux container, so workspace paths come from
        # ``tmp_path`` (under /private/var/...). Setting workspace_root to
        # the filesystem root lets any absolute path resolve cleanly; the
        # production default (``/mount/software``) is exercised in
        # integration tests against a real container.
        workspace_root="/",
        default_branch_prefix="brain/software/",
        default_executor=ExecutorId.CLAUDE_CODE,
        default_max_wallclock_seconds=30,
        default_test_command="true",
        commit_author_name="Brain",
        commit_author_email="brain@local",
    )


@pytest.fixture
def fixture_repo(tmp_path: Path) -> Path:
    """Materialise one fresh git working tree with an initial commit."""
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
    """Yield a staging root directory pointing under the test tmp tree."""
    root = tmp_path / "staging"
    root.mkdir()
    return root


def _git(cwd: Path, *args: str) -> str:
    """Run ``git`` against ``cwd`` and return stdout."""
    result = subprocess.run(
        ["git", *args],
        check=True,
        capture_output=True,
        text=True,
        cwd=str(cwd),
    )
    return result.stdout


class _Snapshot:
    """Mock adapter snapshot scripting helper."""

    def __init__(
        self,
        *,
        phases: list[TaskPhase],
        exit_code: int = 0,
        termination_reason: TerminationReason = TerminationReason.EXECUTOR_EXITED,
        worktree_mutator: object | None = None,
        raise_on_collect: Exception | None = None,
        raise_on_run: Exception | None = None,
    ) -> None:
        self.phases = phases
        self.exit_code = exit_code
        self.termination_reason = termination_reason
        self.worktree_mutator = worktree_mutator
        self.raise_on_collect = raise_on_collect
        self.raise_on_run = raise_on_run


class _MockCodingAdapter:
    """Phase A-conformant adapter fake driven by a scripted snapshot list."""

    def __init__(self, *, script: _Snapshot) -> None:
        self._script = script
        self._poll_index = 0
        self.specs: list[CodingTaskSpec] = []
        self.cancel_calls: list[str] = []
        self._handle: CodingTaskHandle | None = None
        self._collected = False

    def health(self) -> ExecutorHealthStatus:
        return ExecutorHealthStatus(ready=True, executors=())

    def list_executors(self) -> tuple[ExecutorInfo, ...]:
        return ()

    def run_task(self, *, spec: CodingTaskSpec) -> CodingTaskHandle:
        if self._script.raise_on_run is not None:
            raise self._script.raise_on_run
        self.specs.append(spec)
        # Apply any deterministic worktree mutation up front so that
        # subsequent poll/collect calls see the mutated state.
        if callable(self._script.worktree_mutator):
            self._script.worktree_mutator(Path(spec.worktree_path))
        self._handle = CodingTaskHandle(
            handle_id=f"handle-{spec.task_id}",
            task_id=spec.task_id,
            container_id=f"container-{spec.task_id}",
            started_at=datetime.now(UTC),
        )
        return self._handle

    def poll(self, *, handle: CodingTaskHandle) -> CodingTaskStatusSnapshot:
        index = min(self._poll_index, len(self._script.phases) - 1)
        phase = self._script.phases[index]
        self._poll_index += 1
        return CodingTaskStatusSnapshot(
            handle_id=handle.handle_id,
            phase=phase,
            last_observed_at=datetime.now(UTC),
            exit_code=self._script.exit_code if phase == TaskPhase.SUCCEEDED else None,
        )

    def cancel(self, *, handle: CodingTaskHandle) -> None:
        self.cancel_calls.append(handle.handle_id)

    def logs(self, *, handle: CodingTaskHandle) -> CodingTaskLogs:
        return CodingTaskLogs(handle_id=handle.handle_id, stdout=b"", stderr=b"")

    def collect(self, *, handle: CodingTaskHandle) -> CodingTaskResult:
        if self._script.raise_on_collect is not None:
            raise self._script.raise_on_collect
        if self._collected:
            raise CodingTaskNotFoundError(handle.handle_id)
        self._collected = True
        terminal_phase = self._script.phases[-1]
        return CodingTaskResult(
            handle_id=handle.handle_id,
            task_id=handle.task_id,
            phase=terminal_phase,
            exit_code=self._script.exit_code
            if terminal_phase == TaskPhase.SUCCEEDED
            else 1,
            elapsed_seconds=0.05,
            termination_reason=self._script.termination_reason,
        )

    def list_owned(self) -> tuple[CodingTaskHandle, ...]:
        return () if self._handle is None else (self._handle,)

    def resolve_workspace_host_path(self, *, workspace_path: str) -> str | None:
        """Mirror the path through unchanged so tests pass the bind-mount gate."""
        return workspace_path


def _make_service(
    *,
    staging_root: Path,
    adapter: _MockCodingAdapter | None = None,
    workspace_repo: InMemoryWorkspaceRepository | None = None,
    task_repo: InMemoryTaskRepository | None = None,
) -> DefaultSoftwareService:
    """Build a Software Service with in-memory repositories for tests."""
    return DefaultSoftwareService(
        settings=_settings(staging_root=staging_root),
        adapter=adapter,
        workspace_repository=workspace_repo or InMemoryWorkspaceRepository(),
        task_repository=task_repo or InMemoryTaskRepository(),
        poll_interval_seconds=0.0,
    )


def _register(
    service: DefaultSoftwareService,
    *,
    path: Path,
    test_command: str = "true",
    branch_prefix: str = "brain/code",
    max_wallclock_seconds: int = 30,
    default_executor: ExecutorId = ExecutorId.CLAUDE_CODE,
) -> Workspace:
    """Register a workspace and return the persisted record."""
    envelope = service.register_workspace(
        meta=_meta(),
        path=str(path),
        default_executor=default_executor,
        test_command=test_command,
        max_wallclock_seconds=max_wallclock_seconds,
        branch_prefix=branch_prefix,
    )
    assert envelope.ok, envelope.errors
    assert envelope.payload is not None
    return envelope.payload.value


# --------------------------------------------------------------------------
# Workspace registration
# --------------------------------------------------------------------------


def test_register_workspace_persists_row(
    fixture_repo: Path, staging_root: Path
) -> None:
    """Registering one git working tree should append a Workspace row."""
    service = _make_service(staging_root=staging_root)

    envelope = service.register_workspace(
        meta=_meta(),
        path=str(fixture_repo),
        default_executor=ExecutorId.CLAUDE_CODE,
        test_command="true",
        max_wallclock_seconds=30,
        branch_prefix="brain/code",
    )

    assert envelope.ok is True
    assert envelope.payload is not None
    workspace = envelope.payload.value
    assert workspace.path == str(fixture_repo.resolve())
    assert workspace.default_executor is ExecutorId.CLAUDE_CODE
    assert workspace.revoked_at is None


def test_register_workspace_rejects_missing_path(staging_root: Path) -> None:
    """Registration should reject paths that do not exist."""
    service = _make_service(staging_root=staging_root)
    envelope = service.register_workspace(
        meta=_meta(),
        path="/nonexistent/path/__brain_test__",
        default_executor=ExecutorId.CLAUDE_CODE,
        test_command="true",
        max_wallclock_seconds=30,
        branch_prefix="brain/code",
    )
    assert envelope.ok is False
    assert any("does not exist" in error.message for error in envelope.errors)


def test_register_workspace_rejects_non_git_directory(
    tmp_path: Path, staging_root: Path
) -> None:
    """Registration should reject directories that are not git working trees."""
    plain = tmp_path / "plain"
    plain.mkdir()
    service = _make_service(staging_root=staging_root)

    envelope = service.register_workspace(
        meta=_meta(),
        path=str(plain),
        default_executor=ExecutorId.CLAUDE_CODE,
        test_command="true",
        max_wallclock_seconds=30,
        branch_prefix="brain/code",
    )

    assert envelope.ok is False
    assert any("not the root of a git" in error.message for error in envelope.errors)


def test_register_workspace_rejects_duplicate_path(
    fixture_repo: Path, staging_root: Path
) -> None:
    """Registering the same path twice should be rejected with conflict."""
    service = _make_service(staging_root=staging_root)
    _register(service, path=fixture_repo)

    envelope = service.register_workspace(
        meta=_meta(),
        path=str(fixture_repo),
        default_executor=ExecutorId.CLAUDE_CODE,
        test_command="true",
        max_wallclock_seconds=30,
        branch_prefix="brain/code",
    )

    assert envelope.ok is False
    assert any("already registered" in error.message for error in envelope.errors)


def test_register_workspace_accepts_empty_test_command(
    fixture_repo: Path, staging_root: Path
) -> None:
    """`test_command` is optional; an empty value persists as-is."""
    service = _make_service(staging_root=staging_root)
    envelope = service.register_workspace(
        meta=_meta(),
        path=str(fixture_repo),
        default_executor=ExecutorId.CLAUDE_CODE,
        test_command="",
        max_wallclock_seconds=30,
        branch_prefix="brain/code",
    )
    assert envelope.ok is True
    assert envelope.payload is not None
    assert envelope.payload.value.test_command == ""


# --------------------------------------------------------------------------
# Workspace listing & revocation
# --------------------------------------------------------------------------


def test_list_workspaces_excludes_revoked_by_default(
    fixture_repo: Path, tmp_path: Path, staging_root: Path
) -> None:
    """Listing should exclude revoked rows unless include_revoked=True."""
    other_repo = tmp_path / "other"
    other_repo.mkdir()
    _git(other_repo, "init", "-q", "-b", "main")
    service = _make_service(staging_root=staging_root)

    workspace_a = _register(service, path=fixture_repo)
    workspace_b = _register(service, path=other_repo)
    revoke = service.revoke_workspace(meta=_meta(), workspace_id=workspace_b.id)
    assert revoke.ok

    listed = service.list_workspaces(meta=_meta())
    assert listed.ok and listed.payload is not None
    assert {row.id for row in listed.payload.value} == {workspace_a.id}

    full = service.list_workspaces(meta=_meta(), include_revoked=True)
    assert full.ok and full.payload is not None
    assert {row.id for row in full.payload.value} == {workspace_a.id, workspace_b.id}


def test_revoke_workspace_is_idempotent(fixture_repo: Path, staging_root: Path) -> None:
    """Revoking an already-revoked workspace should return the existing row."""
    service = _make_service(staging_root=staging_root)
    workspace = _register(service, path=fixture_repo)

    first = service.revoke_workspace(meta=_meta(), workspace_id=workspace.id)
    assert first.ok and first.payload is not None
    revoked_at = first.payload.value.revoked_at
    assert revoked_at is not None

    second = service.revoke_workspace(meta=_meta(), workspace_id=workspace.id)
    assert second.ok and second.payload is not None
    assert second.payload.value.revoked_at == revoked_at


def test_revoke_workspace_returns_not_found(staging_root: Path) -> None:
    """Revoking an unknown workspace_id should return a not_found error."""
    service = _make_service(staging_root=staging_root)
    envelope = service.revoke_workspace(meta=_meta(), workspace_id="does-not-exist")
    assert envelope.ok is False
    assert any("workspace not found" in error.message for error in envelope.errors)


# --------------------------------------------------------------------------
# run_task happy path
# --------------------------------------------------------------------------


def _scripted_executor(*, mutator) -> _MockCodingAdapter:
    """Build a mock adapter that runs to SUCCEEDED with the given mutator."""
    return _MockCodingAdapter(
        script=_Snapshot(
            phases=[TaskPhase.RUNNING, TaskPhase.SUCCEEDED],
            exit_code=0,
            worktree_mutator=mutator,
        )
    )


def test_run_task_happy_path_creates_branch_and_commit(
    fixture_repo: Path, staging_root: Path
) -> None:
    """run_task should create a branch, run executor, run tests, and commit."""

    def mutator(worktree: Path) -> None:
        (worktree / "feature.txt").write_text("done\n")

    adapter = _scripted_executor(mutator=mutator)
    service = _make_service(staging_root=staging_root, adapter=adapter)
    workspace = _register(service, path=fixture_repo, test_command="true")

    envelope = service.run_task_sync(
        meta=_meta(),
        workspace_id=workspace.id,
        prompt="add feature.txt with done",
    )

    assert envelope.ok, envelope.errors
    assert envelope.payload is not None
    task = envelope.payload.value
    assert task.status is TaskStatus.SUCCEEDED
    assert task.test_passed is True
    assert task.commit_sha is not None
    assert task.branch.startswith("brain/code/")
    # Worktree directory exists and contains a fresh commit.
    worktree = staging_root / task.id
    assert worktree.exists()
    git_log = subprocess.run(
        ["git", "-C", str(worktree), "log", "--oneline"],
        check=True,
        capture_output=True,
        text=True,
    ).stdout
    assert task.commit_sha[:7] in git_log
    # Commit message subject should be derived from the operator prompt.
    assert "add feature.txt with done" in git_log
    # Commit author should be the configured Brain bot identity.
    show = subprocess.run(
        [
            "git",
            "-C",
            str(worktree),
            "show",
            "-s",
            "--format=%an <%ae>",
            task.commit_sha,
        ],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    assert show == "Brain <brain@local>"


def test_run_task_passes_executor_override_to_adapter(
    fixture_repo: Path, staging_root: Path
) -> None:
    """run_task should honor the executor override over workspace default."""

    adapter = _scripted_executor(
        mutator=lambda worktree: (worktree / "x.txt").write_text("x")
    )
    service = _make_service(staging_root=staging_root, adapter=adapter)
    workspace = _register(
        service, path=fixture_repo, default_executor=ExecutorId.CLAUDE_CODE
    )

    envelope = service.run_task_sync(
        meta=_meta(),
        workspace_id=workspace.id,
        prompt="do thing",
        executor=ExecutorId.CODEX,
    )
    assert envelope.ok, envelope.errors
    assert adapter.specs[0].executor is ExecutorId.CODEX
    assert envelope.payload is not None
    assert envelope.payload.value.executor is ExecutorId.CODEX


def test_run_task_polls_through_running_phases(
    fixture_repo: Path, staging_root: Path
) -> None:
    """run_task should keep polling while adapter reports RUNNING."""

    def mutator(worktree: Path) -> None:
        (worktree / "f.txt").write_text("f")

    adapter = _MockCodingAdapter(
        script=_Snapshot(
            phases=[TaskPhase.RUNNING, TaskPhase.RUNNING, TaskPhase.SUCCEEDED],
            exit_code=0,
            worktree_mutator=mutator,
        )
    )
    service = _make_service(staging_root=staging_root, adapter=adapter)
    workspace = _register(service, path=fixture_repo)

    envelope = service.run_task_sync(
        meta=_meta(), workspace_id=workspace.id, prompt="prompt"
    )
    assert envelope.ok
    assert envelope.payload is not None
    assert envelope.payload.value.status is TaskStatus.SUCCEEDED


# --------------------------------------------------------------------------
# run_task rejection paths
# --------------------------------------------------------------------------


def test_run_task_rejects_revoked_workspace(
    fixture_repo: Path, staging_root: Path
) -> None:
    """run_task on a revoked workspace should return a validation error."""
    adapter = _scripted_executor(mutator=lambda w: None)
    service = _make_service(staging_root=staging_root, adapter=adapter)
    workspace = _register(service, path=fixture_repo)
    service.revoke_workspace(meta=_meta(), workspace_id=workspace.id)

    envelope = service.run_task_sync(
        meta=_meta(), workspace_id=workspace.id, prompt="anything"
    )
    assert envelope.ok is False
    assert any("revoked" in error.message for error in envelope.errors)
    assert adapter.specs == []


def test_run_task_rejects_unknown_workspace(staging_root: Path) -> None:
    """run_task on an unknown workspace_id should return a not_found error."""
    adapter = _scripted_executor(mutator=lambda w: None)
    service = _make_service(staging_root=staging_root, adapter=adapter)
    envelope = service.run_task_sync(meta=_meta(), workspace_id="missing", prompt="x")
    assert envelope.ok is False
    assert any("workspace not found" in error.message for error in envelope.errors)


# --------------------------------------------------------------------------
# Test failure semantics
# --------------------------------------------------------------------------


def test_run_task_failing_test_command_does_not_commit(
    fixture_repo: Path, staging_root: Path
) -> None:
    """Failing test command should leave worktree uncommitted, status=FAILED."""

    def mutator(worktree: Path) -> None:
        (worktree / "broken.txt").write_text("broken\n")

    adapter = _scripted_executor(mutator=mutator)
    service = _make_service(staging_root=staging_root, adapter=adapter)
    workspace = _register(service, path=fixture_repo, test_command="false")

    envelope = service.run_task_sync(
        meta=_meta(), workspace_id=workspace.id, prompt="break things"
    )
    assert envelope.ok
    assert envelope.payload is not None
    task = envelope.payload.value
    assert task.status is TaskStatus.FAILED
    assert task.test_passed is False
    assert task.commit_sha is None
    # Worktree is preserved with its uncommitted change for inspection.
    worktree = staging_root / task.id
    assert (worktree / "broken.txt").exists()
    porcelain = subprocess.run(
        ["git", "-C", str(worktree), "status", "--porcelain"],
        check=True,
        capture_output=True,
        text=True,
    ).stdout
    assert "broken.txt" in porcelain


def test_run_task_executor_failure_skips_test_step(
    fixture_repo: Path, staging_root: Path
) -> None:
    """Non-zero executor exit should record FAILED without test invocation."""

    adapter = _MockCodingAdapter(
        script=_Snapshot(
            phases=[TaskPhase.RUNNING, TaskPhase.FAILED],
            exit_code=2,
            termination_reason=TerminationReason.RUNTIME_ERROR,
            worktree_mutator=None,
        )
    )
    service = _make_service(staging_root=staging_root, adapter=adapter)
    workspace = _register(service, path=fixture_repo)

    envelope = service.run_task_sync(
        meta=_meta(), workspace_id=workspace.id, prompt="will fail"
    )
    assert envelope.ok
    assert envelope.payload is not None
    task = envelope.payload.value
    assert task.status is TaskStatus.FAILED
    assert task.test_passed is None
    assert task.termination_reason is TerminationReason.RUNTIME_ERROR


def test_run_task_no_changes_succeeds_without_test_or_commit(
    fixture_repo: Path, staging_root: Path
) -> None:
    """Clean executor exit with no worktree changes should succeed silently."""
    adapter = _MockCodingAdapter(
        script=_Snapshot(
            phases=[TaskPhase.RUNNING, TaskPhase.SUCCEEDED],
            exit_code=0,
            worktree_mutator=None,
        )
    )
    service = _make_service(staging_root=staging_root, adapter=adapter)
    workspace = _register(service, path=fixture_repo, test_command="false")

    envelope = service.run_task_sync(
        meta=_meta(), workspace_id=workspace.id, prompt="no-op"
    )
    assert envelope.ok
    assert envelope.payload is not None
    task = envelope.payload.value
    assert task.status is TaskStatus.SUCCEEDED
    assert task.commit_sha is None
    assert task.test_passed is None


# --------------------------------------------------------------------------
# Cancellation
# --------------------------------------------------------------------------


def test_cancel_task_signals_adapter_and_marks_cancelled(
    fixture_repo: Path, staging_root: Path
) -> None:
    """cancel_task should signal the adapter and persist CANCELLED status."""
    # Pre-seed a RUNNING task without going through run_task so we can
    # exercise the cancellation path against a known-mid-run state.
    adapter = _MockCodingAdapter(
        script=_Snapshot(phases=[TaskPhase.RUNNING], exit_code=0)
    )
    workspace_repo = InMemoryWorkspaceRepository()
    task_repo = InMemoryTaskRepository()
    service = _make_service(
        staging_root=staging_root,
        adapter=adapter,
        workspace_repo=workspace_repo,
        task_repo=task_repo,
    )
    workspace = _register(service, path=fixture_repo)

    seeded = Task(
        id="01HZZZTEST0000000000000000",
        workspace_id=workspace.id,
        executor=ExecutorId.CLAUDE_CODE,
        branch="brain/code/test-abc",
        prompt_object_ref=None,
        status=TaskStatus.RUNNING,
        commit_sha=None,
        test_passed=None,
        stdout_object_ref=None,
        stderr_object_ref=None,
        termination_reason=None,
        failure_detail=None,
        started_at=datetime.now(UTC),
        finished_at=None,
        adapter_handle_id="prior-handle",
        adapter_container_id="prior-container",
        adapter_started_at=datetime.now(UTC),
    )
    task_repo.append(task=seeded)

    envelope = service.cancel_task(meta=_meta(), task_id=seeded.id)
    assert envelope.ok
    assert envelope.payload is not None
    cancelled = envelope.payload.value
    assert cancelled.status is TaskStatus.CANCELLED
    assert cancelled.termination_reason is TerminationReason.CANCELLED
    assert cancelled.finished_at is not None
    assert adapter.cancel_calls == ["prior-handle"]


def test_cancel_task_is_idempotent_on_terminal_task(
    fixture_repo: Path, staging_root: Path
) -> None:
    """Cancelling a terminal task should return the existing row unchanged."""
    adapter = _MockCodingAdapter(
        script=_Snapshot(phases=[TaskPhase.SUCCEEDED], exit_code=0)
    )
    workspace_repo = InMemoryWorkspaceRepository()
    task_repo = InMemoryTaskRepository()
    service = _make_service(
        staging_root=staging_root,
        adapter=adapter,
        workspace_repo=workspace_repo,
        task_repo=task_repo,
    )
    workspace = _register(service, path=fixture_repo)
    finished_at = datetime.now(UTC)
    succeeded = Task(
        id="01HZZZTEST0000000000000001",
        workspace_id=workspace.id,
        executor=ExecutorId.CLAUDE_CODE,
        branch="brain/code/test-abc",
        prompt_object_ref="",
        status=TaskStatus.SUCCEEDED,
        commit_sha="abc1234",
        test_passed=True,
        stdout_object_ref=None,
        stderr_object_ref=None,
        termination_reason=TerminationReason.EXECUTOR_EXITED,
        failure_detail=None,
        started_at=datetime.now(UTC),
        finished_at=finished_at,
    )
    task_repo.append(task=succeeded)

    envelope = service.cancel_task(meta=_meta(), task_id=succeeded.id)
    assert envelope.ok
    assert envelope.payload is not None
    assert envelope.payload.value.status is TaskStatus.SUCCEEDED
    assert envelope.payload.value.finished_at == finished_at
    assert adapter.cancel_calls == []


def test_cancel_task_returns_not_found_for_unknown_id(staging_root: Path) -> None:
    """Cancelling an unknown task_id should return a not_found error."""
    service = _make_service(staging_root=staging_root)
    envelope = service.cancel_task(meta=_meta(), task_id="missing")
    assert envelope.ok is False
    assert any("task not found" in error.message for error in envelope.errors)


# --------------------------------------------------------------------------
# Lineage row shape across transitions
# --------------------------------------------------------------------------


def test_run_task_persists_lineage_rows_for_each_transition(
    fixture_repo: Path, staging_root: Path
) -> None:
    """Repository should observe PENDING/RUNNING/TESTING/COMMITTING/SUCCEEDED."""

    def mutator(worktree: Path) -> None:
        (worktree / "thing.txt").write_text("thing\n")

    adapter = _scripted_executor(mutator=mutator)
    workspace_repo = InMemoryWorkspaceRepository()
    task_repo = _RecordingTaskRepository()
    service = _make_service(
        staging_root=staging_root,
        adapter=adapter,
        workspace_repo=workspace_repo,
        task_repo=task_repo,
    )
    workspace = _register(service, path=fixture_repo)

    envelope = service.run_task_sync(
        meta=_meta(), workspace_id=workspace.id, prompt="add thing"
    )
    assert envelope.ok
    assert envelope.payload is not None

    statuses = [row.status for row in task_repo.snapshots]
    assert TaskStatus.PENDING in statuses
    assert TaskStatus.RUNNING in statuses
    assert TaskStatus.TESTING in statuses
    assert TaskStatus.COMMITTING in statuses
    assert statuses[-1] is TaskStatus.SUCCEEDED


def test_task_status_returns_persisted_row(
    fixture_repo: Path, staging_root: Path
) -> None:
    """task_status should return the most recently persisted row."""
    adapter = _scripted_executor(
        mutator=lambda worktree: (worktree / "f.txt").write_text("f")
    )
    service = _make_service(staging_root=staging_root, adapter=adapter)
    workspace = _register(service, path=fixture_repo)
    run = service.run_task_sync(
        meta=_meta(), workspace_id=workspace.id, prompt="anything"
    )
    assert run.ok
    assert run.payload is not None

    status = service.task_status(meta=_meta(), task_id=run.payload.value.id)
    assert status.ok
    assert status.payload is not None
    assert status.payload.value.id == run.payload.value.id
    assert status.payload.value.status is TaskStatus.SUCCEEDED


class _RecordingTaskRepository(InMemoryTaskRepository):
    """Task repository that captures one snapshot per write for assertions."""

    def __init__(self) -> None:
        super().__init__()
        self.snapshots: list[Task] = []

    def append(self, *, task: Task) -> Task:
        self.snapshots.append(task)
        return super().append(task=task)

    def update(self, *, task: Task) -> Task:
        self.snapshots.append(task)
        return super().update(task=task)


# --------------------------------------------------------------------------
# Async / wait surface
# --------------------------------------------------------------------------


def test_run_task_async_returns_running_immediately(
    fixture_repo: Path, staging_root: Path
) -> None:
    """run_task_async should return with status=RUNNING; drive completes async."""
    adapter = _scripted_executor(
        mutator=lambda worktree: (worktree / "x.txt").write_text("x")
    )
    service = _make_service(staging_root=staging_root, adapter=adapter)
    workspace = _register(service, path=fixture_repo)

    envelope = service.run_task_async(
        meta=_meta(), workspace_id=workspace.id, prompt="add x"
    )
    assert envelope.ok, envelope.errors
    assert envelope.payload is not None
    initial = envelope.payload.value
    assert initial.status is TaskStatus.RUNNING
    assert initial.adapter_handle_id is not None
    assert initial.adapter_container_id is not None
    assert initial.adapter_started_at is not None
    assert initial.finished_at is None

    final = service.wait_for_task(
        meta=_meta(), task_id=initial.id, max_wait_seconds=5.0
    )
    assert final.ok, final.errors
    assert final.payload is not None
    assert final.payload.value.status is TaskStatus.SUCCEEDED
    service.shutdown(wait=True)


def test_run_task_sync_persists_adapter_handle_fields(
    fixture_repo: Path, staging_root: Path
) -> None:
    """Sync dispatch should also stamp adapter_* columns on the row."""
    adapter = _scripted_executor(
        mutator=lambda worktree: (worktree / "y.txt").write_text("y")
    )
    service = _make_service(staging_root=staging_root, adapter=adapter)
    workspace = _register(service, path=fixture_repo)

    envelope = service.run_task_sync(
        meta=_meta(), workspace_id=workspace.id, prompt="add y"
    )
    assert envelope.ok, envelope.errors
    assert envelope.payload is not None
    final = envelope.payload.value
    assert final.adapter_handle_id is not None
    assert final.adapter_container_id is not None
    assert final.adapter_started_at is not None


def test_wait_for_task_short_circuits_on_terminal(
    fixture_repo: Path, staging_root: Path
) -> None:
    """wait_for_task on an already-terminal task should return immediately."""
    adapter = _scripted_executor(mutator=lambda _w: None)
    service = _make_service(staging_root=staging_root, adapter=adapter)
    workspace = _register(service, path=fixture_repo)
    run = service.run_task_sync(meta=_meta(), workspace_id=workspace.id, prompt="quick")
    assert run.ok
    assert run.payload is not None
    task_id = run.payload.value.id

    waited = service.wait_for_task(meta=_meta(), task_id=task_id, max_wait_seconds=0.0)
    assert waited.ok
    assert waited.payload is not None
    assert waited.payload.value.id == task_id
    assert waited.payload.value.status is TaskStatus.SUCCEEDED


def test_wait_for_task_times_out_on_non_terminal(
    fixture_repo: Path, staging_root: Path
) -> None:
    """wait_for_task should return a timed-out failure envelope without blocking forever."""
    workspace_repo = InMemoryWorkspaceRepository()
    task_repo = InMemoryTaskRepository()
    workspace = Workspace(
        id="01HZZZZZZZZZZZZZZZZZZZZZZ1",
        path=str(fixture_repo),
        default_executor=ExecutorId.CLAUDE_CODE,
        test_command="true",
        max_wallclock_seconds=30,
        branch_prefix="brain/code",
        created_at=datetime.now(UTC),
        revoked_at=None,
    )
    workspace_repo.append(workspace=workspace)
    pending = Task(
        id="01HZZZZZZZZZZZZZZZZZZZZZZ2",
        workspace_id=workspace.id,
        executor=ExecutorId.CLAUDE_CODE,
        branch="brain/code/dummy-12345678",
        prompt_object_ref="",
        status=TaskStatus.RUNNING,
        started_at=datetime.now(UTC),
    )
    task_repo.append(task=pending)
    # Construct service with reattach disabled so the in-flight row stays put.
    service = DefaultSoftwareService(
        settings=_settings(staging_root=staging_root),
        adapter=None,
        workspace_repository=workspace_repo,
        task_repository=task_repo,
        wait_interval_seconds=0.01,
        reattach_on_init=False,
    )

    envelope = service.wait_for_task(
        meta=_meta(), task_id=pending.id, max_wait_seconds=0.05
    )
    assert not envelope.ok
    assert envelope.payload is not None
    assert envelope.payload.value.status is TaskStatus.RUNNING
    assert any(err.code == "DEADLINE_EXCEEDED" for err in envelope.errors)
    service.shutdown(wait=True)


def test_wait_for_task_unknown_id_returns_not_found(staging_root: Path) -> None:
    """wait_for_task should surface NOT_FOUND when the task does not exist."""
    service = _make_service(staging_root=staging_root, adapter=None)
    envelope = service.wait_for_task(
        meta=_meta(), task_id="01ABSENT-TASK-ID-DOES-NOT-EXIST", max_wait_seconds=0.0
    )
    assert not envelope.ok
    assert envelope.errors


def test_reattach_drives_orphaned_task_to_terminal(
    fixture_repo: Path, staging_root: Path
) -> None:
    """A non-terminal task in the repo at construction should be driven to terminal."""
    workspace_repo = InMemoryWorkspaceRepository()
    task_repo = InMemoryTaskRepository()
    workspace = Workspace(
        id="01HZZZZZZZZZZZZZZZZZZZZZZ3",
        path=str(fixture_repo),
        default_executor=ExecutorId.CLAUDE_CODE,
        test_command="true",
        max_wallclock_seconds=30,
        branch_prefix="brain/code",
        created_at=datetime.now(UTC),
        revoked_at=None,
    )
    workspace_repo.append(workspace=workspace)
    # Create a task as if a previous Brain Core process had dispatched it
    # but crashed before driving it to terminal.
    task = Task(
        id="01HZZZZZZZZZZZZZZZZZZZZZZ4",
        workspace_id=workspace.id,
        executor=ExecutorId.CLAUDE_CODE,
        branch="brain/code/orphan-12345678",
        prompt_object_ref="",
        status=TaskStatus.RUNNING,
        started_at=datetime.now(UTC),
        adapter_handle_id="prior-handle",
        adapter_container_id="prior-container",
        adapter_started_at=datetime.now(UTC),
    )
    task_repo.append(task=task)

    adapter = _scripted_executor(mutator=lambda _w: None)
    service = DefaultSoftwareService(
        settings=_settings(staging_root=staging_root),
        adapter=adapter,
        workspace_repository=workspace_repo,
        task_repository=task_repo,
        poll_interval_seconds=0.0,
        wait_interval_seconds=0.01,
    )
    final = service.wait_for_task(meta=_meta(), task_id=task.id, max_wait_seconds=5.0)
    assert final.ok, final.errors
    assert final.payload is not None
    assert final.payload.value.status in {
        TaskStatus.SUCCEEDED,
        TaskStatus.FAILED,
    }, final.payload.value
    service.shutdown(wait=True)


def test_reattach_fails_row_with_missing_adapter_handle_columns(
    fixture_repo: Path, staging_root: Path
) -> None:
    """Reattach should refuse non-terminal rows with no persisted adapter handle."""
    workspace_repo = InMemoryWorkspaceRepository()
    task_repo = InMemoryTaskRepository()
    workspace = Workspace(
        id="01REATTACHNOHANDLEWORKSPACE",
        path=str(fixture_repo),
        default_executor=ExecutorId.CLAUDE_CODE,
        test_command="true",
        max_wallclock_seconds=30,
        branch_prefix="brain/code",
        created_at=datetime.now(UTC),
        revoked_at=None,
    )
    workspace_repo.append(workspace=workspace)
    task = Task(
        id="01REATTACHNOHANDLETASKID0001",
        workspace_id=workspace.id,
        executor=ExecutorId.CLAUDE_CODE,
        branch="brain/code/abandoned-12345678",
        prompt_object_ref=None,
        status=TaskStatus.RUNNING,
        started_at=datetime.now(UTC),
    )
    task_repo.append(task=task)

    service = DefaultSoftwareService(
        settings=_settings(staging_root=staging_root),
        adapter=_scripted_executor(mutator=lambda _w: None),
        workspace_repository=workspace_repo,
        task_repository=task_repo,
        poll_interval_seconds=0.0,
    )
    service.shutdown(wait=True)

    final = task_repo.get_by_id(task_id=task.id)
    assert final is not None
    assert final.status is TaskStatus.FAILED
    assert final.termination_reason is TerminationReason.RUNTIME_ERROR
    assert final.failure_detail is not None
    assert "before adapter dispatch" in final.failure_detail


def test_resume_from_committing_uses_existing_commit_idempotently(
    fixture_repo: Path, staging_root: Path
) -> None:
    """A row in COMMITTING with a commit already on disk should finalize, not re-commit."""
    workspace_repo = InMemoryWorkspaceRepository()
    task_repo = InMemoryTaskRepository()
    workspace = Workspace(
        id="01RESUMECOMMITWORKSPACEAA01",
        path=str(fixture_repo),
        default_executor=ExecutorId.CLAUDE_CODE,
        test_command="true",
        max_wallclock_seconds=30,
        branch_prefix="brain/code",
        created_at=datetime.now(UTC),
        revoked_at=None,
    )
    workspace_repo.append(workspace=workspace)

    task_id = "01RESUMECOMMITTASKID0000001"
    branch = "brain/code/resumed-feature"
    worktree_path = staging_root / task_id
    subprocess.run(
        [
            "git",
            "-C",
            str(fixture_repo),
            "worktree",
            "add",
            "-b",
            branch,
            str(worktree_path),
        ],
        check=True,
        capture_output=True,
    )
    (worktree_path / "feature.txt").write_text("resumed\n")
    subprocess.run(
        ["git", "-C", str(worktree_path), "add", "feature.txt"],
        check=True,
        capture_output=True,
    )
    subprocess.run(
        [
            "git",
            "-C",
            str(worktree_path),
            "-c",
            "user.email=brain@local",
            "-c",
            "user.name=Brain",
            "commit",
            "-m",
            "resumed feature",
        ],
        check=True,
        capture_output=True,
    )
    expected_sha = subprocess.run(
        ["git", "-C", str(worktree_path), "rev-parse", "HEAD"],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()

    task = Task(
        id=task_id,
        workspace_id=workspace.id,
        executor=ExecutorId.CLAUDE_CODE,
        branch=branch,
        prompt_object_ref=None,
        status=TaskStatus.COMMITTING,
        started_at=datetime.now(UTC),
        test_passed=True,
        adapter_handle_id="prior-handle",
        adapter_container_id="prior-container",
        adapter_started_at=datetime.now(UTC),
    )
    task_repo.append(task=task)

    service = DefaultSoftwareService(
        settings=_settings(staging_root=staging_root),
        adapter=_scripted_executor(mutator=lambda _w: None),
        workspace_repository=workspace_repo,
        task_repository=task_repo,
        poll_interval_seconds=0.0,
        wait_interval_seconds=0.01,
    )
    final = service.wait_for_task(meta=_meta(), task_id=task.id, max_wait_seconds=5.0)
    service.shutdown(wait=True)

    assert final.ok, final.errors
    assert final.payload is not None
    finished = final.payload.value
    assert finished.status is TaskStatus.SUCCEEDED
    assert finished.commit_sha == expected_sha


def test_resume_from_testing_re_runs_test_command(
    fixture_repo: Path, staging_root: Path
) -> None:
    """A row in TESTING should re-run the test command without re-polling the executor."""
    workspace_repo = InMemoryWorkspaceRepository()
    task_repo = InMemoryTaskRepository()
    workspace = Workspace(
        id="01RESUMETESTWORKSPACEAAAA01",
        path=str(fixture_repo),
        default_executor=ExecutorId.CLAUDE_CODE,
        test_command="true",
        max_wallclock_seconds=30,
        branch_prefix="brain/code",
        created_at=datetime.now(UTC),
        revoked_at=None,
    )
    workspace_repo.append(workspace=workspace)

    task_id = "01RESUMETESTTASKID000000001"
    branch = "brain/code/resumed-test"
    worktree_path = staging_root / task_id
    subprocess.run(
        [
            "git",
            "-C",
            str(fixture_repo),
            "worktree",
            "add",
            "-b",
            branch,
            str(worktree_path),
        ],
        check=True,
        capture_output=True,
    )
    (worktree_path / "feature.txt").write_text("uncommitted\n")

    task = Task(
        id=task_id,
        workspace_id=workspace.id,
        executor=ExecutorId.CLAUDE_CODE,
        branch=branch,
        prompt_object_ref=None,
        status=TaskStatus.TESTING,
        started_at=datetime.now(UTC),
        adapter_handle_id="prior-handle",
        adapter_container_id="prior-container",
        adapter_started_at=datetime.now(UTC),
    )
    task_repo.append(task=task)

    # Adapter should never be polled — TESTING phase skips the executor poll.
    adapter = _MockCodingAdapter(script=_Snapshot(phases=[TaskPhase.RUNNING]))
    service = DefaultSoftwareService(
        settings=_settings(staging_root=staging_root),
        adapter=adapter,
        workspace_repository=workspace_repo,
        task_repository=task_repo,
        poll_interval_seconds=0.0,
        wait_interval_seconds=0.01,
    )
    final = service.wait_for_task(meta=_meta(), task_id=task.id, max_wait_seconds=5.0)
    service.shutdown(wait=True)

    assert final.ok, final.errors
    assert final.payload is not None
    finished = final.payload.value
    assert finished.status is TaskStatus.SUCCEEDED
    assert finished.test_passed is True
    assert finished.commit_sha is not None
