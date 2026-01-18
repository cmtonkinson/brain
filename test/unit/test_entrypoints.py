"""Unit tests for entrypoint context guards."""

import pytest

from entrypoints import EntrypointContext, EntrypointContextError, require_entrypoint_context


def test_entrypoint_guard_requires_actor():
    """Ensure the guard rejects missing actor context."""
    context = EntrypointContext(entrypoint="scheduler", actor=None, channel="cli")

    with pytest.raises(EntrypointContextError):
        require_entrypoint_context(context)


def test_entrypoint_guard_requires_channel():
    """Ensure the guard rejects missing channel context."""
    context = EntrypointContext(entrypoint="scheduler", actor="system", channel=None)

    with pytest.raises(EntrypointContextError):
        require_entrypoint_context(context)
