"""Schema definitions for attention router interruption policies."""

from __future__ import annotations

from datetime import time
from enum import Enum

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class ScoreRange(BaseModel):
    """Range constraint for normalized scores."""

    model_config = ConfigDict(extra="forbid")

    minimum: float | None = Field(default=None, ge=0.0, le=1.0)
    maximum: float | None = Field(default=None, ge=0.0, le=1.0)

    @model_validator(mode="after")
    def _validate_bounds(self) -> "ScoreRange":
        """Ensure the range has at least one bound and ordered values."""
        if self.minimum is None and self.maximum is None:
            raise ValueError("ScoreRange requires minimum or maximum.")
        if self.minimum is not None and self.maximum is not None and self.minimum > self.maximum:
            raise ValueError("ScoreRange minimum cannot exceed maximum.")
        return self


class UrgencyConstraint(BaseModel):
    """Constraint for referencing urgency levels or scores."""

    model_config = ConfigDict(extra="forbid")

    levels: set[str] | None = None
    score: ScoreRange | None = None

    @field_validator("levels")
    @classmethod
    def _validate_levels(cls, value: set[str] | None) -> set[str] | None:
        """Reject empty urgency level strings."""
        if value is None:
            return None
        normalized = {item.strip() for item in value if item is not None}
        if not normalized or any(not item for item in normalized):
            raise ValueError("Urgency levels must be non-empty strings.")
        return normalized

    @model_validator(mode="after")
    def _validate_constraint(self) -> "UrgencyConstraint":
        """Ensure at least one urgency constraint is defined."""
        if not self.levels and self.score is None:
            raise ValueError("UrgencyConstraint requires levels or score.")
        return self


class PreferenceCondition(BaseModel):
    """Condition for matching user preferences."""

    model_config = ConfigDict(extra="forbid")

    key: str = Field(..., min_length=1)
    value: str | int | bool | None = None

    @field_validator("key")
    @classmethod
    def _strip_key(cls, value: str) -> str:
        """Normalize preference keys and reject blanks."""
        normalized = value.strip()
        if not normalized:
            raise ValueError("Preference key must be non-empty.")
        return normalized


class TimeWindow(BaseModel):
    """Window of time for policy applicability."""

    model_config = ConfigDict(extra="forbid")

    start: time
    end: time
    timezone: str | None = None
    days_of_week: list[int] | None = None

    @field_validator("days_of_week")
    @classmethod
    def _validate_days(cls, value: list[int] | None) -> list[int] | None:
        """Ensure days of week values fall within 0-6."""
        if value is None:
            return None
        if not value:
            raise ValueError("days_of_week cannot be empty when provided.")
        for day in value:
            if day < 0 or day > 6:
                raise ValueError("days_of_week must be between 0 and 6.")
        return value

    @field_validator("timezone")
    @classmethod
    def _strip_timezone(cls, value: str | None) -> str | None:
        """Normalize timezone names."""
        if value is None:
            return None
        normalized = value.strip()
        if not normalized:
            raise ValueError("timezone must be non-empty when provided.")
        return normalized

    @model_validator(mode="after")
    def _validate_window(self) -> "TimeWindow":
        """Ensure the window has a non-zero duration."""
        if self.start == self.end:
            raise ValueError("TimeWindow start and end cannot be identical.")
        return self


class AuthorizationScope(BaseModel):
    """Scope constraints for action authorization context."""

    model_config = ConfigDict(extra="forbid")

    autonomy_levels: set[str] | None = None
    approval_statuses: set[str] | None = None
    policy_tags: set[str] | None = None

    @field_validator("autonomy_levels", "approval_statuses", "policy_tags")
    @classmethod
    def _validate_tokens(cls, value: set[str] | None) -> set[str] | None:
        """Normalize scope tokens and reject empty values."""
        if value is None:
            return None
        normalized = {item.strip() for item in value if item is not None}
        if not normalized or any(not item for item in normalized):
            raise ValueError("Values must be non-empty strings.")
        return normalized


class PolicyOutcomeKind(str, Enum):
    """Allowed policy outcomes for interruption routing."""

    DROP = "DROP"
    LOG_ONLY = "LOG_ONLY"
    DEFER = "DEFER"
    BATCH = "BATCH"
    NOTIFY = "NOTIFY"
    ESCALATE = "ESCALATE"


class PolicyOutcome(BaseModel):
    """Outcome produced when a policy applies."""

    model_config = ConfigDict(extra="forbid")

    kind: PolicyOutcomeKind
    channel: str | None = None

    @field_validator("channel")
    @classmethod
    def _strip_channel(cls, value: str | None) -> str | None:
        """Normalize channel names."""
        if value is None:
            return None
        normalized = value.strip()
        if not normalized:
            raise ValueError("channel must be non-empty when provided.")
        return normalized

    @model_validator(mode="after")
    def _validate_channel(self) -> "PolicyOutcome":
        """Require channels for notify and escalate outcomes."""
        needs_channel = self.kind in {PolicyOutcomeKind.NOTIFY, PolicyOutcomeKind.ESCALATE}
        if needs_channel and not self.channel:
            raise ValueError("channel is required for notify and escalate outcomes.")
        if not needs_channel and self.channel:
            raise ValueError("channel is only valid for notify and escalate outcomes.")
        return self


class PolicyScope(BaseModel):
    """Matching criteria for interruption policies."""

    model_config = ConfigDict(extra="forbid")

    signal_types: set[str] | None = None
    source_components: set[str] | None = None
    urgency: UrgencyConstraint | None = None
    confidence: ScoreRange | None = None
    channel_cost: ScoreRange | None = None
    preferences: list[PreferenceCondition] | None = None
    time_windows: list[TimeWindow] | None = None
    authorization: AuthorizationScope | None = None

    @field_validator("signal_types", "source_components")
    @classmethod
    def _validate_tokens(cls, value: set[str] | None) -> set[str] | None:
        """Normalize token sets and reject empty values."""
        if value is None:
            return None
        normalized = {item.strip() for item in value if item is not None}
        if not normalized or any(not item for item in normalized):
            raise ValueError("Values must be non-empty strings.")
        return normalized


class AttentionPolicy(BaseModel):
    """Versioned interruption policy definition."""

    model_config = ConfigDict(extra="forbid")

    policy_id: str = Field(..., min_length=1)
    version: str = Field(..., min_length=1)
    description: str | None = None
    scope: PolicyScope
    outcome: PolicyOutcome

    @field_validator("policy_id", "version")
    @classmethod
    def _strip_required_fields(cls, value: str) -> str:
        """Normalize required identifiers."""
        normalized = value.strip()
        if not normalized:
            raise ValueError("Required fields must be non-empty strings.")
        return normalized

    @field_validator("description")
    @classmethod
    def _strip_description(cls, value: str | None) -> str | None:
        """Normalize descriptions."""
        if value is None:
            return None
        normalized = value.strip()
        if not normalized:
            raise ValueError("description must be non-empty when provided.")
        return normalized
