"""Integration-style tests for filesystem substrate real FS semantics."""

from __future__ import annotations

from resources.substrates.filesystem import (
    FilesystemSubstrateSettings,
    LocalFilesystemBlobSubstrate,
)


def test_atomic_write_replace_and_delete_cycle(tmp_path) -> None:
    """Substrate should atomically write, read, stat, and delete one blob."""
    substrate = LocalFilesystemBlobSubstrate(
        settings=FilesystemSubstrateSettings(root_dir=str(tmp_path))
    )
    digest = "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"

    path = substrate.write_blob(digest_hex=digest, extension="bin", content=b"hello")
    assert path.exists()
    assert substrate.read_blob(digest_hex=digest, extension="bin") == b"hello"
    assert substrate.stat_blob(digest_hex=digest, extension="bin").st_size == 5
    assert substrate.delete_blob(digest_hex=digest, extension="bin") is True
