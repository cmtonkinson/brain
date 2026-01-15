"""Access control helpers for inbound message channels."""

from config import settings


def is_sender_allowed(channel: str, sender: str) -> bool:
    """Return True only if sender is explicitly allowed for the channel."""
    channel_allowlist = settings.signal.allowed_senders_by_channel.get(channel)
    if channel_allowlist is not None:
        return sender in channel_allowlist

    if channel == "signal":
        return sender in settings.signal.allowed_senders

    return False
