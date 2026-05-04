"""Apply / dry-run / list / boot-guard orchestration."""

from __future__ import annotations

import logging
import os
import sys
from dataclasses import dataclass
from pathlib import Path

from lib.core.upgrades.discovery import (
    UpgradeDescriptor,
    discover_upgrades,
)
from lib.core.upgrades.execution import (
    InteractiveWithoutTtyError,
    compute_module_sha256,
    execute_upgrade,
)
from lib.core.upgrades.ledger import (
    ZERO_SHA_SENTINEL,
    Ledger,
    LedgerEntry,
    LedgerNotFoundError,
    append_entry,
    ledger_lock,
    ledger_path,
    now_utc_iso,
    read_ledger,
)

_LOGGER = logging.getLogger(__name__)

DEFAULT_CONFIG_DIR = (
    Path(os.environ.get("XDG_CONFIG_HOME", "").strip() or (Path.home() / ".config"))
    / "brain"
)
DEFAULT_CACHE_DIR = (
    Path(os.environ.get("XDG_CACHE_HOME", "").strip() or (Path.home() / ".cache"))
    / "brain"
)
EXIT_LEDGER_PENDING = 78


class UpgradesPendingError(RuntimeError):
    """Raised by boot guard when pre-services upgrades are pending."""


class LedgerMissingError(RuntimeError):
    """Raised when a runner action requires a ledger but none exists."""


@dataclass(frozen=True, slots=True)
class PendingSet:
    """Pending breakdown for one runner pass."""

    pending: tuple[UpgradeDescriptor, ...]
    pre_services: tuple[UpgradeDescriptor, ...]
    post_services: tuple[UpgradeDescriptor, ...]


def upgrades_root(repo_root: Path) -> Path:
    """Resolve the upgrades directory (override via ``BRAIN_UPGRADES_DIR``)."""
    override = os.getenv("BRAIN_UPGRADES_DIR", "").strip()
    if override:
        return Path(override).expanduser().resolve()
    return repo_root / "upgrades"


def config_dir() -> Path:
    """Resolve the Brain config directory (override via ``BRAIN_CONFIG_DIR``)."""
    override = os.getenv("BRAIN_CONFIG_DIR", "").strip()
    if override:
        return Path(override).expanduser().resolve()
    return DEFAULT_CONFIG_DIR


def cache_dir() -> Path:
    """Resolve the Brain cache directory (override via ``BRAIN_CACHE_DIR``)."""
    override = os.getenv("BRAIN_CACHE_DIR", "").strip()
    if override:
        return Path(override).expanduser().resolve()
    return DEFAULT_CACHE_DIR


def log_root(repo_root: Path) -> Path:
    """Resolve the logs/upgrades root."""
    return repo_root / "logs" / "upgrades"


def compute_pending(
    *,
    repo_root: Path,
    ledger: Ledger,
) -> PendingSet:
    """Return upgrades present on disk but not in the ledger.

    Also emits WARNING-level log records for any *already-applied*
    upgrade whose ``upgrade.py`` SHA-256 on disk no longer matches the
    ledger entry. Drift is not fatal — once an upgrade is applied, the
    operator's environment reflects the version that ran, and editing
    the source after the fact is sometimes legitimate (typo fix to a
    docstring, etc.). It is, however, always worth surfacing so the
    operator can decide.
    """
    descriptors = discover_upgrades(upgrades_root(repo_root))
    _assert_no_slug_drift(descriptors=descriptors, ledger=ledger)
    _warn_module_sha_drift(descriptors=descriptors, ledger=ledger)
    pending = tuple(d for d in descriptors if not ledger.is_applied(d.upgrade_id))
    pre = tuple(d for d in pending if d.phase == "pre-services")
    post = tuple(d for d in pending if d.phase == "post-services")
    return PendingSet(pending=pending, pre_services=pre, post_services=post)


def apply_pending(*, repo_root: Path) -> int:
    """Apply all pending upgrades in lex order. Return the count applied."""
    try:
        ledger = read_ledger()
    except LedgerNotFoundError as exc:
        raise LedgerMissingError(
            f"upgrades ledger missing at {ledger_path()}; run `make install`"
        ) from exc

    pending_set = compute_pending(repo_root=repo_root, ledger=ledger)
    if not pending_set.pending:
        print("No pending upgrades.")
        return 0

    applied_count = 0
    with ledger_lock():
        # Re-read after acquiring the lock to defeat TOCTOU with a sibling run.
        ledger = read_ledger()
        for descriptor in pending_set.pending:
            if ledger.is_applied(descriptor.upgrade_id):
                continue
            print(
                f"applying [{descriptor.phase}] {descriptor.upgrade_id} "
                f"{descriptor.slug} — {descriptor.description}",
                flush=True,
            )
            try:
                result = execute_upgrade(
                    descriptor,
                    repo_root=repo_root,
                    config_dir=config_dir(),
                    state_dir=ledger_path().parent,
                    cache_dir=cache_dir(),
                    log_root=log_root(repo_root),
                )
            except InteractiveWithoutTtyError as exc:
                print(f"refusing to run interactive upgrade: {exc}", file=sys.stderr)
                return applied_count
            if result.exit_code != 0 or result.timed_out:
                detail = (
                    "timed out" if result.timed_out else f"exit code {result.exit_code}"
                )
                print(
                    f"upgrade {descriptor.upgrade_id} {descriptor.slug} failed "
                    f"({detail}); aborting run",
                    file=sys.stderr,
                )
                return applied_count
            entry = LedgerEntry(
                upgrade_id=descriptor.upgrade_id,
                slug=descriptor.slug,
                phase=descriptor.phase,
                applied_at=now_utc_iso(),
                duration_seconds=round(result.duration_seconds, 6),
                module_sha256=result.module_sha256,
                interactive=descriptor.interactive,
                grandfathered=False,
            )
            append_entry(entry)
            ledger = read_ledger()
            applied_count += 1

    print(f"applied {applied_count} upgrade(s).")
    return applied_count


