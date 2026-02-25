"""Request validation models for Attention Router Service public API."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field, field_validator


def _strip_text(value: object) -> object:
    """Normalize surrounding whitespace for textual request fields."""
    if isinstance(value, str):
        return value.strip()
    return value


class RouteNotificationRequest(BaseModel):
    """Validate one outbound route-notification request payload."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    actor: str = Field(default="operator", min_length=1)
    channel: str = Field(default="", min_length=0)
    title: str = Field(default="", min_length=0)
    message: str = Field(min_length=1)
    recipient_e164: str = Field(default="", min_length=0)
    sender_e164: str = Field(default="", min_length=0)
    dedupe_key: str = Field(default="", min_length=0)
    batch_key: str = Field(default="", min_length=0)
    force: bool = False

    @field_validator(
        "actor",
        "channel",
        "title",
        "message",
        "recipient_e164",
        "sender_e164",
        "dedupe_key",
        "batch_key",
        mode="before",
    )
    @classmethod
    def _strip_fields(cls, value: object) -> object:
        """Normalize textual payload fields before validation."""
        return _strip_text(value)


class FlushBatchRequest(BaseModel):
    """Validate one batched notification flush request payload."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    batch_key: str = Field(min_length=1)
    actor: str = Field(default="operator", min_length=1)
    channel: str = Field(default="", min_length=0)
    recipient_e164: str = Field(default="", min_length=0)
    sender_e164: str = Field(default="", min_length=0)
    title: str = Field(default="", min_length=0)

    @field_validator(
        "batch_key",
        "actor",
        "channel",
        "recipient_e164",
        "sender_e164",
        "title",
        mode="before",
    )
    @classmethod
    def _strip_fields(cls, value: object) -> object:
        """Normalize textual payload fields before validation."""
        return _strip_text(value)


class CorrelateApprovalRequest(BaseModel):
    """Validate one approval-correlation normalization request payload."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    actor: str = Field(min_length=1)
    channel: str = Field(min_length=1)
    message_text: str = Field(default="", min_length=0)
    approval_token: str = Field(default="", min_length=0)
    reply_to_proposal_token: str = Field(default="", min_length=0)
    reaction_to_proposal_token: str = Field(default="", min_length=0)

    @field_validator(
        "actor",
        "channel",
        "message_text",
        "approval_token",
        "reply_to_proposal_token",
        "reaction_to_proposal_token",
        mode="before",
    )
    @classmethod
    def _strip_fields(cls, value: object) -> object:
        """Normalize textual payload fields before validation."""
        return _strip_text(value)
