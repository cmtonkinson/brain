"""Tests for DAG orchestration, readiness polling, and retry semantics."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

import pytest

from packages.brain_core.boot.contracts import (
    BootDependencyError,
    BootHookContract,
    BootHookExecutionError,
    BootReadinessTimeoutError,
)
from packages.brain_core.boot.orchestrator import run_boot_hooks
from packages.brain_shared.config import CoreBootSettings


@dataclass(slots=True)
class _FakeClock:
    """Deterministic monotonic time source for timeout/retry tests."""

    now: float = 0.0

    def monotonic(self) -> float:
        """Return current fake monotonic timestamp."""
        return self.now

    def sleep(self, duration: float) -> None:
        """Advance fake time by requested sleep duration."""
        self.now += duration


def _hook(
    *,
    component_id: str,
    dependencies: tuple[str, ...] = tuple(),
    is_ready: Callable[[], bool] | None = None,
    boot: Callable[[], None] | None = None,
) -> BootHookContract:
    """Build one test hook contract with defaults."""
    return BootHookContract(
        component_id=component_id,
        module_name=f"{component_id}.boot",
        dependencies=dependencies,
        is_ready=is_ready or (lambda: True),
        boot=boot or (lambda: None),
    )


def test_run_boot_hooks_executes_in_topological_order() -> None:
    """Hooks should execute after dependencies according to DAG order."""
    executed: list[str] = []
    hooks = (
        _hook(component_id="service_a", boot=lambda: executed.append("service_a")),
        _hook(
            component_id="service_b",
            dependencies=("service_a",),
            boot=lambda: executed.append("service_b"),
        ),
    )

    result = run_boot_hooks(hooks, settings=CoreBootSettings())

    assert result.execution_order == ("service_a", "service_b")
    assert executed == ["service_a", "service_b"]


def test_run_boot_hooks_polls_readiness_until_ready() -> None:
    """Hooks should poll readiness and only execute once ready."""
    ready_counter = {"calls": 0}

    def is_ready() -> bool:
        ready_counter["calls"] += 1
        return ready_counter["calls"] >= 3

    executed: list[str] = []
    clock = _FakeClock()
    hooks = (
        _hook(
            component_id="service_a",
            is_ready=is_ready,
            boot=lambda: executed.append("booted"),
        ),
    )

    run_boot_hooks(
        hooks,
        settings=CoreBootSettings(readiness_poll_interval_seconds=1.0),
        sleeper=clock.sleep,
        monotonic=clock.monotonic,
    )

    assert executed == ["booted"]
    assert ready_counter["calls"] == 3
    assert clock.now == 2.0


def test_run_boot_hooks_retries_boot_until_success() -> None:
    """Hook execution should retry failures up to configured max attempts."""
    attempts = {"count": 0}

    def flaky_boot() -> None:
        attempts["count"] += 1
        if attempts["count"] < 3:
            raise RuntimeError("transient failure")

    clock = _FakeClock()

    run_boot_hooks(
        (_hook(component_id="service_a", boot=flaky_boot),),
        settings=CoreBootSettings(boot_retry_attempts=3, boot_retry_delay_seconds=2.0),
        sleeper=clock.sleep,
        monotonic=clock.monotonic,
    )

    assert attempts["count"] == 3
    assert clock.now == 4.0


def test_run_boot_hooks_fails_hard_on_boot_failure() -> None:
    """Permanent hook failure should abort orchestration immediately."""
    executed: list[str] = []

    def boom() -> None:
        raise RuntimeError("fatal")

    hooks = (
        _hook(component_id="service_a", boot=boom),
        _hook(
            component_id="service_b",
            dependencies=("service_a",),
            boot=lambda: executed.append("service_b"),
        ),
    )

    with pytest.raises(BootHookExecutionError):
        run_boot_hooks(hooks, settings=CoreBootSettings(boot_retry_attempts=2))

    assert executed == []


def test_run_boot_hooks_raises_on_missing_dependency() -> None:
    """Unknown dependency references should fail validation before execution."""
    hooks = (_hook(component_id="service_a", dependencies=("service_missing",)),)

    with pytest.raises(BootDependencyError):
        run_boot_hooks(hooks, settings=CoreBootSettings())


def test_run_boot_hooks_raises_on_cycle() -> None:
    """Cyclic dependency graphs should be rejected."""
    hooks = (
        _hook(component_id="service_a", dependencies=("service_b",)),
        _hook(component_id="service_b", dependencies=("service_a",)),
    )

    with pytest.raises(BootDependencyError):
        run_boot_hooks(hooks, settings=CoreBootSettings())


def test_run_boot_hooks_raises_when_readiness_times_out() -> None:
    """Readiness probes should fail when timeout elapses before readiness."""
    clock = _FakeClock()
    hooks = (_hook(component_id="service_a", is_ready=lambda: False),)

    with pytest.raises(BootReadinessTimeoutError):
        run_boot_hooks(
            hooks,
            settings=CoreBootSettings(
                readiness_poll_interval_seconds=1.0,
                readiness_timeout_seconds=2.0,
            ),
            sleeper=clock.sleep,
            monotonic=clock.monotonic,
        )


def test_run_boot_hooks_raises_when_boot_duration_exceeds_timeout() -> None:
    """Hook execution should fail when boot runtime exceeds configured timeout."""
    clock = _FakeClock()

    def slow_boot() -> None:
        clock.sleep(6.0)

    with pytest.raises(BootHookExecutionError):
        run_boot_hooks(
            (_hook(component_id="service_a", boot=slow_boot),),
            settings=CoreBootSettings(boot_timeout_seconds=5.0),
            sleeper=clock.sleep,
            monotonic=clock.monotonic,
        )
