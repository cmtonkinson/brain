"""Runner orchestration: apply, dry-run, boot guards, slug drift."""

from __future__ import annotations

import json
import logging
import subprocess
import sys
import time
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

import pytest

from lib.core.upgrades.discovery import DiscoveryError
from lib.core.upgrades.ledger import (
    LEDGER_SCHEMA_VERSION,
    ZERO_SHA_SENTINEL,
    Ledger,
    LedgerEntry,
    LedgerLockedError,
    ledger_lock,
    now_utc_iso,
    read_ledger,
    write_ledger,
)
from lib.core.upgrades.runner import (
    LedgerMissingError,
    UpgradesPendingError,
    apply_pending,
    assert_pre_services_clean,
    list_pending,
    render_dryrun,
    warn_post_services_pending,
)


@contextmanager
def _capture_logger(
    name: str, level: int = logging.WARNING
) -> Iterator[list[logging.LogRecord]]:
    """Attach a transient handler to ``name`` and yield its captured records.

    Robust to Brain's Alembic startup-migrations stack invoking
    ``fileConfig(..., disable_existing_loggers=True)`` earlier in the test
    session — that sets ``disabled=True`` on every named logger that
    existed at the time, silencing them. We force the captured logger
    enabled and at the desired level for the duration of the context, then
    restore exactly as we found things. Direct attachment also avoids
    pytest ``caplog``, which lives at the root logger and can be cleared
    by ``configure_logging``.
    """
    captured: list[logging.LogRecord] = []

    class _ListHandler(logging.Handler):
        def emit(self, record: logging.LogRecord) -> None:
            captured.append(record)

    handler = _ListHandler(level=level)
    target = logging.getLogger(name)
    previous_level = target.level
    previous_disabled = target.disabled
    target.addHandler(handler)
    target.disabled = False
    target.setLevel(min(previous_level, level) if previous_level else level)
    try:
        yield captured
    finally:
        target.removeHandler(handler)
        target.setLevel(previous_level)
        target.disabled = previous_disabled


def _seed_empty_ledger() -> None:
    write_ledger(
        Ledger(
            schema_version=LEDGER_SCHEMA_VERSION,
            installed_at=now_utc_iso(),
            applied=[],
        )
    )


def test_apply_refuses_when_ledger_missing(isolated_state_env, make_upgrade):
    make_upgrade(upgrade_id="20260505_0001", slug="alpha")

    with pytest.raises(LedgerMissingError, match="run .make install."):
        apply_pending(repo_root=isolated_state_env["tmp_path"])


def test_dryrun_refuses_when_ledger_missing(isolated_state_env, make_upgrade):
    make_upgrade(upgrade_id="20260505_0001", slug="alpha")

    with pytest.raises(LedgerMissingError):
        render_dryrun(repo_root=isolated_state_env["tmp_path"])


def test_apply_writes_ledger_entry(isolated_state_env, make_upgrade):
    _seed_empty_ledger()
    make_upgrade(
        upgrade_id="20260505_0001",
        slug="alpha",
        body='    (ctx.state_dir / "marker.txt").write_text("done")\n',
    )

    rc = apply_pending(repo_root=isolated_state_env["tmp_path"])

    assert rc == 1
    state_dir = isolated_state_env["state_dir"]
    assert (state_dir / "marker.txt").read_text() == "done"
    ledger = read_ledger()
    assert len(ledger.applied) == 1
    entry = ledger.applied[0]
    assert entry.upgrade_id == "20260505_0001"
    assert entry.slug == "alpha"
    assert entry.grandfathered is False
    assert entry.module_sha256 != "0" * 64


def test_apply_skips_already_applied(isolated_state_env, make_upgrade):
    _seed_empty_ledger()
    make_upgrade(
        upgrade_id="20260505_0001",
        slug="alpha",
        body='    (ctx.state_dir / "marker").write_text("1")\n',
    )

    apply_pending(repo_root=isolated_state_env["tmp_path"])
    marker = isolated_state_env["state_dir"] / "marker"
    marker.unlink()

    rc = apply_pending(repo_root=isolated_state_env["tmp_path"])

    assert rc == 0
    assert not marker.exists()  # script did not re-run
    assert len(read_ledger().applied) == 1


