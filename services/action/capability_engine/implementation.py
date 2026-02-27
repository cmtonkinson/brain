"""Concrete Capability Engine Service implementation."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from packages.brain_shared.config import BrainSettings
from packages.brain_shared.envelope import (
    Envelope,
    EnvelopeMeta,
    failure,
    success,
    validate_meta,
)
from packages.brain_shared.errors import (
    ErrorDetail,
    codes,
    not_found_error,
    validation_error,
)
from packages.brain_shared.ids import generate_ulid_str
from packages.brain_shared.logging import get_logger, public_api_instrumented
from resources.adapters.utcp_code_mode import (
    LocalFileUtcpCodeModeAdapter,
    UtcpCodeModeAdapter,
    UtcpCodeModeLoadResult,
    resolve_utcp_code_mode_adapter_settings,
)
from services.action.capability_engine.component import SERVICE_COMPONENT_ID
from services.action.capability_engine.config import (
    CapabilityEngineSettings,
    resolve_capability_engine_settings,
)
from services.action.capability_engine.domain import (
    CapabilityDescriptor,
    CapabilityEngineHealthStatus,
    CapabilityExecutionResponse,
    CapabilityInvocationAuditRow,
    CapabilityInvocationMetadata,
    CapabilityInvokeResult,
    CapabilityPolicySummary,
)
from services.action.capability_engine.data.repository import (
    InMemoryCapabilityInvocationAuditRepository,
    PostgresCapabilityInvocationAuditRepository,
)
from services.action.capability_engine.data.runtime import (
    CapabilityEnginePostgresRuntime,
)
from services.action.capability_engine.interfaces import (
    CapabilityInvocationAuditRepository,
)
from services.action.capability_engine.registry import (
    CapabilityRegistry,
    CapabilityRuntime,
)
from services.action.capability_engine.service import CapabilityEngineService
from services.action.policy_service.domain import (
    CapabilityInvocationRequest,
    CapabilityPolicyInput,
    InvocationPolicyInput,
    PolicyDecision,
    PolicyExecutionResult,
    UNKNOWN_CALL_TARGET_REASON,
    utc_now,
)
from services.action.policy_service.service import PolicyService

_LOGGER = get_logger(__name__)
_REASON_AUTONOMY_EXCEEDS_ENGINE_LIMIT = "autonomy_exceeds_engine_limit"


@dataclass(frozen=True)
class _InvokeInternalResult:
    """Internal invocation result used by both public and nested invoke paths."""

    allowed: bool
    output: dict[str, Any] | None
    errors: tuple[ErrorDetail, ...]
    policy: CapabilityPolicySummary
    proposal_token: str
    capability_version: str


@dataclass(frozen=True)
class _NestedRuntime(CapabilityRuntime):
    """Runtime helper passed to handlers for nested capability invocation."""

    engine: "DefaultCapabilityEngineService"
    parent_request: CapabilityInvocationRequest

    def invoke_nested(
        self,
        *,
        capability_id: str,
        input_payload: dict[str, Any],
    ) -> CapabilityExecutionResponse:
        child_meta = self.parent_request.metadata.model_copy(
            update={
                "parent_id": self.parent_request.metadata.envelope_id,
                "envelope_id": generate_ulid_str(),
            }
        )
        child_invocation = InvocationPolicyInput(
            actor=self.parent_request.invocation.actor,
            source=self.parent_request.invocation.source,
            channel=self.parent_request.invocation.channel,
            invocation_id=generate_ulid_str(),
            parent_invocation_id=self.parent_request.invocation.invocation_id,
        )

        nested = self.engine._invoke_internal(
            meta=child_meta,
            capability_id=capability_id,
            input_payload=input_payload,
            invocation=child_invocation,
        )
        if not nested.allowed:
            return CapabilityExecutionResponse(output=None)
        return CapabilityExecutionResponse(output=nested.output)


class DefaultCapabilityEngineService(CapabilityEngineService):
    """Default CES implementation enforcing policy-gated capability execution."""

    def __init__(
        self,
        *,
        settings: CapabilityEngineSettings,
        policy_service: PolicyService,
        registry: CapabilityRegistry,
        code_mode_adapter: UtcpCodeModeAdapter | None = None,
        code_mode_config: UtcpCodeModeLoadResult | None = None,
        audit_repository: CapabilityInvocationAuditRepository | None = None,
    ) -> None:
        self._settings = settings
        self._policy_service = policy_service
        self._registry = registry
        self._code_mode_adapter = code_mode_adapter
        self._code_mode_config = code_mode_config
        self._audit_repository = (
            audit_repository or InMemoryCapabilityInvocationAuditRepository()
        )

    def _load_capabilities(self) -> None:
        """Discover capability manifests from configured discovery root."""
        self._registry.discover(root=Path(self._settings.discovery_root))

    @classmethod
    def from_settings(
        cls,
        settings: BrainSettings,
        *,
        policy_service: PolicyService,
        registry: CapabilityRegistry | None = None,
    ) -> "DefaultCapabilityEngineService":
        """Build CES from typed settings and injected Policy Service dependency."""
        resolved = resolve_capability_engine_settings(settings)
        active_registry = registry or CapabilityRegistry()
        active_registry.discover(root=Path(resolved.discovery_root))
        code_mode_adapter_settings = resolve_utcp_code_mode_adapter_settings(settings)
        code_mode_adapter = LocalFileUtcpCodeModeAdapter(
            settings=code_mode_adapter_settings
        )
        code_mode_config = code_mode_adapter.load()
        runtime = CapabilityEnginePostgresRuntime.from_settings(settings)
        return cls(
            settings=resolved,
            policy_service=policy_service,
            registry=active_registry,
            code_mode_adapter=code_mode_adapter,
            code_mode_config=code_mode_config,
            audit_repository=PostgresCapabilityInvocationAuditRepository(
                runtime.schema_sessions
            ),
        )

    @public_api_instrumented(
        logger=_LOGGER,
        component_id=str(SERVICE_COMPONENT_ID),
        id_fields=("meta",),
    )
    def health(self, *, meta: EnvelopeMeta) -> Envelope[CapabilityEngineHealthStatus]:
        """Return service readiness and local registry/audit counters."""
        try:
            validate_meta(meta)
        except ValueError as exc:
            return failure(
                meta=meta,
                errors=[validation_error(str(exc), code=codes.INVALID_ARGUMENT)],
            )

        return success(
            meta=meta,
            payload=CapabilityEngineHealthStatus(
                service_ready=True,
                policy_ready=True,
                discovered_capabilities=self._registry.count(),
                invocation_audit_rows=self._audit_repository.count(),
                detail="ok",
            ),
        )

    @public_api_instrumented(
        logger=_LOGGER,
        component_id=str(SERVICE_COMPONENT_ID),
        id_fields=("meta",),
    )
    def describe_capabilities(
        self, *, meta: EnvelopeMeta
    ) -> Envelope[tuple[CapabilityDescriptor, ...]]:
        """Return descriptors for all registered capabilities."""
        try:
            validate_meta(meta)
        except ValueError as exc:
            return failure(
                meta=meta,
                errors=[validation_error(str(exc), code=codes.INVALID_ARGUMENT)],
            )

        descriptors = tuple(
            CapabilityDescriptor(
                capability_id=manifest.capability_id,
                kind=manifest.kind,
                version=manifest.version,
                summary=manifest.summary,
                input_types=manifest.input_types,
                output_types=manifest.output_types,
                autonomy=manifest.autonomy,
                requires_approval=manifest.requires_approval,
                side_effects=manifest.side_effects,
                required_capabilities=manifest.required_capabilities,
            )
            for manifest in self._registry.list_manifests()
        )
        return success(meta=meta, payload=descriptors)

    @public_api_instrumented(
        logger=_LOGGER,
        component_id=str(SERVICE_COMPONENT_ID),
        id_fields=(),
    )
    def invoke_capability(
        self,
        *,
        meta: EnvelopeMeta,
        capability_id: str,
        input_payload: dict[str, object],
        invocation: CapabilityInvocationMetadata,
    ) -> Envelope[CapabilityInvokeResult]:
        """Invoke one capability package by ``capability_id`` through Policy Service."""
        try:
            validate_meta(meta)
        except ValueError as exc:
            return failure(
                meta=meta,
                errors=[validation_error(str(exc), code=codes.INVALID_ARGUMENT)],
            )

        result = self._invoke_internal(
            meta=meta,
            capability_id=capability_id,
            input_payload={key: value for key, value in input_payload.items()},
            invocation=InvocationPolicyInput.model_validate(
                invocation.model_dump(mode="python")
            ),
        )
        self._append_audit_row(
            meta=meta,
            capability_id=capability_id,
            capability_version=result.capability_version,
            summary=result.policy,
            proposal_token=result.proposal_token,
            invocation=invocation,
        )

        if not result.allowed:
            return failure(meta=meta, errors=result.errors)

        return success(
            meta=meta,
            payload=CapabilityInvokeResult(
                capability_id=capability_id,
                capability_version=result.capability_version,
                output=result.output,
                policy_decision_id=result.policy.decision_id,
                policy_regime_id=result.policy.policy_regime_id,
                policy_allowed=result.policy.allowed,
                policy_reason_codes=result.policy.reason_codes,
                policy_obligations=result.policy.obligations,
                proposal_token=result.proposal_token,
            ),
        )

    def _invoke_internal(
        self,
        *,
        meta: EnvelopeMeta,
        capability_id: str,
        input_payload: dict[str, Any],
        invocation: InvocationPolicyInput,
    ) -> _InvokeInternalResult:
        manifest = self._registry.resolve_manifest(capability_id=capability_id)
        if manifest is None:
            errors = (
                not_found_error(
                    "capability not found",
                    code=codes.RESOURCE_NOT_FOUND,
                    metadata={"capability_id": capability_id},
                ),
            )
            return self._denied_internal(
                capability_version="unknown",
                errors=errors,
                reason_codes=(codes.RESOURCE_NOT_FOUND,),
            )

        if not manifest.enabled:
            errors = (
                validation_error(
                    "capability is disabled",
                    code=codes.PERMISSION_DENIED,
                    metadata={"capability_id": capability_id},
                ),
            )
            return self._denied_internal(
                capability_version=manifest.version,
                errors=errors,
                reason_codes=("capability_disabled",),
            )
        if manifest.autonomy > self._settings.default_max_autonomy:
            errors = (
                validation_error(
                    "capability autonomy exceeds engine ceiling",
                    code=codes.PERMISSION_DENIED,
                    metadata={
                        "capability_id": capability_id,
                        "capability_autonomy": str(manifest.autonomy),
                        "engine_max_autonomy": str(self._settings.default_max_autonomy),
                    },
                ),
            )
            return self._denied_internal(
                capability_version=manifest.version,
                errors=errors,
                reason_codes=(_REASON_AUTONOMY_EXCEEDS_ENGINE_LIMIT,),
            )

        request = CapabilityInvocationRequest(
            metadata=meta,
            capability=CapabilityPolicyInput(
                capability_id=manifest.capability_id,
                kind=manifest.kind,
                version=manifest.version,
                autonomy=manifest.autonomy,
                requires_approval=manifest.requires_approval,
                side_effects=manifest.side_effects,
                required_capabilities=manifest.required_capabilities,
            ),
            invocation=invocation,
            input_payload=input_payload,
        )
        policy_result = self._invoke_with_policy(request=request)

        proposal_token = ""
        if policy_result.proposal is not None:
            proposal_token = policy_result.proposal.proposal_token
        summary = CapabilityPolicySummary(
            decision_id=policy_result.decision.decision_id,
            policy_regime_id=policy_result.decision.policy_regime_id,
            allowed=policy_result.decision.allowed,
            reason_codes=policy_result.decision.reason_codes,
            obligations=policy_result.decision.obligations,
            proposal_token=proposal_token,
        )

        return _InvokeInternalResult(
            allowed=policy_result.allowed,
            output=policy_result.output,
            errors=policy_result.errors,
            policy=summary,
            proposal_token=proposal_token,
            capability_version=manifest.version,
        )

    def _invoke_with_policy(
        self, *, request: CapabilityInvocationRequest
    ) -> PolicyExecutionResult:
        handler = self._registry.resolve_handler(
            capability_id=request.capability.capability_id
        )
        runtime = _NestedRuntime(engine=self, parent_request=request)

        if handler is None:
            return self._policy_service.authorize_and_execute(
                request=request,
                execute=lambda _: self._missing_handler_result(request=request),
            )

        return self._policy_service.authorize_and_execute(
            request=request,
            execute=lambda allowed_request: PolicyExecutionResult(
                allowed=True,
                output=handler(allowed_request, runtime).output,
                errors=(),
                decision=self._placeholder_allow_decision(),
                proposal=None,
            ),
        )

    def _append_audit_row(
        self,
        *,
        meta: EnvelopeMeta,
        capability_id: str,
        capability_version: str,
        summary: CapabilityPolicySummary,
        proposal_token: str,
        invocation: CapabilityInvocationMetadata,
    ) -> None:
        self._audit_repository.append(
            row=CapabilityInvocationAuditRow(
                audit_id=generate_ulid_str(),
                envelope_id=meta.envelope_id,
                trace_id=meta.trace_id,
                parent_id=meta.parent_id,
                invocation_id=invocation.invocation_id,
                parent_invocation_id=invocation.parent_invocation_id,
                actor=invocation.actor,
                source=invocation.source,
                channel=invocation.channel,
                capability_id=capability_id,
                capability_version=capability_version,
                policy_decision_id=summary.decision_id,
                policy_regime_id=summary.policy_regime_id,
                allowed=summary.allowed,
                reason_codes=summary.reason_codes,
                proposal_token=proposal_token,
                created_at=datetime.now(UTC),
            ),
        )

    def _denied_internal(
        self,
        *,
        capability_version: str,
        errors: tuple[ErrorDetail, ...],
        reason_codes: tuple[str, ...],
    ) -> _InvokeInternalResult:
        summary = CapabilityPolicySummary(
            decision_id="prepolicy-deny",
            policy_regime_id="prepolicy-deny",
            allowed=False,
            reason_codes=reason_codes,
            obligations=(),
        )
        return _InvokeInternalResult(
            allowed=False,
            output=None,
            errors=errors,
            policy=summary,
            proposal_token="",
            capability_version=capability_version,
        )

    @staticmethod
    def _placeholder_allow_decision() -> PolicyDecision:
        return PolicyDecision(
            decision_id="placeholder",
            policy_regime_id="placeholder",
            policy_regime_hash="placeholder",
            allowed=True,
            reason_codes=(),
            obligations=(),
            policy_metadata={},
            decided_at=utc_now(),
            policy_name="placeholder",
            policy_version="1",
        )

    def _missing_handler_result(
        self, *, request: CapabilityInvocationRequest
    ) -> PolicyExecutionResult:
        return PolicyExecutionResult(
            allowed=False,
            output=None,
            errors=(
                not_found_error(
                    "capability handler not found",
                    code=codes.RESOURCE_NOT_FOUND,
                    metadata={"capability_id": request.capability.capability_id},
                ),
            ),
            decision=self._placeholder_allow_decision().model_copy(
                update={"allowed": False, "reason_codes": (UNKNOWN_CALL_TARGET_REASON,)}
            ),
            proposal=None,
        )
