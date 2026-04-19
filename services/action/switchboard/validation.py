"""Request validation models for Switchboard Service public API."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field, field_validator


def _strip_text(value: object) -> object:
    """Normalize surrounding whitespace for textual request fields."""
    if isinstance(value, str):
        return value.strip()
    return value


class IngestSignalMessageRequest(BaseModel):
    """Validate one raw inbound Signal payload."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    raw_body_json: str = Field(min_length=2)

    @field_validator("raw_body_json", mode="before")
    @classmethod
    def _strip_fields(cls, value: object) -> object:
        """Normalize textual payload fields before validation."""
        return _strip_text(value)


class EnqueueConsoleMessageRequest(BaseModel):
    """Validate one inbound console operator message."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    message_text: str = Field(min_length=1)

    @field_validator("message_text", mode="before")
    @classmethod
    def _strip_fields(cls, value: object) -> object:
        """Normalize textual payload fields before validation."""
        return _strip_text(value)


class PollOperatorInstructionRequest(BaseModel):
    """Validate one poll request for queued operator instructions."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    wait_timeout_seconds: float = Field(default=0.0, ge=0.0)


class PollConsoleResponseRequest(BaseModel):
    """Validate one poll request for queued console responses."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    wait_timeout_seconds: float = Field(default=0.0, ge=0.0)
