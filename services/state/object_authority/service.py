"""Authoritative in-process Python API for Object Authority Service."""

from __future__ import annotations

from abc import ABC, abstractmethod

from packages.brain_shared.config import BrainSettings
from packages.brain_shared.envelope import Envelope, EnvelopeMeta
from resources.adapters.filesystem.substrate import FilesystemBlobAdapter
from services.state.object_authority.domain import ObjectGetResult, ObjectRecord


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


def build_object_authority_service(
    *,
    settings: BrainSettings,
    blob_store: FilesystemBlobAdapter | None = None,
) -> ObjectAuthorityService:
    """Build default Object Authority implementation from typed settings."""
    from resources.adapters.filesystem import (
        LocalFilesystemBlobAdapter,
        resolve_filesystem_adapter_settings,
    )
    from services.state.object_authority.config import resolve_object_authority_settings
    from services.state.object_authority.data import (
        ObjectPostgresRuntime,
        PostgresObjectRepository,
    )
    from services.state.object_authority.implementation import (
        DefaultObjectAuthorityService,
    )

    fs_settings = resolve_filesystem_adapter_settings(settings)
    runtime = ObjectPostgresRuntime.from_settings(settings)
    return DefaultObjectAuthorityService(
        settings=resolve_object_authority_settings(settings),
        repository=PostgresObjectRepository(runtime.schema_sessions),
        blob_store=blob_store or LocalFilesystemBlobAdapter(settings=fs_settings),
        default_extension=fs_settings.default_extension,
    )
