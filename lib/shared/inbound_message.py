"""Canonical inbound operator message contracts shared by adapters and Relay."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from lib.shared.auth.slash_authenticity import SlashAuthenticityProof


class InboundSender(BaseModel):
    """Normalized sender identity supplied by an inbound adapter."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    id: str = ""
    display_name: str = ""
    e164: str = ""


class InboundMessageRef(BaseModel):
    """Reference to another channel-local message."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    channel_message_id: str = ""
    timestamp_ms: int | None = None


class InboundThreadRef(BaseModel):
    """Thread/conversation reference normalized by an adapter."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    id: str = ""
    title: str = ""


class InboundReaction(BaseModel):
    """Reaction attached to another inbound message."""

    model_config = ConfigDict(frozen=True, extra="forbid")
    text: str
    target: InboundMessageRef | None = None


class InboundLink(BaseModel):
    """URL detected in or supplied with an inbound message."""

    model_config = ConfigDict(frozen=True, extra="forbid")
    url: str
    label: str = ""


class InboundAttachment(BaseModel):
    """Attachment metadata normalized by an inbound adapter."""

    model_config = ConfigDict(frozen=True, extra="forbid")
    kind: Literal["image", "file", "audio", "video", "unknown"] = "unknown"
    name: str = ""
    content_type: str = ""
    size_bytes: int | None = None
    adapter_ref: str = ""
    metadata: dict[str, str] = Field(default_factory=dict)


class InboundApproval(BaseModel):
    """Approval/rejection intent detected before Relay consumption."""

    model_config = ConfigDict(frozen=True, extra="forbid")
    intent: Literal["approve", "reject"]
    source: Literal["text", "reaction"]
    token: str = ""


class InboundSlashCommand(BaseModel):
    """Slash command detected in an inbound operator message."""

    model_config = ConfigDict(frozen=True, extra="forbid")
    name: str
    args_text: str = ""


class InboundMessage(BaseModel):
    """High-water-mark inbound operator message DTO consumed by Relay."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    channel: str
    sender: InboundSender = Field(default_factory=InboundSender)
    message_text: str = ""
    timestamp_ms: int
    source_device: str = ""
    thread: InboundThreadRef | None = None
    reply_to: InboundMessageRef | None = None
    reaction: InboundReaction | None = None
    links: tuple[InboundLink, ...] = ()
    attachments: tuple[InboundAttachment, ...] = ()
    approval: InboundApproval | None = None
    slash_command: InboundSlashCommand | None = None
    slash_authenticity: SlashAuthenticityProof | None = None
    reply_to_proposal_token: str = ""
    reaction_to_proposal_token: str = ""
    raw_metadata: dict[str, str] = Field(default_factory=dict)

    def relay_payload(self) -> dict[str, Any]:
        """Return a JSON-safe payload for queue persistence."""
        return self.model_dump(mode="json")


__all__ = [
    "InboundApproval",
    "InboundAttachment",
    "InboundLink",
    "InboundMessage",
    "InboundMessageRef",
    "InboundReaction",
    "InboundSender",
    "InboundSlashCommand",
    "InboundThreadRef",
]
