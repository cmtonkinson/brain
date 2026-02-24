"""Vault Authority Service native package exports."""

from packages.brain_shared.envelope import Envelope, EnvelopeKind, EnvelopeMeta
from packages.brain_shared.errors import ErrorCategory, ErrorDetail
from services.state.vault_authority.component import MANIFEST
from services.state.vault_authority.config import VaultAuthoritySettings
from services.state.vault_authority.domain import (
    FileEdit,
    SearchFileMatch,
    VaultEntry,
    VaultEntryType,
    VaultFileRecord,
)
from services.state.vault_authority.implementation import DefaultVaultAuthorityService
from services.state.vault_authority.service import VaultAuthorityService

__all__ = [
    "DefaultVaultAuthorityService",
    "Envelope",
    "EnvelopeKind",
    "EnvelopeMeta",
    "ErrorCategory",
    "ErrorDetail",
    "FileEdit",
    "MANIFEST",
    "SearchFileMatch",
    "VaultAuthorityService",
    "VaultAuthoritySettings",
    "VaultEntry",
    "VaultEntryType",
    "VaultFileRecord",
]
