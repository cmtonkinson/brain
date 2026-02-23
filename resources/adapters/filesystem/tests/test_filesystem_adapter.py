"""Unit tests for local filesystem blob adapter behavior."""

from __future__ import annotations

from pathlib import Path

import pytest

import resources.adapters.filesystem.adapter as filesystem_adapter_module
from resources.adapters.filesystem import (
    FilesystemAdapterSettings,
    LocalFilesystemBlobAdapter,
)

_DIGEST = "abcdef0123456789abcdef0123456789abcdef0123456789abcdef0123456789"


def _adapter(tmp_path: Path) -> LocalFilesystemBlobAdapter:
    """Create one adapter rooted in test temp directory."""
    settings = FilesystemAdapterSettings(root_dir=str(tmp_path))
    return LocalFilesystemBlobAdapter(settings=settings)


def test_resolve_path_uses_digest_fanout_and_extension(tmp_path: Path) -> None:
    """Adapter path layout should shard by digest prefix and include extension."""
    adapter = _adapter(tmp_path)

    path = adapter.resolve_path(digest_hex=_DIGEST, extension="ext")

    assert path == tmp_path / "ab" / "cd" / f"{_DIGEST}.ext"


def test_write_read_delete_cycle(tmp_path: Path) -> None:
    """Write, read, and delete should roundtrip one blob cleanly."""
    adapter = _adapter(tmp_path)

    adapter.write_blob(digest_hex=_DIGEST, extension="bin", content=b"hello")
    assert adapter.read_blob(digest_hex=_DIGEST, extension="bin") == b"hello"
    assert adapter.delete_blob(digest_hex=_DIGEST, extension="bin") is True
    assert adapter.delete_blob(digest_hex=_DIGEST, extension="bin") is False


def test_write_is_idempotent_when_target_exists(tmp_path: Path) -> None:
    """Second write to existing digest path should be no-op success."""
    adapter = _adapter(tmp_path)

    first = adapter.write_blob(digest_hex=_DIGEST, extension="bin", content=b"same")
    second = adapter.write_blob(digest_hex=_DIGEST, extension="bin", content=b"same")

    assert first == second
    assert first.read_bytes() == b"same"


def test_write_failure_cleans_temp_files(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Temp files should be cleaned even when atomic replace fails."""
    adapter = _adapter(tmp_path)

    def _raise_replace(*args: object, **kwargs: object) -> object:
        del args, kwargs
        raise OSError("replace failed")

    monkeypatch.setattr(filesystem_adapter_module.os, "replace", _raise_replace)

    with pytest.raises(OSError, match="replace failed"):
        adapter.write_blob(digest_hex=_DIGEST, extension="bin", content=b"payload")

    fanout_dir = tmp_path / "ab" / "cd"
    tmp_files = list(fanout_dir.glob(".blobtmp-*.tmp"))
    assert tmp_files == []


def test_write_fails_when_root_is_file(tmp_path: Path) -> None:
    """Root path configured as a file must raise explicit OS error."""
    root_file = tmp_path / "root-file"
    root_file.write_text("not-a-dir", encoding="utf-8")
    adapter = LocalFilesystemBlobAdapter(
        settings=FilesystemAdapterSettings(root_dir=str(root_file))
    )

    with pytest.raises(OSError, match="not a directory"):
        adapter.write_blob(digest_hex=_DIGEST, extension="bin", content=b"payload")


def test_stat_blob_returns_filesystem_metadata(tmp_path: Path) -> None:
    """Stat should return metadata for an existing persisted blob path."""
    adapter = _adapter(tmp_path)
    path = adapter.write_blob(digest_hex=_DIGEST, extension="bin", content=b"payload")

    stat = adapter.stat_blob(digest_hex=_DIGEST, extension="bin")

    assert stat.st_size == 7
    assert stat.st_ino == path.stat().st_ino


def test_invalid_digest_hex_is_rejected() -> None:
    """Digest must be lowercase hex with exact sha256 length."""
    settings = FilesystemAdapterSettings(root_dir="./var/blobs")
    adapter = LocalFilesystemBlobAdapter(settings=settings)

    with pytest.raises(ValueError, match="exactly 64 hex characters"):
        adapter.resolve_path(digest_hex="abc123", extension="bin")

    with pytest.raises(ValueError, match="must be hexadecimal"):
        adapter.resolve_path(digest_hex="g" * 64, extension="bin")
