"""Mock Signal client for skill tests."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class MockSignalClient:
    sent_messages: list[dict[str, str]] = field(default_factory=list)

    async def send_message(self, recipient: str, body: str) -> dict[str, str]:
        self.sent_messages.append({"recipient": recipient, "body": body})
        return {"message_id": f"mock-{len(self.sent_messages)}"}
