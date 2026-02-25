"""Concrete Policy Service implementation with dedupe and approval flow."""

from __future__ import annotations

from datetime import datetime, timedelta
from hashlib import sha256
import json

from packages.brain_shared.config import BrainSettings
from packages.brain_shared.envelope import (
    Envelope,
    EnvelopeMeta,
    failure,
    success,
    validate_meta,
)
from packages.brain_shared.errors import codes, policy_error, validation_error
from packages.brain_shared.ids import generate_ulid_str
from packages.brain_shared.logging import get_logger, public_api_instrumented
from services.action.policy_service.component import SERVICE_COMPONENT_ID
from services.action.policy_service.config import (
    PolicyServiceSettings,
    resolve_policy_service_settings,
)
from services.action.policy_service.domain import (
    APPROVAL_REQUIRED_OBLIGATION,
    ApprovalProposal,
    CapabilityInvocationRequest,
    PolicyApprovalProposalRow,
    PolicyDecision,
    PolicyDecisionLogRow,
    PolicyDedupeLogRow,
    PolicyExecutionResult,
    PolicyHealthStatus,
    utc_now,
)
from services.action.policy_service.service import PolicyExecuteCallback, PolicyService

_LOGGER = get_logger(__name__)
_REASON_APPROVAL_TOKEN_EXPIRED = "approval_token_expired"
_REASON_APPROVAL_TOKEN_INVALID = "approval_token_invalid"
_REASON_APPROVAL_REQUIRED = "approval_required"
_REASON_AUTONOMY_EXCEEDS_LIMIT = "autonomy_exceeds_limit"
_REASON_CAPABILITY_NOT_ALLOWED_PREFIX = "capability_not_allowed"
_REASON_CHANNEL_DENIED = "channel_denied"
_REASON_CHANNEL_NOT_ALLOWED = "channel_not_allowed"
_REASON_DEDUPE_DUPLICATE_REQUEST = "dedupe_duplicate_request"
_REASON_MISSING_ACTOR_CONTEXT = "missing_actor_context"
_REASON_MISSING_CHANNEL_CONTEXT = "missing_channel_context"
_REASON_POLICY_ERROR = "policy_error"


