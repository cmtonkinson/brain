"""Domain contracts for Object Authority Service payloads."""

from __future__ import annotations

from datetime import datetime

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


class ObjectGetResult(BaseModel):
    """Get-object payload including object metadata and full blob content."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    object: ObjectRecord
    content: bytes


class HealthStatus(BaseModel):
    """OAS and owned dependency readiness status payload."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    service_ready: bool
    substrate_ready: bool
    detail: str
