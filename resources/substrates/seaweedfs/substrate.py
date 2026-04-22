"""Transport-agnostic protocol for blob substrate operations."""

from __future__ import annotations

from typing import Protocol

from pydantic import BaseModel, ConfigDict


class BlobHealthStatus(BaseModel):
    """Blob substrate readiness payload."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    ready: bool
    detail: str


class BlobStat(BaseModel):
    """Provider-neutral metadata for one stored blob."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    key: str
    size_bytes: int
    etag: str
    content_type: str


class BlobSubstrate(Protocol):
    """Protocol for digest-keyed blob persistence operations."""

    def health(self) -> BlobHealthStatus:
        """Probe blob substrate readiness."""

    def resolve_key(self, *, digest_hex: str, extension: str) -> str:
        """Resolve one deterministic provider key for digest and extension."""

    def write_blob(self, *, digest_hex: str, extension: str, content: bytes) -> str:
        """Write one blob and return its provider key."""

    def read_blob(self, *, digest_hex: str, extension: str) -> bytes:
        """Read one blob by digest and extension."""

    def stat_blob(self, *, digest_hex: str, extension: str) -> BlobStat:
        """Return metadata for one stored blob."""

    def delete_blob(self, *, digest_hex: str, extension: str) -> bool:
        """Delete one blob and return whether an object existed."""
