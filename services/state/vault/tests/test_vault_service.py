"""Behavior tests for Vault Service implementation."""

from __future__ import annotations

from dataclasses import dataclass

from lib.shared.envelope import EnvelopeKind, new_meta
from resources.substrates.obsidian import (
    FileEditOperation,
    ObsidianSubstrate,
    ObsidianSubstrateAlreadyExistsError,
    ObsidianSubstrateConflictError,
    ObsidianSubstrateDependencyError,
    ObsidianSubstrateInternalError,
    ObsidianHealthStatus,
    ObsidianSubstrateNotFoundError,
    ObsidianEntry,
    ObsidianEntryType,
    ObsidianFileRecord,
    ObsidianSearchMatch,
)
from services.state.vault.config import VaultSettings
from services.state.vault.domain import FileEdit
from services.state.vault.implementation import DefaultVaultService


@dataclass
class _SearchCall:
    query: str
    directory_scope: str
    limit: int


class _FakeSubstrate(ObsidianSubstrate):
    """In-memory substrate fake for Vault behavior tests."""

    def __init__(self) -> None:
        self.entries: list[ObsidianEntry] = []
        self.files: dict[str, ObsidianFileRecord] = {}
        self.edit_calls: list[list[FileEditOperation]] = []
        self.search_calls: list[_SearchCall] = []
        self.raise_on_create: Exception | None = None
        self.raise_on_update: Exception | None = None
        self.raise_on_get: Exception | None = None
        self.health_status = ObsidianHealthStatus(ready=True, detail="ok")

    def health(self) -> ObsidianHealthStatus:
        return self.health_status

    def list_directory(self, *, directory_path: str) -> list[ObsidianEntry]:
        return list(self.entries)

    def create_directory(
        self, *, directory_path: str, recursive: bool
    ) -> ObsidianEntry:
        return ObsidianEntry(
            path=directory_path,
            name=directory_path.rsplit("/", maxsplit=1)[-1],
            entry_type=ObsidianEntryType.DIRECTORY,
            revision="dir:1",
        )

    def delete_directory(
        self,
        *,
        directory_path: str,
        recursive: bool,
        missing_ok: bool,
        use_trash: bool,
    ) -> bool:
        return True

    def create_file(self, *, file_path: str, content: str) -> ObsidianFileRecord:
        if self.raise_on_create is not None:
            raise self.raise_on_create
        record = ObsidianFileRecord(path=file_path, content=content, revision="r1")
        self.files[file_path] = record
        return record

    def get_file(self, *, file_path: str) -> ObsidianFileRecord:
        if self.raise_on_get is not None:
            raise self.raise_on_get
        record = self.files.get(file_path)
        if record is None:
            raise ObsidianSubstrateNotFoundError("missing")
        return record

    def update_file(
        self,
        *,
        file_path: str,
        content: str,
        if_revision: str,
        force: bool,
    ) -> ObsidianFileRecord:
        if self.raise_on_update is not None:
            raise self.raise_on_update
        record = ObsidianFileRecord(path=file_path, content=content, revision="r2")
        self.files[file_path] = record
        return record

    def append_file(
        self,
        *,
        file_path: str,
        content: str,
        if_revision: str,
        force: bool,
    ) -> ObsidianFileRecord:
        existing = self.files.get(
            file_path, ObsidianFileRecord(path=file_path, content="")
        )
        record = ObsidianFileRecord(
            path=file_path,
            content=f"{existing.content}{content}",
            revision="r3",
        )
        self.files[file_path] = record
        return record

    def edit_file(
        self,
        *,
        file_path: str,
        edits: tuple[FileEditOperation, ...] | list[FileEditOperation],
        if_revision: str,
        force: bool,
    ) -> ObsidianFileRecord:
        self.edit_calls.append(list(edits))
        return ObsidianFileRecord(
            path=file_path, content=f"edited:{len(edits)}", revision="r4"
        )

    def move_path(
        self,
        *,
        source_path: str,
        target_path: str,
        if_revision: str,
        force: bool,
    ) -> ObsidianEntry:
        return ObsidianEntry(
            path=target_path,
            name=target_path.rsplit("/", maxsplit=1)[-1],
            entry_type=ObsidianEntryType.FILE,
            revision="move:1",
        )

    def delete_file(
        self,
        *,
        file_path: str,
        missing_ok: bool,
        use_trash: bool,
        if_revision: str,
        force: bool,
    ) -> bool:
        return self.files.pop(file_path, None) is not None

    def search_files(
        self,
        *,
        query: str,
        directory_scope: str,
        limit: int,
    ) -> list[ObsidianSearchMatch]:
        self.search_calls.append(
            _SearchCall(query=query, directory_scope=directory_scope, limit=limit)
        )
        return [
            ObsidianSearchMatch(path="notes/alpha.md", score=1.0, snippets=("alpha",))
        ]


