"""Concrete Policy Service implementation with regime snapshots and approvals."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from hashlib import sha256
import json
from typing import Any

from lib.shared.approval import normalize_approval_intent
from lib.shared.auth.slash_authenticity import (
    SlashAuthenticityError,
    default_secret_path,
    read_secret,
    verify_proof,
)
from lib.shared.config import ApprovalResponseSettings, CoreRuntimeSettings
from lib.shared.envelope import (
    Envelope,
    EnvelopeKind,
    EnvelopeMeta,
    success,
    validate_meta,
)
from lib.shared.errors import codes, policy_error
from lib.shared.ids import generate_ulid_str
from lib.shared.logging import get_logger, public_api_instrumented
from services.effect.relay.domain import ApprovalNotificationPayload
from services.effect.relay.service import RelayService
from services.reason.policy.component import SERVICE_COMPONENT_ID
from services.reason.policy.config import (
    PolicyServiceSettings,
    resolve_policy_service_settings,
)
from services.reason.policy.data.repository import (
    InMemoryPolicyPersistenceRepository,
    PostgresPolicyPersistenceRepository,
)
from services.reason.policy.data.runtime import PolicyServicePostgresRuntime
from services.reason.policy.domain import (
    APPROVAL_REQUIRED_OBLIGATION,
    UNKNOWN_CALL_TARGET_REASON,
    ActorPolicyDeclaration,
    ApprovalProposal,
    OpInvocationRequest,
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
)
from services.reason.policy.interfaces import PolicyPersistenceRepository
from services.reason.policy.service import PolicyExecuteCallback, PolicyService

_LOGGER = get_logger(__name__)

_REASON_APPROVAL_AMBIGUOUS = "approval_ambiguous"
_REASON_APPROVAL_CLARIFICATION_REQUIRED = "approval_clarification_required"
_REASON_APPROVAL_REQUIRED = "approval_required"
_REASON_APPROVAL_TOKEN_EXPIRED = "approval_token_expired"
_REASON_APPROVAL_TOKEN_INVALID = "approval_token_invalid"
_REASON_CALLBACK_DENIED = "execution_denied"
_REASON_OP_DISABLED = "op_disabled"
_REASON_CHANNEL_DENIED = "channel_denied"
_REASON_CHANNEL_NOT_ALLOWED = "channel_not_allowed"
_REASON_DEDUPE_DUPLICATE_REQUEST = "dedupe_duplicate_request"
_REASON_POLICY_ERROR = "policy_error"
_REASON_ACTOR_DENIED = "actor_denied"
_REASON_ACTOR_NOT_ALLOWED = "actor_not_allowed"
_REASON_APPROVAL_NOTIFICATION_FAILED = "approval_notification_failed"
_REASON_SLASH_AUTHENTICITY_INVALID = "slash_authenticity_invalid"

_TOKEN_VALID = "valid"
_TOKEN_INVALID = "invalid"
_TOKEN_EXPIRED = "expired"

# Proposal tokens are derived from the first N hex chars of a SHA-256 digest.
# 26 chars = 104 bits of entropy, matching ULID string length for consistency.
_PROPOSAL_TOKEN_LENGTH = 26


class DefaultPolicyService(PolicyService):
    """Default policy service implementing effective-policy ownership and approvals."""

    def __init__(
        self,
        *,
        settings: PolicyServiceSettings,
        persistence: PolicyPersistenceRepository | None = None,
        outbound_service: RelayService | None = None,
        approval_response_settings: ApprovalResponseSettings | None = None,
    ) -> None:
        self._settings = settings
        self._persistence = persistence or InMemoryPolicyPersistenceRepository()
        self._outbound_service = outbound_service
        self._approval_response_settings = (
            approval_response_settings
            if approval_response_settings is not None
            else ApprovalResponseSettings()
        )
        self._seen_envelopes: dict[str, datetime] = {}
        # In-memory nonce ledger for slash authenticity replay protection.
        # Single-instance Brain Core, so process-local state is sufficient;
        # entries auto-expire on read past the validity window.
        self._slash_authenticity_seen_nonces: dict[str, datetime] = {}
        self._effective_policy = self._initialize_effective_policy()

    @classmethod
    def from_settings(
        cls,
        settings: CoreRuntimeSettings,
        *,
        outbound_service: RelayService | None = None,
    ) -> "DefaultPolicyService":
        """Build policy service from typed root runtime settings."""
        runtime = PolicyServicePostgresRuntime.from_settings(settings)
        return cls(
            settings=resolve_policy_service_settings(settings),
            persistence=PostgresPolicyPersistenceRepository(runtime.schema_sessions),
            outbound_service=outbound_service,
            approval_response_settings=settings.core.profile.approval_responses,
        )

    @public_api_instrumented(
        logger=_LOGGER,
        component_id=str(SERVICE_COMPONENT_ID),
        id_fields=("meta",),
    )
    def health(self, *, meta: EnvelopeMeta) -> Envelope[PolicyHealthStatus]:
        """Return service readiness, regime pointer, and audit row counters."""
        validate_meta(meta)

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
        request: OpInvocationRequest,
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
                created_at=datetime.now(UTC),
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
            op_id: rule.model_dump(mode="python") for op_id, rule in base.rules.items()
        }
        for overlay in sorted(overlays, key=lambda item: item.name):
            for unset_path in overlay.unset:
                self._unset_path(rules=rules, path=unset_path)
            for op_id, patch in overlay.rules.items():
                current = rules.get(op_id, PolicyRule().model_dump(mode="python"))
                patch_data = patch.model_dump(mode="python", exclude_none=True)
                for key, value in patch_data.items():
                    current[key] = value
                rules[op_id] = current

        validated = {
            op_id: PolicyRule.model_validate(rule) for op_id, rule in rules.items()
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
        op_id = parts[1]
        field_name = parts[2]
        if op_id in rules:
            rules[op_id].pop(field_name, None)

    def _evaluate_policy(
        self, *, request: OpInvocationRequest
    ) -> tuple[PolicyDecision, ApprovalProposal | None]:
        now = datetime.now(UTC)
        regime = self._require_active_regime()
        reason_codes: list[str] = []
        obligations: list[str] = []
        policy_metadata: dict[str, str] = {}

        dedupe_reason = self._check_dedupe(request=request, now=now)
        if dedupe_reason is not None:
            reason_codes.append(dedupe_reason)

        rule = self._effective_policy.rules.get(request.op_policy.op_id)
        wildcard_rule = self._effective_policy.rules.get("*")
        if rule is None and wildcard_rule is None:
            reason_codes.append(UNKNOWN_CALL_TARGET_REASON)
            rule = PolicyRule(enabled=False)
        elif rule is None:
            rule = wildcard_rule

        if not rule.enabled:
            reason_codes.append(_REASON_OP_DISABLED)

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

        proposal: ApprovalProposal | None = None
        actor_policy = self._settings.actors.get(request.invocation.actor.strip())
        actor_default = self._actor_effect_default(
            actor_policy=actor_policy,
            effect=request.op_policy.effect,
        )
        if actor_default == "deny":
            reason_codes.append(_REASON_ACTOR_DENIED)
        actor_override = self._actor_override(
            actor_policy=actor_policy,
            op_id=request.op_policy.op_id,
        )
        if actor_override is not None and actor_override.allow is False:
            reason_codes.append(_REASON_ACTOR_DENIED)

        approval = (
            request.op_policy.approval if rule.approval is None else rule.approval
        )
        if actor_default == "require_approval":
            approval = "always"
        if actor_override is not None and actor_override.approval is not None:
            approval = actor_override.approval
        approval_required = approval == "always"
        if approval_required:
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
                policy_metadata["expires_at"] = proposal.expires_at.isoformat()
                if not self._notify_outbound(request=request, proposal=proposal):
                    reason_codes.append(_REASON_APPROVAL_NOTIFICATION_FAILED)
            elif approved_token:
                self._persistence.mark_proposal_status(
                    token=approved_token, status="approved"
                )

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
        request: OpInvocationRequest,
        now: datetime,
    ) -> tuple[bool, str | None, str]:
        if request.invocation.slash_authenticity is not None:
            authentic = self._resolve_slash_authenticity(request=request, now=now)
            if authentic[0]:
                return authentic
            if authentic[1] is not None:
                return authentic

        token = request.invocation.approval_token.strip()
        if token:
            token_status = self._validate_approval_token(
                token=token,
                actor=request.invocation.actor,
                channel=request.invocation.channel,
                now=now,
            )
            if token_status == _TOKEN_VALID:
                return True, None, token
            if token_status == _TOKEN_EXPIRED:
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

    def _actor_effect_default(
        self,
        *,
        actor_policy: ActorPolicyDeclaration | None,
        effect: str,
    ) -> str:
        """Return one actor default posture for the op effect."""
        if actor_policy is None:
            return "allow"
        return str(getattr(actor_policy.defaults, effect))

    def _actor_override(
        self,
        *,
        actor_policy: ActorPolicyDeclaration | None,
        op_id: str,
    ):
        """Return one actor's explicit per-op override when configured."""
        if actor_policy is None:
            return None
        return actor_policy.overrides.get(op_id)

    def _resolve_slash_authenticity(
        self,
        *,
        request: OpInvocationRequest,
        now: datetime,
    ) -> tuple[bool, str | None, str]:
        """Verify a slash authenticity HMAC and accept it as approval if valid.

        Returns ``(True, None, "")`` on a verified proof, ``(False, reason, "")``
        on an invalid one, or ``(False, None, "")`` if there is nothing to do.
        """
        proof = request.invocation.slash_authenticity
        if proof is None:
            return False, None, ""
        validity_seconds = self._settings.slash_authenticity_validity_seconds
        # Sweep expired nonces opportunistically to keep the ledger bounded.
        cutoff = now - timedelta(seconds=validity_seconds)
        self._slash_authenticity_seen_nonces = {
            nonce: seen_at
            for nonce, seen_at in self._slash_authenticity_seen_nonces.items()
            if seen_at > cutoff
        }
        if proof.nonce in self._slash_authenticity_seen_nonces:
            return False, _REASON_SLASH_AUTHENTICITY_INVALID, ""
        try:
            secret = read_secret(default_secret_path())
        except SlashAuthenticityError:
            _LOGGER.warning(
                "slash authenticity secret unavailable; cannot verify proof"
            )
            return False, _REASON_SLASH_AUTHENTICITY_INVALID, ""
        now_ms = int(now.timestamp() * 1000)
        if not verify_proof(
            secret,
            channel=request.invocation.channel,
            message_text=request.invocation.message_text,
            proof=proof,
            now_ms=now_ms,
            validity_seconds=validity_seconds,
        ):
            return False, _REASON_SLASH_AUTHENTICITY_INVALID, ""
        self._slash_authenticity_seen_nonces[proof.nonce] = now
        return True, None, ""

    def _resolve_deterministic_correlation(
        self,
        *,
        request: OpInvocationRequest,
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
            if status == _TOKEN_VALID:
                return True, None, linked_token
            if status == _TOKEN_EXPIRED:
                return False, _REASON_APPROVAL_TOKEN_EXPIRED, ""
            return False, _REASON_APPROVAL_TOKEN_INVALID, ""

        text = request.invocation.message_text.strip().lower()
        if text == "":
            return False, None, ""

        intent = normalize_approval_intent(
            message_text=text,
            settings=self._approval_response_settings,
        )
        if intent is None:
            return False, None, ""

        pending = list(
            self._persistence.list_pending_proposals(
                actor=request.invocation.actor,
                channel=request.invocation.channel,
                now=now,
            )
        )
        mentioned = [
            item for item in pending if item.proposal.proposal_token.lower() in text
        ]
        if len(mentioned) == 1:
            token = mentioned[0].proposal.proposal_token
            if intent == "approve":
                return True, None, token
            if intent == "reject":
                self._persistence.mark_proposal_status(token=token, status="rejected")
                return False, _REASON_APPROVAL_REQUIRED, ""

        if len(pending) != 1:
            return False, None, ""

        if intent == "approve":
            return True, None, pending[0].proposal.proposal_token
        if intent == "reject":
            self._persistence.mark_proposal_status(
                token=pending[0].proposal.proposal_token, status="rejected"
            )
            return False, _REASON_APPROVAL_REQUIRED, ""
        return False, None, ""

    def _resolve_disambiguation(
        self,
        *,
        request: OpInvocationRequest,
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
            proposal = self._persistence.find_pending_proposal(token=best_token)
            if proposal is not None:
                self._persistence.increment_proposal_clarification_attempts(
                    token=proposal.proposal_token
                )
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
        expires_at = decision.policy_metadata.get("expires_at", "")
        if expires_at:
            metadata["expires_at"] = expires_at

        return PolicyExecutionResult(
            allowed=False,
            output=None,
            errors=(
                policy_error(
                    "policy denied op invocation",
                    code=codes.PERMISSION_DENIED,
                    metadata=metadata,
                ),
            ),
            decision=decision,
            proposal=proposal,
        )

    def _append_decision_row(
        self, *, request: OpInvocationRequest, decision: PolicyDecision
    ) -> None:
        self._persistence.append_decision(
            row=PolicyDecisionLogRow(
                decision=decision,
                metadata=request.metadata,
                actor=request.invocation.actor,
                channel=request.invocation.channel,
                op_id=request.op_policy.op_id,
            ),
        )

    def _check_dedupe(
        self, *, request: OpInvocationRequest, now: datetime
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
        request: OpInvocationRequest,
        regime: PolicyRegimeSnapshot,
        now: datetime,
    ) -> ApprovalProposal:
        payload = {
            "op_id": request.op_policy.op_id,
            "version": request.op_policy.version,
            "actor": request.invocation.actor,
            "channel": request.invocation.channel,
            "input": request.input_payload,
        }
        digest = sha256(
            json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
        ).hexdigest()
        proposal_token = digest[:_PROPOSAL_TOKEN_LENGTH]
        expires_at = now + timedelta(seconds=self._settings.approval_ttl_seconds)
        return ApprovalProposal(
            proposal_token=proposal_token,
            op_id=request.op_policy.op_id,
            op_version=request.op_policy.version,
            summary=f"Approval required for {request.op_policy.op_id}",
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
        proposal = self._persistence.find_pending_proposal(token=token)
        if proposal is None:
            return _TOKEN_INVALID
        if proposal.actor != actor or proposal.channel != channel:
            return _TOKEN_INVALID
        if proposal.expires_at < now:
            self._persistence.mark_proposal_status(token=token, status="expired")
            return _TOKEN_EXPIRED
        return _TOKEN_VALID

    def _notify_outbound(
        self,
        *,
        request: OpInvocationRequest,
        proposal: ApprovalProposal,
    ) -> bool:
        """Route one approval proposal via Relay outbound when configured."""
        if self._outbound_service is None:
            return True

        routed_meta = request.metadata.model_copy(
            update={
                "envelope_id": generate_ulid_str(),
                "parent_id": request.metadata.envelope_id,
                "kind": EnvelopeKind.EVENT,
                "source": str(SERVICE_COMPONENT_ID),
                "timestamp": datetime.now(UTC),
            }
        )
        routed = self._outbound_service.route_approval_notification(
            meta=routed_meta,
            approval=ApprovalNotificationPayload(
                proposal_token=proposal.proposal_token,
                op_id=proposal.op_id,
                op_version=proposal.op_version,
                summary=proposal.summary,
                actor=proposal.actor,
                channel=proposal.channel,
                trace_id=proposal.trace_id,
                invocation_id=proposal.invocation_id,
                input_payload=request.input_payload,
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

        self._trim_seen_envelopes()

    def _trim_seen_envelopes(self) -> None:
        """Evict stale entries from the in-memory dedupe map."""
        window = self._settings.dedupe_window_seconds
        if window <= 0:
            return
        cutoff = datetime.now(UTC) - timedelta(seconds=window)
        stale = [
            key for key, seen_at in self._seen_envelopes.items() if seen_at < cutoff
        ]
        for key in stale:
            del self._seen_envelopes[key]
