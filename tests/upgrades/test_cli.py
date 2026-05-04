"""CLI dispatcher: subcommand routing, exit codes, listing flags."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from pathlib import Path

import pytest

from lib.core.upgrades.cli import (
    EXIT_GENERIC_FAILURE,
    EXIT_LEDGER_MISSING,
    EXIT_OK,
    EXIT_TEMP_FAIL,
    EXIT_USAGE,
    main,
)
from lib.core.upgrades.ledger import (
    LEDGER_SCHEMA_VERSION,
    Ledger,
    now_utc_iso,
    read_ledger,
    write_ledger,
)


def _seed_empty_ledger() -> None:
    write_ledger(
        Ledger(
            schema_version=LEDGER_SCHEMA_VERSION,
            installed_at=now_utc_iso(),
            applied=[],
        )
    )


def test_cli_status_returns_summary(isolated_state_env, make_upgrade, capsys):
    _seed_empty_ledger()
    make_upgrade(upgrade_id="20260505_0001", slug="alpha", phase="post-services")
    make_upgrade(upgrade_id="20260505_0002", slug="beta", phase="pre-services")

    rc = main(["status"])

    captured = capsys.readouterr()
    assert rc == EXIT_OK
    assert "0 applied, 2 pending" in captured.out
    assert "1 pre-services pending" in captured.out
    assert "1 post-services pending" in captured.out


def test_cli_status_returns_78_when_ledger_missing(
    isolated_state_env, make_upgrade, capsys
):
    make_upgrade(upgrade_id="20260505_0001", slug="alpha")

    rc = main(["status"])

    assert rc == EXIT_LEDGER_MISSING
    assert "ledger not found" in capsys.readouterr().err


def test_cli_apply_returns_zero_on_success(isolated_state_env, make_upgrade, capsys):
    _seed_empty_ledger()
    make_upgrade(
        upgrade_id="20260505_0001",
        slug="ok",
        body='    (ctx.state_dir / "ok").write_text("y")\n',
    )

    rc = main(["apply"])

    assert rc == EXIT_OK
    assert (isolated_state_env["state_dir"] / "ok").read_text() == "y"
    assert len(read_ledger().applied) == 1


def test_cli_apply_returns_failure_when_step_fails(
    isolated_state_env, make_upgrade, capsys
):
    _seed_empty_ledger()
    make_upgrade(
        upgrade_id="20260505_0001",
        slug="fails",
        body='    raise RuntimeError("boom")\n',
    )

    rc = main(["apply"])

    assert rc == EXIT_GENERIC_FAILURE
    assert read_ledger().applied == []


def test_cli_apply_returns_78_when_ledger_missing(
    isolated_state_env, make_upgrade, capsys
):
    make_upgrade(upgrade_id="20260505_0001", slug="alpha")

    rc = main(["apply"])

    assert rc == EXIT_LEDGER_MISSING


def test_cli_dry_run_lists_pending(isolated_state_env, make_upgrade, capsys):
    _seed_empty_ledger()
    make_upgrade(upgrade_id="20260505_0001", slug="alpha")

    rc = main(["dry-run"])

    out = capsys.readouterr().out
    assert rc == EXIT_OK
    assert "20260505_0001" in out
    assert "alpha" in out


def test_cli_list_json_emits_pending_only(isolated_state_env, make_upgrade, capsys):
    _seed_empty_ledger()
    make_upgrade(upgrade_id="20260505_0001", slug="a")
    make_upgrade(upgrade_id="20260505_0002", slug="b")
    main(["apply"])

    capsys.readouterr()  # flush
    rc = main(["list", "--json", "--pending-only"])
    out = capsys.readouterr().out

    assert rc == EXIT_OK
    parsed = json.loads(out)
    assert parsed == []  # all applied → no pending


def test_cli_list_json_includes_applied_and_pending(
    isolated_state_env, make_upgrade, capsys
):
    _seed_empty_ledger()
    make_upgrade(upgrade_id="20260505_0001", slug="a")
    main(["apply"])
    make_upgrade(upgrade_id="20260505_0002", slug="b")

    capsys.readouterr()
    rc = main(["list", "--json"])
    out = capsys.readouterr().out

    assert rc == EXIT_OK
    parsed = json.loads(out)
    statuses = {row["id"]: row["status"] for row in parsed}
    assert statuses == {"20260505_0001": "applied", "20260505_0002": "pending"}


def test_cli_new_scaffolds(isolated_state_env, capsys):
    rc = main(["new", "--name", "my_thing"])

    out = capsys.readouterr().out
    assert rc == EXIT_OK
    upgrades_dir = isolated_state_env["upgrades_dir"]
    matches = list(upgrades_dir.glob("*_my_thing"))
    assert len(matches) == 1
    assert (matches[0] / "upgrade.py").is_file()
    assert (matches[0] / "test_upgrade.py").is_file()
    assert "Created:" in out


def test_cli_new_rejects_invalid_name(isolated_state_env, capsys):
    rc = main(["new", "--name", "Bad-Name"])

    assert rc == EXIT_USAGE
    assert "invalid upgrade name" in capsys.readouterr().err


def test_cli_main_unknown_subcommand_exits_two(isolated_state_env):
    with pytest.raises(SystemExit) as excinfo:
        main(["bogus"])

    assert excinfo.value.code == 2


# --------------------------------------------------------------------------
# Concurrent apply: CLI returns 75 (EX_TEMPFAIL) when the lock is held
# --------------------------------------------------------------------------


def test_cli_apply_returns_75_when_ledger_locked(
    isolated_state_env, make_upgrade, tmp_path, capsys
):
    """A second `bin/upgrade apply` while the lock is held returns 75."""
    _seed_empty_ledger()
    make_upgrade(
        upgrade_id="20260505_0001",
        slug="alpha",
        body='    (ctx.state_dir / "ran").write_text("yes")\n',
    )
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

        rc = main(["apply"])

        assert rc == EXIT_TEMP_FAIL
        assert "another upgrade run is in progress" in capsys.readouterr().err
        assert read_ledger().applied == []
    finally:
        signal_file.write_text("release")
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait()


# --------------------------------------------------------------------------
# bin/upgrade shell wrapper smoke test
# --------------------------------------------------------------------------


def test_bin_upgrade_dispatches_to_python_cli(isolated_state_env):
    """The bash wrapper at bin/upgrade execs the Python CLI.

    Smoke-only: invokes ``status`` against an isolated env with no
    ledger and asserts the wrapper surfaces the same EXIT_LEDGER_MISSING
    exit code (78) the Python CLI returns directly.
    """
    repo_root = Path(__file__).resolve().parents[2]
    wrapper = repo_root / "bin" / "upgrade"
    assert wrapper.is_file()
    assert os.access(wrapper, os.X_OK), f"{wrapper} is not executable"

    env = os.environ.copy()
    env["BRAIN_STATE_DIR"] = str(isolated_state_env["state_dir"])
    env["BRAIN_CONFIG_DIR"] = str(isolated_state_env["config_dir"])
    env["BRAIN_CACHE_DIR"] = str(isolated_state_env["cache_dir"])
    env["BRAIN_UPGRADES_DIR"] = str(isolated_state_env["upgrades_dir"])
    env.pop("BRAIN_UPGRADES_LEDGER", None)

    result = subprocess.run(
        [str(wrapper), "status"],
        env=env,
        capture_output=True,
        text=True,
        timeout=30,
        cwd=str(repo_root),
    )

    assert result.returncode == EXIT_LEDGER_MISSING, (
        f"stdout={result.stdout!r}\nstderr={result.stderr!r}"
    )
    assert "ledger not found" in result.stderr
