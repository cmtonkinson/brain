"""Public Brain SDK interface for CLI and agent callers."""

from packages.brain_sdk.calls import (
    CapabilityDescriptor,
    CapabilityInvokeResult,
    CoreComponentHealth,
    CoreHealthResult,
    LmsChatResult,
    MemoryContextBlock,
    MemoryDialogueTurn,
    MemoryProfileContext,
    PolicyDecision,
    SwitchboardOperatorInstruction,
    core_health,
    describe_capabilities,
    invoke_capability,
    lms_chat,
    memory_assemble_context,
    memory_record_response,
    switchboard_poll_operator_instruction,
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
    "CapabilityDescriptor",
    "CapabilityInvokeResult",
    "CoreComponentHealth",
    "CoreHealthResult",
    "DomainError",
    "LmsChatResult",
    "MetaOverrides",
    "MemoryContextBlock",
    "MemoryDialogueTurn",
    "MemoryProfileContext",
    "PolicyDecision",
    "SdkErrorDetail",
    "SwitchboardOperatorInstruction",
    "TransportError",
    "core_health",
    "describe_capabilities",
    "invoke_capability",
    "lms_chat",
    "memory_assemble_context",
    "memory_record_response",
    "switchboard_poll_operator_instruction",
]
