"""Local content-addressed object store backed by the filesystem."""

from __future__ import annotations

import hashlib
import os
from pathlib import Path
from typing import Union
from uuid import uuid4

_ObjectPayload = Union[bytes, bytearray, memoryview, str]


class ObjectStore:
    """Content-addressed object store for durable blob storage."""

    def __init__(self, root_dir: str | Path) -> None:
        """Initialize the object store using the configured root directory."""
        self._root_dir = Path(root_dir).expanduser().resolve()

    @property
    def root_dir(self) -> Path:
        """Return the root directory for stored objects."""
        return self._root_dir

    def write(self, payload: _ObjectPayload) -> str:
        """Store a blob and return its deterministic object key."""
        data = _normalize_payload(payload)
        digest = _digest_payload(data)
        object_key = _format_object_key(digest)
        path = self._path_for_digest(digest)
        if path.exists():
            return object_key

        path.parent.mkdir(parents=True, exist_ok=True)
        tmp_path = path.parent / f".{digest}.tmp-{uuid4().hex}"
        try:
            with open(tmp_path, "wb") as handle:
                handle.write(data)
                handle.flush()
                os.fsync(handle.fileno())
            if path.exists():
                return object_key
            os.replace(tmp_path, path)
        finally:
            if tmp_path.exists():
                tmp_path.unlink(missing_ok=True)

        return object_key

    def read(self, object_key: str) -> bytes:
        """Read a stored blob by object key."""
        digest = _parse_object_key(object_key)
        path = self._path_for_digest(digest)
        return path.read_bytes()

    def delete(self, object_key: str) -> bool:
        """Delete a stored blob by object key, returning True for idempotence."""
        digest = _parse_object_key(object_key)
        path = self._path_for_digest(digest)
        if path.exists():
            path.unlink()
        return True

    def _path_for_digest(self, digest: str) -> Path:
        """Return the filesystem path for the given hex digest."""
        return self._root_dir / digest[:2] / digest[2:4] / digest


def _normalize_payload(payload: _ObjectPayload) -> bytes:
    """Normalize supported payload types into raw bytes."""
    if isinstance(payload, bytes):
        return payload
    if isinstance(payload, (bytearray, memoryview)):
        return bytes(payload)
    if isinstance(payload, str):
        return payload.encode("utf-8")
    raise TypeError("Object payload must be bytes-like or UTF-8 text.")


def _digest_payload(payload: bytes) -> str:
    """Return the hex digest for the content-addressed object payload."""
    seeded = b"b1:\0" + payload
    return hashlib.sha256(seeded).hexdigest()


def _format_object_key(digest: str) -> str:
    """Format an object key from the provided hex digest."""
    return f"b1:sha256:{digest}"


def _parse_object_key(object_key: str) -> str:
    """Validate and extract the hex digest from an object key."""
    prefix = "b1:sha256:"
    if not object_key.startswith(prefix):
        raise ValueError("Object key must start with 'b1:sha256:'.")
    digest = object_key[len(prefix) :]
    if len(digest) != 64:
        raise ValueError("Object key digest must be 64 hex characters.")
    if any(ch not in "0123456789abcdef" for ch in digest.lower()):
        raise ValueError("Object key digest must be hexadecimal.")
    return digest.lower()