def _service() -> tuple[DefaultVaultService, _FakeSubstrate]:
    """Build deterministic Vault with in-memory substrate fake."""
    substrate = _FakeSubstrate()
    service = DefaultVaultService(
        settings=VaultSettings(max_search_limit=10),
        substrate=substrate,
    )
    return service, substrate


def _meta() -> object:
    """Build valid envelope metadata for tests."""
    return new_meta(kind=EnvelopeKind.COMMAND, source="test", principal="operator")


def test_create_file_rejects_non_markdown_paths() -> None:
    """Create file should enforce markdown-only file extension policy."""
    service, _substrate = _service()

    result = service.create_file(meta=_meta(), file_path="notes.txt", content="x")

    assert result.ok is False
    assert result.errors[0].category.value == "validation"


def test_list_directory_returns_file_and_directory_metadata() -> None:
    """Directory listing should include both directory and file entries."""
    service, substrate = _service()
    substrate.entries = [
        ObsidianEntry(
            path="notes",
            name="notes",
            entry_type=ObsidianEntryType.DIRECTORY,
            revision="d1",
        ),
        ObsidianEntry(
            path="notes/todo.md",
            name="todo.md",
            entry_type=ObsidianEntryType.FILE,
            revision="f1",
        ),
    ]

    result = service.list_directory(meta=_meta(), directory_path="")

    assert result.ok is True
    assert result.payload is not None
    assert [item.entry_type.value for item in result.payload.value] == [
        "directory",
        "file",
    ]


def test_list_directory_limit_is_capped_by_service_settings() -> None:
    """Directory list should cap returned entry count by configured maximum."""
    substrate = _FakeSubstrate()
    service = DefaultVaultService(
        settings=VaultSettings(max_list_limit=1, max_search_limit=10),
        substrate=substrate,
    )
    substrate.entries = [
        ObsidianEntry(
            path="notes",
            name="notes",
            entry_type=ObsidianEntryType.DIRECTORY,
            revision="d1",
        ),
        ObsidianEntry(
            path="notes/todo.md",
            name="todo.md",
            entry_type=ObsidianEntryType.FILE,
            revision="f1",
        ),
    ]

    result = service.list_directory(meta=_meta(), directory_path="")

    assert result.ok is True
    assert result.payload is not None
    assert len(result.payload.value) == 1


def test_update_file_maps_conflict_to_conflict_error() -> None:
    """Substrate conflict errors should surface as conflict-category envelope errors."""
    service, substrate = _service()
    substrate.files["notes/todo.md"] = ObsidianFileRecord(
        path="notes/todo.md",
        content="current",
        revision="r1",
    )
    substrate.raise_on_update = ObsidianSubstrateConflictError("revision mismatch")

    result = service.update_file(
        meta=_meta(),
        file_path="notes/todo.md",
        content="updated",
        if_revision="r1",
    )

    assert result.ok is False
    assert result.errors[0].category.value == "conflict"


def test_update_file_enforces_if_revision_precondition() -> None:
    """Update should fail with conflict when provided revision does not match."""
    service, substrate = _service()
    substrate.files["notes/todo.md"] = ObsidianFileRecord(
        path="notes/todo.md",
        content="current",
        revision="r2",
    )

    result = service.update_file(
        meta=_meta(),
        file_path="notes/todo.md",
        content="updated",
        if_revision="r1",
        force=False,
    )

    assert result.ok is False
    assert result.errors[0].category.value == "conflict"
    assert result.errors[0].metadata.get("expected_revision") == "r1"
    assert result.errors[0].metadata.get("actual_revision") == "r2"


def test_search_limit_is_capped_by_service_settings() -> None:
    """Search should cap requested limit to configured maximum."""
    service, substrate = _service()

    result = service.search_files(
        meta=_meta(),
        query="alpha",
        directory_scope="notes",
        limit=999,
    )

    assert result.ok is True
    assert substrate.search_calls[-1].limit == 10


