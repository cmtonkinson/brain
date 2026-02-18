"""Typed envelope result model for east-west service calls."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Generic, TypeVar

from packages.brain_shared.errors import ErrorDetail

from .meta import EnvelopeMeta


T = TypeVar("T")


@dataclass(frozen=True)
class Result(Generic[T]):
    """Envelope-like typed response for in-process service boundaries."""

    metadata: EnvelopeMeta
    payload: T | None
    errors: list[ErrorDetail] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        """Return True when no errors are present."""
        return len(self.errors) == 0

    @property
    def has_payload(self) -> bool:
        """Return True when payload is present."""
        return self.payload is not None
