"""Concrete Policy Service implementation with regime snapshots and approvals."""

from __future__ import annotations

from datetime import datetime, timedelta
from hashlib import sha256
import json
from typing import Any

from packages.brain_shared.config import CoreRuntimeSettings
from packages.brain_shared.envelope import (
    Envelope,
    EnvelopeKind,
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
from services.action.policy_service.data.repository import (
    InMemoryPolicyPersistenceRepository,
    PostgresPolicyPersistenceRepository,
)
from services.action.policy_service.data.runtime import PolicyServicePostgresRuntime
from services.action.policy_service.domain import (
    APPROVAL_REQUIRED_OBLIGATION,
    ApprovalProposal,
    CapabilityInvocationRequest,
    PolicyApprovalProposalRow,
    PolicyDecision,
    PolicyDecisionLogRow,
    PolicyDedupeLogRow,
    PolicyDocument,
    PolicyExecutionResult,
    PolicyHealthStatus,
    PolicyOverlay,
    PolicyRegimeSnapshot,
    PolicyRule,
    utc_now,
)
from services.action.policy_service.interfaces import PolicyPersistenceRepository
from services.action.policy_service.service import PolicyExecuteCallback, PolicyService
from services.action.attention_router.domain import (
    ApprovalNotificationPayload as RouterApprovalNotificationPayload,
)
from services.action.attention_router.service import (
    AttentionRouterService,
    build_attention_router_service,
)

_LOGGER = get_logger(__name__)

_REASON_APPROVAL_AMBIGUOUS = "approval_ambiguous"
_REASON_APPROVAL_CLARIFICATION_REQUIRED = "approval_clarification_required"
_REASON_APPROVAL_REQUIRED = "approval_required"
_REASON_APPROVAL_TOKEN_EXPIRED = "approval_token_expired"
_REASON_APPROVAL_TOKEN_INVALID = "approval_token_invalid"
_REASON_AUTONOMY_EXCEEDS_LIMIT = "autonomy_exceeds_limit"
_REASON_CALLBACK_DENIED = "execution_denied"
_REASON_CAPABILITY_DISABLED = "capability_disabled"
_REASON_CHANNEL_DENIED = "channel_denied"
_REASON_CHANNEL_NOT_ALLOWED = "channel_not_allowed"
_REASON_DEDUPE_DUPLICATE_REQUEST = "dedupe_duplicate_request"
_REASON_POLICY_ERROR = "policy_error"
_REASON_UNKNOWN_CALL_TARGET = "unknown_call_target"
_REASON_ACTOR_DENIED = "actor_denied"
_REASON_ACTOR_NOT_ALLOWED = "actor_not_allowed"
_REASON_APPROVAL_NOTIFICATION_FAILED = "approval_notification_failed"


class DefaultPolicyService(PolicyService):
    """Default policy service implementing effective-policy ownership and approvals."""

    def __init__(
        self,
        *,
        settings: PolicyServiceSettings,
        persistence: PolicyPersistenceRepository | None = None,
        attention_router_service: AttentionRouterService | None = None,
    ) -> None:
        self._settings = settings
        self._persistence = persistence or InMemoryPolicyPersistenceRepository()
        self._attention_router_service = attention_router_service
        self._seen_envelopes: dict[str, datetime] = {}
        self._effective_policy = self._initialize_effective_policy()

    @classmethod
    def from_settings(
        cls,
        settings: CoreRuntimeSettings,
        *,
        attention_router_service: AttentionRouterService | None = None,
    ) -> "DefaultPolicyService":
        """Build policy service from typed root runtime settings."""
        runtime = PolicyServicePostgresRuntime.from_settings(settings)
        return cls(
            settings=resolve_policy_service_settings(settings),
            persistence=PostgresPolicyPersistenceRepository(runtime.schema_sessions),
            attention_router_service=attention_router_service
            or build_attention_router_service(settings=settings),
        )

    @public_api_instrumented(
        logger=_LOGGER,
        component_id=str(SERVICE_COMPONENT_ID),
        id_fields=("meta",),
    )
    def health(self, *, meta: EnvelopeMeta) -> Envelope[PolicyHealthStatus]:
        """Return service readiness, regime pointer, and audit row counters."""
        try:
            validate_meta(meta)
        except ValueError as exc:
            return failure(
                meta=meta,
                errors=[validation_error(str(exc), code=codes.INVALID_ARGUMENT)],
            )

        active_regime = self._persistence.get_active_policy_regime_id()

        return success(
            meta=meta,
            payload=PolicyHealthStatus(
                service_ready=True,
                active_policy_regime_id=active_regime,
                regime_rows=len(self._persistence.list_policy_regimes()),
                decision_log_rows=self._persistence.count_decisions(),
                proposal_rows=self._persistence.count_proposals(),
                dedupe_rows=self._persistence.count_dedupe(),
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
        """Apply policy checks and execute callback only when authorization passes."""
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
            self._apply_retention()
            return PolicyExecutionResult(
                allowed=False,
                output=None,
                errors=(error,),
                decision=failed_decision,
                proposal=None,
            )

        resolved = decision
        if not callback_result.allowed:
            callback_reasons = tuple(
                code
                for code in callback_result.decision.reason_codes
                if code not in resolved.reason_codes
            )
            reason_codes = (*resolved.reason_codes, *callback_reasons)
            if not reason_codes:
                reason_codes = (*resolved.reason_codes, _REASON_CALLBACK_DENIED)
            resolved = resolved.model_copy(
                update={"allowed": False, "reason_codes": reason_codes}
            )

        self._append_decision_row(request=request, decision=resolved)
        self._apply_retention()
        return callback_result.model_copy(
            update={"decision": resolved, "allowed": resolved.allowed}
        )

    def _initialize_effective_policy(self) -> PolicyDocument:
        effective = self._merge_policy(
            base=self._settings.base_policy, overlays=self._settings.overlays
        )
        payload = effective.model_dump(mode="python")
        serialized = json.dumps(payload, sort_keys=True, separators=(",", ":"))
        policy_hash = sha256(serialized.encode("utf-8")).hexdigest()
        existing = self._persistence.upsert_policy_regime(
            snapshot=PolicyRegimeSnapshot(
                policy_regime_id=generate_ulid_str(),
                policy_hash=policy_hash,
                policy_json=serialized,
                policy_id=effective.policy_id,
                policy_version=effective.policy_version,
                created_at=utc_now(),
            )
        )
        self._persistence.set_active_policy_regime(
            policy_regime_id=existing.policy_regime_id
        )
        return effective

    def _merge_policy(
        self, *, base: PolicyDocument, overlays: tuple[PolicyOverlay, ...]
    ) -> PolicyDocument:
        rules: dict[str, dict[str, Any]] = {
            capability_id: rule.model_dump(mode="python")
            for capability_id, rule in base.rules.items()
        }
        for overlay in sorted(overlays, key=lambda item: item.name):
            for unset_path in overlay.unset:
                self._unset_path(rules=rules, path=unset_path)
            for capability_id, patch in overlay.rules.items():
                current = rules.get(
                    capability_id, PolicyRule().model_dump(mode="python")
                )
                patch_data = patch.model_dump(mode="python", exclude_none=True)
                for key, value in patch_data.items():
                    current[key] = value
                rules[capability_id] = current

        validated = {
            capability_id: PolicyRule.model_validate(rule)
            for capability_id, rule in rules.items()
        }
        return PolicyDocument(
            policy_id=base.policy_id,
            policy_version=base.policy_version,
            rules=validated,
        )

    def _unset_path(self, *, rules: dict[str, dict[str, Any]], path: str) -> None:
        parts = [part for part in path.split(".") if part]
        if len(parts) != 3 or parts[0] != "rules":
            return
        capability_id = parts[1]
        field_name = parts[2]
        if capability_id in rules:
            rules[capability_id].pop(field_name, None)

    def _evaluate_policy(
        self, *, request: CapabilityInvocationRequest
    ) -> tuple[PolicyDecision, ApprovalProposal | None]:
        now = utc_now()
        regime = self._require_active_regime()
        reason_codes: list[str] = []
        obligations: list[str] = []
        policy_metadata: dict[str, str] = {}

        dedupe_reason = self._check_dedupe(request=request, now=now)
        if dedupe_reason is not None:
            reason_codes.append(dedupe_reason)

        rule = self._effective_policy.rules.get(request.capability.capability_id)
        wildcard_rule = self._effective_policy.rules.get("*")
        if rule is None and wildcard_rule is None:
            reason_codes.append(_REASON_UNKNOWN_CALL_TARGET)
            rule = PolicyRule(enabled=False)
        elif rule is None:
            rule = wildcard_rule

        if not rule.enabled:
            reason_codes.append(_REASON_CAPABILITY_DISABLED)

        actor = request.invocation.actor.strip()
        channel = request.invocation.channel.strip()

        if rule.actors_deny and actor in rule.actors_deny:
            reason_codes.append(_REASON_ACTOR_DENIED)
        if rule.actors_allow and actor not in rule.actors_allow:
            reason_codes.append(_REASON_ACTOR_NOT_ALLOWED)
        if rule.channels_deny and channel in rule.channels_deny:
            reason_codes.append(_REASON_CHANNEL_DENIED)
        if rule.channels_allow and channel not in rule.channels_allow:
            reason_codes.append(_REASON_CHANNEL_NOT_ALLOWED)

        if (
            rule.autonomy_ceiling is not None
            and request.capability.autonomy > rule.autonomy_ceiling
        ):
            reason_codes.append(_REASON_AUTONOMY_EXCEEDS_LIMIT)

        proposal: ApprovalProposal | None = None
        requires_approval = (
            request.capability.requires_approval
            if rule.require_approval is None
            else rule.require_approval
        )
        if requires_approval:
            approved, approval_reason, approved_token = self._resolve_approval(
                request=request,
                now=now,
            )
            if not approved:
                obligations.append(APPROVAL_REQUIRED_OBLIGATION)
                if approval_reason is not None:
                    reason_codes.append(approval_reason)
                proposal = self._create_proposal(
                    request=request, regime=regime, now=now
                )
                self._persistence.append_proposal(
                    row=PolicyApprovalProposalRow(proposal=proposal, status="pending")
                )
                policy_metadata["proposal_token"] = proposal.proposal_token
                if not self._notify_attention_router(
                    request=request, proposal=proposal
                ):
                    reason_codes.append(_REASON_APPROVAL_NOTIFICATION_FAILED)
            elif approved_token:
                self._mark_proposal_approved(token=approved_token)

        allowed = len(reason_codes) == 0 and len(obligations) == 0
        decision = PolicyDecision(
            decision_id=generate_ulid_str(),
            policy_regime_id=regime.policy_regime_id,
            policy_regime_hash=regime.policy_hash,
            allowed=allowed,
            reason_codes=tuple(reason_codes),
            obligations=tuple(obligations),
            policy_metadata=policy_metadata,
            decided_at=now,
            policy_name=self._effective_policy.policy_id,
            policy_version=self._effective_policy.policy_version,
        )
        return decision, proposal

    def _resolve_approval(
        self,
        *,
        request: CapabilityInvocationRequest,
        now: datetime,
    ) -> tuple[bool, str | None, str]:
        token = request.invocation.approval_token.strip()
        if token:
            token_status = self._validate_approval_token(
                token=token,
                actor=request.invocation.actor,
                channel=request.invocation.channel,
                now=now,
            )
            if token_status == "valid":
                return True, None, token
            if token_status == "expired":
                return False, _REASON_APPROVAL_TOKEN_EXPIRED, ""
            return False, _REASON_APPROVAL_TOKEN_INVALID, ""

        deterministic = self._resolve_deterministic_correlation(
            request=request, now=now
        )
        if deterministic[0]:
            return deterministic
        if deterministic[1] is not None:
            return deterministic

        disambiguated = self._resolve_disambiguation(request=request)
        if disambiguated[0]:
            return disambiguated
        if disambiguated[1] is not None:
            return disambiguated

        return False, _REASON_APPROVAL_REQUIRED, ""

    def _resolve_deterministic_correlation(
        self,
        *,
        request: CapabilityInvocationRequest,
        now: datetime,
    ) -> tuple[bool, str | None, str]:
        linked_token = request.invocation.reply_to_proposal_token.strip()
        if not linked_token:
            linked_token = request.invocation.reaction_to_proposal_token.strip()
        if linked_token:
            status = self._validate_approval_token(
                token=linked_token,
                actor=request.invocation.actor,
                channel=request.invocation.channel,
                now=now,
            )
            if status == "valid":
                return True, None, linked_token
            if status == "expired":
                return False, _REASON_APPROVAL_TOKEN_EXPIRED, ""
            return False, _REASON_APPROVAL_TOKEN_INVALID, ""

        text = request.invocation.message_text.strip().lower()
        if text == "":
            return False, None, ""

        pending = self._pending_proposals(
            actor=request.invocation.actor,
            channel=request.invocation.channel,
        )
        if len(pending) != 1:
            return False, None, ""

        affirmative = {"approve", "yes", "ok", "ship it", "do it"}
        negative = {"deny", "no", "reject", "cancel"}
        if text in affirmative:
            return True, None, pending[0].proposal.proposal_token
        if text in negative:
            self._mark_proposal_rejected(token=pending[0].proposal.proposal_token)
            return False, _REASON_APPROVAL_REQUIRED, ""
        return False, None, ""

    def _resolve_disambiguation(
        self,
        *,
        request: CapabilityInvocationRequest,
    ) -> tuple[bool, str | None, str]:
        raw = request.input_payload.get("_policy_disambiguation")
        if not isinstance(raw, list) or len(raw) == 0:
            return False, None, ""

        best_token = ""
        best_confidence = 0.0
        for item in raw:
            if not isinstance(item, dict):
                continue
            token = str(item.get("proposal_token", "")).strip()
            confidence = float(item.get("confidence", 0.0))
            if confidence > best_confidence and token:
                best_token = token
                best_confidence = confidence

        if best_token == "":
            return False, None, ""
        if best_confidence >= self._settings.auto_bind_threshold:
            return True, None, best_token
        if best_confidence >= self._settings.clarify_threshold:
            proposal = self._find_pending_proposal(best_token)
            if proposal is not None:
                self._increment_clarification_attempts(token=proposal.proposal_token)
                if proposal.clarification_attempts >= 1:
                    return False, _REASON_APPROVAL_AMBIGUOUS, ""
            return False, _REASON_APPROVAL_CLARIFICATION_REQUIRED, ""
        return False, _REASON_APPROVAL_AMBIGUOUS, ""

    def _deny_result(
        self,
        *,
        decision: PolicyDecision,
        proposal: ApprovalProposal | None,
    ) -> PolicyExecutionResult:
        metadata = {
            "reason_codes": ",".join(decision.reason_codes),
            "policy_regime_id": decision.policy_regime_id,
        }
        proposal_token = decision.policy_metadata.get("proposal_token", "")
        if proposal_token:
            metadata["proposal_token"] = proposal_token

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
        self._persistence.append_decision(
            row=PolicyDecisionLogRow(
                decision=decision,
                metadata=request.metadata,
                actor=request.invocation.actor,
                channel=request.invocation.channel,
                capability_id=request.capability.capability_id,
            ),
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
        self._persistence.append_dedupe(
            row=PolicyDedupeLogRow(
                dedupe_key=dedupe_key,
                envelope_id=request.metadata.envelope_id,
                trace_id=request.metadata.trace_id,
                denied=denied,
                window_seconds=self._settings.dedupe_window_seconds,
                created_at=now,
            ),
        )
        return reason

    def _create_proposal(
        self,
        *,
        request: CapabilityInvocationRequest,
        regime: PolicyRegimeSnapshot,
        now: datetime,
    ) -> ApprovalProposal:
        payload = {
            "capability_id": request.capability.capability_id,
            "version": request.capability.version,
            "actor": request.invocation.actor,
            "channel": request.invocation.channel,
            "input": request.input_payload,
        }
        digest = sha256(
            json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
        ).hexdigest()
        proposal_token = digest[:26]
        expires_at = now + timedelta(seconds=self._settings.approval_ttl_seconds)
        return ApprovalProposal(
            proposal_token=proposal_token,
            capability_id=request.capability.capability_id,
            capability_version=request.capability.version,
            summary=f"Approval required for {request.capability.capability_id}",
            actor=request.invocation.actor,
            channel=request.invocation.channel,
            trace_id=request.metadata.trace_id,
            invocation_id=request.invocation.invocation_id,
            policy_regime_id=regime.policy_regime_id,
            created_at=now,
            expires_at=expires_at,
        )

    def _validate_approval_token(
        self,
        *,
        token: str,
        actor: str,
        channel: str,
        now: datetime,
    ) -> str:
        proposal = self._find_pending_proposal(token)
        if proposal is None:
            return "invalid"
        if proposal.actor != actor or proposal.channel != channel:
            return "invalid"
        if proposal.expires_at < now:
            self._mark_proposal_expired(token=token)
            return "expired"
        return "valid"

    def _find_pending_proposal(self, token: str) -> ApprovalProposal | None:
        return self._persistence.find_pending_proposal(token=token)

    def _pending_proposals(
        self,
        *,
        actor: str,
        channel: str,
    ) -> list[PolicyApprovalProposalRow]:
        return list(
            self._persistence.list_pending_proposals(actor=actor, channel=channel)
        )

    def _mark_proposal_approved(self, *, token: str) -> None:
        self._persistence.mark_proposal_status(token=token, status="approved")

    def _mark_proposal_rejected(self, *, token: str) -> None:
        self._persistence.mark_proposal_status(token=token, status="rejected")

    def _mark_proposal_expired(self, *, token: str) -> None:
        self._persistence.mark_proposal_status(token=token, status="expired")

    def _increment_clarification_attempts(self, *, token: str) -> None:
        self._persistence.increment_proposal_clarification_attempts(token=token)

    def _notify_attention_router(
        self,
        *,
        request: CapabilityInvocationRequest,
        proposal: ApprovalProposal,
    ) -> bool:
        """Route one approval proposal via Attention Router when configured."""
        if self._attention_router_service is None:
            return True

        routed_meta = request.metadata.model_copy(
            update={
                "envelope_id": generate_ulid_str(),
                "parent_id": request.metadata.envelope_id,
                "kind": EnvelopeKind.EVENT,
                "source": str(SERVICE_COMPONENT_ID),
                "timestamp": utc_now(),
            }
        )
        routed = self._attention_router_service.route_approval_notification(
            meta=routed_meta,
            approval=RouterApprovalNotificationPayload(
                proposal_token=proposal.proposal_token,
                capability_id=proposal.capability_id,
                capability_version=proposal.capability_version,
                summary=proposal.summary,
                actor=proposal.actor,
                channel=proposal.channel,
                trace_id=proposal.trace_id,
                invocation_id=proposal.invocation_id,
                expires_at=proposal.expires_at,
            ),
        )
        return routed.ok

    def _require_active_regime(self) -> PolicyRegimeSnapshot:
        active_policy_regime_id = self._persistence.get_active_policy_regime_id()
        if active_policy_regime_id == "":
            raise RuntimeError("policy regime pointer not initialized")
        for regime in self._persistence.list_policy_regimes():
            if regime.policy_regime_id == active_policy_regime_id:
                return regime
        raise RuntimeError("active policy regime missing")

    def _apply_retention(self) -> None:
        max_age = self._settings.retention_max_age_seconds
        if max_age is not None:
            self._persistence.trim_by_max_age(max_age_seconds=max_age)

        max_rows = self._settings.retention_max_rows
        if max_rows is not None:
            self._persistence.trim_by_max_rows(max_rows=max_rows)