def test_apply_aborts_on_first_failure(isolated_state_env, make_upgrade):
    _seed_empty_ledger()
    make_upgrade(
        upgrade_id="20260505_0001",
        slug="alpha",
        body='    raise RuntimeError("boom")\n',
    )
    make_upgrade(
        upgrade_id="20260505_0002",
        slug="beta",
        body='    (ctx.state_dir / "should-not-exist").write_text("nope")\n',
    )

    rc = apply_pending(repo_root=isolated_state_env["tmp_path"])

    assert rc == 0  # zero applied
    state_dir = isolated_state_env["state_dir"]
    assert not (state_dir / "should-not-exist").exists()
    assert read_ledger().applied == []


def test_apply_propagates_env_contract(isolated_state_env, make_upgrade):
    _seed_empty_ledger()
    make_upgrade(
        upgrade_id="20260505_0001",
        slug="env_check",
        body="""\
    import os
    required = [
        "BRAIN_UPGRADE_ID",
        "BRAIN_UPGRADE_SLUG",
        "BRAIN_UPGRADE_PHASE",
        "BRAIN_UPGRADE_INTERACTIVE",
        "BRAIN_REPO_ROOT",
        "BRAIN_CONFIG_DIR",
        "BRAIN_STATE_DIR",
        "BRAIN_CACHE_DIR",
        "BRAIN_LOG_DIR",
    ]
    missing = [k for k in required if not os.environ.get(k)]
    if missing:
        raise RuntimeError(f"missing env: {missing}")
    (ctx.state_dir / "env-ok").write_text("yes")
""",
    )

    apply_pending(repo_root=isolated_state_env["tmp_path"])

    assert (isolated_state_env["state_dir"] / "env-ok").read_text() == "yes"


def test_apply_writes_logs_under_logs_upgrades(isolated_state_env, make_upgrade):
    _seed_empty_ledger()
    make_upgrade(
        upgrade_id="20260505_0001",
        slug="logger",
        body='    print("hello-from-upgrade")\n',
    )

    apply_pending(repo_root=isolated_state_env["tmp_path"])

    log_dir = isolated_state_env["tmp_path"] / "logs" / "upgrades" / "20260505_0001"
    assert (log_dir / "stdout.log").exists()
    assert (log_dir / "meta.json").exists()
    assert "hello-from-upgrade" in (log_dir / "stdout.log").read_text()
    meta = json.loads((log_dir / "meta.json").read_text())
    assert meta["exit_code"] == 0
    assert meta["upgrade_id"] == "20260505_0001"
    assert meta["env_brain"]["BRAIN_UPGRADE_ID"] == "20260505_0001"


def test_apply_respects_timeout(isolated_state_env, make_upgrade):
    _seed_empty_ledger()
    make_upgrade(
        upgrade_id="20260505_0001",
        slug="slow",
        timeout_seconds=1,
        body="    import time\n    time.sleep(30)\n",
    )

    rc = apply_pending(repo_root=isolated_state_env["tmp_path"])

    assert rc == 0  # nothing recorded
    assert read_ledger().applied == []
    meta_path = (
        isolated_state_env["tmp_path"]
        / "logs"
        / "upgrades"
        / "20260505_0001"
        / "meta.json"
    )
    meta = json.loads(meta_path.read_text())
    assert meta["timed_out"] is True


def test_apply_subprocess_isolated_from_runner_state(isolated_state_env, make_upgrade):
    _seed_empty_ledger()
    make_upgrade(
        upgrade_id="20260505_0001",
        slug="poison",
        body="""\
    import sys
    sys.modules["sentinel_marker"] = object()
""",
    )

    apply_pending(repo_root=isolated_state_env["tmp_path"])

    assert "sentinel_marker" not in sys.modules


