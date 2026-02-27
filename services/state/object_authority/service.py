"""Authoritative in-process Python API for Object Authority Service."""

from __future__ import annotations

from abc import ABC, abstractmethod

from packages.brain_shared.config import CoreRuntimeSettings
from packages.brain_shared.envelope import Envelope, EnvelopeMeta
from resources.substrates.filesystem.substrate import FilesystemBlobSubstrate
from services.state.object_authority.domain import (
    HealthStatus,
    ObjectGetResult,
    ObjectRecord,
)


class ObjectAuthorityService(ABC):
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
    ) -> Envelope[ObjectRecord]:
        """Persist one blob and return authoritative object record."""

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
        """Return OAS and owned dependency readiness status."""


def build_object_authority_service(
    *,
    settings: CoreRuntimeSettings,
    blob_store: FilesystemBlobSubstrate | None = None,
) -> ObjectAuthorityService:
    """Build default Object Authority implementation from typed settings."""
    from resources.substrates.filesystem import (
        LocalFilesystemBlobSubstrate,
        resolve_filesystem_substrate_settings,
    )
    from services.state.object_authority.config import resolve_object_authority_settings
    from services.state.object_authority.data import (
        ObjectPostgresRuntime,
        PostgresObjectRepository,
    )
    from services.state.object_authority.implementation import (
        DefaultObjectAuthorityService,
    )

    fs_settings = resolve_filesystem_substrate_settings(settings)
    runtime = ObjectPostgresRuntime.from_settings(settings)
    return DefaultObjectAuthorityService(
        settings=resolve_object_authority_settings(settings),
        repository=PostgresObjectRepository(runtime.schema_sessions),
        blob_store=blob_store or LocalFilesystemBlobSubstrate(settings=fs_settings),
        default_extension=fs_settings.default_extension,
    )
