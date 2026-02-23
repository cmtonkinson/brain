"""Transport-agnostic Obsidian adapter contracts and DTOs."""

from __future__ import annotations

from enum import StrEnum
from typing import Protocol, Sequence

from pydantic import BaseModel, ConfigDict


class ObsidianAdapterError(Exception):
    """Base exception for adapter-level failures."""


class ObsidianAdapterDependencyError(ObsidianAdapterError):
    """Dependency-level failure (network/upstream unavailable)."""


class ObsidianAdapterInternalError(ObsidianAdapterError):
    """Internal adapter failure (schema/mapping/contract mismatch)."""


class ObsidianAdapterNotFoundError(ObsidianAdapterError):
    """Target file or directory does not exist."""


class ObsidianAdapterAlreadyExistsError(ObsidianAdapterError):
    """Target creation failed because the resource already exists."""


class ObsidianAdapterConflictError(ObsidianAdapterError):
    """Operation conflicted with current resource state."""


class ObsidianEntryType(StrEnum):
    """Normalized vault entry type classification."""

    DIRECTORY = "directory"
    FILE = "file"


class ObsidianEntry(BaseModel):
    """One vault directory listing entry."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    path: str
    name: str
    entry_type: ObsidianEntryType
    size_bytes: int = 0
    created_at: str = ""
    updated_at: str = ""
    revision: str = ""


class ObsidianFileRecord(BaseModel):
    """One vault file read/write payload."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    path: str
    content: str
    size_bytes: int = 0
    created_at: str = ""
    updated_at: str = ""
    revision: str = ""


class ObsidianSearchMatch(BaseModel):
    """One lexical search match in the vault."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    path: str
    score: float = 0.0
    snippets: tuple[str, ...] = ()
    updated_at: str = ""
    revision: str = ""


class FileEditOperation(BaseModel):
    """One line-based edit operation applied to file content."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    start_line: int
    end_line: int
    content: str


class ObsidianAdapter(Protocol):
    """Protocol for Obsidian Local REST API-backed vault operations."""

    def list_directory(self, *, directory_path: str) -> list[ObsidianEntry]:
        """List file and directory entries directly under one path."""

    def create_directory(
        self, *, directory_path: str, recursive: bool
    ) -> ObsidianEntry:
        """Create one directory and return resulting metadata."""

    def delete_directory(
        self,
        *,
        directory_path: str,
        recursive: bool,
        missing_ok: bool,
        use_trash: bool,
    ) -> bool:
        """Delete one directory, optionally recursively."""

    def create_file(self, *, file_path: str, content: str) -> ObsidianFileRecord:
        """Create one file and fail when it already exists."""

    def get_file(self, *, file_path: str) -> ObsidianFileRecord:
        """Read one file by path."""

    def update_file(
        self,
        *,
        file_path: str,
        content: str,
        if_revision: str,
        force: bool,
    ) -> ObsidianFileRecord:
        """Replace one file content, optionally guarded by revision token."""

    def append_file(
        self,
        *,
        file_path: str,
        content: str,
        if_revision: str,
        force: bool,
    ) -> ObsidianFileRecord:
        """Append one content fragment to a file."""

    def edit_file(
        self,
        *,
        file_path: str,
        edits: Sequence[FileEditOperation],
        if_revision: str,
        force: bool,
    ) -> ObsidianFileRecord:
        """Apply line-based edits to a file."""

    def move_path(
        self,
        *,
        source_path: str,
        target_path: str,
        if_revision: str,
        force: bool,
    ) -> ObsidianEntry:
        """Move or rename one file or directory path."""

    def delete_file(
        self,
        *,
        file_path: str,
        missing_ok: bool,
        use_trash: bool,
        if_revision: str,
        force: bool,
    ) -> bool:
        """Delete one file, optionally by moving to Obsidian trash."""

    def search_files(
        self,
        *,
        query: str,
        directory_scope: str,
        limit: int,
    ) -> list[ObsidianSearchMatch]:
        """Run lexical file search through Obsidian Local REST API."""
