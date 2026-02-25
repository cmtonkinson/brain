"""Integration-style tests for filesystem adapter real FS semantics."""

from __future__ import annotations

from resources.adapters.filesystem import (
    FilesystemAdapterSettings,
    LocalFilesystemBlobAdapter,
)


def test_atomic_write_replace_and_delete_cycle(tmp_path) -> None:
    """Adapter should atomically write, read, stat, and delete one blob."""
    adapter = LocalFilesystemBlobAdapter(
        settings=FilesystemAdapterSettings(root_dir=str(tmp_path))
    )
    digest = "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"

    path = adapter.write_blob(digest_hex=digest, extension="bin", content=b"hello")
    assert path.exists()
    assert adapter.read_blob(digest_hex=digest, extension="bin") == b"hello"
    assert adapter.stat_blob(digest_hex=digest, extension="bin").st_size == 5
    assert adapter.delete_blob(digest_hex=digest, extension="bin") is True
