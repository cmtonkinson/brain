"""Signal messaging integration via signal-cli-rest-api."""

import logging
from datetime import datetime
from typing import Any

from config import settings
from models import SignalMessage
from attention.router_gate import ensure_router_context
from services.http_client import AsyncHttpClient, ErrorConfig, ErrorStrategy

logger = logging.getLogger(__name__)


class SignalClient:
    """Client for signal-cli-rest-api."""

    def __init__(self, api_url: str | None = None):
        """Initialize the client with the configured API URL."""
        self.api_url = (api_url or settings.signal.url).rstrip("/")

    async def poll_messages(self, phone_number: str) -> list[SignalMessage]:
        """Poll for new messages.

        Args:
            phone_number: The registered phone number to poll for

        Returns:
            List of new SignalMessage objects
        """
        logger.info("Signal poll request: %s", phone_number)
        client = AsyncHttpClient(
            error_config=ErrorConfig(strategy=ErrorStrategy.LOG_AND_RETURN_NONE)
        )
        response = await client.get(f"{self.api_url}/v1/receive/{phone_number}")
        if response is None:
            return []

        envelopes = response.json()
        messages = []
        for envelope_wrapper in envelopes:
            envelope = envelope_wrapper.get("envelope", {})
            data_message = envelope.get("dataMessage")

            # Skip non-data messages (receipts, typing indicators, etc.)
            if not data_message:
                continue

            # Skip empty messages
            message_text = data_message.get("message")
            if not message_text:
                continue

            # Parse timestamp (milliseconds since epoch)
            timestamp_ms = data_message.get("timestamp", 0)
            timestamp = datetime.fromtimestamp(timestamp_ms / 1000)

            messages.append(
                SignalMessage(
                    sender=envelope.get("source", "unknown"),
                    message=message_text,
                    timestamp=timestamp,
                    source_device=envelope.get("sourceDevice", 1),
                    expires_in_seconds=data_message.get("expiresInSeconds", 0),
                )
            )

        logger.info("Signal poll response: %s message(s)", len(messages))
        return messages

    async def send_message(
        self,
        from_number: str,
        to_number: str,
        message: str,
        *,
        source_component: str = "unknown",
    ) -> bool:
        """Send a message via Signal.

        Args:
            from_number: The sender's phone number (agent's number)
            to_number: The recipient's phone number
            message: The message text to send

        Returns:
            True if message was sent successfully, False otherwise
        """
        ensure_router_context(source_component, "signal")
        logger.info("Signal send request: to=%s chars=%s", to_number, len(message))
        client = AsyncHttpClient(
            error_config=ErrorConfig(strategy=ErrorStrategy.LOG_AND_RETURN_NONE)
        )
        response = await client.post(
            f"{self.api_url}/v2/send",
            json={
                "message": message,
                "text_mode": "styled",
                "number": from_number,
                "recipients": [to_number],
            },
        )

        if response is None:
            return False

        logger.info("Signal send response: to=%s status=success", to_number)
        return True

    async def get_accounts(self) -> list[dict[str, Any]]:
        """Get list of registered accounts.

        Returns:
            List of account information dicts
        """
        client = AsyncHttpClient(
            error_config=ErrorConfig(strategy=ErrorStrategy.LOG_AND_RETURN_NONE)
        )
        response = await client.get(f"{self.api_url}/v1/accounts")
        if response is None:
            return []
        return response.json()

    async def check_connection(self) -> bool:
        """Check if Signal API is reachable.

        Returns:
            True if API is reachable, False otherwise
        """
        client = AsyncHttpClient(error_config=ErrorConfig(strategy=ErrorStrategy.LOG_AND_SUPPRESS))
        response = await client.get(f"{self.api_url}/v1/about")
        return response is not None and response.status_code == 200
