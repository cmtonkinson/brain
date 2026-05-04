"""Grandfather-writer: initialize the upgrade ledger on fresh installs.

The installer enumerates every upgrade currently present in the repo's
``upgrades/`` tree at install time and records each one as
``grandfathered: true`` in the ledger. Subsequent ``make upgrade`` runs
therefore consider those upgrades already applied — they reflect changes the
operator's fresh checkout already incorporates via current
``config/*.yaml.sample`` files.
"""

from __future__ import annotations

from pathlib import Path

from lib.core.upgrades.discovery import UpgradeDescriptor, discover_upgrades
from lib.core.upgrades.ledger import (
    LEDGER_SCHEMA_VERSION,
    ZERO_SHA_SENTINEL,
    Ledger,
    LedgerEntry,
    ledger_path,
    now_utc_iso,
    write_ledger,
)


class LedgerAlreadyExistsError(RuntimeError):
    """Raised when initialization is attempted but a ledger already exists."""


def write_grandfathered_ledger(
    *,
    upgrades_root: Path,
    ledger_target: Path | None = None,
    installed_at: str | None = None,
) -> Ledger:
    """Initialize the ledger with one grandfathered entry per current upgrade.

    Refuses to overwrite an existing ledger. Returns the in-memory ``Ledger``
    that was just written.
    """
    target = ledger_target if ledger_target is not None else ledger_path()
    if target.exists():
        raise LedgerAlreadyExistsError(
            f"upgrades ledger already exists at {target}; refusing to overwrite"
        )

    descriptors = discover_upgrades(upgrades_root)
    timestamp = installed_at or now_utc_iso()

    ledger = Ledger(
        schema_version=LEDGER_SCHEMA_VERSION,
        installed_at=timestamp,
        applied=[_grandfathered_entry(d, timestamp) for d in descriptors],
    )
    write_ledger(ledger, target)
    return ledger


def _grandfathered_entry(
    descriptor: UpgradeDescriptor, installed_at: str
) -> LedgerEntry:
    """Produce a sentinel ledger entry for one not-actually-executed upgrade."""
    return LedgerEntry(
        upgrade_id=descriptor.upgrade_id,
        slug=descriptor.slug,
        phase=descriptor.phase,
        applied_at=installed_at,
        duration_seconds=0.0,
        module_sha256=ZERO_SHA_SENTINEL,
        interactive=descriptor.interactive,
        grandfathered=True,
    )
