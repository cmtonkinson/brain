"""Request validation models for Vault Authority Service public API."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator
from packages.brain_shared.vault_paths import (
    normalize_vault_directory_path,
    normalize_vault_file_path,
    normalize_vault_relative_path,
)


def _strip_text(value: object) -> object:
    """Normalize surrounding whitespace for textual request fields."""
    if isinstance(value, str):
        return value.strip()
    return value


def _normalize_directory_path(value: str, *, allow_root: bool = False) -> str:
    """Normalize one vault directory path."""
    return normalize_vault_directory_path(value, allow_root=allow_root)


def _normalize_file_path(value: str) -> str:
    """Normalize one markdown file path and enforce ``.md`` extension."""
    return normalize_vault_file_path(value, suffix=".md")


class ListDirectoryRequest(BaseModel):
    """Validate one list-directory request payload."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    directory_path: str = ""

    @field_validator("directory_path", mode="before")
    @classmethod
    def _strip(cls, value: object) -> object:
        """Normalize surrounding whitespace for directory path."""
        return _strip_text(value)

    @field_validator("directory_path")
    @classmethod
    def _normalize(cls, value: str) -> str:
        """Normalize root-or-relative listing scope."""
        return _normalize_directory_path(value, allow_root=True)


class CreateDirectoryRequest(BaseModel):
    """Validate one create-directory request payload."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    directory_path: str
    recursive: bool = False

    @field_validator("directory_path", mode="before")
    @classmethod
    def _strip(cls, value: object) -> object:
        """Normalize surrounding whitespace for directory path."""
        return _strip_text(value)

    @field_validator("directory_path")
    @classmethod
    def _normalize(cls, value: str) -> str:
        """Normalize one non-empty directory path."""
        return _normalize_directory_path(value)


class DeleteDirectoryRequest(BaseModel):
    """Validate one delete-directory request payload."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    directory_path: str
    recursive: bool = False
    missing_ok: bool = False
    use_trash: bool = True

    @field_validator("directory_path", mode="before")
    @classmethod
    def _strip(cls, value: object) -> object:
        """Normalize surrounding whitespace for directory path."""
        return _strip_text(value)

    @field_validator("directory_path")
    @classmethod
    def _normalize(cls, value: str) -> str:
        """Normalize one non-empty directory path."""
        return _normalize_directory_path(value)


class CreateFileRequest(BaseModel):
    """Validate one create-file request payload."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    file_path: str
    content: str = ""

    @field_validator("file_path", mode="before")
    @classmethod
    def _strip_file_path(cls, value: object) -> object:
        """Normalize surrounding whitespace for file path."""
        return _strip_text(value)

    @field_validator("content", mode="before")
    @classmethod
    def _normalize_content(cls, value: object) -> object:
        """Normalize ``None`` content to empty string."""
        if value is None:
            return ""
        return value

    @field_validator("file_path")
    @classmethod
    def _normalize_file(cls, value: str) -> str:
        """Normalize markdown file path."""
        return _normalize_file_path(value)


class GetFileRequest(BaseModel):
    """Validate one get-file request payload."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    file_path: str

    @field_validator("file_path", mode="before")
    @classmethod
    def _strip_file_path(cls, value: object) -> object:
        """Normalize surrounding whitespace for file path."""
        return _strip_text(value)

    @field_validator("file_path")
    @classmethod
    def _normalize_file(cls, value: str) -> str:
        """Normalize markdown file path."""
        return _normalize_file_path(value)


class _MutateFileRequest(BaseModel):
    """Base request for mutating one markdown file."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    file_path: str
    if_revision: str = ""
    force: bool = False

    @field_validator("file_path", mode="before")
    @classmethod
    def _strip_file_path(cls, value: object) -> object:
        """Normalize surrounding whitespace for file path."""
        return _strip_text(value)

    @field_validator("if_revision", mode="before")
    @classmethod
    def _strip_revision(cls, value: object) -> object:
        """Normalize surrounding whitespace for revision token."""
        return _strip_text(value)

    @field_validator("file_path")
    @classmethod
    def _normalize_file(cls, value: str) -> str:
        """Normalize markdown file path."""
        return _normalize_file_path(value)


class UpdateFileRequest(_MutateFileRequest):
    """Validate one full file-update request payload."""

    content: str


class AppendFileRequest(_MutateFileRequest):
    """Validate one append-file request payload."""

    content: str


class FileEditRequest(BaseModel):
    """Validate one line-range file edit operation."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    start_line: int = Field(ge=1)
    end_line: int = Field(ge=1)
    content: str

    @model_validator(mode="after")
    def _validate_bounds(self) -> "FileEditRequest":
        """Enforce inclusive line-range ordering."""
        if self.end_line < self.start_line:
            raise ValueError("end_line must be >= start_line")
        return self


class EditFileRequest(_MutateFileRequest):
    """Validate one edit-file request payload."""

    edits: tuple[FileEditRequest, ...] = Field(default_factory=tuple)

    @field_validator("edits")
    @classmethod
    def _require_edits(
        cls, value: tuple[FileEditRequest, ...]
    ) -> tuple[FileEditRequest, ...]:
        """Reject empty edit operations for explicit edit semantics."""
        if len(value) == 0:
            raise ValueError("edits must include at least one operation")
        return value


class MovePathRequest(BaseModel):
    """Validate one move-path request payload."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    source_path: str
    target_path: str
    if_revision: str = ""
    force: bool = False

    @field_validator("source_path", "target_path", "if_revision", mode="before")
    @classmethod
    def _strip_fields(cls, value: object) -> object:
        """Normalize surrounding whitespace for text path fields."""
        return _strip_text(value)

    @field_validator("source_path", "target_path")
    @classmethod
    def _normalize_paths(cls, value: str) -> str:
        """Normalize one non-empty path for move operations."""
        return normalize_vault_relative_path(value, allow_root=False)


class DeleteFileRequest(BaseModel):
    """Validate one delete-file request payload."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    file_path: str
    missing_ok: bool = False
    use_trash: bool = True
    if_revision: str = ""
    force: bool = False

    @field_validator("file_path", "if_revision", mode="before")
    @classmethod
    def _strip_fields(cls, value: object) -> object:
        """Normalize surrounding whitespace for text request fields."""
        return _strip_text(value)

    @field_validator("file_path")
    @classmethod
    def _normalize_file(cls, value: str) -> str:
        """Normalize markdown file path."""
        return _normalize_file_path(value)


class SearchFilesRequest(BaseModel):
    """Validate one search-files request payload."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    query: str = Field(min_length=1)
    directory_scope: str = ""
    limit: int = Field(default=20, gt=0)

    @field_validator("query", "directory_scope", mode="before")
    @classmethod
    def _strip_fields(cls, value: object) -> object:
        """Normalize surrounding whitespace for textual request fields."""
        return _strip_text(value)

    @field_validator("directory_scope")
    @classmethod
    def _normalize_scope(cls, value: str) -> str:
        """Normalize optional directory scope path."""
        return _normalize_directory_path(value, allow_root=True)
