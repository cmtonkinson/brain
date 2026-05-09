"""Shared parsing helpers for inbound operator message text."""

from __future__ import annotations

import re

from lib.shared.approval import normalize_approval_intent
from lib.shared.config import ApprovalResponseSettings
from lib.shared.inbound_message import InboundApproval, InboundLink, InboundSlashCommand

_SLASH_COMMAND_RE = re.compile(r"^/([a-zA-Z][a-zA-Z0-9-]*)(?:\s+(.*))?$", re.DOTALL)
_URL_RE = re.compile(r"https?://[^\s<>()]+[^\s<>().,;:'\"]")
_TOKEN_RE = re.compile(r"\b([a-fA-F0-9]{16,64})\b")


def parse_slash_command(message_text: str) -> InboundSlashCommand | None:
    """Return a slash command when *message_text* is exactly command-shaped."""
    match = _SLASH_COMMAND_RE.match(message_text.strip())
    if match is None:
        return None
    return InboundSlashCommand(
        name=match.group(1).lower(),
        args_text=(match.group(2) or "").strip(),
    )


def parse_links(message_text: str) -> tuple[InboundLink, ...]:
    """Extract plain URLs from inbound text without transport-specific metadata."""
    seen: set[str] = set()
    links: list[InboundLink] = []
    for match in _URL_RE.finditer(message_text):
        url = match.group(0)
        if url in seen:
            continue
        seen.add(url)
        links.append(InboundLink(url=url))
    return tuple(links)


def parse_text_approval(
    message_text: str,
    *,
    settings: ApprovalResponseSettings | None = None,
) -> InboundApproval | None:
    """Return approval intent and optional token from operator text."""
    intent = normalize_approval_intent(message_text=message_text, settings=settings)
    if intent is None:
        return None
    token_match = _TOKEN_RE.search(message_text)
    return InboundApproval(
        intent=intent,
        source="text",
        token="" if token_match is None else token_match.group(1),
    )


__all__ = ["parse_links", "parse_slash_command", "parse_text_approval"]
