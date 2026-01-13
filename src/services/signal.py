"""Signal messaging integration via signal-cli-rest-api."""

import logging
from datetime import datetime
from typing import Any

import httpx

from config import settings
from models import SignalMessage

logger = logging.getLogger(__name__)


class SignalClient:
    """Client for signal-cli-rest-api."""

    def __init__(self, api_url: str | None = None):
        self.api_url = (api_url or settings.signal_api_url).rstrip("/")

    async def poll_messages(self, phone_number: str) -> list[SignalMessage]:
        """Poll for new messages.

        Args:
            phone_number: The registered phone number to poll for

        Returns:
            List of new SignalMessage objects
        """
        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                response = await client.get(
                    f"{self.api_url}/v1/receive/{phone_number}"
                )
                response.raise_for_status()
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

            if messages:
                logger.info(f"Received {len(messages)} new message(s)")

            return messages

        except httpx.HTTPStatusError as e:
            logger.error(f"Signal API error: {e}")
            return []
        except httpx.RequestError as e:
            logger.error(f"Signal connection error: {e}")
            return []
        except Exception as e:
            logger.error(f"Error polling messages: {e}")
            return []

    async def send_message(
        self,
        from_number: str,
        to_number: str,
        message: str,
    ) -> bool:
        """Send a message via Signal.

        Args:
            from_number: The sender's phone number (agent's number)
            to_number: The recipient's phone number
            message: The message text to send

        Returns:
            True if message was sent successfully, False otherwise
        """
        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                response = await client.post(
                    f"{self.api_url}/v2/send",
                    json={
                        "message": message,
                        "text_mode": "styled",
                        "number": from_number,
                        "recipients": [to_number],
                    },
                )
                response.raise_for_status()

            logger.info(f"Sent message to {to_number}")
            return True

        except httpx.HTTPStatusError as e:
            logger.error(f"Failed to send message: {e}")
            return False
        except httpx.RequestError as e:
            logger.error(f"Signal connection error: {e}")
            return False

    async def get_accounts(self) -> list[dict[str, Any]]:
        """Get list of registered accounts.

        Returns:
            List of account information dicts
        """
        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                response = await client.get(f"{self.api_url}/v1/accounts")
                response.raise_for_status()
                return response.json()
        except Exception as e:
            logger.error(f"Failed to get accounts: {e}")
            return []

    async def check_connection(self) -> bool:
        """Check if Signal API is reachable.

        Returns:
            True if API is reachable, False otherwise
        """
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                response = await client.get(f"{self.api_url}/v1/about")
                return response.status_code == 200
        except Exception:
            return False