def test_apply_records_module_sha256(isolated_state_env, make_upgrade):
    _seed_empty_ledger()
    directory = make_upgrade(upgrade_id="20260505_0001", slug="hashed")

    apply_pending(repo_root=isolated_state_env["tmp_path"])

    entry = read_ledger().applied[0]
    import hashlib

    expected = hashlib.sha256((directory / "upgrade.py").read_bytes()).hexdigest()
    assert entry.module_sha256 == expected


def test_dryrun_lists_only_pending(isolated_state_env, make_upgrade):
    _seed_empty_ledger()
    make_upgrade(upgrade_id="20260505_0001", slug="alpha")
    make_upgrade(upgrade_id="20260601_0001", slug="beta", phase="pre-services")

    out = render_dryrun(repo_root=isolated_state_env["tmp_path"])

    assert "20260505_0001" in out
    assert "20260601_0001" in out
    assert "alpha" in out
    assert "beta" in out
    assert "[pre-services]" in out
    assert "[post-services]" in out


def test_dryrun_does_not_invoke_run(isolated_state_env, make_upgrade):
    _seed_empty_ledger()
    make_upgrade(
        upgrade_id="20260505_0001",
        slug="explosive",
        body='    (ctx.state_dir / "ran").write_text("oops")\n',
    )

    render_dryrun(repo_root=isolated_state_env["tmp_path"])

    assert not (isolated_state_env["state_dir"] / "ran").exists()


def test_dryrun_empty_when_nothing_pending(isolated_state_env):
    _seed_empty_ledger()

    out = render_dryrun(repo_root=isolated_state_env["tmp_path"])

    assert "No pending upgrades." in out


def test_assert_pre_services_clean_passes_when_empty(isolated_state_env):
    _seed_empty_ledger()

    assert_pre_services_clean(repo_root=isolated_state_env["tmp_path"])


def test_assert_pre_services_clean_raises_on_pending(isolated_state_env, make_upgrade):
    _seed_empty_ledger()
    make_upgrade(upgrade_id="20260505_0001", slug="alpha", phase="pre-services")

    with pytest.raises(UpgradesPendingError, match="pre-services upgrades pending"):
        assert_pre_services_clean(repo_root=isolated_state_env["tmp_path"])


def test_assert_pre_services_clean_raises_when_ledger_missing(
    isolated_state_env, make_upgrade
):
    make_upgrade(upgrade_id="20260505_0001", slug="alpha", phase="pre-services")

    with pytest.raises(UpgradesPendingError, match="ledger missing"):
        assert_pre_services_clean(repo_root=isolated_state_env["tmp_path"])


def test_assert_pre_services_clean_ignores_post_services_pending(
    isolated_state_env, make_upgrade
):
    _seed_empty_ledger()
    make_upgrade(upgrade_id="20260505_0001", slug="alpha", phase="post-services")

    assert_pre_services_clean(repo_root=isolated_state_env["tmp_path"])


def test_warn_post_services_pending_silent_when_clean(isolated_state_env):
    _seed_empty_ledger()

    with _capture_logger("root") as records:
        warn_post_services_pending(repo_root=isolated_state_env["tmp_path"])

    assert not any("upgrades pending" in r.getMessage() for r in records)


def test_warn_post_services_pending_warns_when_pending(
    isolated_state_env, make_upgrade
):
    _seed_empty_ledger()
    make_upgrade(upgrade_id="20260505_0001", slug="alpha", phase="post-services")

    with _capture_logger("root") as records:
        warn_post_services_pending(repo_root=isolated_state_env["tmp_path"])

    assert any("post-services upgrades pending" in r.getMessage() for r in records)


def test_compute_pending_rejects_slug_drift(isolated_state_env, make_upgrade):
    _seed_empty_ledger()
    make_upgrade(upgrade_id="20260505_0001", slug="renamed_on_disk")

    # Forge a ledger entry with a different slug for the same id.
    ledger = read_ledger()
    ledger.applied.append(
        LedgerEntry(
            upgrade_id="20260505_0001",
            slug="original_slug",
            phase="post-services",
            applied_at=now_utc_iso(),
            duration_seconds=0.0,
            module_sha256="0" * 64,
            interactive=False,
            grandfathered=True,
        )
    )
    write_ledger(ledger)

    with pytest.raises(DiscoveryError, match="slug drift"):
        list_pending(repo_root=isolated_state_env["tmp_path"])


