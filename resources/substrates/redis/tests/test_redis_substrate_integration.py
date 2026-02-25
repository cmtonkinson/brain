"""Real-provider integration tests for Redis substrate behavior."""

from __future__ import annotations

import pytest

from packages.brain_shared.config import load_settings
from resources.substrates.redis.config import resolve_redis_settings
from resources.substrates.redis.redis_substrate import RedisClientSubstrate
from tests.integration.helpers import real_provider_tests_enabled


pytestmark = pytest.mark.skipif(
    not real_provider_tests_enabled(),
    reason="set BRAIN_RUN_INTEGRATION_REAL=1 to run real-provider integration tests",
)


def test_key_value_and_fifo_queue_roundtrip() -> None:
    """Redis substrate should roundtrip key/value and queue operations."""
    substrate = RedisClientSubstrate(settings=resolve_redis_settings(load_settings()))
    key = "int:redis:key"
    queue = "int:redis:queue"

    substrate.set_value(key=key, value="v1", ttl_seconds=30)
    assert substrate.get_value(key=key) == "v1"
    assert substrate.delete_value(key=key) is True

    substrate.push_queue(queue=queue, value="a")
    substrate.push_queue(queue=queue, value="b")
    assert substrate.peek_queue(queue=queue) == "a"
    assert substrate.pop_queue(queue=queue) == "a"
