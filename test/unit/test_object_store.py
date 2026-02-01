"""Unit tests for the local object store."""

import hashlib
from concurrent.futures import ThreadPoolExecutor

import pytest

from services.object_store import ObjectStore


def _expected_key(payload: bytes) -> str:
    """Return the expected object key for the payload."""
    seeded = b"b1:\0" + payload
    digest = hashlib.sha256(seeded).hexdigest()
    return f"b1:sha256:{digest}"


def test_write_read_delete_cycle(tmp_path):
    """Ensure write/read/delete follow the expected semantics."""
    store = ObjectStore(tmp_path)
    payload = b"hello"

    key = store.write(payload)
    assert key == _expected_key(payload)
    digest = key.split(":")[-1]
    expected_path = tmp_path / digest[:2] / digest[2:4] / digest
    assert expected_path.exists()

    stored = store.read(key)
    assert stored == payload

    assert store.delete(key) is True
    assert store.delete(key) is True

    with pytest.raises(FileNotFoundError):
        store.read(key)


def test_write_is_deterministic(tmp_path):
    """Ensure duplicate writes return the same object key."""
    store = ObjectStore(tmp_path)
    payload = "same-content"

    first = store.write(payload)
    second = store.write(payload)

    assert first == second


def test_write_concurrent_is_idempotent(tmp_path):
    """Ensure concurrent writes converge on a single stored blob."""
    store = ObjectStore(tmp_path)
    payload = b"concurrent"

    with ThreadPoolExecutor(max_workers=4) as pool:
        results = list(pool.map(store.write, [payload] * 4))

    assert len(set(results)) == 1


def test_write_failure_cleans_temp_file(tmp_path, monkeypatch):
    """Ensure partial writes do not leave temp files behind."""
    store = ObjectStore(tmp_path)
    payload = b"temp-cleanup"
    digest = _expected_key(payload).split(":")[-1]

    def _raise_replace(*args, **kwargs):
        raise OSError("replace failed")

    monkeypatch.setattr("services.object_store.os.replace", _raise_replace)

    with pytest.raises(OSError, match="replace failed"):
        store.write(payload)

    tmp_matches = list((tmp_path / digest[:2] / digest[2:4]).glob(f".{digest}.tmp-*"))
    assert tmp_matches == []


def test_large_payload_roundtrip(tmp_path):
    """Ensure large payloads are stored and read back intact."""
    store = ObjectStore(tmp_path)
    payload = b"x" * (2 * 1024 * 1024)

    key = store.write(payload)
    assert key == _expected_key(payload)

    stored = store.read(key)
    assert stored == payload


def test_bytes_like_payloads(tmp_path):
    """Ensure bytes-like payloads are accepted."""
    store = ObjectStore(tmp_path)
    payload = b"bytes-like"

    key_bytes = store.write(payload)
    key_bytearray = store.write(bytearray(payload))
    key_memory = store.write(memoryview(payload))

    assert key_bytes == key_bytearray == key_memory


def test_write_fails_when_root_is_file(tmp_path):
    """Ensure invalid root paths raise an explicit error."""
    root_file = tmp_path / "not-a-dir"
    root_file.write_text("nope", encoding="utf-8")
    store = ObjectStore(root_file)

    with pytest.raises(OSError):
        store.write(b"payload")
