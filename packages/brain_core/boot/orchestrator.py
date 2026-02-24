"""DAG-based orchestration for component boot hooks."""

from __future__ import annotations

import time
from dataclasses import dataclass
from collections.abc import Callable
from graphlib import CycleError, TopologicalSorter

from packages.brain_shared.config import CoreBootSettings

from .contracts import (
    BootDependencyError,
    BootHookContract,
    BootHookExecutionError,
    BootReadinessTimeoutError,
)


@dataclass(frozen=True, slots=True)
class BootResult:
    """Result metadata from one completed full boot plan."""

    execution_order: tuple[str, ...]


def run_boot_hooks(
    hooks: tuple[BootHookContract, ...],
    *,
    settings: CoreBootSettings,
    sleeper: Callable[[float], None] = time.sleep,
    monotonic: Callable[[], float] = time.monotonic,
) -> BootResult:
    """Execute discovered boot hooks in dependency order and fail on first error."""
    if not hooks:
        return BootResult(execution_order=tuple())

    by_component: dict[str, BootHookContract] = {}
    for hook in hooks:
        previous = by_component.get(hook.component_id)
        if previous is not None and previous.module_name != hook.module_name:
            raise BootDependencyError(
                f"duplicate boot hook definitions for component '{hook.component_id}'"
            )
        by_component[hook.component_id] = hook

    graph: dict[str, tuple[str, ...]] = {}
    for hook in hooks:
        missing = sorted(dep for dep in hook.dependencies if dep not in by_component)
        if missing:
            raise BootDependencyError(
                f"component '{hook.component_id}' references missing boot dependencies: {missing}"
            )
        graph[hook.component_id] = hook.dependencies

    try:
        sorter = TopologicalSorter(graph)
        ordered_components = tuple(sorter.static_order())
    except CycleError as exc:
        raise BootDependencyError(f"boot dependency cycle detected: {exc}") from exc

    execution_order: list[str] = []
    for component_id in ordered_components:
        hook = by_component[component_id]
        _wait_for_readiness(
            hook=hook,
            timeout_seconds=settings.readiness_timeout_seconds,
            poll_interval_seconds=settings.readiness_poll_interval_seconds,
            sleeper=sleeper,
            monotonic=monotonic,
        )
        _execute_with_retries(
            hook=hook,
            retry_attempts=settings.boot_retry_attempts,
            retry_delay_seconds=settings.boot_retry_delay_seconds,
            timeout_seconds=settings.boot_timeout_seconds,
            sleeper=sleeper,
            monotonic=monotonic,
        )
        execution_order.append(component_id)

    return BootResult(execution_order=tuple(execution_order))


def _wait_for_readiness(
    *,
    hook: BootHookContract,
    timeout_seconds: float,
    poll_interval_seconds: float,
    sleeper: Callable[[float], None],
    monotonic: Callable[[], float],
) -> None:
    """Poll one hook readiness until true or timeout."""
    deadline = monotonic() + timeout_seconds
    while True:
        if bool(hook.is_ready()):
            return
        if monotonic() >= deadline:
            raise BootReadinessTimeoutError(
                f"boot readiness timed out for component '{hook.component_id}'"
            )
        sleeper(poll_interval_seconds)


def _execute_with_retries(
    *,
    hook: BootHookContract,
    retry_attempts: int,
    retry_delay_seconds: float,
    timeout_seconds: float,
    sleeper: Callable[[float], None],
    monotonic: Callable[[], float],
) -> None:
    """Execute one boot hook with fail-hard retries and runtime timeout checks."""
    failure: Exception | None = None
    for attempt in range(1, retry_attempts + 1):
        started = monotonic()
        try:
            hook.boot()
        except Exception as exc:  # pragma: no cover - explicit fail-hard policy
            failure = exc
            if attempt < retry_attempts and retry_delay_seconds > 0:
                sleeper(retry_delay_seconds)
            continue

        elapsed = monotonic() - started
        if elapsed > timeout_seconds:
            raise BootHookExecutionError(
                "boot hook exceeded timeout for "
                f"component '{hook.component_id}': {elapsed:.3f}s > {timeout_seconds:.3f}s"
            )
        return

    raise BootHookExecutionError(
        f"boot hook failed for component '{hook.component_id}' after {retry_attempts} attempts"
    ) from failure
