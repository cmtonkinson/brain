# Upgrades
Forward-only host-side state mutations that Alembic can't express. Edit user
YAML, reset caches, drop and rebuild Qdrant collections, repair Valkey keys
— anything that has to happen on the operator's machine without changing
per-service SQL schema.

Per-service Alembic migrations are unaffected; they continue to live under
`services/<plane>/<service>/migrations/` and run automatically at Core boot.

------------------------------------------------------------------------
## Concepts
An *upgrade* is one ordered directory under `upgrades/`. Each runs at most
once per install (unless re-applied manually after operator intervention).
The on-disk identity is the directory name:
`YYYYMMDD_NNNN_<snake_case_slug>`. Lexicographic sort = total order.

Each upgrade has a *phase*:
* `pre-services` — runs before the Brain stack boots. Touches host-side
  state only (configs, dotfiles, caches). Cannot assume Postgres / Valkey /
  Qdrant / SeaweedFS are reachable.
* `post-services` — runs after `make up`. May connect to any substrate.

The runner does not enforce idempotency or offer a rollback path. A failed
upgrade is *not* recorded in the ledger; the operator fixes the world (or
the upgrade) and re-runs `make upgrade`.

------------------------------------------------------------------------
## Operator Workflow
Routine update flow:
```sh
git pull
make upgrade-dryrun   # see what's pending
make upgrade          # apply
make up               # start the stack
```

`make install` is the *installer*, not part of this system. It runs once
on a fresh checkout (or re-runs with `RECONFIGURE=1`) to populate
`~/.config/brain/*.yaml`. On a fresh install, the installer also
initializes the upgrade ledger — every upgrade currently in `upgrades/`
is marked `grandfathered: true` so the new install does not re-execute
upgrades whose effects are already reflected in current
`config/*.yaml.sample` files.

If `make upgrade` reports `upgrades ledger missing`, run `make install`
first.

If Core refuses to start with `pre-services upgrades pending`, run
`make upgrade` then `make up`.

------------------------------------------------------------------------
## Make Targets
* `make install` — interactive setup wizard. Re-runnable.
  `make install RECONFIGURE=1` re-walks the wizard against an already-
  configured install and preserves the ledger.
* `make upgrade` — apply pending upgrades in lex order.
* `make upgrade-dryrun` — list pending upgrades without applying.
* `make new-upgrade NAME=<snake_case_slug>` — scaffold a new upgrade
  directory with stub `upgrade.py` and `test_upgrade.py`.

CLI equivalents live at `bin/install` and `bin/upgrade`. The latter
exposes additional subcommands:
* `bin/upgrade list [--json] [--pending-only]` — diagnostic listing.
* `bin/upgrade status` — one-line summary of applied vs pending.

Exit codes for `bin/upgrade`:
* `0` — success.
* `1` — discovery error or step failure.
* `2` — usage error.
* `75` — another `make upgrade` is already in progress (lockfile held).
* `78` — upgrade ledger missing (run `make install` first).

------------------------------------------------------------------------
## Author Workflow
To create a new upgrade:
```sh
make new-upgrade NAME=fix_shared_yaml_dsn
```
This creates `upgrades/YYYYMMDD_NNNN_fix_shared_yaml_dsn/upgrade.py` plus
a sibling `test_upgrade.py`.

Edit `upgrade.py`:
```python
"""Rewrite a stale Postgres DSN in shared.yaml."""

from lib.core.upgrades.api import UpgradeContext

DESCRIPTION = "Rewrite the Postgres DSN in shared.yaml from old to new host"
PHASE = "pre-services"
INTERACTIVE = False
TIMEOUT_SECONDS = 300


def run(ctx: UpgradeContext) -> None:
    target = ctx.config_dir / "shared.yaml"
    text = target.read_text()
    target.write_text(text.replace("old-host:5432", "new-host:5432"))
```

The `UpgradeContext` (`lib.core.upgrades.api.UpgradeContext`) carries:
* `upgrade_id`, `slug`, `phase`, `interactive`
* `repo_root`, `config_dir`, `state_dir`, `cache_dir`, `log_dir` (all
  pre-resolved `Path` instances)