def test_search_normalizes_directory_scope_trailing_slash() -> None:
    """Search should accept directory scopes with a trailing slash."""
    service, substrate = _service()

    result = service.search_files(
        meta=_meta(),
        query="alpha",
        directory_scope="professional/",
        limit=5,
    )

    assert result.ok is True
    assert substrate.search_calls[-1].directory_scope == "professional"


def test_edit_file_maps_edit_operations_and_returns_payload() -> None:
    """Edit should pass validated operations to substrate and map payload."""
    service, _substrate = _service()

    result = service.edit_file(
        meta=_meta(),
        file_path="notes/todo.md",
        edits=[FileEdit(start_line=1, end_line=1, content="first")],
    )

    assert result.ok is True
    assert result.payload is not None
    assert result.payload.value.content == "edited:1"


def test_edit_file_accepts_dict_edit_payloads_from_op_invocation() -> None:
    """Edit should accept dict-shaped edits passed through Execution/agent tool payloads."""
    service, substrate = _service()

    result = service.edit_file(
        meta=_meta(),
        file_path="notes/todo.md",
        edits=[{"start_line": 2, "end_line": 3, "content": "patched"}],
    )

    assert result.ok is True
    assert substrate.edit_calls == [
        [FileEditOperation(start_line=2, end_line=3, content="patched")]
    ]


def test_move_path_allows_directory_names_with_dots() -> None:
    """Directory moves should allow dotted segment names."""
    service, _substrate = _service()

    result = service.move_path(
        meta=_meta(),
        source_path="notes.v1/project",
        target_path="notes.v2/project",
    )

    assert result.ok is True
    assert result.payload is not None
    assert result.payload.value.path == "notes.v2/project"


def test_move_path_rejects_file_directory_type_mismatch() -> None:
    """Move should reject source/target type mismatches between file and directory."""
    service, _substrate = _service()

    result = service.move_path(
        meta=_meta(),
        source_path="notes/todo.md",
        target_path="notes/archive",
    )

    assert result.ok is False
    assert result.errors[0].category.value == "validation"


def test_edit_file_validation_error_uses_field_scoped_message() -> None:
    """Validation errors should include stable field-scoped message format."""
    service, _substrate = _service()

    result = service.edit_file(meta=_meta(), file_path="notes/todo.md", edits=[])

    assert result.ok is False
    assert result.errors[0].category.value == "validation"
    assert result.errors[0].message.startswith("edits:")


def test_validate_request_surfaces_all_pydantic_errors() -> None:
    """Validation should report every error, not just the first."""
    service, _substrate = _service()

    result = service.edit_file(
        meta=_meta(),
        file_path="../escape.md",
        edits=[],
    )

    assert result.ok is False
    assert len(result.errors) >= 2


def test_health_maps_owned_substrate_probe() -> None:
    """Vault health should map owned Obsidian substrate health payload."""
    service, substrate = _service()
    substrate.health_status = ObsidianHealthStatus(
        ready=False, detail="dependency unavailable"
    )

    result = service.health(meta=_meta())

    assert result.ok is True
    assert result.payload is not None
    assert result.payload.value.service_ready is True
    assert result.payload.value.substrate_ready is False
    assert result.payload.value.detail == "dependency unavailable"


# --- Happy path coverage ---


def test_create_file_returns_file_record_on_success() -> None:
    """Create file happy path should return mapped VaultFileRecord."""
    service, _substrate = _service()

    result = service.create_file(
        meta=_meta(), file_path="notes/new.md", content="hello"
    )

    assert result.ok is True
    assert result.payload is not None
    assert result.payload.value.path == "notes/new.md"
    assert result.payload.value.content == "hello"


def test_get_file_returns_file_record_on_success() -> None:
    """Get file happy path should return mapped VaultFileRecord."""
    service, substrate = _service()
    substrate.files["notes/todo.md"] = ObsidianFileRecord(
        path="notes/todo.md", content="existing", revision="r1"
    )

    result = service.get_file(meta=_meta(), file_path="notes/todo.md")

    assert result.ok is True
    assert result.payload is not None
    assert result.payload.value.content == "existing"
    assert result.payload.value.revision == "r1"


def test_get_file_returns_not_found_error() -> None:
    """Get file should return not_found error when substrate raises NotFoundError."""
    service, _substrate = _service()

    result = service.get_file(meta=_meta(), file_path="notes/missing.md")

    assert result.ok is False
    assert result.errors[0].category.value == "not_found"


