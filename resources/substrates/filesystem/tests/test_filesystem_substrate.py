"""Unit tests for local filesystem blob substrate behavior."""

from __future__ import annotations

from pathlib import Path

import pytest

import resources.substrates.filesystem.filesystem_substrate as filesystem_substrate_module
from resources.substrates.filesystem import (
    FilesystemSubstrateSettings,
    LocalFilesystemBlobSubstrate,
)

_DIGEST = "abcdef0123456789abcdef0123456789abcdef0123456789abcdef0123456789"


def _substrate(tmp_path: Path) -> LocalFilesystemBlobSubstrate:
    """Create one substrate rooted in test temp directory."""
    settings = FilesystemSubstrateSettings(root_dir=str(tmp_path))
    return LocalFilesystemBlobSubstrate(settings=settings)


def test_resolve_path_uses_digest_fanout_and_extension(tmp_path: Path) -> None:
    """Substrate path layout should shard by digest prefix and include extension."""
    substrate = _substrate(tmp_path)

    path = substrate.resolve_path(digest_hex=_DIGEST, extension="ext")

    assert path == tmp_path / "ab" / "cd" / f"{_DIGEST}.ext"


def test_write_read_delete_cycle(tmp_path: Path) -> None:
    """Write, read, and delete should roundtrip one blob cleanly."""
    substrate = _substrate(tmp_path)

    substrate.write_blob(digest_hex=_DIGEST, extension="bin", content=b"hello")
    assert substrate.read_blob(digest_hex=_DIGEST, extension="bin") == b"hello"
    assert substrate.delete_blob(digest_hex=_DIGEST, extension="bin") is True
    assert substrate.delete_blob(digest_hex=_DIGEST, extension="bin") is False


def test_write_is_idempotent_when_target_exists(tmp_path: Path) -> None:
    """Second write to existing digest path should be no-op success."""
    substrate = _substrate(tmp_path)

    first = substrate.write_blob(digest_hex=_DIGEST, extension="bin", content=b"same")
    second = substrate.write_blob(digest_hex=_DIGEST, extension="bin", content=b"same")

    assert first == second
    assert first.read_bytes() == b"same"


def test_write_failure_cleans_temp_files(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Temp files should be cleaned even when atomic replace fails."""
    substrate = _substrate(tmp_path)

    def _raise_replace(*args: object, **kwargs: object) -> object:
        del args, kwargs
        raise OSError("replace failed")

    monkeypatch.setattr(filesystem_substrate_module.os, "replace", _raise_replace)

    with pytest.raises(OSError, match="replace failed"):
        substrate.write_blob(digest_hex=_DIGEST, extension="bin", content=b"payload")

    fanout_dir = tmp_path / "ab" / "cd"
    tmp_files = list(fanout_dir.glob(".blobtmp-*.tmp"))
    assert tmp_files == []


def test_write_fails_when_root_is_file(tmp_path: Path) -> None:
    """Root path configured as a file must raise explicit OS error."""
    root_file = tmp_path / "root-file"
    root_file.write_text("not-a-dir", encoding="utf-8")
    substrate = LocalFilesystemBlobSubstrate(
        settings=FilesystemSubstrateSettings(root_dir=str(root_file))
    )

    with pytest.raises(OSError, match="not a directory"):
        substrate.write_blob(digest_hex=_DIGEST, extension="bin", content=b"payload")


def test_stat_blob_returns_filesystem_metadata(tmp_path: Path) -> None:
    """Stat should return metadata for an existing persisted blob path."""
    substrate = _substrate(tmp_path)
    path = substrate.write_blob(digest_hex=_DIGEST, extension="bin", content=b"payload")

    stat = substrate.stat_blob(digest_hex=_DIGEST, extension="bin")

    assert stat.st_size == 7
    assert stat.st_ino == path.stat().st_ino


def test_invalid_digest_hex_is_rejected() -> None:
    """Digest must be lowercase hex with exact sha256 length."""
    settings = FilesystemSubstrateSettings(root_dir="./var/blobs")
    substrate = LocalFilesystemBlobSubstrate(settings=settings)

    with pytest.raises(ValueError, match="exactly 64 hex characters"):
        substrate.resolve_path(digest_hex="abc123", extension="bin")

    with pytest.raises(ValueError, match="must be hexadecimal"):
        substrate.resolve_path(digest_hex="g" * 64, extension="bin")
