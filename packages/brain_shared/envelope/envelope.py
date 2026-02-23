"""Typed envelope response model for east-west service calls."""

from __future__ import annotations

from typing import Generic, TypeVar

from pydantic import BaseModel, ConfigDict, Field

from packages.brain_shared.errors import ErrorDetail

from .meta import EnvelopeMeta
from .payload import Payload


T = TypeVar("T")


class Envelope(BaseModel, Generic[T]):
    """Canonical typed envelope with metadata, payload, and errors."""

    model_config = ConfigDict(frozen=True)

    metadata: EnvelopeMeta
    payload: Payload[T] | None
    errors: list[ErrorDetail] = Field(default_factory=list)

    @property
    def ok(self) -> bool:
        """Return ``True`` when no errors are present."""
        return len(self.errors) == 0

    @property
    def has_payload(self) -> bool:
        """Return ``True`` when payload is present."""
        return self.payload is not None
