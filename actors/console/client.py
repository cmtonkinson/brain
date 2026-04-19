"""Thin wrapper around BrainSdkClient for console TUI operations."""

from __future__ import annotations

from packages.brain_sdk import (
    BrainSdkClient,
    ConsoleEnqueueResult,
    ConsoleResponseMessage,
    MemoryContextBlock,
    MemorySessionRef,
)


class ConsoleClient:
    """Synchronous Brain SDK client pre-configured for console channel operations."""

    def __init__(self, *, host: str, port: int, timeout_seconds: float) -> None:
        self._sdk = BrainSdkClient(
            host=host,
            port=port,
            timeout_seconds=timeout_seconds,
            source="console",
            principal="operator",
        )

    def ingest(self, text: str) -> ConsoleEnqueueResult:
        """Submit one operator message to Brain via the console channel."""
        return self._sdk.switchboard_enqueue_console(message_text=text)

    def poll_response(
        self, *, wait_timeout_seconds: float = 30.0
    ) -> ConsoleResponseMessage | None:
        """Long-poll for the next Brain response on the console channel."""
        return self._sdk.switchboard_poll_console_response(
            wait_timeout_seconds=wait_timeout_seconds,
        )

    def load_history(self) -> list[tuple[str, str]]:
        """Load recent conversation history as (role, content) pairs.

        Returns turns from the shared memory session. ``role`` is ``"user"``
        for operator messages and ``"assistant"`` for Brain responses.
        """
        session: MemorySessionRef = self._sdk.memory_get_latest_or_create_session()
        snapshot: MemoryContextBlock = self._sdk.memory_assemble_snapshot(
            session_id=session.session_id,
            exclude_latest=False,
        )
        return [
            (turn.role, turn.content)
            for turn in snapshot.recent_turns
            if not turn.is_summary
        ]

    def close(self) -> None:
        """Release underlying HTTP resources."""
        self._sdk.close()
