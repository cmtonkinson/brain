"""Concrete Capability Engine Service implementation."""

from __future__ import annotations

from dataclasses import dataclass
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
from packages.brain_shared.errors import codes, not_found_error, validation_error
from packages.brain_shared.ids import generate_ulid_str
from packages.brain_shared.logging import get_logger, public_api_instrumented
from services.action.capability_engine.component import SERVICE_COMPONENT_ID
from services.action.capability_engine.config import (
    CapabilityEngineSettings,
    resolve_capability_engine_settings,
)
from services.action.capability_engine.domain import (
    CapabilityEngineHealthStatus,
    CapabilityExecutionResponse,
    CapabilityIdentity,
    CapabilityInvokeResult,
    CapabilityPolicyContext,
)
from services.action.capability_engine.registry import (
    CapabilityRegistry,
    CapabilityRuntime,
)
from services.action.capability_engine.service import CapabilityEngineService
from services.action.policy_service.domain import (
    CapabilityInvocationRequest,
    CapabilityRef,
    PolicyDecision,
    PolicyContext,
    PolicyExecutionResult,
    utc_now,
)
from services.action.policy_service.service import PolicyService

_LOGGER = get_logger(__name__)


@dataclass(frozen=True)
class _NestedRuntime(CapabilityRuntime):
    """Runtime helper passed to handlers for nested capability invocation."""

    engine: "DefaultCapabilityEngineService"
    parent_request: CapabilityInvocationRequest

    def invoke_nested(
        self,
        *,
        kind: str,
        namespace: str,
        name: str,
        version: str,
        input_payload: dict[str, Any],
    ) -> CapabilityExecutionResponse:
        child_capability = CapabilityIdentity(
            kind=kind,
            namespace=namespace,
            name=name,
            version=version,
        )
        child_context = self.engine._narrow_child_policy_context(  # noqa: SLF001
            parent=self.parent_request.policy_context,
            child_capability=child_capability,
        )
        child_meta = self.parent_request.metadata.model_copy(
            update={
                "parent_id": self.parent_request.metadata.envelope_id,
                "envelope_id": generate_ulid_str(),
            }
        )
        child_request = CapabilityInvocationRequest(
            metadata=child_meta,
            capability=CapabilityRef.model_validate(
                child_capability.model_dump(mode="python")
            ),
            input_payload=input_payload,
            policy_context=child_context,
            declared_autonomy=self.parent_request.declared_autonomy,
            requires_approval=False,
        )
        nested_result = self.engine._invoke_with_policy(request=child_request)  # noqa: SLF001
        if not nested_result.allowed:
            return CapabilityExecutionResponse(output=None)
        return CapabilityExecutionResponse(output=nested_result.output)


