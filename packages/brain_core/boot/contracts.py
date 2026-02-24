"""Contracts and errors for Brain core boot hooks."""

from __future__ import annotations

from collections.abc import Callable, Iterable
from dataclasses import dataclass
import inspect
from typing import TypeVar

from packages.brain_shared.config import BrainSettings


class BootError(RuntimeError):
    """Base error for all core boot orchestration failures."""


class BootContractError(BootError):
    """Raised when a discovered ``boot.py`` module violates the hook contract."""


class BootDependencyError(BootError):
    """Raised when boot hook dependencies are invalid or unresolved."""


class BootReadinessTimeoutError(BootError):
    """Raised when a hook dependency never reports ready before timeout."""


class BootHookExecutionError(BootError):
    """Raised when a hook ``boot`` callable fails after all retry attempts."""


@dataclass(frozen=True, slots=True)
class BootHookContract:
    """Concrete callable contract loaded from one component ``boot.py`` module."""

    component_id: str
    module_name: str
    dependencies: tuple[str, ...]
    is_ready: Callable[[BootContext], bool]
    boot: Callable[[BootContext], None]


@dataclass(frozen=True, slots=True)
class BootAttempt:
    """One execution attempt for one component boot hook."""

    component_id: str
    attempt: int
    max_attempts: int


TResolved = TypeVar("TResolved")


@dataclass(frozen=True, slots=True)
class BootContext:
    """Runtime context shared with all component boot hooks."""

    settings: BrainSettings
    resolve_component: Callable[[str], object]

    def require_component(self, component_id: str) -> object:
        """Resolve one component runtime object or raise with stable message."""
        resolved = self.resolve_component(component_id)
        if resolved is None:
            raise BootDependencyError(
                f"boot context missing runtime instance for component '{component_id}'"
            )
        return resolved


def coerce_dependencies(value: object, *, module_name: str) -> tuple[str, ...]:
    """Validate and normalize one ``dependencies`` attribute into component ids."""
    if isinstance(value, str):
        raise BootContractError(
            f"{module_name}.dependencies must be an iterable of component ids, not str"
        )
    if not isinstance(value, Iterable):
        raise BootContractError(
            f"{module_name}.dependencies must be an iterable of component ids"
        )

    normalized: list[str] = []
    seen: set[str] = set()
    for raw in value:
        if not isinstance(raw, str) or not raw:
            raise BootContractError(
                f"{module_name}.dependencies must contain only non-empty strings"
            )
        if raw not in seen:
            normalized.append(raw)
            seen.add(raw)
    return tuple(normalized)


def require_context_callable(
    value: object, *, module_name: str, attribute_name: str
) -> Callable[[BootContext], object]:
    """Ensure one required attribute is a callable matching ``Callable[[BootContext], T]``."""
    if not callable(value):
        raise BootContractError(f"{module_name}.{attribute_name} must be callable")
    signature = inspect.signature(value)
    parameters = tuple(signature.parameters.values())
    if len(parameters) != 1:
        raise BootContractError(
            f"{module_name}.{attribute_name} must accept exactly one 'ctx' argument"
        )
    return value
