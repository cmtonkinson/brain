"""Request validation models for Switchboard Service public API."""

from __future__ import annotations

from pydantic import AnyHttpUrl, BaseModel, ConfigDict, Field, field_validator


def _strip_text(value: object) -> object:
    """Normalize surrounding whitespace for textual request fields."""
    if isinstance(value, str):
        return value.strip()
    return value


class IngestSignalWebhookRequest(BaseModel):
    """Validate one inbound webhook ingress request payload."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    raw_body_json: str = Field(min_length=2)
    header_timestamp: str = Field(min_length=1)
    header_signature: str = Field(min_length=1)

    @field_validator(
        "raw_body_json", "header_timestamp", "header_signature", mode="before"
    )
    @classmethod
    def _strip_fields(cls, value: object) -> object:
        """Normalize textual payload fields before validation."""
        return _strip_text(value)


class RegisterSignalWebhookRequest(BaseModel):
    """Validate one webhook registration request payload."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    callback_url: AnyHttpUrl
    shared_secret_ref: str = ""

    @field_validator("shared_secret_ref", mode="before")
    @classmethod
    def _strip_ref(cls, value: object) -> object:
        """Normalize surrounding whitespace for secret reference values."""
        return _strip_text(value)
