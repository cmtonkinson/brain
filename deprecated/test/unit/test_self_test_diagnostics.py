"""Unit tests for the diagnostics self-test runner."""

from __future__ import annotations

import asyncio

from diagnostics import self_test


class _StubObsidian:
    """Minimal Obsidian stub for dependency wiring."""

    async def list_dir(self, path: str) -> list[str]:
        """Return a fixed list for testing."""
        return ["note.md"]


class _StubCodeMode:
    """Minimal Code-Mode stub for dependency wiring."""

    client = None


def _deps() -> self_test.SelfTestDependencies:
    """Build minimal dependencies for diagnostics tests."""
    return self_test.SelfTestDependencies(
        obsidian=_StubObsidian(),
        code_mode=_StubCodeMode(),
    )


def test_full_self_test_passes_when_all_pass(monkeypatch) -> None:
    """Ensure full self-test returns PASS when no subsystems fail."""

    async def _ok() -> self_test.SubsystemTestResult:
        return self_test.SubsystemTestResult(True, "ok", 0.01)

    monkeypatch.setattr(
        self_test,
        "_build_subsystem_tests",
        lambda deps: {"one": _ok, "two": _ok},
    )

    report = asyncio.run(self_test.run_full_self_test(_deps()))

    assert report["status"] == self_test.SelfTestStatus.PASS.value
    assert all(result["passed"] for result in report["results"].values())


def test_full_self_test_fails_when_none_pass(monkeypatch) -> None:
    """Ensure full self-test returns FAIL when no subsystems pass."""

    async def _fail() -> self_test.SubsystemTestResult:
        return self_test.SubsystemTestResult(False, "nope", 0.01)

    monkeypatch.setattr(
        self_test,
        "_build_subsystem_tests",
        lambda deps: {"one": _fail, "two": _fail},
    )

    report = asyncio.run(self_test.run_full_self_test(_deps()))

    assert report["status"] == self_test.SelfTestStatus.FAIL.value
    assert all(not result["passed"] for result in report["results"].values())


def test_full_self_test_partial_when_mixed(monkeypatch) -> None:
    """Ensure full self-test returns PARTIAL when mixed outcomes occur."""

    async def _ok() -> self_test.SubsystemTestResult:
        return self_test.SubsystemTestResult(True, "ok", 0.01)

    async def _fail() -> self_test.SubsystemTestResult:
        return self_test.SubsystemTestResult(False, "nope", 0.01)

    monkeypatch.setattr(
        self_test,
        "_build_subsystem_tests",
        lambda deps: {"one": _ok, "two": _fail},
    )

    report = asyncio.run(self_test.run_full_self_test(_deps()))

    assert report["status"] == self_test.SelfTestStatus.PARTIAL.value
    assert {"one", "two"} == set(report["results"].keys())


def test_run_subsystem_test_unknown_returns_failure() -> None:
    """Ensure unknown subsystem tests return a failed result."""
    result = asyncio.run(self_test.run_subsystem_test("missing", _deps()))

    assert result["passed"] is False
    assert "Unknown subsystem test" in str(result["message"])


def test_format_self_test_report_includes_summary() -> None:
    """Ensure formatting includes status and subsystem details."""
    report = self_test.SelfTestReport(
        status=self_test.SelfTestStatus.PARTIAL,
        results={
            "one": self_test.SubsystemTestResult(True, "ok", 0.01),
            "two": self_test.SubsystemTestResult(False, "nope", 0.02),
        },
    )

    rendered = self_test.format_self_test_report(report.as_dict())

    assert "Self-test: PARTIAL" in rendered
    assert "- one: PASS" in rendered
    assert "- two: FAIL" in rendered