def test_apply_pre_then_post_in_lex_order(isolated_state_env, make_upgrade):
    _seed_empty_ledger()
    state = isolated_state_env["state_dir"]
    make_upgrade(
        upgrade_id="20260505_0001",
        slug="pre",
        phase="pre-services",
        body=(
            "    p = ctx.state_dir / 'order.log'\n"
            "    existing = p.read_text() if p.exists() else ''\n"
            "    p.write_text(existing + 'pre\\n')\n"
        ),
    )
    make_upgrade(
        upgrade_id="20260505_0002",
        slug="post",
        phase="post-services",
        body=(
            "    p = ctx.state_dir / 'order.log'\n"
            "    existing = p.read_text() if p.exists() else ''\n"
            "    p.write_text(existing + 'post\\n')\n"
        ),
    )

    apply_pending(repo_root=isolated_state_env["tmp_path"])

    log = (state / "order.log").read_text().splitlines()
    assert log == ["pre", "post"]


# --------------------------------------------------------------------------
# Interactive stdio mode
# --------------------------------------------------------------------------


def test_apply_interactive_refuses_without_tty(
    isolated_state_env, make_upgrade, monkeypatch, capsys
):
    """Interactive upgrades raise + the run aborts when stdin is not a tty."""
    _seed_empty_ledger()
    make_upgrade(
        upgrade_id="20260505_0001",
        slug="needs_tty",
        interactive=True,
        body='    (ctx.state_dir / "should-not-exist").write_text("ran")\n',
    )
    # Pytest stdin is normally not a tty already, but pin it to be sure
    # the test isn't sensitive to the test harness's invocation shape.
    monkeypatch.setattr(
        "lib.core.upgrades.execution._has_controlling_tty", lambda: False
    )

    rc = apply_pending(repo_root=isolated_state_env["tmp_path"])

    assert rc == 0  # nothing applied
    assert read_ledger().applied == []
    state_dir = isolated_state_env["state_dir"]
    assert not (state_dir / "should-not-exist").exists()
    captured = capsys.readouterr()
    assert "refusing to run interactive upgrade" in captured.err


def test_apply_interactive_inherits_terminal_skips_log_capture(
    isolated_state_env, make_upgrade, monkeypatch
):
    """Interactive subprocesses inherit the terminal — no stdout/stderr.log."""
    _seed_empty_ledger()
    make_upgrade(
        upgrade_id="20260505_0001",
        slug="interactive_runs",
        interactive=True,
        body=(
            '    (ctx.state_dir / "interactive-marker").write_text("ran")\n'
            '    print("would-be-on-terminal")\n'
        ),
    )
    monkeypatch.setattr(
        "lib.core.upgrades.execution._has_controlling_tty", lambda: True
    )

    rc = apply_pending(repo_root=isolated_state_env["tmp_path"])

    assert rc == 1
    state_dir = isolated_state_env["state_dir"]
    assert (state_dir / "interactive-marker").read_text() == "ran"
    log_dir = isolated_state_env["tmp_path"] / "logs" / "upgrades" / "20260505_0001"
    # meta.json is always written; stdout.log and stderr.log are NOT
    # because the interactive branch leaves stdio attached to the
    # operator's terminal (no tee, no file capture).
    assert (log_dir / "meta.json").is_file()
    assert not (log_dir / "stdout.log").exists()
    assert not (log_dir / "stderr.log").exists()
    meta = json.loads((log_dir / "meta.json").read_text())
    assert meta["interactive"] is True


# --------------------------------------------------------------------------
# Module-SHA drift detection
# --------------------------------------------------------------------------


