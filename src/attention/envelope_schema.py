"""Schema definitions for attention router notification envelopes."""

from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import Any
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator, model_validator


class EnvelopeDecision(str, Enum):
    """Decision outcomes for envelope validation."""

    ACCEPT = "ACCEPT"
    LOG_ONLY = "LOG_ONLY"


class ProvenanceInput(BaseModel):
    """Normalized provenance input metadata for a notification."""

    model_config = ConfigDict(extra="forbid")

    input_type: str = Field(..., min_length=1)
    reference: str = Field(..., min_length=1)
    description: str | None = None

    @field_validator("input_type", "reference")
    @classmethod
    def _strip_required(cls, value: str) -> str:
        """Normalize required string fields."""
        normalized = value.strip()
        if not normalized:
            raise ValueError("Required fields must be non-empty strings.")
        return normalized

    @field_validator("description")
    @classmethod
    def _strip_description(cls, value: str | None) -> str | None:
        """Normalize optional descriptions."""
        if value is None:
            return None
        normalized = value.strip()
        if not normalized:
            raise ValueError("description must be non-empty when provided.")
        return normalized


class NotificationEnvelope(BaseModel):
    """Versioned wrapper for notification payload metadata."""

    model_config = ConfigDict(extra="forbid")

    version: str = Field(..., min_length=1)
    source_component: str = Field(..., min_length=1)
    origin_signal: str = Field(..., min_length=1)
    confidence: float = Field(..., ge=0.0, le=1.0)
    provenance: list[ProvenanceInput] = Field(..., min_length=1)

    @field_validator("version", "source_component", "origin_signal")
    @classmethod
    def _strip_required_fields(cls, value: str) -> str:
        """Normalize required identifiers."""
        normalized = value.strip()
        if not normalized:
            raise ValueError("Required fields must be non-empty strings.")
        return normalized


class RoutingIntent(str, Enum):
    """Supported routing intents for attention requests."""

    DELIVER = "DELIVER"
    LOG_ONLY = "LOG_ONLY"


class ActionAuthorizationContext(BaseModel):
    """Action authorization metadata attached to routing requests."""

    model_config = ConfigDict(extra="forbid")

    autonomy_level: str | None = None
    approval_status: str | None = None
    policy_tags: list[str] = Field(default_factory=list)

    @field_validator("autonomy_level", "approval_status")
    @classmethod
    def _strip_optional(cls, value: str | None) -> str | None:
        """Normalize optional string fields."""
        if value is None:
            return None
        normalized = value.strip()
        if not normalized:
            raise ValueError("Optional fields must be non-empty when provided.")
        return normalized

    @field_validator("policy_tags")
    @classmethod
    def _strip_tags(cls, value: list[str]) -> list[str]:
        """Normalize policy tags and reject blanks."""
        normalized = [item.strip() for item in value if item is not None]
        if any(not item for item in normalized):
            raise ValueError("policy_tags must be non-empty strings.")
        return normalized


class SignalPayload(BaseModel):
    """Signal channel payload metadata."""

    model_config = ConfigDict(extra="forbid")

    from_number: str = Field(..., min_length=1)
    to_number: str = Field(..., min_length=1)
    message: str = Field(..., min_length=1)

    @field_validator("from_number", "to_number", "message")
    @classmethod
    def _strip_required(cls, value: str) -> str:
        """Normalize required payload fields."""
        normalized = value.strip()
        if not normalized:
            raise ValueError("Required fields must be non-empty strings.")
        return normalized


