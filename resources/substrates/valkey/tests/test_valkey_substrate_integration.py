"""Real-provider integration tests for Valkey substrate behavior."""

from __future__ import annotations

import pytest

from resources.substrates.valkey.config import ValkeySettings
from resources.substrates.valkey.valkey_substrate import ValkeyClientSubstrate
from tests.integration.helpers import real_provider_tests_enabled

pytest_plugins = ("tests.integration.fixtures",)


pytestmark = pytest.mark.skipif(
    not real_provider_tests_enabled(),
    reason="set BRAIN_RUN_INTEGRATION_REAL=1 to run real-provider integration tests",
)


def test_key_value_and_fifo_queue_roundtrip(valkey_url: str) -> None:
    """Valkey substrate should roundtrip key/value and queue operations."""
    substrate = ValkeyClientSubstrate(settings=ValkeySettings(url=valkey_url))
    key = "int:valkey:key"
    queue = "int:valkey:queue"

    substrate.set_value(key=key, value="v1", ttl_seconds=30)
    assert substrate.get_value(key=key) == "v1"
    assert substrate.delete_value(key=key) is True

    substrate.push_queue(queue=queue, value="a")
    substrate.push_queue(queue=queue, value="b")
    assert substrate.peek_queue(queue=queue) == "a"
    assert substrate.pop_queue(queue=queue) == "a"