class DefaultPolicyService(PolicyService):
    """Default policy service with in-memory append-only audit artifacts."""

    def __init__(self, *, settings: PolicyServiceSettings) -> None:
        self._settings = settings
        self._decision_log: list[PolicyDecisionLogRow] = []
        self._proposal_log: list[PolicyApprovalProposalRow] = []
        self._dedupe_log: list[PolicyDedupeLogRow] = []
        self._seen_envelopes: dict[str, datetime] = {}

    @classmethod
    def from_settings(cls, settings: BrainSettings) -> "DefaultPolicyService":
        """Build policy service from typed root runtime settings."""
        return cls(settings=resolve_policy_service_settings(settings))

    @public_api_instrumented(
        logger=_LOGGER,
        component_id=str(SERVICE_COMPONENT_ID),
        id_fields=("meta",),
    )
    def health(self, *, meta: EnvelopeMeta) -> Envelope[PolicyHealthStatus]:
        """Return service readiness and in-memory audit counters."""
        try:
            validate_meta(meta)
        except ValueError as exc:
            return failure(
                meta=meta,
                errors=[validation_error(str(exc), code=codes.INVALID_ARGUMENT)],
            )

        return success(
            meta=meta,
            payload=PolicyHealthStatus(
                service_ready=True,
                decision_log_rows=len(self._decision_log),
                proposal_rows=len(self._proposal_log),
                dedupe_rows=len(self._dedupe_log),
                detail="ok",
            ),
        )

    @public_api_instrumented(
        logger=_LOGGER,
        component_id=str(SERVICE_COMPONENT_ID),
    )
    def authorize_and_execute(
        self,
        *,
        request: CapabilityInvocationRequest,
        execute: PolicyExecuteCallback,
    ) -> PolicyExecutionResult:
        """Apply dedupe/policy checks and execute callback only when authorized."""
        decision, proposal = self._evaluate_policy(request=request)
        if not decision.allowed:
            self._append_decision_row(request=request, decision=decision)
            self._apply_retention()
            return self._deny_result(decision=decision, proposal=proposal)

        try:
            callback_result = execute(request)
        except Exception as exc:  # noqa: BLE001
            error = policy_error(
                "policy callback execution failed",
                code=codes.INTERNAL_ERROR,
                metadata={"exception": str(type(exc).__name__)},
            )
            failed_decision = decision.model_copy(
                update={
                    "allowed": False,
                    "reason_codes": (*decision.reason_codes, _REASON_POLICY_ERROR),
                }
            )
            self._append_decision_row(request=request, decision=failed_decision)
            return PolicyExecutionResult(
                allowed=False,
                output=None,
                errors=(error,),
                decision=failed_decision,
                proposal=None,
            )

        self._append_decision_row(request=request, decision=decision)
        self._apply_retention()
        return callback_result.model_copy(update={"decision": decision})

    def _evaluate_policy(
        self, *, request: CapabilityInvocationRequest
    ) -> tuple[PolicyDecision, ApprovalProposal | None]:
        now = utc_now()
        reason_codes: list[str] = []
        obligations: list[str] = []
        metadata: dict[str, str] = {}

        dedupe_reason = self._check_dedupe(request=request, now=now)
        if dedupe_reason is not None:
            reason_codes.append(dedupe_reason)

        actor = request.policy_context.actor.strip()
        channel = request.policy_context.channel.strip()
        if actor == "":
            reason_codes.append(_REASON_MISSING_ACTOR_CONTEXT)
        if channel == "":
            reason_codes.append(_REASON_MISSING_CHANNEL_CONTEXT)

        if channel.startswith("denied:"):
            reason_codes.append(_REASON_CHANNEL_DENIED)
        if channel == "forbidden":
            reason_codes.append(_REASON_CHANNEL_NOT_ALLOWED)

        if request.policy_context.allowed_capabilities:
            capability_id = request.capability.capability_id
            if capability_id not in request.policy_context.allowed_capabilities:
                reason_codes.append(
                    f"{_REASON_CAPABILITY_NOT_ALLOWED_PREFIX}:{capability_id}"
                )

        max_autonomy = request.policy_context.max_autonomy
        if max_autonomy is not None and request.declared_autonomy > max_autonomy:
            reason_codes.append(_REASON_AUTONOMY_EXCEEDS_LIMIT)

        proposal: ApprovalProposal | None = None
        if request.requires_approval:
            token_state = self._validate_approval_token(request=request, now=now)
            if token_state == "missing":
                obligations.append(APPROVAL_REQUIRED_OBLIGATION)
                reason_codes.append(_REASON_APPROVAL_REQUIRED)
                proposal = self._create_proposal(request=request, now=now)
                metadata["proposal_id"] = proposal.proposal_id
            elif token_state == "expired":
                reason_codes.append(_REASON_APPROVAL_TOKEN_EXPIRED)
            elif token_state == "invalid":
                reason_codes.append(_REASON_APPROVAL_TOKEN_INVALID)

        if proposal is not None:
            self._proposal_log.append(
                PolicyApprovalProposalRow(proposal=proposal, status="pending")
            )

        allowed = len(reason_codes) == 0 and len(obligations) == 0
        decision = PolicyDecision(
            decision_id=generate_ulid_str(),
            allowed=allowed,
            reason_codes=tuple(reason_codes),
            obligations=tuple(obligations),
            policy_metadata=metadata,
            decided_at=now,
            policy_name="policy_service.v1",
            policy_version="1",
        )
        return decision, proposal

    def _deny_result(
        self,
        *,
        decision: PolicyDecision,
        proposal: ApprovalProposal | None,
    ) -> PolicyExecutionResult:
        metadata = {"reason_codes": ",".join(decision.reason_codes)}
        proposal_id = decision.policy_metadata.get("proposal_id", "")
        if proposal_id:
            metadata["proposal_id"] = proposal_id

        return PolicyExecutionResult(
            allowed=False,
            output=None,
            errors=(
                policy_error(
                    "policy denied capability invocation",
                    code=codes.PERMISSION_DENIED,
                    metadata=metadata,
                ),
            ),
            decision=decision,
            proposal=proposal,
        )

    def _append_decision_row(
        self, *, request: CapabilityInvocationRequest, decision: PolicyDecision
    ) -> None:
        self._decision_log.append(
            PolicyDecisionLogRow(
                decision=decision,
                metadata=request.metadata,
                actor=request.policy_context.actor,
                channel=request.policy_context.channel,
                capability_id=request.capability.capability_id,
            )
        )

    def _check_dedupe(
        self, *, request: CapabilityInvocationRequest, now: datetime
    ) -> str | None:
        dedupe_key = request.metadata.envelope_id
        seen_at = self._seen_envelopes.get(dedupe_key)
        denied = False
        reason: str | None = None
        if seen_at is not None and self._settings.dedupe_window_seconds > 0:
            delta_seconds = (now - seen_at).total_seconds()
            if delta_seconds <= self._settings.dedupe_window_seconds:
                denied = True
                reason = _REASON_DEDUPE_DUPLICATE_REQUEST
        self._seen_envelopes[dedupe_key] = now
        self._dedupe_log.append(
            PolicyDedupeLogRow(
                dedupe_key=dedupe_key,
                envelope_id=request.metadata.envelope_id,
                trace_id=request.metadata.trace_id,
                denied=denied,
                window_seconds=self._settings.dedupe_window_seconds,
                created_at=now,
            )
        )
        return reason

    def _create_proposal(
        self, *, request: CapabilityInvocationRequest, now: datetime
    ) -> ApprovalProposal:
        payload = {
            "kind": request.capability.kind,
            "namespace": request.capability.namespace,
            "name": request.capability.name,
            "version": request.capability.version,
            "actor": request.policy_context.actor,
            "channel": request.policy_context.channel,
            "input": request.input_payload,
        }
        digest = sha256(
            json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
        ).hexdigest()
        proposal_id = digest[:26]
        expires_at = now + timedelta(seconds=self._settings.approval_ttl_seconds)
        return ApprovalProposal(
            proposal_id=proposal_id,
            action_kind=request.capability.kind,
            action_name=f"{request.capability.namespace}.{request.capability.name}",
            action_version=request.capability.version or "latest",
            autonomy=request.declared_autonomy,
            required_capabilities=(request.capability.capability_id,),
            reason_for_review=APPROVAL_REQUIRED_OBLIGATION,
            actor=request.policy_context.actor,
            channel=request.policy_context.channel,
            trace_id=request.metadata.trace_id,
            invocation_id=request.policy_context.invocation_id,
            created_at=now,
            expires_at=expires_at,
        )

    def _validate_approval_token(
        self, *, request: CapabilityInvocationRequest, now: datetime
    ) -> str:
        proposal_id = request.policy_context.approval_token.strip()
        if proposal_id == "":
            return "missing"

        proposal = self._find_pending_proposal(proposal_id=proposal_id)
        if proposal is None:
            return "invalid"

        if proposal.actor != request.policy_context.actor:
            return "invalid"

        if proposal.expires_at < now:
            return "expired"
        return "valid"

    def _find_pending_proposal(self, *, proposal_id: str) -> ApprovalProposal | None:
        if proposal_id == "":
            return None
        for row in reversed(self._proposal_log):
            if row.proposal.proposal_id == proposal_id and row.status == "pending":
                return row.proposal
        return None

    def _apply_retention(self) -> None:
        max_age = self._settings.retention_max_age_seconds
        if max_age is not None:
            cutoff = utc_now() - timedelta(seconds=max_age)
            self._decision_log = [
                row for row in self._decision_log if row.decision.decided_at >= cutoff
            ]
            self._proposal_log = [
                row for row in self._proposal_log if row.proposal.created_at >= cutoff
            ]
            self._dedupe_log = [
                row for row in self._dedupe_log if row.created_at >= cutoff
            ]

        max_rows = self._settings.retention_max_rows
        if max_rows is not None:
            self._decision_log = self._decision_log[-max_rows:]
            self._proposal_log = self._proposal_log[-max_rows:]
            self._dedupe_log = self._dedupe_log[-max_rows:]