class RoutingEnvelope(BaseModel):
    """Normalized routing envelope for attention router requests."""

    model_config = ConfigDict(extra="forbid")

    version: str = Field(..., min_length=1)
    signal_type: str = Field(..., min_length=1)
    signal_reference: str = Field(..., min_length=1)
    actor: str = Field(..., min_length=1)
    owner: str = Field(..., min_length=1)
    channel_hint: str | None = None
    urgency: float = Field(..., ge=0.0, le=1.0)
    channel_cost: float = Field(..., ge=0.0, le=1.0)
    content_type: str = Field(..., min_length=1)
    correlation_id: str = Field(default_factory=lambda: uuid4().hex, min_length=1)
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    topic: str | None = None
    category: str | None = None
    routing_intent: RoutingIntent = RoutingIntent.DELIVER
    authorization: ActionAuthorizationContext | None = None
    signal_payload: SignalPayload | None = None
    notification: NotificationEnvelope

    @field_validator("version", "signal_type", "signal_reference", "actor", "owner", "content_type")
    @classmethod
    def _strip_required_fields(cls, value: str) -> str:
        """Normalize required routing fields."""
        normalized = value.strip()
        if not normalized:
            raise ValueError("Required fields must be non-empty strings.")
        return normalized

    @field_validator("channel_hint", "topic", "category")
    @classmethod
    def _strip_optional_fields(cls, value: str | None) -> str | None:
        """Normalize optional routing fields."""
        if value is None:
            return None
        normalized = value.strip()
        if not normalized:
            raise ValueError("Optional fields must be non-empty when provided.")
        return normalized

    @field_validator("correlation_id")
    @classmethod
    def _strip_correlation_id(cls, value: str) -> str:
        """Normalize correlation identifiers."""
        normalized = value.strip()
        if not normalized:
            raise ValueError("correlation_id must be non-empty.")
        return normalized

    @field_validator("timestamp")
    @classmethod
    def _ensure_timezone(cls, value: datetime) -> datetime:
        """Ensure routing timestamps are timezone-aware."""
        if value.tzinfo is None:
            return value.replace(tzinfo=timezone.utc)
        return value

    @field_validator("notification")
    @classmethod
    def _validate_notification(cls, value: NotificationEnvelope) -> NotificationEnvelope:
        """Ensure nested notification envelope is present."""
        return value

    @model_validator(mode="after")
    def _validate_notification_consistency(self) -> "RoutingEnvelope":
        """Ensure notification metadata matches routing fields."""
        if self.notification.version != self.version:
            raise ValueError("notification.version must match routing version.")
        if self.notification.origin_signal != self.signal_reference:
            raise ValueError("notification.origin_signal must match signal_reference.")
        return self


class RoutingEnvelopeValidationResult(BaseModel):
    """Result of validating a routing envelope payload."""

    model_config = ConfigDict(extra="forbid")

    decision: EnvelopeDecision
    errors: list[str]
    envelope: RoutingEnvelope | None = None


class EnvelopeValidationResult(BaseModel):
    """Result of validating a notification envelope payload."""

    model_config = ConfigDict(extra="forbid")

    decision: EnvelopeDecision
    errors: list[str]
    envelope: NotificationEnvelope | None = None


def validate_envelope_payload(payload: dict[str, Any]) -> EnvelopeValidationResult:
    """Validate a notification envelope payload for routing decisions."""
    try:
        envelope = NotificationEnvelope.model_validate(payload)
    except ValidationError as exc:
        return EnvelopeValidationResult(
            decision=EnvelopeDecision.LOG_ONLY,
            errors=[error["msg"] for error in exc.errors()],
            envelope=None,
        )
    return EnvelopeValidationResult(
        decision=EnvelopeDecision.ACCEPT,
        errors=[],
        envelope=envelope,
    )


def validate_routing_envelope_payload(payload: dict[str, Any]) -> RoutingEnvelopeValidationResult:
    """Validate a routing envelope payload for attention routing."""
    try:
        envelope = RoutingEnvelope.model_validate(payload)
    except ValidationError as exc:
        return RoutingEnvelopeValidationResult(
            decision=EnvelopeDecision.LOG_ONLY,
            errors=[error["msg"] for error in exc.errors()],
            envelope=None,
        )
    return RoutingEnvelopeValidationResult(
        decision=EnvelopeDecision.ACCEPT,
        errors=[],
        envelope=envelope,
    )
