"""Self-test diagnostics for core Brain subsystems."""

from __future__ import annotations

import re
import time
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Awaitable, Callable

from qdrant_client import QdrantClient

from config import settings
from self_diagnostic_utils import (
    contains_expected_name,
    extract_allowed_directories,
    extract_allowed_directories_from_text,
    extract_code_mode_result,
    extract_content_text,
    parse_code_mode_payload,
)
from services.code_mode import CodeModeManager
from services.letta import LettaService
from services.signal import SignalClient
from tools.obsidian import ObsidianClient


class SelfTestStatus(str, Enum):
    """Aggregate outcome for the full self-test."""

    PASS = "PASS"
    PARTIAL = "PARTIAL"
    FAIL = "FAIL"


@dataclass(frozen=True)
class SubsystemTestResult:
    """Structured result for a single subsystem check."""

    passed: bool
    message: str
    duration_seconds: float

    def as_dict(self) -> dict[str, object]:
        """Render the result as a serializable mapping."""
        return {
            "passed": self.passed,
            "message": self.message,
            "duration_seconds": self.duration_seconds,
        }


@dataclass(frozen=True)
class SelfTestReport:
    """Aggregate report for the full self-test."""

    status: SelfTestStatus
    results: dict[str, SubsystemTestResult]

    def as_dict(self) -> dict[str, object]:
        """Render the report as a serializable mapping."""
        return {
            "status": self.status.value,
            "results": {name: result.as_dict() for name, result in self.results.items()},
        }


@dataclass(frozen=True)
class SelfTestDependencies:
    """Dependency container for running subsystem diagnostics."""

    obsidian: ObsidianClient
    code_mode: CodeModeManager
    signal_client: SignalClient | None = None
    letta_service: LettaService | None = None
    qdrant_client: QdrantClient | None = None


async def run_full_self_test(deps: SelfTestDependencies) -> dict[str, object]:
    """Run the full self-test suite and return a serializable report."""
    report = await _run_full_self_test_report(deps)
    return report.as_dict()


async def run_subsystem_test(name: str, deps: SelfTestDependencies) -> dict[str, object]:
    """Run a single subsystem test by name and return a serializable result."""
    tests = _build_subsystem_tests(deps)
    if name not in tests:
        result = SubsystemTestResult(
            passed=False,
            message=f"Unknown subsystem test: {name}",
            duration_seconds=0.0,
        )
        return result.as_dict()
    result = await _run_subsystem_test(tests[name])
    return result.as_dict()


def format_self_test_report(report: dict[str, object] | SelfTestReport) -> str:
    """Format a self-test report into a readable summary."""
    if isinstance(report, SelfTestReport):
        report_payload = report.as_dict()
    else:
        report_payload = report
    status = str(report_payload.get("status", "UNKNOWN"))
    raw_results = report_payload.get("results", {})
    results = _normalize_results_payload(raw_results)
    total = len(results)
    passed = sum(1 for result in results.values() if result.passed)
    failed = total - passed
    header = f"Self-test: {status} (passed {passed}/{total}, failed {failed})"
    lines = [header]
    for name, result in results.items():
        line_status = "PASS" if result.passed else "FAIL"
        duration = f"{result.duration_seconds:.3f}s"
        message = result.message.strip() or "no details"
        lines.append(f"- {name}: {line_status} ({duration}) {message}")
    return "\n".join(lines)


async def _run_full_self_test_report(deps: SelfTestDependencies) -> SelfTestReport:
    """Run the full self-test suite and return a structured report."""
    tests = _build_subsystem_tests(deps)
    results: dict[str, SubsystemTestResult] = {}
    for name, test in tests.items():
        results[name] = await _run_subsystem_test(test)
    status = _derive_overall_status(results)
    return SelfTestReport(status=status, results=results)


def _build_subsystem_tests(
    deps: SelfTestDependencies,
) -> dict[str, Callable[[], Awaitable[SubsystemTestResult]]]:
    """Construct the subsystem test registry."""
    return {
        "obsidian": lambda: _test_obsidian(deps),
        "letta": lambda: _test_letta(deps),
        "signal": lambda: _test_signal(deps),
        "qdrant": lambda: _test_qdrant(deps),
        "code-mode": lambda: _test_code_mode(deps),
        "mcp/filesystem": lambda: _test_mcp_filesystem(deps),
        "mcp/calendar": lambda: _test_mcp_calendar(deps),
        "mcp/reminders": lambda: _test_mcp_reminders(deps),
        "mcp/github": lambda: _test_mcp_github(deps),
    }


async def _run_subsystem_test(
    test: Callable[[], Awaitable[SubsystemTestResult]],
) -> SubsystemTestResult:
    """Measure and execute a subsystem test."""
    started = time.perf_counter()
    try:
        result = await test()
    except Exception as exc:  # pragma: no cover - defensive fallback
        duration = time.perf_counter() - started
        return SubsystemTestResult(
            passed=False,
            message=f"exception: {exc}",
            duration_seconds=duration,
        )
    if result.duration_seconds <= 0:
        duration = time.perf_counter() - started
        return SubsystemTestResult(
            passed=result.passed,
            message=result.message,
            duration_seconds=duration,
        )
    return result