class DefaultCapabilityEngineService(CapabilityEngineService):
    """Default CES implementation enforcing policy-gated capability execution."""

    def __init__(
        self,
        *,
        settings: CapabilityEngineSettings,
        policy_service: PolicyService,
        registry: CapabilityRegistry,
    ) -> None:
        self._settings = settings
        self._policy_service = policy_service
        self._registry = registry

    @classmethod
    def from_settings(
        cls,
        settings: BrainSettings,
        *,
        policy_service: PolicyService,
        registry: CapabilityRegistry | None = None,
    ) -> "DefaultCapabilityEngineService":
        """Build CES from typed settings and injected policy service dependency."""
        resolved = resolve_capability_engine_settings(settings)
        active_registry = registry or CapabilityRegistry()
        active_registry.discover(root=Path(resolved.discovery_root))
        return cls(
            settings=resolved,
            policy_service=policy_service,
            registry=active_registry,
        )

    @public_api_instrumented(
        logger=_LOGGER,
        component_id=str(SERVICE_COMPONENT_ID),
        id_fields=("meta",),
    )
    def health(self, *, meta: EnvelopeMeta) -> Envelope[CapabilityEngineHealthStatus]:
        """Return service readiness and discovered capability counts."""
        try:
            validate_meta(meta)
        except ValueError as exc:
            return failure(
                meta=meta,
                errors=[validation_error(str(exc), code=codes.INVALID_ARGUMENT)],
            )

        policy_health = self._policy_service.health(meta=meta)
        return success(
            meta=meta,
            payload=CapabilityEngineHealthStatus(
                service_ready=True,
                policy_ready=policy_health.ok,
                discovered_capabilities=self._registry.count(),
                detail="ok" if policy_health.ok else "policy service unhealthy",
            ),
        )

    @public_api_instrumented(
        logger=_LOGGER,
        component_id=str(SERVICE_COMPONENT_ID),
        id_fields=(),
    )
    def invoke_capability(
        self,
        *,
        meta: EnvelopeMeta,
        capability: CapabilityIdentity,
        input_payload: dict[str, object],
        policy_context: CapabilityPolicyContext,
    ) -> Envelope[CapabilityInvokeResult]:
        """Invoke one capability via policy wrapper with dedupe and approval handling."""
        try:
            validate_meta(meta)
        except ValueError as exc:
            return failure(
                meta=meta,
                errors=[validation_error(str(exc), code=codes.INVALID_ARGUMENT)],
            )

        capability_ref = CapabilityRef.model_validate(
            capability.model_dump(mode="python")
        )
        capability_id = capability_ref.capability_id
        spec = self._registry.resolve_spec(capability_id=capability_id)
        if spec is None:
            return failure(
                meta=meta,
                errors=[
                    not_found_error(
                        "capability not found",
                        code=codes.RESOURCE_NOT_FOUND,
                        metadata={"capability_id": capability_id},
                    )
                ],
            )

        request = CapabilityInvocationRequest(
            metadata=meta,
            capability=capability_ref,
            input_payload={key: value for key, value in input_payload.items()},
            policy_context=PolicyContext.model_validate(
                policy_context.model_dump(mode="python")
            ),
            declared_autonomy=spec.autonomy,
            requires_approval=spec.requires_approval,
        )

        result = self._invoke_with_policy(request=request)
        if not result.allowed:
            return failure(meta=meta, errors=result.errors)

        return success(
            meta=meta,
            payload=CapabilityInvokeResult(
                capability_id=capability_id,
                output=result.output,
                policy_decision_id=result.decision.decision_id,
                policy_allowed=result.decision.allowed,
                policy_reason_codes=result.decision.reason_codes,
                proposal_id=(
                    "" if result.proposal is None else result.proposal.proposal_id
                ),
            ),
        )

    def _invoke_with_policy(
        self, *, request: CapabilityInvocationRequest
    ) -> PolicyExecutionResult:
        handler = self._registry.resolve_handler(
            capability_id=request.capability.capability_id
        )

        if handler is None:
            return self._policy_service.authorize_and_execute(
                request=request,
                execute=lambda _: self._missing_handler_result(request=request),
            )

        runtime = _NestedRuntime(engine=self, parent_request=request)
        return self._policy_service.authorize_and_execute(
            request=request,
            execute=lambda allowed_request: PolicyExecutionResult(
                allowed=True,
                output=handler(allowed_request, runtime).output,
                errors=(),
                decision=self._default_allow_decision(),
                proposal=None,
            ),
        )

    def _narrow_child_policy_context(
        self,
        *,
        parent: PolicyContext,
        child_capability: CapabilityIdentity,
    ) -> PolicyContext:
        child_id = (
            f"{child_capability.kind}:{child_capability.namespace}:"
            f"{child_capability.name}:{child_capability.version or 'latest'}"
        )
        allowed = tuple({*parent.allowed_capabilities, child_id})
        return parent.model_copy(
            update={
                "allowed_capabilities": allowed,
                "parent_invocation_id": parent.invocation_id,
                "approval_token": "",
            }
        )

    @staticmethod
    def _default_allow_decision() -> PolicyDecision:
        # Callback return decision is overwritten by policy wrapper.
        return PolicyDecision(
            decision_id="placeholder",
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
            decision=self._default_allow_decision(),
            proposal=None,
        )
