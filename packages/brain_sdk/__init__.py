"""Public Brain SDK interface for CLI and agent callers."""

from packages.brain_sdk.calls import (
    CoreComponentHealth,
    CoreHealthResult,
    LmsChatResult,
    VaultEntry,
    VaultFile,
    VaultSearchMatch,
    core_health,
    lms_chat,
    vault_get,
    vault_list,
    vault_search,
)
from packages.brain_sdk.client import BrainClient, BrainSdkClient
from packages.brain_sdk.config import BrainSdkConfig
from packages.brain_sdk.errors import (
    BrainConflictError,
    BrainDependencyError,
    BrainDomainError,
    BrainInternalError,
    BrainNotFoundError,
    BrainPolicyError,
    BrainSdkError,
    BrainTransportError,
    BrainValidationError,
    SdkErrorDetail,
)
from packages.brain_sdk.meta import MetaOverrides

DomainError = BrainDomainError
TransportError = BrainTransportError

__all__ = [
    "BrainClient",
    "BrainSdkClient",
    "BrainConflictError",
    "BrainDependencyError",
    "BrainDomainError",
    "BrainInternalError",
    "BrainNotFoundError",
    "BrainPolicyError",
    "BrainSdkConfig",
    "BrainSdkError",
    "BrainTransportError",
    "BrainValidationError",
    "CoreComponentHealth",
    "CoreHealthResult",
    "DomainError",
    "LmsChatResult",
    "MetaOverrides",
    "SdkErrorDetail",
    "TransportError",
    "VaultEntry",
    "VaultFile",
    "VaultSearchMatch",
    "core_health",
    "lms_chat",
    "vault_get",
    "vault_list",
    "vault_search",
]