def _derive_overall_status(results: dict[str, SubsystemTestResult]) -> SelfTestStatus:
    """Derive the aggregate self-test status from subsystem outcomes."""
    passes = sum(1 for result in results.values() if result.passed)
    fails = sum(1 for result in results.values() if not result.passed)
    if passes == 0:
        return SelfTestStatus.FAIL
    if fails == 0:
        return SelfTestStatus.PASS
    return SelfTestStatus.PARTIAL


def _normalize_results_payload(
    raw_results: object,
) -> dict[str, SubsystemTestResult]:
    """Normalize a serialized results payload into structured outcomes."""
    if not isinstance(raw_results, dict):
        return {}
    normalized: dict[str, SubsystemTestResult] = {}
    for name, payload in raw_results.items():
        if isinstance(payload, SubsystemTestResult):
            normalized[name] = payload
            continue
        if not isinstance(payload, dict):
            continue
        passed = bool(payload.get("passed"))
        message = str(payload.get("message", "")).strip()
        duration_raw = payload.get("duration_seconds", 0.0)
        try:
            duration = float(duration_raw)
        except (TypeError, ValueError):
            duration = 0.0
        normalized[name] = SubsystemTestResult(
            passed=passed,
            message=message or "no details",
            duration_seconds=duration,
        )
    return normalized


async def _test_obsidian(deps: SelfTestDependencies) -> SubsystemTestResult:
    """Verify Obsidian connectivity by listing the vault root."""
    started = time.perf_counter()
    try:
        entries = await deps.obsidian.list_dir("")
        if entries:
            message = f"{len(entries)} entries"
            return SubsystemTestResult(True, message, time.perf_counter() - started)
        return SubsystemTestResult(False, "empty directory listing", time.perf_counter() - started)
    except Exception as exc:
        return SubsystemTestResult(False, f"error: {exc}", time.perf_counter() - started)


async def _test_letta(deps: SelfTestDependencies) -> SubsystemTestResult:
    """Verify Letta archival search availability."""
    started = time.perf_counter()
    letta = deps.letta_service or LettaService()
    if not letta.enabled:
        return SubsystemTestResult(False, "not configured", time.perf_counter() - started)
    try:
        await _to_thread(letta.search_archival_memory, "smoke test")
        return SubsystemTestResult(True, "archival search ok", time.perf_counter() - started)
    except Exception as exc:
        return SubsystemTestResult(False, f"error: {exc}", time.perf_counter() - started)


async def _test_signal(deps: SelfTestDependencies) -> SubsystemTestResult:
    """Verify Signal connectivity and account visibility."""
    started = time.perf_counter()
    client = deps.signal_client or SignalClient()
    try:
        connected = await client.check_connection()
        if not connected:
            return SubsystemTestResult(False, "connection failed", time.perf_counter() - started)
        accounts = await client.get_accounts()
        if not accounts:
            return SubsystemTestResult(False, "no accounts returned", time.perf_counter() - started)
        return SubsystemTestResult(
            True,
            f"{len(accounts)} account(s)",
            time.perf_counter() - started,
        )
    except Exception as exc:
        return SubsystemTestResult(False, f"error: {exc}", time.perf_counter() - started)


async def _test_qdrant(deps: SelfTestDependencies) -> SubsystemTestResult:
    """Verify Qdrant connectivity by listing collections."""
    started = time.perf_counter()
    client = deps.qdrant_client or QdrantClient(url=settings.qdrant.url)
    try:
        collections = client.get_collections()
        count = len(collections.collections or [])
        return SubsystemTestResult(
            True,
            f"{count} collection(s)",
            time.perf_counter() - started,
        )
    except Exception as exc:
        return SubsystemTestResult(False, f"error: {exc}", time.perf_counter() - started)


async def _test_code_mode(deps: SelfTestDependencies) -> SubsystemTestResult:
    """Verify Code-Mode tool discovery."""
    started = time.perf_counter()
    if deps.code_mode.client is None:
        return SubsystemTestResult(False, "not configured", time.perf_counter() - started)
    try:
        response = await deps.code_mode.search_tools("list tools")
        if response.startswith("Code-Mode is not configured"):
            return SubsystemTestResult(False, "not configured", time.perf_counter() - started)
        if _has_tool_results(response):
            return SubsystemTestResult(True, "tools listed", time.perf_counter() - started)
        return SubsystemTestResult(False, "empty tool search", time.perf_counter() - started)
    except Exception as exc:
        return SubsystemTestResult(False, f"error: {exc}", time.perf_counter() - started)


