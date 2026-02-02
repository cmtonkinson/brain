"""Unit tests for the ingestion hook registry."""

from __future__ import annotations

from uuid import UUID

import pytest

from ingestion.hooks import HookFilters, clear_hooks, register_hook, unregister_hook


def _dummy_callback(ingestion_id: UUID, stage: str, records: tuple[object, ...]) -> None:
    """Simple hook used for registration tests."""
    return None


def test_register_and_unregister_hook() -> None:
    """Hooks can be registered and unregistered via their identifiers."""
    clear_hooks()
    hook_id = register_hook("extract", _dummy_callback)
    assert isinstance(hook_id, UUID)
    assert unregister_hook(hook_id) is True
    assert unregister_hook(hook_id) is False
    clear_hooks()


def test_register_hook_with_filters_accepts_valid_values() -> None:
    """Registering a hook with filters succeeds when the callback signature is valid."""
    clear_hooks()
    filters = HookFilters(mime_types={"text/plain"}, min_size_bytes=0, artifact_types={"raw"})
    hook_id = register_hook("store", _dummy_callback, filters=filters)
    assert isinstance(hook_id, UUID)
    clear_hooks()


def test_register_hook_rejects_invalid_signature() -> None:
    """Callbacks that do not accept three positional arguments are rejected."""
    clear_hooks()

    def wrong_callback(a: int, b: str) -> None:  # type: ignore[no-untyped-def]
        return None

    with pytest.raises(TypeError):
        register_hook("store", wrong_callback)
    clear_hooks()
