"""Domain contracts for Vault Authority Service payloads."""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum

from pydantic import BaseModel, ConfigDict


class VaultEntryType(StrEnum):
    """Vault entry type classification returned by directory and move APIs."""

    DIRECTORY = "directory"
    FILE = "file"


class VaultEntry(BaseModel):
    """One vault entry metadata object."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    path: str
    name: str
    entry_type: VaultEntryType
    size_bytes: int = 0
    created_at: datetime | None = None
    updated_at: datetime | None = None
    revision: str = ""


class VaultFileRecord(BaseModel):
    """One materialized vault file record with metadata and content."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    path: str
    content: str
    size_bytes: int = 0
    created_at: datetime | None = None
    updated_at: datetime | None = None
    revision: str = ""


class FileEdit(BaseModel):
    """One line-range edit operation for text replacement."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    start_line: int
    end_line: int
    content: str


class SearchFileMatch(BaseModel):
    """One lexical search match result from vault file search."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    path: str
    score: float
    snippets: tuple[str, ...] = ()
    updated_at: datetime | None = None
    revision: str = ""
