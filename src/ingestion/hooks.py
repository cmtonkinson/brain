"""Ingestion hook registry and filter helpers."""

from __future__ import annotations

import inspect
import threading
import uuid
from dataclasses import dataclass
from typing import Callable, Sequence
from uuid import UUID

from ingestion.constants import STAGE_SET
from models import ProvenanceRecord, ProvenanceSource

CallbackType = Callable[[UUID, str, Sequence[ProvenanceRecord]], None]


@dataclass(frozen=True)
class StageArtifactDescriptor:
    """Lightweight descriptor for stage artifacts used during filter evaluation."""

    object_key: str
    mime_type: str | None
    size_bytes: int | None
    artifact_type: str | None
    sources: tuple[ProvenanceSource, ...]

    @property
    def source_types(self) -> tuple[str, ...]:
        """Return the source_type values captured for the descriptor."""
        return tuple(source.source_type for source in self.sources)

    @property
    def source_uris(self) -> tuple[str | None, ...]:
        """Return the source URI values associated with the descriptor."""
        return tuple(source.source_uri for source in self.sources)


@dataclass(frozen=True)
class HookFilters:
    """Filters that narrow hook invocation eligibility."""

    mime_types: frozenset[str] | None = None
    source_types: frozenset[str] | None = None
    min_size_bytes: int | None = None
    max_size_bytes: int | None = None
    artifact_types: frozenset[str] | None = None
    source_uri_matches: frozenset[str] | None = None

    def __post_init__(self) -> None:
        """Normalize filter collections and enforce invariants."""
        object.__setattr__(self, "mime_types", _normalize_set(self.mime_types))
        object.__setattr__(self, "source_types", _normalize_set(self.source_types))
        object.__setattr__(self, "artifact_types", _normalize_set(self.artifact_types))
        object.__setattr__(self, "source_uri_matches", _normalize_set(self.source_uri_matches))
        if self.min_size_bytes is not None and self.min_size_bytes < 0:
            raise ValueError("min_size_bytes must be non-negative")
        if self.max_size_bytes is not None and self.max_size_bytes < 0:
            raise ValueError("max_size_bytes must be non-negative")
        if (
            self.min_size_bytes is not None
            and self.max_size_bytes is not None
            and self.min_size_bytes > self.max_size_bytes
        ):
            raise ValueError("min_size_bytes cannot be greater than max_size_bytes")

    def matches(self, descriptor: StageArtifactDescriptor) -> bool:
        """Return True when the descriptor satisfies the filters."""
        if self.mime_types and (descriptor.mime_type not in self.mime_types):
            return False
        if self.artifact_types and (descriptor.artifact_type not in self.artifact_types):
            return False
        if self.source_types and not any(
            source_type in self.source_types for source_type in descriptor.source_types
        ):
            return False
        if self.min_size_bytes is not None:
            if descriptor.size_bytes is None or descriptor.size_bytes < self.min_size_bytes:
                return False
        if self.max_size_bytes is not None:
            if descriptor.size_bytes is None or descriptor.size_bytes > self.max_size_bytes:
                return False
        if self.source_uri_matches and not any(
            _matches_uri(uri, self.source_uri_matches) for uri in descriptor.source_uris
        ):
            return False
        return True

    def is_defensive(self) -> bool:
        """Return True when the filters impose any constraints."""
        return any(
            (
                self.mime_types,
                self.source_types,
                self.artifact_types,
                self.source_uri_matches,
                self.min_size_bytes is not None,
                self.max_size_bytes is not None,
            )
        )


@dataclass(frozen=True)
class HookRegistration:
    """Information stored for a registered hook."""

    hook_id: UUID
    stage: str
    callback: CallbackType
    filters: HookFilters | None


class HookRegistry:
    """In-memory registry for hook callbacks."""

    def __init__(self) -> None:
        """Initialize the registry with thread-safety primitives."""
        self._lock = threading.RLock()
        self._hooks: dict[UUID, HookRegistration] = {}

    def register_hook(
        self, stage: str, callback: CallbackType, filters: HookFilters | None = None
    ) -> UUID:
        """Register a hook and return its identifier."""
        self._validate_stage(stage)
        self._validate_callback(callback)
        hook_id = uuid.uuid4()
        registration = HookRegistration(
            stage=stage, callback=callback, filters=filters, hook_id=hook_id
        )
        with self._lock:
            self._hooks[hook_id] = registration
        return hook_id

    def unregister_hook(self, hook_id: UUID) -> bool:
        """Remove a hook by its identifier."""
        with self._lock:
            return self._hooks.pop(hook_id, None) is not None

    def hooks_for_stage(self, stage: str) -> tuple[HookRegistration, ...]:
        """Return registered hooks applicable to the stage."""
        self._validate_stage(stage)
        with self._lock:
            return tuple(reg for reg in self._hooks.values() if reg.stage == stage)

    def clear(self) -> None:
        """Remove all registered hooks."""
        with self._lock:
            self._hooks.clear()

    def _validate_stage(self, stage: str) -> None:
        """Ensure the provided stage is recognized."""
        if stage not in STAGE_SET:
            raise ValueError(f"unknown stage: {stage}")

    def _validate_callback(self, callback: CallbackType) -> None:
        """Ensure the callback signature matches the expected shape."""
        signature = inspect.signature(callback)
        parameters = [
            param
            for param in signature.parameters.values()
            if param.kind
            in (inspect.Parameter.POSITIONAL_ONLY, inspect.Parameter.POSITIONAL_OR_KEYWORD)
        ]
        if len(parameters) != 3 or any(
            param.kind in (inspect.Parameter.VAR_POSITIONAL, inspect.Parameter.VAR_KEYWORD)
            for param in signature.parameters.values()
        ):
            raise TypeError("hooks must accept exactly three positional arguments")


_REGISTRY = HookRegistry()


def register_hook(
    stage: str,
    callback: CallbackType,
    *,
    filters: HookFilters | None = None,
) -> UUID:
    """Register a hook callback for the given stage."""
    return _REGISTRY.register_hook(stage, callback, filters)


def unregister_hook(hook_id: UUID) -> bool:
    """Unregister a previously registered hook."""
    return _REGISTRY.unregister_hook(hook_id)


def hooks_for_stage(stage: str) -> tuple[HookRegistration, ...]:
    """Return the hooks configured for a stage."""
    return _REGISTRY.hooks_for_stage(stage)


def clear_hooks() -> None:
    """Remove all hooks from the global registry (tests only)."""
    _REGISTRY.clear()


def get_hook_registry() -> HookRegistry:
    """Return the default hook registry instance."""
    return _REGISTRY


def _normalize_set(value: Sequence[str] | None) -> frozenset[str] | None:
    """Convert a sequence of strings into a frozenset or None."""
    if value is None:
        return None
    return frozenset(str(item) for item in value)


def _matches_uri(uri: str | None, patterns: frozenset[str]) -> bool:
    """Return True when the uri matches any configured pattern."""
    if uri is None:
        return False
    return any(pattern in uri or uri.startswith(pattern) for pattern in patterns)
