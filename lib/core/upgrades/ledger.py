"""Applied-state ledger: read/write/lock for ``upgrades.json``.

The ledger is the single source of truth for which upgrades have been applied
on this install. It lives outside Postgres because some upgrades may need to
run before Postgres is available, and the installer initializes it before
Postgres exists at all.
"""

from __future__ import annotations

import fcntl
import json
import os
import sys
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

LEDGER_SCHEMA_VERSION = 1
ZERO_SHA_SENTINEL = "0" * 64
DEFAULT_STATE_DIR = (
    Path(
        os.environ.get("XDG_STATE_HOME", "").strip()
        or (Path.home() / ".local" / "state")
    )
    / "brain"
)
LEDGER_FILENAME = "upgrades.json"
LOCK_FILENAME = "upgrades.lock"


class LedgerNotFoundError(RuntimeError):
    """Raised when the ledger file is expected but absent."""


class LedgerCorruptError(RuntimeError):
    """Raised when the ledger file exists but cannot be parsed."""


class LedgerLockedError(RuntimeError):
    """Raised when another process holds the ledger lock."""


@dataclass(frozen=True, slots=True)
class LedgerEntry:
    """One applied (or grandfathered) upgrade as recorded in the ledger."""

    upgrade_id: str
    slug: str
    phase: str
    applied_at: str
    duration_seconds: float
    module_sha256: str
    interactive: bool
    grandfathered: bool

    def to_json(self) -> dict[str, Any]:
        return {
            "id": self.upgrade_id,
            "slug": self.slug,
            "phase": self.phase,
            "applied_at": self.applied_at,
            "duration_seconds": self.duration_seconds,
            "module_sha256": self.module_sha256,
            "interactive": self.interactive,
            "grandfathered": self.grandfathered,
        }

    @classmethod
    def from_json(cls, data: dict[str, Any]) -> LedgerEntry:
        return cls(
            upgrade_id=str(data["id"]),
            slug=str(data["slug"]),
            phase=str(data["phase"]),
            applied_at=str(data["applied_at"]),
            duration_seconds=float(data["duration_seconds"]),
            module_sha256=str(data["module_sha256"]),
            interactive=bool(data.get("interactive", False)),
            grandfathered=bool(data.get("grandfathered", False)),
        )


@dataclass(slots=True)
class Ledger:
    """In-memory view of the on-disk ledger file."""

    schema_version: int
    installed_at: str
    applied: list[LedgerEntry] = field(default_factory=list)

    def is_applied(self, upgrade_id: str) -> bool:
        return any(entry.upgrade_id == upgrade_id for entry in self.applied)

    def get(self, upgrade_id: str) -> LedgerEntry | None:
        for entry in self.applied:
            if entry.upgrade_id == upgrade_id:
                return entry
        return None

    def to_json(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "installed_at": self.installed_at,
            "applied": [entry.to_json() for entry in self.applied],
        }


def state_dir() -> Path:
    """Resolve the Brain state directory (override via ``BRAIN_STATE_DIR``)."""
    override = os.getenv("BRAIN_STATE_DIR", "").strip()
    if override:
        return Path(override).expanduser().resolve()
    return DEFAULT_STATE_DIR


def ledger_path() -> Path:
    """Resolve the ledger path (override via ``BRAIN_UPGRADES_LEDGER``)."""
    override = os.getenv("BRAIN_UPGRADES_LEDGER", "").strip()
    if override:
        return Path(override).expanduser().resolve()
    return state_dir() / LEDGER_FILENAME


def lock_path() -> Path:
    """Resolve the ledger lockfile path. Always sits next to the ledger."""
    return ledger_path().parent / LOCK_FILENAME


def now_utc_iso() -> str:
    """Return the current time as an ISO-8601 UTC string with microseconds."""
    return datetime.now(tz=UTC).isoformat()


def read_ledger(path: Path | None = None) -> Ledger:
    """Read and parse the ledger from disk.

    Raises ``LedgerNotFoundError`` if the file is absent and
    ``LedgerCorruptError`` if it exists but cannot be parsed.
    """
    target = path if path is not None else ledger_path()
    if not target.exists():
        raise LedgerNotFoundError(f"upgrades ledger not found at {target}")
    try:
        with target.open("r", encoding="utf-8") as fh:
            data = json.load(fh)
    except json.JSONDecodeError as exc:
        raise LedgerCorruptError(
            f"ledger at {target} is not valid JSON: {exc}"
        ) from exc

    try:
        schema_version = int(data["schema_version"])
        installed_at = str(data["installed_at"])
        applied_raw = data.get("applied", [])
        applied = [LedgerEntry.from_json(entry) for entry in applied_raw]
    except (KeyError, TypeError, ValueError) as exc:
        raise LedgerCorruptError(
            f"ledger at {target} has unexpected structure: {exc}"
        ) from exc

    if schema_version != LEDGER_SCHEMA_VERSION:
        raise LedgerCorruptError(
            f"ledger at {target} has unsupported schema_version "
            f"{schema_version}; expected {LEDGER_SCHEMA_VERSION}"
        )

    return Ledger(
        schema_version=schema_version,
        installed_at=installed_at,
        applied=applied,
    )


def write_ledger(ledger: Ledger, path: Path | None = None) -> None:
    """Atomically write the ledger to disk via tempfile + ``os.replace``."""
    target = path if path is not None else ledger_path()
    target.parent.mkdir(parents=True, exist_ok=True)
    tmp = target.with_name(target.name + ".tmp")
    payload = json.dumps(ledger.to_json(), indent=2, sort_keys=False) + "\n"
    with tmp.open("w", encoding="utf-8") as fh:
        fh.write(payload)
        fh.flush()
        os.fsync(fh.fileno())
    os.replace(tmp, target)


def append_entry(entry: LedgerEntry, path: Path | None = None) -> None:
    """Append an entry to the on-disk ledger atomically.

    Caller MUST hold the lock (see ``ledger_lock``). The atomic write is for
    crash safety; the lock is for concurrent-process safety.
    """
    target = path if path is not None else ledger_path()
    ledger = read_ledger(target)
    ledger.applied.append(entry)
    write_ledger(ledger, target)


@contextmanager
def ledger_lock(path: Path | None = None):
    """Acquire an exclusive non-blocking flock on the ledger lockfile.

    Raises ``LedgerLockedError`` immediately if the lock is held elsewhere.
    The lockfile is created on demand and never cleaned up (cheap, harmless).
    """
    target = path if path is not None else lock_path()
    target.parent.mkdir(parents=True, exist_ok=True)
    fh = target.open("a+", encoding="utf-8")
    try:
        try:
            fcntl.flock(fh.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            holder = _read_lock_holder(target)
            raise LedgerLockedError(
                f"another upgrade run is in progress (lock held at {target}"
                + (f", pid {holder}" if holder else "")
                + "); aborting"
            ) from exc
        try:
            fh.seek(0)
            fh.truncate()
            fh.write(str(os.getpid()))
            fh.flush()
            yield
        finally:
            fcntl.flock(fh.fileno(), fcntl.LOCK_UN)
    finally:
        fh.close()


def _read_lock_holder(target: Path) -> str | None:
    """Best-effort read of the lockfile contents (the holder pid)."""
    try:
        with target.open("r", encoding="utf-8") as fh:
            value = fh.read().strip()
    except OSError:
        return None
    return value or None


def exit_temp_fail(message: str) -> None:
    """Print a clear message and exit 75 (``EX_TEMPFAIL``)."""
    print(message, file=sys.stderr)
    sys.exit(75)
