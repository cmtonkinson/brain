"""Mock Signal client for skill tests."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class MockSignalClient:
    """Mock Signal client that records outbound messages."""

    sent_messages: list[dict[str, str]] = field(default_factory=list)

    async def send_message(self, recipient: str, body: str) -> dict[str, str]:
        """Record a sent message and return a mock id."""
        self.sent_messages.append({"recipient": recipient, "body": body})
        return {"message_id": f"mock-{len(self.sent_messages)}"}