async def _test_mcp_filesystem(deps: SelfTestDependencies) -> SubsystemTestResult:
    """Verify MCP filesystem access by listing an allowed directory."""
    started = time.perf_counter()
    if deps.code_mode.client is None:
        return SubsystemTestResult(False, "not configured", time.perf_counter() - started)
    try:
        allowed_code = "result = filesystem.list_allowed_directories({})\nreturn result"
        allowed_output = await deps.code_mode.call_tool_chain(allowed_code)
        allowed_raw = extract_code_mode_result(allowed_output)
        allowed_parsed = parse_code_mode_payload(allowed_raw)
        allowed_dirs = extract_allowed_directories(allowed_parsed)
        if not allowed_dirs:
            allowed_dirs = extract_allowed_directories_from_text(allowed_output)
        if not allowed_dirs:
            return SubsystemTestResult(
                False, "no allowed directories", time.perf_counter() - started
            )
        base_path = Path(allowed_dirs[0]).expanduser().resolve()
        code = f"result = filesystem.list_directory({{'path': {str(base_path)!r}}})\nreturn result"
        output = await deps.code_mode.call_tool_chain(code)
        raw = extract_code_mode_result(output)
        if _has_non_empty_listing(raw):
            return SubsystemTestResult(True, "base directory listed", time.perf_counter() - started)
        return SubsystemTestResult(
            False,
            "empty directory listing",
            time.perf_counter() - started,
        )
    except Exception as exc:
        return SubsystemTestResult(False, f"error: {exc}", time.perf_counter() - started)


async def _test_mcp_calendar(deps: SelfTestDependencies) -> SubsystemTestResult:
    """Verify MCP EventKit calendar access."""
    started = time.perf_counter()
    if deps.code_mode.client is None:
        return SubsystemTestResult(False, "not configured", time.perf_counter() - started)
    try:
        code = "result = eventkit.list_event_calendars({})\nreturn result"
        output = await deps.code_mode.call_tool_chain(code)
        raw = extract_code_mode_result(output)
        expected_calendar = settings.user.test_calendar_name
        if _has_non_empty_listing(raw) and contains_expected_name(raw, expected_calendar):
            return SubsystemTestResult(True, "calendars listed", time.perf_counter() - started)
        if _has_non_empty_listing(raw):
            return SubsystemTestResult(
                False,
                f"missing expected calendar: {expected_calendar}",
                time.perf_counter() - started,
            )
        return SubsystemTestResult(False, "no calendars", time.perf_counter() - started)
    except Exception as exc:
        return SubsystemTestResult(False, f"error: {exc}", time.perf_counter() - started)


async def _test_mcp_reminders(deps: SelfTestDependencies) -> SubsystemTestResult:
    """Verify MCP EventKit reminder list access."""
    started = time.perf_counter()
    if deps.code_mode.client is None:
        return SubsystemTestResult(False, "not configured", time.perf_counter() - started)
    try:
        code = "result = eventkit.list_calendars({})\nreturn result"
        output = await deps.code_mode.call_tool_chain(code)
        raw = extract_code_mode_result(output)
        expected_reminders = settings.user.test_reminder_list_name
        if _has_non_empty_listing(raw) and contains_expected_name(raw, expected_reminders):
            return SubsystemTestResult(True, "reminder lists listed", time.perf_counter() - started)
        if _has_non_empty_listing(raw):
            return SubsystemTestResult(
                False,
                f"missing expected reminder list: {expected_reminders}",
                time.perf_counter() - started,
            )
        return SubsystemTestResult(False, "no reminder lists", time.perf_counter() - started)
    except Exception as exc:
        return SubsystemTestResult(False, f"error: {exc}", time.perf_counter() - started)


async def _test_mcp_github(deps: SelfTestDependencies) -> SubsystemTestResult:
    """Verify MCP GitHub connectivity by fetching the authenticated user."""
    started = time.perf_counter()
    if deps.code_mode.client is None:
        return SubsystemTestResult(False, "not configured", time.perf_counter() - started)
    try:
        code = "result = github.get_me({})\nreturn result"
        output = await deps.code_mode.call_tool_chain(code)
        raw = extract_code_mode_result(output)
        if _has_non_empty_listing(raw):
            return SubsystemTestResult(True, "authenticated user", time.perf_counter() - started)
        return SubsystemTestResult(False, "empty response", time.perf_counter() - started)
    except Exception as exc:
        return SubsystemTestResult(False, f"error: {exc}", time.perf_counter() - started)


async def _to_thread(func: Callable[..., object], *args: object) -> object:
    """Run a sync function in the default thread pool."""
    import asyncio

    return await asyncio.to_thread(func, *args)


def _has_non_empty_listing(raw: str | None) -> bool:
    """Return True when a Code-Mode listing payload is non-empty."""
    if raw is None:
        return False
    if raw in ("", "None", "null", "[]", "{}"):
        return False
    parsed = parse_code_mode_payload(raw)
    text = extract_content_text(parsed)
    if text is not None:
        return bool(text.strip())
    if isinstance(parsed, (list, tuple, set, dict)):
        return bool(parsed)
    return parsed is not None


def _has_tool_results(raw: str) -> bool:
    """Return True when a Code-Mode tool search includes tool rows."""
    return bool(re.search(r"^- \S+:", raw, re.MULTILINE))