* `logger` (writes to `log_dir/upgrade.log` for non-interactive runs)

Co-located helpers are loaded with
`lib.core.upgrades.api.load_sibling(__file__, "wizard")`. Sibling tests
live at `upgrades/<id>_<slug>/test_upgrade.py`; pytest discovers them via
the project's `--import-mode=importlib` option.

For interactive upgrades (TUIs, prompts) set `INTERACTIVE = True` and the
runner connects stdin/stdout/stderr directly to the operator's terminal.
The runner refuses to run interactive upgrades without a controlling tty.

------------------------------------------------------------------------
## Execution Model
The runner executes each upgrade in a fresh subprocess of `python -m
lib.core.upgrades.execute <upgrade_dir>` for isolation, clean timeout
behavior, and per-upgrade stdio mode. The subprocess inherits the
following env vars:

| Variable | Value |
|---|---|
| `BRAIN_UPGRADE_ID` | The id (e.g. `20260505_0001`) |
| `BRAIN_UPGRADE_SLUG` | The slug (e.g. `fix_shared_yaml_dsn`) |
| `BRAIN_UPGRADE_PHASE` | `pre-services` or `post-services` |
| `BRAIN_UPGRADE_INTERACTIVE` | `0` or `1` |
| `BRAIN_REPO_ROOT` | Absolute repo root |
| `BRAIN_CONFIG_DIR` | Resolved `~/.config/brain` |
| `BRAIN_STATE_DIR` | Resolved `~/.local/state/brain` |
| `BRAIN_CACHE_DIR` | Resolved `~/.cache/brain` |
| `BRAIN_LOG_DIR` | Per-upgrade `<repo>/logs/upgrades/<id>/` |

Non-interactive upgrades have their stdout/stderr captured to
`logs/upgrades/<id>/{stdout,stderr}.log` and tee'd to the runner's
stdout. A `meta.json` is written for both modes. Per-run summary lines
land in `logs/upgrades/_run-<ISO>.log`.

------------------------------------------------------------------------
## Ledger
`~/.local/state/brain/upgrades.json` is the source of truth for what has
been applied on this install. Schema:

```json
{
  "schema_version": 1,
  "installed_at": "2026-05-05T14:00:00.000000Z",
  "applied": [
    {
      "id": "20260505_0001",
      "slug": "fix_shared_yaml_dsn",
      "phase": "pre-services",
      "applied_at": "2026-05-05T14:00:00.000000Z",
      "duration_seconds": 0.0,
      "module_sha256": "0000000000000000000000000000000000000000000000000000000000000000",
      "interactive": false,
      "grandfathered": true
    }
  ]
}
```

Grandfathered entries (sentinel `module_sha256` of all zeroes) were never
executed by this install — the installer recorded them so the runner
treats them as applied. Real applies record the actual SHA-256 of the
upgrade module file.

The runner takes a non-blocking `flock` on
`~/.local/state/brain/upgrades.lock` while applying. Concurrent runs
exit 75 (`EX_TEMPFAIL`).

------------------------------------------------------------------------
## Boot Guard
Core checks the ledger at startup. If pre-services upgrades are pending
(or the ledger is missing entirely), Core refuses to boot and exits 78.
Post-services pending upgrades log a warning and let boot proceed.

The check is gated on `core.boot.assert_upgrades_clean` (default `true`).
See [Configuration](configuration.md).

------------------------------------------------------------------------
## When NOT to Use Upgrades
* For per-service SQL schema changes, write an Alembic migration under
  `services/<plane>/<service>/migrations/` instead.
* For first-install setup (asking the operator their name, Signal phone,
  etc.), extend `lib/setup/wizard.py` instead. The installer is
  re-runnable; upgrades are not.
* For one-off operator chores you'll never want re-applied on another
  install, just run them by hand. The upgrade system is for changes that
  must propagate to every install going forward.


------------------------------------------------------------------------
_End of Upgrades_
