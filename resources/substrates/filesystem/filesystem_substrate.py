"""Filesystem-backed blob substrate with atomic safe-write semantics."""

from __future__ import annotations

import os
from pathlib import Path
from tempfile import NamedTemporaryFile

from resources.substrates.filesystem.config import FilesystemSubstrateSettings
from resources.substrates.filesystem.substrate import (
    FilesystemBlobSubstrate,
    FilesystemHealthStatus,
)
from resources.substrates.filesystem.validation import normalize_extension

_HEX = frozenset("0123456789abcdef")


class LocalFilesystemBlobSubstrate(FilesystemBlobSubstrate):
    """Persist/retrieve blobs on local disk using digest-derived paths."""

    def __init__(self, *, settings: FilesystemSubstrateSettings) -> None:
        self._settings = settings
        self._root = settings.root_path()

    def health(self) -> FilesystemHealthStatus:
        """Return filesystem substrate readiness for root dir access."""
        try:
            self._root.mkdir(parents=True, exist_ok=True)
            if not self._root.is_dir():
                return FilesystemHealthStatus(
                    ready=False,
                    detail=f"root path is not a directory: {self._root}",
                )
        except Exception as exc:  # noqa: BLE001
            return FilesystemHealthStatus(
                ready=False,
                detail=f"filesystem probe failed: {type(exc).__name__}",
            )
        return FilesystemHealthStatus(ready=True, detail="ok")

    def resolve_path(self, *, digest_hex: str, extension: str) -> Path:
        """Resolve the deterministic filesystem path for digest and extension."""
        digest = _normalize_digest_hex(digest_hex)
        ext = normalize_extension(value=extension)
        return self._root / digest[:2] / digest[2:4] / f"{digest}.{ext}"

    def write_blob(self, *, digest_hex: str, extension: str, content: bytes) -> Path:
        """Write one blob atomically and return the resolved final path."""
        path = self.resolve_path(digest_hex=digest_hex, extension=extension)

        if not self._root.exists():
            self._root.mkdir(parents=True, exist_ok=True)
        if not self._root.is_dir():
            raise OSError(f"filesystem substrate root is not a directory: {self._root}")
        path.parent.mkdir(parents=True, exist_ok=True)

        if path.exists():
            return path

        tmp_path: Path | None = None
        try:
            with NamedTemporaryFile(
                mode="wb",
                prefix=f".{self._settings.temp_prefix}-",
                suffix=".tmp",
                dir=path.parent,
                delete=False,
            ) as handle:
                tmp_path = Path(handle.name)
                handle.write(content)
                handle.flush()
                if self._settings.fsync_writes:
                    os.fsync(handle.fileno())

            if path.exists():
                return path
            assert tmp_path is not None
            os.replace(tmp_path, path)
            return path
        finally:
            if tmp_path is not None and tmp_path.exists():
                tmp_path.unlink(missing_ok=True)

    def read_blob(self, *, digest_hex: str, extension: str) -> bytes:
        """Read one blob by digest/extension path."""
        path = self.resolve_path(digest_hex=digest_hex, extension=extension)
        return path.read_bytes()

    def stat_blob(self, *, digest_hex: str, extension: str) -> os.stat_result:
        """Return one blob stat structure."""
        path = self.resolve_path(digest_hex=digest_hex, extension=extension)
        return path.stat()

    def delete_blob(self, *, digest_hex: str, extension: str) -> bool:
        """Delete one blob path and return whether a file existed."""
        path = self.resolve_path(digest_hex=digest_hex, extension=extension)
        if not path.exists():
            return False
        path.unlink()
        return True


def _normalize_digest_hex(value: str) -> str:
    """Validate and normalize one 64-char sha256 digest hex string."""
    normalized = value.strip().lower()
    if len(normalized) != 64:
        raise ValueError("digest_hex must contain exactly 64 hex characters")
    if any(ch not in _HEX for ch in normalized):
        raise ValueError("digest_hex must be hexadecimal")
    return normalized