def test_compute_pending_warns_when_applied_module_sha_changes(
    isolated_state_env, make_upgrade
):
    """Editing an already-applied upgrade.py must surface a warning."""
    _seed_empty_ledger()
    directory = make_upgrade(
        upgrade_id="20260505_0001",
        slug="drifty",
        body='    (ctx.state_dir / "first").write_text("v1")\n',
    )

    apply_pending(repo_root=isolated_state_env["tmp_path"])
    original_entry = read_ledger().applied[0]
    assert original_entry.module_sha256 != ZERO_SHA_SENTINEL

    # Mutate the upgrade source after it's already been applied.
    upgrade_py = directory / "upgrade.py"
    upgrade_py.write_text(
        upgrade_py.read_text() + "\n# trailing comment added post-apply\n"
    )

    # Sanity-check the precondition: post-mutation SHA must differ from
    # the recorded one or the test's own setup is broken.
    import hashlib

    new_sha = hashlib.sha256(upgrade_py.read_bytes()).hexdigest()
    assert new_sha != original_entry.module_sha256

    with _capture_logger("lib.core.upgrades.runner") as records:
        list_pending(repo_root=isolated_state_env["tmp_path"])

    drift_records = [r for r in records if "module sha drift" in r.getMessage()]
    assert len(drift_records) == 1, [r.getMessage() for r in records]
    assert "20260505_0001" in drift_records[0].getMessage()


def test_compute_pending_silent_when_grandfathered_entry_drifts(
    isolated_state_env, make_upgrade
):
    """Grandfathered entries carry the zero-SHA sentinel; never warn."""
    make_upgrade(upgrade_id="20260505_0001", slug="legacy")
    write_ledger(
        Ledger(
            schema_version=LEDGER_SCHEMA_VERSION,
            installed_at=now_utc_iso(),
            applied=[
                LedgerEntry(
                    upgrade_id="20260505_0001",
                    slug="legacy",
                    phase="post-services",
                    applied_at=now_utc_iso(),
                    duration_seconds=0.0,
                    module_sha256=ZERO_SHA_SENTINEL,
                    interactive=False,
                    grandfathered=True,
                )
            ],
        )
    )

    with _capture_logger("lib.core.upgrades.runner") as records:
        list_pending(repo_root=isolated_state_env["tmp_path"])

    assert not any("module sha drift" in r.getMessage() for r in records)


# --------------------------------------------------------------------------
# Concurrent apply: lock + EX_TEMPFAIL
# --------------------------------------------------------------------------


def test_apply_pending_raises_locked_error_when_other_process_holds_lock(
    isolated_state_env, make_upgrade, tmp_path
):
    """A second `apply_pending` must surface LedgerLockedError, not block."""
    _seed_empty_ledger()
    make_upgrade(
        upgrade_id="20260505_0001",
        slug="alpha",
        body='    (ctx.state_dir / "ran").write_text("yes")\n',
    )
    state_dir = isolated_state_env["state_dir"]

    # Spawn a holder process that grabs the lock and waits for a release
    # signal. We can't take the lock from this process and call
    # apply_pending in the same process — flock(LOCK_EX) is per-process,
    # so the same pid can re-enter without blocking.
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
            apply_pending(repo_root=isolated_state_env["tmp_path"])
        # The held lock prevents any application; ledger stays empty.
        assert read_ledger().applied == []
    finally:
        signal_file.write_text("release")
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait()


def test_apply_pending_re_enters_cleanly_after_lock_released(
    isolated_state_env, make_upgrade
):
    """After the lock context exits the next apply_pending succeeds."""
    _seed_empty_ledger()
    make_upgrade(
        upgrade_id="20260505_0001",
        slug="alpha",
        body='    (ctx.state_dir / "ran").write_text("yes")\n',
    )
    # Acquire and release in this process — the matched pair must leave
    # no stale state behind.
    with ledger_lock():
        pass
    rc = apply_pending(repo_root=isolated_state_env["tmp_path"])
    assert rc == 1
    assert (isolated_state_env["state_dir"] / "ran").read_text() == "yes"
