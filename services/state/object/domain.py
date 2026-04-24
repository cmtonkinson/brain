"""Domain contracts for Object Service payloads."""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum

from pydantic import BaseModel, ConfigDict


class ObjectRef(BaseModel):
    """Canonical reference for one blob object key."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    object_key: str


class ObjectMetadata(BaseModel):
    """Authoritative metadata for one persisted blob."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    digest_algorithm: str
    digest_version: str
    digest_hex: str
    extension: str
    content_type: str
    size_bytes: int
    original_filename: str
    source_uri: str
    created_at: datetime
    updated_at: datetime


class ObjectRecord(BaseModel):
    """Object record including identity and metadata."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    ref: ObjectRef
    metadata: ObjectMetadata


class ObjectWriteDisposition(StrEnum):
    """Whether a put-object request created or reused an existing object."""

    created = "created"
    existing = "existing"


class ObjectPutResult(BaseModel):
    """Put-object payload including metadata and dedupe disposition."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    object: ObjectRecord
    write_disposition: ObjectWriteDisposition


class ObjectGetResult(BaseModel):
    """Get-object payload including object metadata and full blob content."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    object: ObjectRecord
    content: bytes


class HealthStatus(BaseModel):
    """Object and owned dependency readiness status payload."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    service_ready: bool
    substrate_ready: bool
    detail: str
