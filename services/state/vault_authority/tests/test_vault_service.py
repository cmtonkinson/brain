"""Behavior tests for Vault Authority Service implementation."""

from __future__ import annotations

from dataclasses import dataclass

from packages.brain_shared.envelope import EnvelopeKind, new_meta
from resources.adapters.obsidian import (
    FileEditOperation,
    ObsidianAdapter,
    ObsidianAdapterConflictError,
    ObsidianAdapterNotFoundError,
    ObsidianEntry,
    ObsidianEntryType,
    ObsidianFileRecord,
    ObsidianSearchMatch,
)
from services.state.vault_authority.config import VaultAuthoritySettings
from services.state.vault_authority.domain import FileEdit
from services.state.vault_authority.implementation import DefaultVaultAuthorityService


@dataclass
class _SearchCall:
    query: str
    directory_scope: str
    limit: int


class _FakeAdapter(ObsidianAdapter):
    """In-memory adapter fake for VAS behavior tests."""

    def __init__(self) -> None:
        self.entries: list[ObsidianEntry] = []
        self.files: dict[str, ObsidianFileRecord] = {}
        self.search_calls: list[_SearchCall] = []
        self.raise_on_update: Exception | None = None
        self.raise_on_get: Exception | None = None

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
        record = ObsidianFileRecord(path=file_path, content=content, revision="r1")
        self.files[file_path] = record
        return record

    def get_file(self, *, file_path: str) -> ObsidianFileRecord:
        if self.raise_on_get is not None:
            raise self.raise_on_get
        record = self.files.get(file_path)
        if record is None:
            raise ObsidianAdapterNotFoundError("missing")
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


def _service() -> tuple[DefaultVaultAuthorityService, _FakeAdapter]:
    """Build deterministic VAS with in-memory adapter fake."""
    adapter = _FakeAdapter()
    service = DefaultVaultAuthorityService(
        settings=VaultAuthoritySettings(max_search_limit=10),
        adapter=adapter,
    )
    return service, adapter


def _meta() -> object:
    """Build valid envelope metadata for tests."""
    return new_meta(kind=EnvelopeKind.COMMAND, source="test", principal="operator")


def test_create_file_rejects_non_markdown_paths() -> None:
    """Create file should enforce markdown-only file extension policy."""
    service, _adapter = _service()

    result = service.create_file(meta=_meta(), file_path="notes.txt", content="x")

    assert result.ok is False
    assert result.errors[0].category.value == "validation"


def test_list_directory_returns_file_and_directory_metadata() -> None:
    """Directory listing should include both directory and file entries."""
    service, adapter = _service()
    adapter.entries = [
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
    adapter = _FakeAdapter()
    service = DefaultVaultAuthorityService(
        settings=VaultAuthoritySettings(max_list_limit=1, max_search_limit=10),
        adapter=adapter,
    )
    adapter.entries = [
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
    """Adapter conflict errors should surface as conflict-category envelope errors."""
    service, adapter = _service()
    adapter.files["notes/todo.md"] = ObsidianFileRecord(
        path="notes/todo.md",
        content="current",
        revision="r1",
    )
    adapter.raise_on_update = ObsidianAdapterConflictError("revision mismatch")

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
    service, adapter = _service()
    adapter.files["notes/todo.md"] = ObsidianFileRecord(
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
    service, adapter = _service()

    result = service.search_files(
        meta=_meta(),
        query="alpha",
        directory_scope="notes",
        limit=999,
    )

    assert result.ok is True
    assert adapter.search_calls[-1].limit == 10


def test_edit_file_maps_edit_operations_and_returns_payload() -> None:
    """Edit should pass validated operations to adapter and map payload."""
    service, _adapter = _service()

    result = service.edit_file(
        meta=_meta(),
        file_path="notes/todo.md",
        edits=[FileEdit(start_line=1, end_line=1, content="first")],
    )

    assert result.ok is True
    assert result.payload is not None
    assert result.payload.value.content == "edited:1"


def test_move_path_allows_directory_names_with_dots() -> None:
    """Directory moves should allow dotted segment names."""
    service, _adapter = _service()

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
    service, _adapter = _service()

    result = service.move_path(
        meta=_meta(),
        source_path="notes/todo.md",
        target_path="notes/archive",
    )

    assert result.ok is False
    assert result.errors[0].category.value == "validation"


def test_edit_file_validation_error_uses_field_scoped_message() -> None:
    """Validation errors should include stable field-scoped message format."""
    service, _adapter = _service()

    result = service.edit_file(meta=_meta(), file_path="notes/todo.md", edits=[])

    assert result.ok is False
    assert result.errors[0].category.value == "validation"
    assert result.errors[0].message.startswith("edits:")
