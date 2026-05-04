"""Subcommand dispatcher for ``bin/upgrade``."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from lib.core.upgrades.discovery import DiscoveryError, discover_upgrades
from lib.core.upgrades.ledger import (
    LedgerLockedError,
    LedgerNotFoundError,
    read_ledger,
)
from lib.core.upgrades.runner import (
    LedgerMissingError,
    apply_pending,
    compute_pending,
    list_pending,
    render_dryrun,
    upgrades_root,
)
from lib.core.upgrades.scaffold import ScaffoldError, scaffold_upgrade

EXIT_OK = 0
EXIT_GENERIC_FAILURE = 1
EXIT_USAGE = 2
EXIT_LEDGER_MISSING = 78
EXIT_TEMP_FAIL = 75


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)
    repo_root = _resolve_repo_root()

    handlers = {
        "apply": _cmd_apply,
        "dry-run": _cmd_dry_run,
        "list": _cmd_list,
        "new": _cmd_new,
        "status": _cmd_status,
    }
    handler = handlers.get(args.subcommand)
    if handler is None:
        parser.print_help(file=sys.stderr)
        return EXIT_USAGE
    return handler(args=args, repo_root=repo_root)


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="upgrade",
        description="Apply, list, or scaffold Brain non-SQL upgrades.",
    )
    sub = parser.add_subparsers(dest="subcommand", required=True)

    sub.add_parser("apply", help="Apply pending upgrades in lex order.")
    sub.add_parser("dry-run", help="Show what would run, in order, without running.")

    list_p = sub.add_parser("list", help="Listing of all and pending upgrades.")
    list_p.add_argument("--json", action="store_true", help="Emit JSON.")
    list_p.add_argument(
        "--pending-only", action="store_true", help="Show only pending upgrades."
    )

    new_p = sub.add_parser("new", help="Scaffold a new upgrade directory.")
    new_p.add_argument("--name", required=True, help="snake_case upgrade slug.")

    sub.add_parser("status", help="One-line summary of applied vs pending.")

    return parser


def _resolve_repo_root() -> Path:
    """Return the repo root by walking up from this file."""
    return Path(__file__).resolve().parents[3]


def _cmd_apply(*, args: argparse.Namespace, repo_root: Path) -> int:
    try:
        expected = len(list_pending(repo_root=repo_root))
    except LedgerMissingError as exc:
        print(str(exc), file=sys.stderr)
        return EXIT_LEDGER_MISSING
    except DiscoveryError as exc:
        print(f"discovery error: {exc}", file=sys.stderr)
        return EXIT_GENERIC_FAILURE

    try:
        applied = apply_pending(repo_root=repo_root)
    except LedgerLockedError as exc:
        print(str(exc), file=sys.stderr)
        return EXIT_TEMP_FAIL
    except DiscoveryError as exc:
        print(f"discovery error: {exc}", file=sys.stderr)
        return EXIT_GENERIC_FAILURE

    if applied < expected:
        return EXIT_GENERIC_FAILURE
    return EXIT_OK


def _cmd_dry_run(*, args: argparse.Namespace, repo_root: Path) -> int:
    try:
        text = render_dryrun(repo_root=repo_root)
    except LedgerMissingError as exc:
        print(str(exc), file=sys.stderr)
        return EXIT_LEDGER_MISSING
    except DiscoveryError as exc:
        print(f"discovery error: {exc}", file=sys.stderr)
        return EXIT_GENERIC_FAILURE
    print(text, end="")
    return EXIT_OK


def _cmd_list(*, args: argparse.Namespace, repo_root: Path) -> int:
    try:
        ledger = read_ledger()
    except LedgerNotFoundError as exc:
        print(str(exc), file=sys.stderr)
        return EXIT_LEDGER_MISSING
    try:
        descriptors = discover_upgrades(upgrades_root(repo_root))
        pending_set = compute_pending(repo_root=repo_root, ledger=ledger)
    except DiscoveryError as exc:
        print(f"discovery error: {exc}", file=sys.stderr)
        return EXIT_GENERIC_FAILURE

    pending_ids = {d.upgrade_id for d in pending_set.pending}
    rows = []
    for d in descriptors:
        applied_entry = ledger.get(d.upgrade_id)
        rows.append(
            {
                "id": d.upgrade_id,
                "slug": d.slug,
                "phase": d.phase,
                "interactive": d.interactive,
                "timeout_seconds": d.timeout_seconds,
                "description": d.description,
                "status": "pending" if d.upgrade_id in pending_ids else "applied",
                "grandfathered": (
                    applied_entry.grandfathered if applied_entry else False
                ),
                "applied_at": applied_entry.applied_at if applied_entry else None,
            }
        )
    if args.pending_only:
        rows = [r for r in rows if r["status"] == "pending"]

    if args.json:
        print(json.dumps(rows, indent=2))
    else:
        for r in rows:
            tag = r["status"].upper()
            extra = " (grandfathered)" if r["grandfathered"] else ""
            print(
                f"{tag:<8} [{r['phase']}] {r['id']} {r['slug']}{extra} — {r['description']}"
            )
    return EXIT_OK


def _cmd_new(*, args: argparse.Namespace, repo_root: Path) -> int:
    try:
        result = scaffold_upgrade(
            name=args.name,
            upgrades_root=upgrades_root(repo_root),
        )
    except ScaffoldError as exc:
        print(str(exc), file=sys.stderr)
        return EXIT_USAGE
    print("Created:")
    print(f"  {result.upgrade_py}")
    print(f"  {result.test_upgrade_py}")
    return EXIT_OK


def _cmd_status(*, args: argparse.Namespace, repo_root: Path) -> int:
    try:
        ledger = read_ledger()
    except LedgerNotFoundError as exc:
        print(str(exc), file=sys.stderr)
        return EXIT_LEDGER_MISSING
    try:
        pending_set = compute_pending(repo_root=repo_root, ledger=ledger)
    except DiscoveryError as exc:
        print(f"discovery error: {exc}", file=sys.stderr)
        return EXIT_GENERIC_FAILURE

    applied = len(ledger.applied)
    pending = len(pending_set.pending)
    pre = len(pending_set.pre_services)
    post = len(pending_set.post_services)
    print(
        f"{applied} applied, {pending} pending "
        f"({pre} pre-services pending, {post} post-services pending)"
    )
    return EXIT_OK


if __name__ == "__main__":
    sys.exit(main())
