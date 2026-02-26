"""Transport-agnostic protocol for filesystem blob substrate operations."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Protocol
from pydantic import BaseModel, ConfigDict


class FilesystemHealthStatus(BaseModel):
    """Filesystem blob substrate readiness payload."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    ready: bool
    detail: str


class FilesystemBlobSubstrate(Protocol):
    """Protocol for digest-keyed filesystem blob persistence operations."""

    def health(self) -> FilesystemHealthStatus:
        """Probe local filesystem substrate readiness."""

    def resolve_path(self, *, digest_hex: str, extension: str) -> Path:
        """Resolve one deterministic file path for digest and extension."""

    def write_blob(self, *, digest_hex: str, extension: str, content: bytes) -> Path:
        """Write one blob atomically and return resolved final path."""

    def read_blob(self, *, digest_hex: str, extension: str) -> bytes:
        """Read one blob by digest and extension."""

    def stat_blob(self, *, digest_hex: str, extension: str) -> os.stat_result:
        """Return filesystem stat for one stored blob."""

    def delete_blob(self, *, digest_hex: str, extension: str) -> bool:
        """Delete one blob and return whether a file existed."""
