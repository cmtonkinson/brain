"""Authoritative in-process Python API for Vault Authority Service."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Sequence

from packages.brain_shared.config import BrainSettings
from packages.brain_shared.envelope import Envelope, EnvelopeMeta
from resources.adapters.obsidian.adapter import ObsidianAdapter
from services.state.vault_authority.domain import (
    FileEdit,
    SearchFileMatch,
    VaultEntry,
    VaultFileRecord,
)


class VaultAuthorityService(ABC):
    """Public API for markdown vault file and directory operations."""

    @abstractmethod
    def list_directory(
        self,
        *,
        meta: EnvelopeMeta,
        directory_path: str,
    ) -> Envelope[list[VaultEntry]]:
        """List file and directory entries under one vault-relative path."""

    @abstractmethod
    def create_directory(
        self,
        *,
        meta: EnvelopeMeta,
        directory_path: str,
        recursive: bool = False,
    ) -> Envelope[VaultEntry]:
        """Create one directory."""

    @abstractmethod
    def delete_directory(
        self,
        *,
        meta: EnvelopeMeta,
        directory_path: str,
        recursive: bool = False,
        missing_ok: bool = False,
        use_trash: bool = True,
    ) -> Envelope[bool]:
        """Delete one directory, optionally recursively and missing-ok."""

    @abstractmethod
    def create_file(
        self,
        *,
        meta: EnvelopeMeta,
        file_path: str,
        content: str,
    ) -> Envelope[VaultFileRecord]:
        """Create one markdown file and fail when it already exists."""

    @abstractmethod
    def get_file(
        self,
        *,
        meta: EnvelopeMeta,
        file_path: str,
    ) -> Envelope[VaultFileRecord]:
        """Read one markdown file by path."""

    @abstractmethod
    def update_file(
        self,
        *,
        meta: EnvelopeMeta,
        file_path: str,
        content: str,
        if_revision: str = "",
        force: bool = False,
    ) -> Envelope[VaultFileRecord]:
        """Replace markdown file content with optional optimistic precondition."""

    @abstractmethod
    def append_file(
        self,
        *,
        meta: EnvelopeMeta,
        file_path: str,
        content: str,
        if_revision: str = "",
        force: bool = False,
    ) -> Envelope[VaultFileRecord]:
        """Append content to one markdown file."""

    @abstractmethod
    def edit_file(
        self,
        *,
        meta: EnvelopeMeta,
        file_path: str,
        edits: Sequence[FileEdit],
        if_revision: str = "",
        force: bool = False,
    ) -> Envelope[VaultFileRecord]:
        """Apply one or more line-range edits to a markdown file."""

    @abstractmethod
    def move_path(
        self,
        *,
        meta: EnvelopeMeta,
        source_path: str,
        target_path: str,
        if_revision: str = "",
        force: bool = False,
    ) -> Envelope[VaultEntry]:
        """Move one file or directory path."""

    @abstractmethod
    def delete_file(
        self,
        *,
        meta: EnvelopeMeta,
        file_path: str,
        missing_ok: bool = False,
        use_trash: bool = True,
        if_revision: str = "",
        force: bool = False,
    ) -> Envelope[bool]:
        """Delete one markdown file."""

    @abstractmethod
    def search_files(
        self,
        *,
        meta: EnvelopeMeta,
        query: str,
        directory_scope: str = "",
        limit: int = 20,
    ) -> Envelope[list[SearchFileMatch]]:
        """Search markdown files lexically through Obsidian Local REST API."""


def build_vault_authority_service(
    *,
    settings: BrainSettings,
    adapter: ObsidianAdapter | None = None,
) -> VaultAuthorityService:
    """Build default Vault Authority implementation from typed settings."""
    from resources.adapters.obsidian import (
        ObsidianLocalRestAdapter,
        resolve_obsidian_adapter_settings,
    )
    from services.state.vault_authority.config import resolve_vault_authority_settings
    from services.state.vault_authority.implementation import (
        DefaultVaultAuthorityService,
    )

    return DefaultVaultAuthorityService(
        settings=resolve_vault_authority_settings(settings),
        adapter=adapter
        or ObsidianLocalRestAdapter(
            settings=resolve_obsidian_adapter_settings(settings)
        ),
    )