def test_append_file_returns_appended_content() -> None:
    """Append file happy path should return record with concatenated content."""
    service, substrate = _service()
    substrate.files["notes/log.md"] = ObsidianFileRecord(
        path="notes/log.md", content="line1\n", revision="r1"
    )

    result = service.append_file(
        meta=_meta(), file_path="notes/log.md", content="line2\n"
    )

    assert result.ok is True
    assert result.payload is not None
    assert result.payload.value.content == "line1\nline2\n"


def test_delete_file_returns_true_on_success() -> None:
    """Delete file happy path should return True when file is removed."""
    service, substrate = _service()
    substrate.files["notes/old.md"] = ObsidianFileRecord(
        path="notes/old.md", content="", revision="r1"
    )

    result = service.delete_file(meta=_meta(), file_path="notes/old.md")

    assert result.ok is True
    assert result.payload is not None
    assert result.payload.value is True


def test_create_directory_returns_entry_on_success() -> None:
    """Create directory happy path should return mapped VaultEntry."""
    service, _substrate = _service()

    result = service.create_directory(meta=_meta(), directory_path="notes/archive")

    assert result.ok is True
    assert result.payload is not None
    assert result.payload.value.entry_type.value == "directory"


def test_update_file_succeeds_without_precondition() -> None:
    """Update without if_revision should succeed without precondition check."""
    service, substrate = _service()
    substrate.files["notes/todo.md"] = ObsidianFileRecord(
        path="notes/todo.md", content="old", revision="r1"
    )

    result = service.update_file(meta=_meta(), file_path="notes/todo.md", content="new")

    assert result.ok is True
    assert result.payload is not None
    assert result.payload.value.content == "new"


# --- Precondition bypass ---


def test_update_file_force_bypasses_revision_precondition() -> None:
    """Update with force=True should skip precondition even with stale revision."""
    service, substrate = _service()
    substrate.files["notes/todo.md"] = ObsidianFileRecord(
        path="notes/todo.md", content="current", revision="r2"
    )

    result = service.update_file(
        meta=_meta(),
        file_path="notes/todo.md",
        content="forced",
        if_revision="r1",
        force=True,
    )

    assert result.ok is True
    assert result.payload is not None
    assert result.payload.value.content == "forced"


# --- Substrate error mapping branches ---


def test_substrate_already_exists_maps_to_conflict_error() -> None:
    """AlreadyExistsError should surface as conflict-category envelope error."""
    service, substrate = _service()
    substrate.raise_on_create = ObsidianSubstrateAlreadyExistsError("file exists")

    result = service.create_file(meta=_meta(), file_path="notes/dup.md", content="")

    assert result.ok is False
    assert result.errors[0].category.value == "conflict"
    assert result.errors[0].code == "ALREADY_EXISTS"


def test_substrate_dependency_error_maps_to_dependency_error() -> None:
    """DependencyError should surface as dependency-category envelope error."""
    service, substrate = _service()
    substrate.raise_on_get = ObsidianSubstrateDependencyError("obsidian unreachable")

    result = service.get_file(meta=_meta(), file_path="notes/todo.md")

    assert result.ok is False
    assert result.errors[0].category.value == "dependency"


def test_substrate_internal_error_maps_to_internal_error() -> None:
    """InternalError should surface as internal-category envelope error."""
    service, substrate = _service()
    substrate.raise_on_get = ObsidianSubstrateInternalError("schema mismatch")

    result = service.get_file(meta=_meta(), file_path="notes/todo.md")

    assert result.ok is False
    assert result.errors[0].category.value == "internal"


def test_substrate_unexpected_exception_maps_to_internal_error() -> None:
    """Unrecognized exceptions should surface as internal-category envelope error."""
    service, substrate = _service()
    substrate.raise_on_get = RuntimeError("something unexpected")

    result = service.get_file(meta=_meta(), file_path="notes/todo.md")

    assert result.ok is False
    assert result.errors[0].category.value == "internal"
    assert result.errors[0].code == "UNEXPECTED_EXCEPTION"


# --- Move path precondition ---


def test_move_file_enforces_revision_precondition() -> None:
    """Move of .md file with if_revision should check precondition."""
    service, substrate = _service()
    substrate.files["notes/old.md"] = ObsidianFileRecord(
        path="notes/old.md", content="", revision="r2"
    )

    result = service.move_path(
        meta=_meta(),
        source_path="notes/old.md",
        target_path="notes/new.md",
        if_revision="r1",
    )

    assert result.ok is False
    assert result.errors[0].category.value == "conflict"
