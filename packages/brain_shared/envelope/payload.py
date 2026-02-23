"""Typed payload wrapper for envelope responses."""

from __future__ import annotations

from typing import Generic, TypeVar

from pydantic import BaseModel, ConfigDict


T = TypeVar("T")


class Payload(BaseModel, Generic[T]):
    """Container for domain payload data carried by an envelope."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    value: T