def list_pending(*, repo_root: Path) -> tuple[UpgradeDescriptor, ...]:
    """Return pending upgrades; raise if the ledger is missing."""
    try:
        ledger = read_ledger()
    except LedgerNotFoundError as exc:
        raise LedgerMissingError(
            f"upgrades ledger missing at {ledger_path()}; run `make install`"
        ) from exc
    return compute_pending(repo_root=repo_root, ledger=ledger).pending


def render_dryrun(*, repo_root: Path) -> str:
    """Format the dry-run listing as a printable string."""
    pending = list_pending(repo_root=repo_root)
    if not pending:
        return "No pending upgrades.\n"
    lines = [f"Pending upgrades ({len(pending)}):", ""]
    for d in pending:
        lines.append(f"  [{d.phase}]  {d.upgrade_id}  {d.slug}")
        lines.append(f"           {d.description}")
        lines.append(
            f"           {d.upgrade_py.relative_to(repo_root) if d.upgrade_py.is_absolute() and _is_subpath(d.upgrade_py, repo_root) else d.upgrade_py}"
        )
        meta = f"timeout={d.timeout_seconds}s"
        if d.interactive:
            meta += "  interactive=true"
        lines.append(f"           {meta}")
        lines.append("")
    lines.append("Run 'make upgrade' to apply.")
    return "\n".join(lines) + "\n"


def assert_pre_services_clean(*, repo_root: Path) -> None:
    """Boot-guard: refuse to proceed if pre-services upgrades are pending.

    Treats a missing ledger the same as "pending": Core cannot boot without
    a configured install. Raises ``UpgradesPendingError``.
    """
    try:
        ledger = read_ledger()
    except LedgerNotFoundError as exc:
        raise UpgradesPendingError(
            "upgrades ledger missing; run `make install` before starting Core"
        ) from exc
    pending_set = compute_pending(repo_root=repo_root, ledger=ledger)
    if pending_set.pre_services:
        ids = ", ".join(d.upgrade_id for d in pending_set.pre_services)
        raise UpgradesPendingError(
            f"pre-services upgrades pending ({ids}); run `make upgrade` "
            "before starting Core"
        )


def warn_post_services_pending(*, repo_root: Path) -> None:
    """Boot-guard: log a warning if post-services upgrades are pending."""
    try:
        ledger = read_ledger()
    except LedgerNotFoundError:
        return
    pending_set = compute_pending(repo_root=repo_root, ledger=ledger)
    if pending_set.post_services:
        ids = ", ".join(d.upgrade_id for d in pending_set.post_services)
        logging.getLogger().warning(
            "post-services upgrades pending; run `make upgrade` after boot",
            extra={"pending_upgrade_ids": ids},
        )


def _assert_no_slug_drift(
    *, descriptors: tuple[UpgradeDescriptor, ...], ledger: Ledger
) -> None:
    """Reject installs where an applied upgrade's slug has changed on disk."""
    descriptor_by_id = {d.upgrade_id: d for d in descriptors}
    for entry in ledger.applied:
        on_disk = descriptor_by_id.get(entry.upgrade_id)
        if on_disk is None:
            continue
        if on_disk.slug != entry.slug:
            from lib.core.upgrades.discovery import DiscoveryError

            raise DiscoveryError(
                f"slug drift for upgrade {entry.upgrade_id}: ledger has "
                f"'{entry.slug}', disk has '{on_disk.slug}'"
            )


def _warn_module_sha_drift(
    *, descriptors: tuple[UpgradeDescriptor, ...], ledger: Ledger
) -> None:
    """Warn when an applied upgrade's ``upgrade.py`` has been edited on disk.

    Skips grandfathered entries (their ``module_sha256`` is the all-zeros
    sentinel — no prior execution actually hashed the file) and entries
    whose directory has been removed from disk (covered separately by
    operator hygiene; not this function's job to flag).
    """
    descriptor_by_id = {d.upgrade_id: d for d in descriptors}
    for entry in ledger.applied:
        if entry.module_sha256 == ZERO_SHA_SENTINEL:
            continue
        on_disk = descriptor_by_id.get(entry.upgrade_id)
        if on_disk is None:
            continue
        try:
            current_sha = compute_module_sha256(on_disk.upgrade_py)
        except OSError:
            # Can't read the file; nothing useful to say. Skip silently.
            continue
        if current_sha != entry.module_sha256:
            _LOGGER.warning(
                "module sha drift for applied upgrade %s (%s): ledger "
                "recorded %s, disk now %s",
                entry.upgrade_id,
                entry.slug,
                entry.module_sha256,
                current_sha,
            )


def _is_subpath(child: Path, parent: Path) -> bool:
    try:
        child.relative_to(parent)
    except ValueError:
        return False
    return True
