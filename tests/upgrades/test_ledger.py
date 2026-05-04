"""Ledger primitives: read/write atomicity, lock, structure validation."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from pathlib import Path

import pytest

from lib.core.upgrades.ledger import (
    LEDGER_SCHEMA_VERSION,
    Ledger,
    LedgerCorruptError,
    LedgerEntry,
    LedgerLockedError,
    LedgerNotFoundError,
    append_entry,
    ledger_lock,
    ledger_path,
    now_utc_iso,
    read_ledger,
    write_ledger,
)


def _empty_ledger() -> Ledger:
    return Ledger(
        schema_version=LEDGER_SCHEMA_VERSION,
        installed_at=now_utc_iso(),
        applied=[],
    )


def _entry(upgrade_id: str, slug: str, *, grandfathered: bool = False) -> LedgerEntry:
    return LedgerEntry(
        upgrade_id=upgrade_id,
        slug=slug,
        phase="post-services",
        applied_at=now_utc_iso(),
        duration_seconds=0.5,
        module_sha256="a" * 64,
        interactive=False,
        grandfathered=grandfathered,
    )


def test_read_missing_ledger_raises(isolated_state_env):
    with pytest.raises(LedgerNotFoundError):
        read_ledger()


def test_write_then_read_roundtrip(isolated_state_env):
    original = _empty_ledger()
    original.applied.append(_entry("20260505_0001", "alpha"))

    write_ledger(original)
    loaded = read_ledger()

    assert loaded.schema_version == LEDGER_SCHEMA_VERSION
    assert loaded.installed_at == original.installed_at
    assert len(loaded.applied) == 1
    assert loaded.applied[0].upgrade_id == "20260505_0001"
    assert loaded.applied[0].slug == "alpha"


def test_write_is_atomic_via_replace(isolated_state_env, monkeypatch):
    write_ledger(_empty_ledger())
    target = ledger_path()
    target_size_before = target.stat().st_size

    real_replace = os.replace

    def boom(src, dst, *args, **kwargs):
        raise RuntimeError("simulated crash mid-replace")

    monkeypatch.setattr("lib.core.upgrades.ledger.os.replace", boom)

    second = _empty_ledger()
    second.applied.append(_entry("20260601_0001", "beta"))
    with pytest.raises(RuntimeError):
        write_ledger(second)

    monkeypatch.setattr("lib.core.upgrades.ledger.os.replace", real_replace)

    # Original file is untouched; tmp must NOT have replaced it.
    assert target.stat().st_size == target_size_before
    assert read_ledger().applied == []


def test_corrupt_ledger_raises_helpful_error(isolated_state_env):
    target = ledger_path()
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text("not json{{")

    with pytest.raises(LedgerCorruptError, match="not valid JSON"):
        read_ledger()


def test_unsupported_schema_version_raises(isolated_state_env):
    target = ledger_path()
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(
        json.dumps(
            {
                "schema_version": 99,
                "installed_at": now_utc_iso(),
                "applied": [],
            }
        )
    )

    with pytest.raises(LedgerCorruptError, match="schema_version"):
        read_ledger()


def test_append_entry_persists_and_preserves_existing(isolated_state_env):
    write_ledger(_empty_ledger())
    append_entry(_entry("20260505_0001", "alpha"))
    append_entry(_entry("20260601_0001", "beta"))

    loaded = read_ledger()

    assert [e.upgrade_id for e in loaded.applied] == [
        "20260505_0001",
        "20260601_0001",
    ]


def test_lock_blocks_concurrent_acquisition(isolated_state_env):
    write_ledger(_empty_ledger())

    with ledger_lock():
        with pytest.raises(LedgerLockedError):
            with ledger_lock():
                pass


def test_lock_released_after_context_exit(isolated_state_env):
    write_ledger(_empty_ledger())

    with ledger_lock():
        pass

    # Should now acquire cleanly.
    with ledger_lock():
        pass


def test_lock_blocks_other_process(isolated_state_env, tmp_path):
    write_ledger(_empty_ledger())
    state_dir = isolated_state_env["state_dir"]
    signal_file = tmp_path / "lock_signal"
    signal_file.write_text("waiting")

    holder_script = tmp_path / "holder.py"
    holder_script.write_text(
        f"""
import os
import sys
import time
from pathlib import Path

os.environ['BRAIN_STATE_DIR'] = {str(state_dir)!r}
os.environ.pop('BRAIN_UPGRADES_LEDGER', None)
sys.path.insert(0, {str(Path(__file__).resolve().parents[2])!r})

from lib.core.upgrades.ledger import ledger_lock

signal_path = Path({str(signal_file)!r})
with ledger_lock():
    signal_path.write_text('acquired')
    deadline = time.monotonic() + 10.0
    while time.monotonic() < deadline:
        if signal_path.read_text() == 'release':
            sys.exit(0)
        time.sleep(0.05)
sys.exit(1)
"""
    )
    proc = subprocess.Popen([sys.executable, str(holder_script)])
    try:
        deadline = time.monotonic() + 5.0
        while time.monotonic() < deadline:
            if signal_file.read_text() == "acquired":
                break
            time.sleep(0.05)
        assert signal_file.read_text() == "acquired"

        with pytest.raises(LedgerLockedError):
            with ledger_lock():
                pass
    finally:
        signal_file.write_text("release")
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait()


def test_grandfathered_round_trip(isolated_state_env):
    ledger = _empty_ledger()
    ledger.applied.append(_entry("20260505_0001", "alpha", grandfathered=True))
    write_ledger(ledger)

    loaded = read_ledger()

    assert loaded.applied[0].grandfathered is True
