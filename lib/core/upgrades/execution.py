"""Subprocess execution for one upgrade with env contract, stdio mode, timeout."""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
import threading
import time
from dataclasses import dataclass
from pathlib import Path

from lib.core.upgrades.discovery import UpgradeDescriptor

DEFAULT_REPO_ROOT = Path.cwd()
TERM_GRACE_SECONDS = 10.0


class InteractiveWithoutTtyError(RuntimeError):
    """Raised when an interactive upgrade is requested without a controlling tty."""


@dataclass(frozen=True, slots=True)
class ExecutionResult:
    """Outcome of running one upgrade in a subprocess."""

    descriptor: UpgradeDescriptor
    exit_code: int
    duration_seconds: float
    module_sha256: str
    timed_out: bool


def compute_module_sha256(upgrade_py: Path) -> str:
    """Return the SHA-256 of an upgrade module file as lowercase hex."""
    h = hashlib.sha256()
    with upgrade_py.open("rb") as fh:
        for chunk in iter(lambda: fh.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def execute_upgrade(
    descriptor: UpgradeDescriptor,
    *,
    repo_root: Path,
    config_dir: Path,
    state_dir: Path,
    cache_dir: Path,
    log_root: Path,
    runner_stdout=None,
) -> ExecutionResult:
    """Run one upgrade in a subprocess.

    Captures stdout/stderr to ``log_root/<id>/{stdout,stderr}.log`` for
    non-interactive upgrades and tees to ``runner_stdout`` (defaults to
    ``sys.stdout``). Interactive upgrades inherit the operator's terminal
    directly. Writes ``log_root/<id>/meta.json`` for both modes.
    """
    if runner_stdout is None:
        runner_stdout = sys.stdout

    log_dir = log_root / descriptor.upgrade_id
    log_dir.mkdir(parents=True, exist_ok=True)

    if descriptor.interactive and not _has_controlling_tty():
        raise InteractiveWithoutTtyError(
            f"upgrade {descriptor.upgrade_id} ({descriptor.slug}) is "
            "interactive but no controlling tty is attached"
        )

    env = _build_env(
        descriptor=descriptor,
        repo_root=repo_root,
        config_dir=config_dir,
        state_dir=state_dir,
        cache_dir=cache_dir,
        log_dir=log_dir,
    )

    cmd = [
        sys.executable,
        "-m",
        "lib.core.upgrades.execute",
        str(descriptor.directory),
    ]

    started_at = time.monotonic()
    started_at_iso = _now_iso()
    timed_out = False
    exit_code = 0

    if descriptor.interactive:
        proc = subprocess.Popen(  # noqa: S603 — controlled cmd, no shell
            cmd,
            cwd=str(repo_root),
            env=env,
            stdin=None,
            stdout=None,
            stderr=None,
        )
        try:
            exit_code = proc.wait(timeout=descriptor.timeout_seconds)
        except subprocess.TimeoutExpired:
            timed_out = True
            exit_code = _kill_with_grace(proc)
    else:
        stdout_log = log_dir / "stdout.log"
        stderr_log = log_dir / "stderr.log"
        with stdout_log.open("wb") as out_fh, stderr_log.open("wb") as err_fh:
            proc = subprocess.Popen(  # noqa: S603 — controlled cmd, no shell
                cmd,
                cwd=str(repo_root),
                env=env,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                bufsize=0,
            )
            tee_threads = [
                _tee(proc.stdout, out_fh, runner_stdout),
                _tee(proc.stderr, err_fh, sys.stderr),
            ]
            try:
                exit_code = proc.wait(timeout=descriptor.timeout_seconds)
            except subprocess.TimeoutExpired:
                timed_out = True
                exit_code = _kill_with_grace(proc)
            for thread in tee_threads:
                thread.join()

    duration = time.monotonic() - started_at
    module_sha256 = compute_module_sha256(descriptor.upgrade_py)

    _write_meta(
        log_dir=log_dir,
        descriptor=descriptor,
        env=env,
        started_at_iso=started_at_iso,
        finished_at_iso=_now_iso(),
        duration_seconds=duration,
        exit_code=exit_code,
        timed_out=timed_out,
        module_sha256=module_sha256,
    )

    return ExecutionResult(
        descriptor=descriptor,
        exit_code=exit_code,
        duration_seconds=duration,
        module_sha256=module_sha256,
        timed_out=timed_out,
    )


def _build_env(
    *,
    descriptor: UpgradeDescriptor,
    repo_root: Path,
    config_dir: Path,
    state_dir: Path,
    cache_dir: Path,
    log_dir: Path,
) -> dict[str, str]:
    """Compose the BRAIN_* env contract for the subprocess."""
    env = os.environ.copy()
    env["BRAIN_UPGRADE_ID"] = descriptor.upgrade_id
    env["BRAIN_UPGRADE_SLUG"] = descriptor.slug
    env["BRAIN_UPGRADE_PHASE"] = descriptor.phase
    env["BRAIN_UPGRADE_INTERACTIVE"] = "1" if descriptor.interactive else "0"
    env["BRAIN_REPO_ROOT"] = str(repo_root)
    env["BRAIN_CONFIG_DIR"] = str(config_dir)
    env["BRAIN_STATE_DIR"] = str(state_dir)
    env["BRAIN_CACHE_DIR"] = str(cache_dir)
    env["BRAIN_LOG_DIR"] = str(log_dir)
    # Ensure the brain repo root (where `lib/` lives) is on PYTHONPATH so the
    # subprocess can import lib.core.upgrades.execute. We resolve to the parent
    # of the `lib` package owning this module — not to ``repo_root``, which in
    # tests may be a tmp dir that does not contain the brain source.
    brain_root = _brain_root()
    pythonpath_existing = env.get("PYTHONPATH", "")
    if pythonpath_existing:
        env["PYTHONPATH"] = f"{brain_root}{os.pathsep}{pythonpath_existing}"
    else:
        env["PYTHONPATH"] = brain_root
    return env


def _brain_root() -> str:
    """Resolve the directory that contains the `lib/` package source tree."""
    # __file__ -> .../lib/core/upgrades/execution.py
    return str(Path(__file__).resolve().parents[3])


def _tee(source, *sinks) -> threading.Thread:
    """Spawn a daemon thread that copies bytes from source to all sinks."""

    def pump() -> None:
        try:
            for line in iter(source.readline, b""):
                for sink in sinks:
                    if hasattr(sink, "buffer"):
                        sink.buffer.write(line)
                        sink.flush()
                    else:
                        sink.write(line)
                        sink.flush()
        finally:
            source.close()

    thread = threading.Thread(target=pump, daemon=True)
    thread.start()
    return thread


def _kill_with_grace(proc: subprocess.Popen) -> int:
    """SIGTERM, wait grace, SIGKILL. Return final exit code."""
    proc.terminate()
    try:
        return proc.wait(timeout=TERM_GRACE_SECONDS)
    except subprocess.TimeoutExpired:
        proc.kill()
        return proc.wait()


def _has_controlling_tty() -> bool:
    """Return True iff the current process has a controlling tty on stdin."""
    try:
        return os.isatty(sys.stdin.fileno())
    except AttributeError, OSError:
        return False


def _now_iso() -> str:
    from datetime import UTC, datetime

    return datetime.now(tz=UTC).isoformat()


def _write_meta(
    *,
    log_dir: Path,
    descriptor: UpgradeDescriptor,
    env: dict[str, str],
    started_at_iso: str,
    finished_at_iso: str,
    duration_seconds: float,
    exit_code: int,
    timed_out: bool,
    module_sha256: str,
) -> None:
    """Write per-upgrade ``meta.json`` for forensics."""
    brain_env = {key: value for key, value in env.items() if key.startswith("BRAIN_")}
    meta = {
        "upgrade_id": descriptor.upgrade_id,
        "slug": descriptor.slug,
        "phase": descriptor.phase,
        "interactive": descriptor.interactive,
        "timeout_seconds": descriptor.timeout_seconds,
        "started_at": started_at_iso,
        "finished_at": finished_at_iso,
        "duration_seconds": duration_seconds,
        "exit_code": exit_code,
        "timed_out": timed_out,
        "module_sha256": module_sha256,
        "env_brain": brain_env,
    }
    payload = json.dumps(meta, indent=2) + "\n"
    target = log_dir / "meta.json"
    tmp = target.with_name(target.name + ".tmp")
    with tmp.open("w", encoding="utf-8") as fh:
        fh.write(payload)
    os.replace(tmp, target)
