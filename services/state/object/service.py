"""Authoritative in-process Python API for Object Service."""

from __future__ import annotations

from abc import ABC, abstractmethod

from lib.shared.config import CoreRuntimeSettings
from lib.shared.envelope import Envelope, EnvelopeMeta
from resources.substrates.seaweedfs.substrate import BlobSubstrate
from services.state.object.domain import (
    HealthStatus,
    ObjectGetResult,
    ObjectPutResult,
    ObjectRecord,
)


class ObjectService(ABC):
    """Public API for durable blob object operations."""

    @abstractmethod
    def put_object(
        self,
        *,
        meta: EnvelopeMeta,
        content: bytes,
        extension: str,
        content_type: str,
        original_filename: str,
        source_uri: str,
    ) -> Envelope[ObjectPutResult]:
        """Persist one blob and return object metadata plus dedupe disposition."""

    @abstractmethod
    def get_object(
        self, *, meta: EnvelopeMeta, object_key: str
    ) -> Envelope[ObjectGetResult]:
        """Read one blob and metadata by canonical object key."""

    @abstractmethod
    def stat_object(
        self, *, meta: EnvelopeMeta, object_key: str
    ) -> Envelope[ObjectRecord]:
        """Read metadata for one blob by canonical object key."""

    @abstractmethod
    def delete_object(self, *, meta: EnvelopeMeta, object_key: str) -> Envelope[bool]:
        """Delete one blob by canonical object key with idempotent semantics."""

    @abstractmethod
    def health(self, *, meta: EnvelopeMeta) -> Envelope[HealthStatus]:
        """Return Object and owned dependency readiness status."""


def build_object_service(
    *,
    settings: CoreRuntimeSettings,
    blob_store: BlobSubstrate | None = None,
) -> ObjectService:
    """Build default Object implementation from typed settings."""
    from resources.substrates.seaweedfs import (
        SeaweedFSBlobSubstrate,
        resolve_seaweedfs_substrate_settings,
    )
    from services.state.object.config import resolve_object_settings
    from services.state.object.data import (
        ObjectPostgresRuntime,
        PostgresObjectRepository,
    )
    from services.state.object.implementation import (
        DefaultObjectService,
    )

    seaweedfs_settings = resolve_seaweedfs_substrate_settings(settings)
    runtime = ObjectPostgresRuntime.from_settings(settings)
    return DefaultObjectService(
        settings=resolve_object_settings(settings),
        repository=PostgresObjectRepository(runtime.schema_sessions),
        blob_store=blob_store or SeaweedFSBlobSubstrate(settings=seaweedfs_settings),
        default_extension=seaweedfs_settings.default_extension,
    )
