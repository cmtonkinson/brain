"""Authoritative in-process Python API for Object Authority Service."""

from __future__ import annotations

from abc import ABC, abstractmethod

from packages.brain_shared.envelope import Envelope, EnvelopeMeta
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
