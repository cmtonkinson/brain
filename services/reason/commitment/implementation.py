"""Concrete Commitment Service implementation."""

from __future__ import annotations

import json
import re
from datetime import UTC, date, datetime, time, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

from pydantic import BaseModel, ValidationError

from lib.shared.envelope import (
    Envelope,
    EnvelopeMeta,
    failure,
    success,
    validate_meta,
)
from lib.shared.errors import (
    ErrorDetail,
    codes,
    conflict_error,
    dependency_error,
    not_found_error,
    validation_error,
)
from lib.shared.logging import get_logger, public_api_instrumented
from resources.substrates.postgres.errors import normalize_postgres_error
from services.effect.relay.service import RelayService
from services.reason.commitment.component import SERVICE_COMPONENT_ID
from services.reason.commitment.config import CommitmentServiceSettings
from services.reason.commitment.data.runtime import CommitmentPostgresRuntime
from services.reason.commitment.domain import (
    CommitmentCandidate,
    CommitmentHistoryResult,
    CommitmentJobLink,
    CommitmentListResult,
    CommitmentMutationResult,
    CommitmentProgressRecord,
    CommitmentRecord,
    CommitmentReviewItem,
    CommitmentReviewRun,
    CommitmentState,
    CommitmentTransitionRecord,
    CreationProposalDecision,
    ExtractCandidatesResult,
    HealthStatus,
    LoopClosureIntent,
    LoopClosureResolutionResult,
    MissDetectionResult,
    ProposalActor,
    ProposalStatus,
    ReviewCategory,
    ReviewDeliveryResult,
    TransitionProposalDecision,
    TurnScanResult,
)
from services.reason.commitment.interfaces import CommitmentRepository
from services.reason.commitment.service import CommitmentService
from services.reason.commitment.validation import (
    CommitmentIdRequest,
    CreateCommitmentRequest,
    CreationProposalDecisionRequest,
    ListCommitmentsRequest,
    ListReviewItemsRequest,
    ListReviewRunsRequest,
    LoopClosureReplyRequest,
    RecordProgressRequest,
    ReviewRunIdRequest,
    TransitionCommitmentRequest,
    TransitionProposalDecisionRequest,
    UpdateCommitmentRequest,
)
from services.effect.language.service import LanguageService, ReasoningLevel
from services.reason.job.service import JobService
from services.reason.recall.service import RecallService
from services.state.cache.service import CacheService

_LOGGER = get_logger(__name__)
_DEFAULT_REVIEW_EPOCH = datetime(1970, 1, 1, tzinfo=UTC)

_PROMPTS_DIR = Path(__file__).resolve().parent / "prompts"
_PROMPT_TEMPLATE_VAR_RE = re.compile(r"\{\{\s*([a-z_][a-z0-9_]*)\s*\}\}")


def _load_prompt_file(path: Path) -> str:
    """Load one prompt text file from disk without altering its contents."""
    return path.read_text(encoding="utf-8")


def _render_prompt_template(template: str, /, **values: str) -> str:
    """Render one prompt template and reject unresolved placeholders."""

    def _replace(match: re.Match[str]) -> str:
        key = match.group(1)
        if key not in values:
            return match.group(0)
        return values[key]

    rendered = _PROMPT_TEMPLATE_VAR_RE.sub(_replace, template)
    unresolved = _PROMPT_TEMPLATE_VAR_RE.findall(rendered)
    if unresolved:
        raise ValueError(
            f"unresolved prompt template placeholders: {', '.join(sorted(unresolved))}"
        )
    return rendered


_DEDUPE_SYSTEM_TEMPLATE = _load_prompt_file(_PROMPTS_DIR / "dedupe-system.txt")
_DEDUPE_USER_TEMPLATE = _load_prompt_file(_PROMPTS_DIR / "dedupe-user-template.txt")
_EXTRACT_SYSTEM_PROMPT = _load_prompt_file(_PROMPTS_DIR / "extract-system.txt")
_EXTRACT_USER_TEMPLATE = _load_prompt_file(_PROMPTS_DIR / "extract-user-template.txt")

_PROGRESS_SNIPPET_MAX_LENGTH = 200

_ALLOWED_TRANSITIONS: dict[CommitmentState, frozenset[CommitmentState]] = {
    CommitmentState.OPEN: frozenset(
        {CommitmentState.COMPLETED, CommitmentState.MISSED, CommitmentState.CANCELED}
    ),
    CommitmentState.MISSED: frozenset(
        {CommitmentState.OPEN, CommitmentState.COMPLETED, CommitmentState.CANCELED}
    ),
    CommitmentState.COMPLETED: frozenset(),
    CommitmentState.CANCELED: frozenset(),
}


class DefaultCommitmentService(CommitmentService):
    """Default Commitment Service implementation with Postgres-backed state."""

    def __init__(
        self,
        *,
        settings: CommitmentServiceSettings,
        repository: CommitmentRepository,
        runtime: CommitmentPostgresRuntime,
        job_service: JobService,
        outbound_service: RelayService | None = None,
        language_service: LanguageService | None = None,
        recall_service: RecallService | None = None,
        cache_service: CacheService | None = None,
    ) -> None:
        self._settings = settings
        self._repository = repository
        self._runtime = runtime
        self._job_service = job_service
        self._outbound_service = outbound_service
        self._language_service = language_service
        self._recall_service = recall_service
        self._cache_service = cache_service
        self._dedupe_system_prompt = _render_prompt_template(
            _DEDUPE_SYSTEM_TEMPLATE,
            max_words=str(settings.dedupe_summary_max_words),
        )

    @public_api_instrumented(logger=_LOGGER, component_id=str(SERVICE_COMPONENT_ID))
    def create_commitment(
        self,
        *,
        meta: EnvelopeMeta,
        description: str,
        provenance_reference: str | None = None,
        ingestion_id: str | None = None,
        source: str | None = None,
        due_by: datetime | date | None = None,
        due_timezone: str | None = None,
        importance: int = 2,
        effort_provided: int = 2,
        effort_inferred: int | None = None,
        confidence: float | None = None,
        requested_by: str = ProposalActor.OPERATOR.value,
    ) -> Envelope[CommitmentMutationResult]:
        """Create one commitment or creation proposal."""
        request, errors = self._validate_request(
            meta=meta,
            model=CreateCommitmentRequest,
            payload={
                "description": description,
                "provenance_reference": provenance_reference,
                "ingestion_id": ingestion_id,
                "source": source,
                "due_by": due_by,
                "due_timezone": due_timezone,
                "importance": importance,
                "effort_provided": effort_provided,
                "effort_inferred": effort_inferred,
                "confidence": confidence,
                "requested_by": requested_by,
            },
        )
        if errors:
            return failure(meta=meta, errors=errors)
        assert isinstance(request, CreateCommitmentRequest)

        try:
            now = datetime.now(UTC)
            normalized_due_by, resolved_timezone = self._normalize_due_by(
                due_by=request.due_by,
                due_timezone=request.due_timezone,
            )
            matched_id, dedupe_conf, match_summary = self._check_dedupe(
                meta=meta,
                description=request.description,
            )
            if matched_id is not None and dedupe_conf is not None:
                proposal = self._repository.create_creation_proposal(
                    description=request.description,
                    provenance_reference=request.provenance_reference,
                    ingestion_id=request.ingestion_id,
                    source=request.source,
                    due_by=normalized_due_by,
                    due_timezone=resolved_timezone,
                    importance=request.importance,
                    effort_provided=request.effort_provided,
                    effort_inferred=request.effort_inferred,
                    requested_by=request.requested_by.value,
                    confidence=request.confidence,
                    matched_commitment_id=matched_id,
                    match_summary=match_summary,
                    dedupe_confidence=dedupe_conf,
                    created_at=now,
                )
                return success(
                    meta=meta,
                    payload=CommitmentMutationResult(creation_proposal=proposal),
                )
            if self._requires_creation_proposal(
                requested_by=request.requested_by,
                confidence=request.confidence,
            ):
                proposal = self._repository.create_creation_proposal(
                    description=request.description,
                    provenance_reference=request.provenance_reference,
                    ingestion_id=request.ingestion_id,
                    source=request.source,
                    due_by=normalized_due_by,
                    due_timezone=resolved_timezone,
                    importance=request.importance,
                    effort_provided=request.effort_provided,
                    effort_inferred=request.effort_inferred,
                    requested_by=request.requested_by.value,
                    confidence=request.confidence,
                    created_at=now,
                )
                return success(
                    meta=meta,
                    payload=CommitmentMutationResult(creation_proposal=proposal),
                )
            commitment = self._create_commitment_record(
                description=request.description,
                provenance_reference=request.provenance_reference,
                ingestion_id=request.ingestion_id,
                source=request.source,
                due_by=normalized_due_by,
                due_timezone=resolved_timezone,
                importance=request.importance,
                effort_provided=request.effort_provided,
                effort_inferred=request.effort_inferred,
                now=now,
            )
            job_link = self._ensure_follow_up_job_for_record(
                meta=meta, commitment=commitment
            )
            refreshed = (
                self._repository.get_commitment(commitment_id=commitment.id)
                or commitment
            )
            return success(
                meta=meta,
                payload=CommitmentMutationResult(
                    commitment=refreshed,
                    job_link=job_link,
                ),
            )
        except Exception as exc:  # noqa: BLE001
            return self._handle_exception(
                meta=meta, operation="create_commitment", exc=exc
            )

    @public_api_instrumented(logger=_LOGGER, component_id=str(SERVICE_COMPONENT_ID))
    def ingest_commitment_candidate(
        self,
        *,
        meta: EnvelopeMeta,
        description: str,
        provenance_reference: str | None = None,
        ingestion_id: str | None = None,
        source: str | None = None,
        due_by: datetime | date | None = None,
        due_timezone: str | None = None,
        importance: int = 2,
        effort_provided: int = 2,
        effort_inferred: int | None = None,
        confidence: float | None = None,
        requested_by: str = ProposalActor.SERVICE.value,
    ) -> Envelope[CommitmentMutationResult]:
        """Accept one typed intake candidate using the normal create path."""
        return self.create_commitment(
            meta=meta,
            description=description,
            provenance_reference=provenance_reference,
            ingestion_id=ingestion_id,
            source=source,
            due_by=due_by,
            due_timezone=due_timezone,
            importance=importance,
            effort_provided=effort_provided,
            effort_inferred=effort_inferred,
            confidence=confidence,
            requested_by=requested_by,
        )

    @public_api_instrumented(
        logger=_LOGGER,
        component_id=str(SERVICE_COMPONENT_ID),
        id_fields=("commitment_id",),
    )
    def update_commitment(
        self,
        *,
        meta: EnvelopeMeta,
        commitment_id: str,
        description: str | None = None,
        provenance_reference: str | None = None,
        ingestion_id: str | None = None,
        source: str | None = None,
        due_by: datetime | date | None = None,
        due_timezone: str | None = None,
        importance: int | None = None,
        effort_provided: int | None = None,
        effort_inferred: int | None = None,
        reviewed_at: datetime | None = None,
    ) -> Envelope[CommitmentMutationResult]:
        """Update one commitment without changing lifecycle state."""
        request, errors = self._validate_request(
            meta=meta,
            model=UpdateCommitmentRequest,
            payload={
                "commitment_id": commitment_id,
                "description": description,
                "provenance_reference": provenance_reference,
                "ingestion_id": ingestion_id,
                "source": source,
                "due_by": due_by,
                "due_timezone": due_timezone,
                "importance": importance,
                "effort_provided": effort_provided,
                "effort_inferred": effort_inferred,
                "reviewed_at": reviewed_at,
            },
        )
        if errors:
            return failure(meta=meta, errors=errors)
        assert isinstance(request, UpdateCommitmentRequest)

        try:
            current = self._repository.get_commitment(
                commitment_id=request.commitment_id
            )
            if current is None:
                return self._not_found(
                    meta=meta, entity="commitment", entity_id=request.commitment_id
                )
            fields = request.model_fields_set
            due_date_changed = "due_by" in fields or "due_timezone" in fields
            normalized_due_by = current.due_by
            resolved_timezone = current.due_timezone
            if due_date_changed:
                normalized_due_by, resolved_timezone = self._normalize_due_by(
                    due_by=request.due_by,
                    due_timezone=request.due_timezone or current.due_timezone,
                )
            now = datetime.now(UTC)
            urgency = self._recompute_urgency_for_update(
                current=current,
                due_by=normalized_due_by,
                due_date_changed=due_date_changed,
                importance=request.importance,
                effort_provided=request.effort_provided,
            )
            repo_kwargs: dict[str, object] = {
                "commitment_id": request.commitment_id,
                "updated_at": now,
            }
            if request.description is not None:
                repo_kwargs["description"] = request.description
            if request.importance is not None:
                repo_kwargs["importance"] = request.importance
            if request.effort_provided is not None:
                repo_kwargs["effort_provided"] = request.effort_provided
            if urgency is not None:
                repo_kwargs["urgency"] = urgency
            for _key in (
                "provenance_reference",
                "ingestion_id",
                "source",
                "effort_inferred",
                "reviewed_at",
            ):
                if _key in fields:
                    repo_kwargs[_key] = getattr(request, _key)
            if due_date_changed:
                repo_kwargs["due_by"] = normalized_due_by
                repo_kwargs["due_timezone"] = resolved_timezone
            if self._is_substantive_update(request):
                repo_kwargs["last_modified_at"] = now
            updated = self._repository.update_commitment(**repo_kwargs)
            if updated is None:
                return self._not_found(
                    meta=meta, entity="commitment", entity_id=request.commitment_id
                )
            job_link = self._ensure_follow_up_job_for_record(
                meta=meta, commitment=updated
            )
            refreshed = (
                self._repository.get_commitment(commitment_id=updated.id) or updated
            )
            return success(
                meta=meta,
                payload=CommitmentMutationResult(
                    commitment=refreshed, job_link=job_link
                ),
            )
        except Exception as exc:  # noqa: BLE001
            return self._handle_exception(
                meta=meta, operation="update_commitment", exc=exc
            )

    @public_api_instrumented(
        logger=_LOGGER,
        component_id=str(SERVICE_COMPONENT_ID),
        id_fields=("commitment_id",),
    )
    def transition_commitment(
        self,
        *,
        meta: EnvelopeMeta,
        commitment_id: str,
        to_state: str,
        requested_by: str,
        reason: str | None = None,
        confidence: float | None = None,
    ) -> Envelope[CommitmentMutationResult]:
        """Transition one commitment or persist a transition proposal."""
        request, errors = self._validate_request(
            meta=meta,
            model=TransitionCommitmentRequest,
            payload={
                "commitment_id": commitment_id,
                "to_state": to_state,
                "requested_by": requested_by,
                "reason": reason,
                "confidence": confidence,
            },
        )
        if errors:
            return failure(meta=meta, errors=errors)
        assert isinstance(request, TransitionCommitmentRequest)

        try:
            current = self._repository.get_commitment(
                commitment_id=request.commitment_id
            )
            if current is None:
                return self._not_found(
                    meta=meta, entity="commitment", entity_id=request.commitment_id
                )
            if request.to_state not in _ALLOWED_TRANSITIONS[current.state]:
                return failure(
                    meta=meta,
                    errors=[
                        conflict_error(
                            f"cannot transition commitment from '{current.state.value}' to '{request.to_state.value}'",
                            code=codes.CONFLICT,
                        )
                    ],
                )
            if self._requires_transition_proposal(
                requested_by=request.requested_by,
                to_state=request.to_state,
                confidence=request.confidence,
            ):
                proposal = self._repository.create_transition_proposal(
                    commitment_id=current.id,
                    from_state=current.state.value,
                    to_state=request.to_state.value,
                    requested_by=request.requested_by.value,
                    confidence=request.confidence,
                    threshold=self._settings.autonomous_transition_confidence_threshold,
                    reason=request.reason,
                    created_at=datetime.now(UTC),
                )
                return success(
                    meta=meta,
                    payload=CommitmentMutationResult(transition_proposal=proposal),
                )
            updated, transition = self._apply_transition(
                meta=meta,
                current=current,
                to_state=request.to_state,
                actor=request.requested_by,
                reason=request.reason,
                confidence=request.confidence,
            )
            return success(
                meta=meta,
                payload=CommitmentMutationResult(
                    commitment=updated, transition=transition
                ),
            )
        except Exception as exc:  # noqa: BLE001
            return self._handle_exception(
                meta=meta, operation="transition_commitment", exc=exc
            )

    @public_api_instrumented(
        logger=_LOGGER,
        component_id=str(SERVICE_COMPONENT_ID),
        id_fields=("commitment_id",),
    )
    def record_progress(
        self,
        *,
        meta: EnvelopeMeta,
        commitment_id: str,
        provenance_reference: str | None = None,
        occurred_at: datetime,
        summary: str,
        snippet: str | None = None,
    ) -> Envelope[CommitmentMutationResult]:
        """Record one progress event and update last_progress_at atomically."""
        request, errors = self._validate_request(
            meta=meta,
            model=RecordProgressRequest,
            payload={
                "commitment_id": commitment_id,
                "provenance_reference": provenance_reference,
                "occurred_at": occurred_at,
                "summary": summary,
                "snippet": snippet,
            },
        )
        if errors:
            return failure(meta=meta, errors=errors)
        assert isinstance(request, RecordProgressRequest)
        try:
            updated, progress = self._repository.create_progress_record(
                commitment_id=request.commitment_id,
                provenance_reference=request.provenance_reference,
                occurred_at=_ensure_utc(request.occurred_at),
                summary=request.summary,
                snippet=request.snippet,
                created_at=datetime.now(UTC),
            )
            if updated is None:
                return self._not_found(
                    meta=meta, entity="commitment", entity_id=request.commitment_id
                )
            return success(
                meta=meta,
                payload=CommitmentMutationResult(commitment=updated, progress=progress),
            )
        except Exception as exc:  # noqa: BLE001
            return self._handle_exception(
                meta=meta, operation="record_progress", exc=exc
            )

    @public_api_instrumented(
        logger=_LOGGER,
        component_id=str(SERVICE_COMPONENT_ID),
        id_fields=("commitment_id",),
    )
    def resolve_loop_closure_reply(
        self,
        *,
        meta: EnvelopeMeta,
        commitment_id: str,
        intent: str,
        response_text: str = "",
        new_due_by: datetime | date | None = None,
        due_timezone: str | None = None,
    ) -> Envelope[LoopClosureResolutionResult]:
        """Resolve one normalized loop-closure reply."""
        request, errors = self._validate_request(
            meta=meta,
            model=LoopClosureReplyRequest,
            payload={
                "commitment_id": commitment_id,
                "intent": intent,
                "response_text": response_text,
                "new_due_by": new_due_by,
                "due_timezone": due_timezone,
            },
        )
        if errors:
            return failure(meta=meta, errors=errors)
        assert isinstance(request, LoopClosureReplyRequest)

        try:
            current = self._repository.get_commitment(
                commitment_id=request.commitment_id
            )
            if current is None:
                return self._not_found(
                    meta=meta, entity="commitment", entity_id=request.commitment_id
                )

            transition: CommitmentTransitionRecord | None = None
            progress = None
            job_link = self._repository.get_job_link(commitment_id=current.id)
            updated = current

            if request.intent == LoopClosureIntent.COMPLETE:
                updated, transition = self._apply_transition(
                    meta=meta,
                    current=current,
                    to_state=CommitmentState.COMPLETED,
                    actor=ProposalActor.OPERATOR,
                    reason="loop_closure_complete",
                    confidence=1.0,
                )
                job_link = self._remove_follow_up_job_for_id(
                    meta=meta, commitment_id=current.id
                )
                progress = self._record_internal_progress(
                    commitment_id=current.id,
                    summary="Commitment marked complete via loop closure",
                    response_text=request.response_text,
                )
            elif request.intent == LoopClosureIntent.CANCEL:
                updated, transition = self._apply_transition(
                    meta=meta,
                    current=current,
                    to_state=CommitmentState.CANCELED,
                    actor=ProposalActor.OPERATOR,
                    reason="loop_closure_cancel",
                    confidence=1.0,
                )
                job_link = self._remove_follow_up_job_for_id(
                    meta=meta, commitment_id=current.id
                )
                progress = self._record_internal_progress(
                    commitment_id=current.id,
                    summary="Commitment canceled via loop closure",
                    response_text=request.response_text,
                )
            elif request.intent == LoopClosureIntent.RENEGOTIATE:
                normalized_due_by, resolved_timezone = self._normalize_due_by(
                    due_by=request.new_due_by,
                    due_timezone=request.due_timezone or current.due_timezone,
                )
                updated = self._repository.update_commitment(
                    commitment_id=current.id,
                    due_by=normalized_due_by,
                    due_timezone=resolved_timezone,
                    urgency=_compute_urgency(
                        importance=current.importance,
                        effort=current.effort_provided,
                        due_by=normalized_due_by,
                        now=datetime.now(UTC),
                    ),
                    last_modified_at=datetime.now(UTC),
                    updated_at=datetime.now(UTC),
                )
                if updated is None:
                    return self._not_found(
                        meta=meta, entity="commitment", entity_id=current.id
                    )
                if current.state == CommitmentState.MISSED:
                    updated, transition = self._apply_transition(
                        meta=meta,
                        current=updated,
                        to_state=CommitmentState.OPEN,
                        actor=ProposalActor.OPERATOR,
                        reason="loop_closure_renegotiate",
                        confidence=1.0,
                    )
                job_link = self._ensure_follow_up_job_for_record(
                    meta=meta, commitment=updated
                )
                progress = self._record_internal_progress(
                    commitment_id=current.id,
                    summary="Commitment renegotiated via loop closure",
                    response_text=request.response_text,
                )
            elif request.intent == LoopClosureIntent.REVIEW:
                updated = self._repository.update_commitment(
                    commitment_id=current.id,
                    reviewed_at=datetime.now(UTC),
                    updated_at=datetime.now(UTC),
                )
                if updated is None:
                    return self._not_found(
                        meta=meta, entity="commitment", entity_id=current.id
                    )
            else:
                updated = current

            return success(
                meta=meta,
                payload=LoopClosureResolutionResult(
                    commitment=updated,
                    intent=request.intent,
                    transition=transition,
                    progress=progress,
                    job_link=job_link,
                ),
            )
        except Exception as exc:  # noqa: BLE001
            return self._handle_exception(
                meta=meta, operation="resolve_loop_closure_reply", exc=exc
            )

    @public_api_instrumented(logger=_LOGGER, component_id=str(SERVICE_COMPONENT_ID))
    def apply_creation_proposal_decision(
        self,
        *,
        meta: EnvelopeMeta,
        proposal_id: str,
        decision: str,
        decided_by: str,
        decision_reason: str | None = None,
    ) -> Envelope[CommitmentMutationResult]:
        """Approve or reject one creation proposal."""
        request, errors = self._validate_request(
            meta=meta,
            model=CreationProposalDecisionRequest,
            payload={
                "proposal_id": proposal_id,
                "decision": decision,
                "decided_by": decided_by,
                "decision_reason": decision_reason,
            },
        )
        if errors:
            return failure(meta=meta, errors=errors)
        assert isinstance(request, CreationProposalDecisionRequest)
        try:
            proposal = self._repository.get_creation_proposal(
                proposal_id=request.proposal_id
            )
            if proposal is None:
                return self._not_found(
                    meta=meta, entity="creation proposal", entity_id=request.proposal_id
                )
            if proposal.status != ProposalStatus.PENDING:
                return failure(
                    meta=meta,
                    errors=[
                        conflict_error(
                            "creation proposal is already decided", code=codes.CONFLICT
                        )
                    ],
                )
            if request.decision == CreationProposalDecision.REJECT:
                decided = self._repository.decide_creation_proposal(
                    proposal_id=proposal.id,
                    status=ProposalStatus.REJECTED.value,
                    decided_by=request.decided_by,
                    decision_reason=request.decision_reason,
                    decided_at=datetime.now(UTC),
                    created_commitment_id=None,
                )
                return success(
                    meta=meta,
                    payload=CommitmentMutationResult(creation_proposal=decided),
                )
            commitment = self._create_commitment_record(
                description=proposal.description,
                provenance_reference=proposal.provenance_reference,
                ingestion_id=proposal.ingestion_id,
                source=proposal.source,
                due_by=proposal.due_by,
                due_timezone=proposal.due_timezone,
                importance=proposal.importance,
                effort_provided=proposal.effort_provided,
                effort_inferred=proposal.effort_inferred,
                now=datetime.now(UTC),
            )
            decided = self._repository.decide_creation_proposal(
                proposal_id=proposal.id,
                status=ProposalStatus.APPROVED.value,
                decided_by=request.decided_by,
                decision_reason=request.decision_reason,
                decided_at=datetime.now(UTC),
                created_commitment_id=commitment.id,
            )
            job_link = self._ensure_follow_up_job_for_record(
                meta=meta, commitment=commitment
            )
            refreshed = (
                self._repository.get_commitment(commitment_id=commitment.id)
                or commitment
            )
            return success(
                meta=meta,
                payload=CommitmentMutationResult(
                    commitment=refreshed,
                    creation_proposal=decided,
                    job_link=job_link,
                ),
            )
        except Exception as exc:  # noqa: BLE001
            return self._handle_exception(
                meta=meta, operation="apply_creation_proposal_decision", exc=exc
            )

    @public_api_instrumented(logger=_LOGGER, component_id=str(SERVICE_COMPONENT_ID))
    def apply_transition_proposal_decision(
        self,
        *,
        meta: EnvelopeMeta,
        proposal_id: str,
        decision: str,
        decided_by: str,
        decision_reason: str | None = None,
    ) -> Envelope[CommitmentMutationResult]:
        """Approve or reject one transition proposal."""
        request, errors = self._validate_request(
            meta=meta,
            model=TransitionProposalDecisionRequest,
            payload={
                "proposal_id": proposal_id,
                "decision": decision,
                "decided_by": decided_by,
                "decision_reason": decision_reason,
            },
        )
        if errors:
            return failure(meta=meta, errors=errors)
        assert isinstance(request, TransitionProposalDecisionRequest)
        try:
            proposal = self._repository.get_transition_proposal(
                proposal_id=request.proposal_id
            )
            if proposal is None:
                return self._not_found(
                    meta=meta,
                    entity="transition proposal",
                    entity_id=request.proposal_id,
                )
            if proposal.status != ProposalStatus.PENDING:
                return failure(
                    meta=meta,
                    errors=[
                        conflict_error(
                            "transition proposal is already decided",
                            code=codes.CONFLICT,
                        )
                    ],
                )
            if request.decision == TransitionProposalDecision.REJECT:
                decided = self._repository.decide_transition_proposal(
                    proposal_id=proposal.id,
                    status=ProposalStatus.REJECTED.value,
                    decided_by=request.decided_by,
                    decision_reason=request.decision_reason,
                    decided_at=datetime.now(UTC),
                )
                return success(
                    meta=meta,
                    payload=CommitmentMutationResult(transition_proposal=decided),
                )
            current = self._repository.get_commitment(
                commitment_id=proposal.commitment_id
            )
            if current is None:
                return self._not_found(
                    meta=meta, entity="commitment", entity_id=proposal.commitment_id
                )
            decided = self._repository.decide_transition_proposal(
                proposal_id=proposal.id,
                status=ProposalStatus.APPROVED.value,
                decided_by=request.decided_by,
                decision_reason=request.decision_reason,
                decided_at=datetime.now(UTC),
            )
            updated, transition = self._apply_transition(
                meta=meta,
                current=current,
                to_state=proposal.to_state,
                actor=ProposalActor.OPERATOR,
                reason=proposal.reason,
                confidence=1.0,
            )
            return success(
                meta=meta,
                payload=CommitmentMutationResult(
                    commitment=updated,
                    transition=transition,
                    transition_proposal=decided,
                ),
            )
        except Exception as exc:  # noqa: BLE001
            return self._handle_exception(
                meta=meta, operation="apply_transition_proposal_decision", exc=exc
            )

    @public_api_instrumented(
        logger=_LOGGER,
        component_id=str(SERVICE_COMPONENT_ID),
        id_fields=("commitment_id",),
    )
    def get_commitment(
        self, *, meta: EnvelopeMeta, commitment_id: str
    ) -> Envelope[CommitmentRecord]:
        """Read one commitment by id."""
        request, errors = self._validate_request(
            meta=meta,
            model=CommitmentIdRequest,
            payload={"commitment_id": commitment_id},
        )
        if errors:
            return failure(meta=meta, errors=errors)
        assert isinstance(request, CommitmentIdRequest)
        record = self._repository.get_commitment(commitment_id=request.commitment_id)
        if record is None:
            return self._not_found(
                meta=meta, entity="commitment", entity_id=request.commitment_id
            )
        return success(meta=meta, payload=record)

    @public_api_instrumented(logger=_LOGGER, component_id=str(SERVICE_COMPONENT_ID))
    def list_commitments(
        self,
        *,
        meta: EnvelopeMeta,
        state: str | None = None,
        limit: int = 50,
        cursor: str | None = None,
    ) -> Envelope[CommitmentListResult]:
        """List commitments with optional state filter and cursor pagination."""
        request, errors = self._validate_request(
            meta=meta,
            model=ListCommitmentsRequest,
            payload={"state": state, "limit": limit, "cursor": cursor},
        )
        if errors:
            return failure(meta=meta, errors=errors)
        assert isinstance(request, ListCommitmentsRequest)
        items = self._repository.list_commitments(
            state=request.state.value if request.state is not None else None,
            limit=request.limit,
            cursor=request.cursor,
        )
        next_cursor = items[-1].id if len(items) == request.limit and items else None
        return success(
            meta=meta,
            payload=CommitmentListResult(items=tuple(items), next_cursor=next_cursor),
        )

    @public_api_instrumented(
        logger=_LOGGER,
        component_id=str(SERVICE_COMPONENT_ID),
        id_fields=("commitment_id",),
    )
    def get_commitment_history(
        self, *, meta: EnvelopeMeta, commitment_id: str
    ) -> Envelope[CommitmentHistoryResult]:
        """Return one commitment plus progress and transition history."""
        record = self._repository.get_commitment(commitment_id=commitment_id)
        if record is None:
            return self._not_found(
                meta=meta, entity="commitment", entity_id=commitment_id
            )
        history = CommitmentHistoryResult(
            commitment=record,
            progress=tuple(self._repository.list_progress(commitment_id=commitment_id)),
            transitions=tuple(
                self._repository.list_transitions(commitment_id=commitment_id)
            ),
        )
        return success(meta=meta, payload=history)

    @public_api_instrumented(
        logger=_LOGGER,
        component_id=str(SERVICE_COMPONENT_ID),
        id_fields=("review_run_id",),
    )
    def get_review_run(
        self, *, meta: EnvelopeMeta, review_run_id: str
    ) -> Envelope[CommitmentReviewRun]:
        """Read one review run by id."""
        request, errors = self._validate_request(
            meta=meta,
            model=ReviewRunIdRequest,
            payload={"review_run_id": review_run_id},
        )
        if errors:
            return failure(meta=meta, errors=errors)
        assert isinstance(request, ReviewRunIdRequest)
        run = self._repository.get_review_run(review_run_id=request.review_run_id)
        if run is None:
            return self._not_found(
                meta=meta, entity="review run", entity_id=request.review_run_id
            )
        return success(meta=meta, payload=run)

    @public_api_instrumented(logger=_LOGGER, component_id=str(SERVICE_COMPONENT_ID))
    def list_review_runs(
        self, *, meta: EnvelopeMeta, limit: int = 50, cursor: str | None = None
    ) -> Envelope[tuple[CommitmentReviewRun, ...]]:
        """List review runs."""
        request, errors = self._validate_request(
            meta=meta,
            model=ListReviewRunsRequest,
            payload={"limit": limit, "cursor": cursor},
        )
        if errors:
            return failure(meta=meta, errors=errors)
        assert isinstance(request, ListReviewRunsRequest)
        return success(
            meta=meta,
            payload=tuple(
                self._repository.list_review_runs(
                    limit=request.limit,
                    cursor=request.cursor,
                )
            ),
        )

    @public_api_instrumented(
        logger=_LOGGER,
        component_id=str(SERVICE_COMPONENT_ID),
        id_fields=("review_run_id",),
    )
    def list_review_items(
        self, *, meta: EnvelopeMeta, review_run_id: str
    ) -> Envelope[tuple[CommitmentReviewItem, ...]]:
        """List review items for one run."""
        request, errors = self._validate_request(
            meta=meta,
            model=ListReviewItemsRequest,
            payload={"review_run_id": review_run_id},
        )
        if errors:
            return failure(meta=meta, errors=errors)
        assert isinstance(request, ListReviewItemsRequest)
        return success(
            meta=meta,
            payload=tuple(
                self._repository.list_review_items(review_run_id=request.review_run_id)
            ),
        )

    @public_api_instrumented(
        logger=_LOGGER,
        component_id=str(SERVICE_COMPONENT_ID),
        id_fields=("commitment_id",),
    )
    def ensure_follow_up_job(
        self, *, meta: EnvelopeMeta, commitment_id: str
    ) -> Envelope[CommitmentMutationResult]:
        """Ensure one active follow-up job exists for one commitment."""
        record = self._repository.get_commitment(commitment_id=commitment_id)
        if record is None:
            return self._not_found(
                meta=meta, entity="commitment", entity_id=commitment_id
            )
        job_link = self._ensure_follow_up_job_for_record(meta=meta, commitment=record)
        refreshed = self._repository.get_commitment(commitment_id=record.id) or record
        return success(
            meta=meta,
            payload=CommitmentMutationResult(commitment=refreshed, job_link=job_link),
        )

    @public_api_instrumented(
        logger=_LOGGER,
        component_id=str(SERVICE_COMPONENT_ID),
        id_fields=("commitment_id",),
    )
    def remove_follow_up_job(
        self, *, meta: EnvelopeMeta, commitment_id: str
    ) -> Envelope[CommitmentMutationResult]:
        """Remove any active follow-up job for one commitment."""
        job_link = self._remove_follow_up_job_for_id(
            meta=meta, commitment_id=commitment_id
        )
        record = self._repository.get_commitment(commitment_id=commitment_id)
        if record is None:
            return self._not_found(
                meta=meta, entity="commitment", entity_id=commitment_id
            )
        return success(
            meta=meta,
            payload=CommitmentMutationResult(commitment=record, job_link=job_link),
        )

    @public_api_instrumented(logger=_LOGGER, component_id=str(SERVICE_COMPONENT_ID))
    def run_miss_detection(
        self, *, meta: EnvelopeMeta, commitment_id: str | None = None
    ) -> Envelope[MissDetectionResult]:
        """Detect and mark due open commitments as MISSED."""
        try:
            now = datetime.now(UTC)
            due = self._repository.list_open_due_commitments(
                due_before=now,
                commitment_id=commitment_id,
            )
            notified_count = 0
            transitioned_ids: list[str] = []
            for record in due:
                updated, _transition = self._apply_transition(
                    meta=meta,
                    current=record,
                    to_state=CommitmentState.MISSED,
                    actor=ProposalActor.SERVICE,
                    reason="miss_detection",
                    confidence=None,
                )
                transitioned_ids.append(updated.id)
                self._remove_follow_up_job_for_id(meta=meta, commitment_id=updated.id)
                if self._notify_missed_commitment(meta=meta, commitment=updated):
                    notified_count += 1
            return success(
                meta=meta,
                payload=MissDetectionResult(
                    checked_count=len(due),
                    missed_count=len(transitioned_ids),
                    notified_count=notified_count,
                    commitment_ids=tuple(transitioned_ids),
                ),
            )
        except Exception as exc:  # noqa: BLE001
            return self._handle_exception(
                meta=meta, operation="run_miss_detection", exc=exc
            )

    @public_api_instrumented(logger=_LOGGER, component_id=str(SERVICE_COMPONENT_ID))
    def build_review_sets(self, *, meta: EnvelopeMeta) -> Envelope[CommitmentReviewRun]:
        """Build and persist one review run and its items."""
        try:
            now = datetime.now(UTC)
            last_run = self._repository.latest_review_run()
            since_at = (
                last_run.run_at if last_run is not None else _DEFAULT_REVIEW_EPOCH
            )
            completed = self._repository.list_completed_since(since=since_at)
            missed = self._repository.list_missed_since(since=since_at)
            modified = self._repository.list_modified_since(since=since_at)
            no_due = self._repository.list_open_without_due_date()
            run = self._repository.create_review_run(
                since_at=since_at,
                run_at=now,
                completed_count=len(completed),
                missed_count=len(missed),
                modified_count=len(modified),
                no_due_date_count=len(no_due),
                created_at=now,
            )
            for category, records in (
                (ReviewCategory.COMPLETED, completed),
                (ReviewCategory.MISSED, missed),
                (ReviewCategory.MODIFIED, modified),
                (ReviewCategory.NO_DUE_DATE, no_due),
            ):
                for record in records:
                    self._repository.create_review_item(
                        review_run_id=run.id,
                        commitment_id=record.id,
                        category=category,
                        message=self._review_item_message(
                            category=category, commitment=record
                        ),
                        presented_at=now,
                        created_at=now,
                    )
                    self._repository.mark_commitment_presented_for_review(
                        commitment_id=record.id,
                        presented_at=now,
                        updated_at=now,
                    )
            refreshed = self._repository.get_review_run(review_run_id=run.id) or run
            return success(meta=meta, payload=refreshed)
        except Exception as exc:  # noqa: BLE001
            return self._handle_exception(
                meta=meta, operation="build_review_sets", exc=exc
            )

    @public_api_instrumented(
        logger=_LOGGER,
        component_id=str(SERVICE_COMPONENT_ID),
        id_fields=("review_run_id",),
    )
    def deliver_review(
        self, *, meta: EnvelopeMeta, review_run_id: str
    ) -> Envelope[ReviewDeliveryResult]:
        """Deliver one review run through Relay outbound."""
        run = self._repository.get_review_run(review_run_id=review_run_id)
        if run is None:
            return self._not_found(
                meta=meta, entity="review run", entity_id=review_run_id
            )
        if self._outbound_service is None:
            return failure(
                meta=meta,
                errors=[
                    dependency_error(
                        "Relay outbound service is not available",
                        code=codes.DEPENDENCY_UNAVAILABLE,
                        retryable=False,
                    )
                ],
            )
        items = self._repository.list_review_items(review_run_id=review_run_id)
        router_env = self._outbound_service.route_notification(
            meta=meta,
            actor="operator",
            title="Commitment review",
            message=self._render_review_message(run=run, items=items),
            dedupe_key=f"commitment-review:{review_run_id}",
        )
        if router_env.errors:
            return failure(meta=meta, errors=router_env.errors)
        delivered_at = datetime.now(UTC)
        reference = None
        if (
            router_env.payload is not None
            and router_env.payload.value.delivery_timestamp_ms is not None
        ):
            reference = str(router_env.payload.value.delivery_timestamp_ms)
        refreshed = (
            self._repository.mark_review_run_delivered(
                review_run_id=review_run_id,
                delivered_at=delivered_at,
                notification_reference=reference,
            )
            or run
        )
        return success(
            meta=meta,
            payload=ReviewDeliveryResult(
                review_run=refreshed,
                decision=router_env.payload.value.decision,
                delivered=router_env.payload.value.delivered,
                detail=router_env.payload.value.detail,
            ),
        )

    @public_api_instrumented(logger=_LOGGER, component_id=str(SERVICE_COMPONENT_ID))
    def extract_commitment_candidates(
        self,
        *,
        meta: EnvelopeMeta,
        text: str,
        context: str = "",
    ) -> Envelope[ExtractCandidatesResult]:
        """Extract zero or more commitment candidate signals from arbitrary text."""
        empty = ExtractCandidatesResult(candidates=())
        if self._language_service is None or not self._settings.extraction_enabled:
            return success(meta=meta, payload=empty)
        try:
            prompt = _render_prompt_template(
                _EXTRACT_USER_TEMPLATE,
                text=text,
                context=context,
            )
            profile = ReasoningLevel(self._settings.extraction_reasoning_level)
            chat_env = self._language_service.chat(
                meta=meta,
                system_prompt=_EXTRACT_SYSTEM_PROMPT,
                prompt=prompt,
                profile=profile,
            )
            if chat_env.errors or chat_env.payload is None:
                _LOGGER.warning(
                    "Extraction Language call failed; returning empty candidates"
                )
                return success(meta=meta, payload=empty)
            raw = chat_env.payload.value.text.strip()
            if not raw:
                _LOGGER.warning(
                    "Extraction Language response is empty; returning empty candidates"
                )
                return success(meta=meta, payload=empty)
            parsed = json.loads(raw)
            if not isinstance(parsed, list):
                _LOGGER.warning(
                    "Extraction Language response is not a JSON array; returning empty candidates"
                )
                return success(meta=meta, payload=empty)
            candidates: list[CommitmentCandidate] = []
            for item in parsed:
                if not isinstance(item, dict):
                    continue
                raw_confidence = item.get("confidence")
                if raw_confidence is None:
                    continue
                try:
                    confidence = float(raw_confidence)
                except TypeError, ValueError:
                    continue
                confidence = max(0.0, min(1.0, confidence))
                if confidence < self._settings.extraction_min_confidence:
                    continue
                description = str(item.get("description") or "").strip()
                if not description:
                    continue
                raw_importance = item.get("importance")
                importance: int | None = None
                if raw_importance is not None:
                    try:
                        importance = max(1, min(3, int(raw_importance)))
                    except TypeError, ValueError:
                        pass
                raw_effort = item.get("effort_provided")
                effort_provided: int | None = None
                if raw_effort is not None:
                    try:
                        effort_provided = max(1, min(3, int(raw_effort)))
                    except TypeError, ValueError:
                        pass
                raw_due_by = item.get("due_by")
                due_by: datetime | None = None
                if raw_due_by is not None:
                    try:
                        due_by = datetime.fromisoformat(str(raw_due_by))
                        if due_by.tzinfo is None:
                            due_by = due_by.replace(tzinfo=UTC)
                    except ValueError:
                        pass
                raw_tz = item.get("due_timezone")
                due_timezone: str | None = (
                    str(raw_tz).strip() if raw_tz is not None else None
                ) or None
                raw_reasoning = item.get("reasoning")
                reasoning: str | None = (
                    str(raw_reasoning).strip() if raw_reasoning is not None else None
                ) or None
                candidates.append(
                    CommitmentCandidate(
                        description=description,
                        importance=importance,
                        effort_provided=effort_provided,
                        due_by=due_by,
                        due_timezone=due_timezone,
                        confidence=confidence,
                        reasoning=reasoning,
                    )
                )
                if len(candidates) >= self._settings.extraction_max_candidates:
                    break
            return success(
                meta=meta,
                payload=ExtractCandidatesResult(candidates=tuple(candidates)),
            )
        except Exception:  # noqa: BLE001
            _LOGGER.warning(
                "Extraction failed; returning empty candidates", exc_info=True
            )
            return success(meta=meta, payload=empty)

    _TURN_SCANNER_CACHE_KEY = "turn-scanner:cursor"

    @public_api_instrumented(logger=_LOGGER, component_id=str(SERVICE_COMPONENT_ID))
    def run_turn_scanner(self, *, meta: EnvelopeMeta) -> Envelope[TurnScanResult]:
        """Scan recent inbound turns for commitment candidates."""
        empty = TurnScanResult(
            turns_scanned=0,
            candidates_extracted=0,
            candidates_ingested=0,
            errors_encountered=0,
        )
        if not self._settings.turn_scanner_enabled:
            return success(meta=meta, payload=empty)
        if self._recall_service is None or self._language_service is None:
            return success(meta=meta, payload=empty)
        if self._cache_service is None:
            return success(meta=meta, payload=empty)

        try:
            validate_meta(meta)
        except ValueError as exc:
            return failure(
                meta=meta,
                errors=[validation_error(str(exc), code=codes.INVALID_ARGUMENT)],
            )

        cursor_env = self._cache_service.get_value(
            meta=meta,
            component_id=str(SERVICE_COMPONENT_ID),
            key=self._TURN_SCANNER_CACHE_KEY,
        )
        after_id: str | None = None
        if cursor_env.ok and cursor_env.payload.value is not None:
            entry = cursor_env.payload.value
            if isinstance(entry.value, str):
                after_id = entry.value

        turns_env = self._recall_service.list_inbound_turns_after(
            meta=meta,
            after_id=after_id,
            limit=self._settings.turn_scanner_batch_size,
        )
        if not turns_env.ok:
            return failure(meta=meta, errors=list(turns_env.payload.errors))

        turns = turns_env.payload.value
        if not turns:
            return success(meta=meta, payload=empty)

        scanned = 0
        extracted = 0
        ingested = 0
        errors = 0
        last_turn_id: str | None = None

        for turn in turns:
            scanned += 1
            last_turn_id = turn.id
            try:
                extract_env = self.extract_commitment_candidates(
                    meta=meta,
                    text=turn.content,
                    context=f"session_id={turn.session_id} turn_id={turn.id}",
                )
                if not extract_env.ok:
                    errors += 1
                    continue
                candidates = extract_env.payload.value.candidates
                extracted += len(candidates)
                for candidate in candidates:
                    ingest_env = self.ingest_commitment_candidate(
                        meta=meta,
                        description=candidate.description,
                        provenance_reference=f"recall:turn:{turn.id}",
                        source="turn-scanner",
                        due_by=candidate.due_by,
                        due_timezone=candidate.due_timezone,
                        importance=candidate.importance or 2,
                        effort_provided=candidate.effort_provided or 2,
                        confidence=candidate.confidence,
                    )
                    if ingest_env.ok:
                        ingested += 1
            except Exception:  # noqa: BLE001
                _LOGGER.warning("Turn scanner error on turn %s", turn.id, exc_info=True)
                errors += 1

        if last_turn_id is not None:
            self._cache_service.set_value(
                meta=meta,
                component_id=str(SERVICE_COMPONENT_ID),
                key=self._TURN_SCANNER_CACHE_KEY,
                value=last_turn_id,
                ttl_seconds=0,
            )

        return success(
            meta=meta,
            payload=TurnScanResult(
                turns_scanned=scanned,
                candidates_extracted=extracted,
                candidates_ingested=ingested,
                errors_encountered=errors,
                last_turn_id=last_turn_id,
            ),
        )

    @public_api_instrumented(logger=_LOGGER, component_id=str(SERVICE_COMPONENT_ID))
    def health(self, *, meta: EnvelopeMeta) -> Envelope[HealthStatus]:
        """Return Commitment Service readiness state."""
        ready = self._runtime.is_healthy()
        return success(
            meta=meta,
            payload=HealthStatus(
                service_ready=ready,
                detail="ok" if ready else "repository unreachable",
            ),
        )

    def _validate_request[T: BaseModel](
        self, *, meta: EnvelopeMeta, model: type[T], payload: dict[str, object]
    ) -> tuple[T | None, list[ErrorDetail]]:
        try:
            validate_meta(meta)
        except ValueError as exc:
            return None, [validation_error(str(exc), code=codes.INVALID_ARGUMENT)]
        try:
            return model.model_validate(payload), []
        except ValidationError as exc:
            first = exc.errors()[0]
            return None, [
                validation_error(str(first["msg"]), code=codes.INVALID_ARGUMENT)
            ]

    def _create_commitment_record(
        self,
        *,
        description: str,
        provenance_reference: str | None,
        ingestion_id: str | None,
        source: str | None,
        due_by: datetime | None,
        due_timezone: str | None,
        importance: int,
        effort_provided: int,
        effort_inferred: int | None,
        now: datetime,
    ) -> CommitmentRecord:
        urgency = _compute_urgency(
            importance=importance,
            effort=effort_provided,
            due_by=due_by,
            now=now,
        )
        return self._repository.create_commitment(
            description=description,
            state=CommitmentState.OPEN.value,
            provenance_reference=provenance_reference,
            ingestion_id=ingestion_id,
            source=source,
            due_by=due_by,
            due_timezone=due_timezone,
            importance=importance,
            effort_provided=effort_provided,
            effort_inferred=effort_inferred,
            urgency=urgency,
            created_at=now,
        )

    def _apply_transition(
        self,
        *,
        meta: EnvelopeMeta,
        current: CommitmentRecord,
        to_state: CommitmentState,
        actor: ProposalActor,
        reason: str | None,
        confidence: float | None,
    ) -> tuple[CommitmentRecord, CommitmentTransitionRecord]:
        if actor == ProposalActor.OPERATOR:
            self._repository.cancel_pending_transition_proposals(
                commitment_id=current.id,
                decided_by=meta.principal,
                decision_reason="user_override",
                decided_at=datetime.now(UTC),
            )
        updated, transition = self._repository.create_transition_record(
            commitment_id=current.id,
            from_state=current.state.value,
            to_state=to_state.value,
            actor=actor.value,
            reason=reason,
            confidence=confidence,
            created_at=datetime.now(UTC),
            ever_missed_at=datetime.now(UTC)
            if to_state == CommitmentState.MISSED
            else None,
        )
        if updated is None:
            raise ValueError(f"commitment not found: {current.id}")
        if to_state in {CommitmentState.COMPLETED, CommitmentState.CANCELED}:
            self._remove_follow_up_job_for_id(meta=meta, commitment_id=current.id)
        return updated, transition

    def _ensure_follow_up_job_for_record(
        self, *, meta: EnvelopeMeta, commitment: CommitmentRecord
    ) -> CommitmentJobLink | None:
        if (
            commitment.due_by is None
            or commitment.due_by <= datetime.now(UTC)
            or commitment.state in {CommitmentState.COMPLETED, CommitmentState.CANCELED}
        ):
            return self._remove_follow_up_job_for_id(
                meta=meta, commitment_id=commitment.id
            )
        timezone_name = commitment.due_timezone or self._settings.default_timezone
        existing = self._repository.get_job_link(commitment_id=commitment.id)
        if existing is not None and existing.is_active and existing.job_id:
            update_env = self._job_service.update_job(
                meta=meta,
                job_id=existing.job_id,
                timezone=timezone_name,
                definition={"run_at": commitment.due_by.isoformat()},
                notes="commitment due date updated",
            )
            if update_env.errors:
                raise RuntimeError(
                    "; ".join(error.message for error in update_env.errors)
                )
            return self._repository.upsert_job_link(
                commitment_id=commitment.id,
                job_id=existing.job_id,
                job_timezone=timezone_name,
                linked_at=datetime.now(UTC),
            )
        create_env = self._job_service.create_job(
            meta=meta,
            summary=f"Miss detection for commitment {commitment.id}",
            details=commitment.description,
            origin_reference=f"commitment:{commitment.id}:follow-up",
            schedule_type="one_time",
            timezone=timezone_name,
            definition={"run_at": commitment.due_by.isoformat()},
            job_action={
                "type": "op_invocation",
                "op_id": self._settings.follow_up_op_id,
                "input_payload": {"commitment_id": commitment.id},
            },
            start_state="active",
        )
        if create_env.errors:
            raise RuntimeError("; ".join(error.message for error in create_env.errors))
        return self._repository.upsert_job_link(
            commitment_id=commitment.id,
            job_id=create_env.payload.value.job.id,
            job_timezone=timezone_name,
            linked_at=datetime.now(UTC),
        )

    def _remove_follow_up_job_for_id(
        self, *, meta: EnvelopeMeta, commitment_id: str
    ) -> CommitmentJobLink | None:
        link = self._repository.get_job_link(commitment_id=commitment_id)
        if link is None:
            return None
        if link.is_active and link.job_id is not None:
            cancel_env = self._job_service.cancel_job(meta=meta, job_id=link.job_id)
            if cancel_env.errors:
                raise RuntimeError(
                    "; ".join(error.message for error in cancel_env.errors)
                )
        return self._repository.clear_job_link(
            commitment_id=commitment_id,
            unlinked_at=datetime.now(UTC),
        )

    def _record_internal_progress(
        self, *, commitment_id: str, summary: str, response_text: str
    ) -> CommitmentProgressRecord:
        _updated, progress = self._repository.create_progress_record(
            commitment_id=commitment_id,
            provenance_reference=None,
            occurred_at=datetime.now(UTC),
            summary=summary,
            snippet=response_text[:_PROGRESS_SNIPPET_MAX_LENGTH]
            if response_text
            else None,
            created_at=datetime.now(UTC),
        )
        return progress

    def _notify_missed_commitment(
        self, *, meta: EnvelopeMeta, commitment: CommitmentRecord
    ) -> bool:
        if self._outbound_service is None:
            return False
        notify_env = self._outbound_service.route_notification(
            meta=meta,
            actor="operator",
            title="Missed commitment",
            message=f"{commitment.description}\nState: MISSED",
            dedupe_key=f"commitment-missed:{commitment.id}",
        )
        return notify_env.ok and bool(
            notify_env.payload and notify_env.payload.value.delivered
        )

    def _normalize_due_by(
        self, *, due_by: datetime | date | None, due_timezone: str | None
    ) -> tuple[datetime | None, str | None]:
        if due_by is None:
            return None, due_timezone
        if isinstance(due_by, datetime):
            return _ensure_utc(due_by), due_timezone or "UTC"
        timezone_name = due_timezone or self._settings.default_timezone
        tz = ZoneInfo(timezone_name)
        local_due = datetime.combine(due_by, time(23, 59, 59), tzinfo=tz)
        return local_due.astimezone(UTC), timezone_name

    def _requires_creation_proposal(
        self, *, requested_by: ProposalActor, confidence: float | None
    ) -> bool:
        return requested_by == ProposalActor.SERVICE and (
            confidence is None
            or confidence < self._settings.autonomous_creation_confidence_threshold
        )

    def _requires_transition_proposal(
        self,
        *,
        requested_by: ProposalActor,
        to_state: CommitmentState,
        confidence: float | None,
    ) -> bool:
        if requested_by == ProposalActor.OPERATOR:
            return False
        if to_state == CommitmentState.MISSED:
            return False
        return (
            confidence is None
            or confidence < self._settings.autonomous_transition_confidence_threshold
        )

    def _check_dedupe(
        self,
        *,
        meta: EnvelopeMeta,
        description: str,
    ) -> tuple[str | None, float | None, str | None]:
        """Return (matched_commitment_id, dedupe_confidence, match_summary) or all-None.

        Gracefully degrades: Language unavailability, disabled config, empty open set,
        parse errors, or low confidence all return ``(None, None, None)`` and
        allow creation to proceed.
        """
        if self._language_service is None or not self._settings.dedupe_enabled:
            return None, None, None
        try:
            open_commitments = self._repository.list_commitments(
                state=CommitmentState.OPEN.value,
                limit=self._settings.dedupe_scan_limit,
                cursor=None,
            )
            if not open_commitments:
                return None, None, None
            existing_lines = "\n".join(
                f"- {c.id}: {c.description}" for c in open_commitments
            )
            prompt = _render_prompt_template(
                _DEDUPE_USER_TEMPLATE,
                new_description=description,
                existing_commitments=existing_lines,
            )
            chat_env = self._language_service.chat(
                meta=meta,
                system_prompt=self._dedupe_system_prompt,
                prompt=prompt,
                profile=ReasoningLevel.QUICK,
            )
            if chat_env.errors or chat_env.payload is None:
                _LOGGER.warning("Dedupe Language call failed; skipping dedupe check")
                return None, None, None
            raw = chat_env.payload.value.text.strip()
            parsed = json.loads(raw)
            dup_id = parsed.get("duplicate_commitment_id")
            confidence = float(parsed.get("confidence", 0.0))
            summary = str(parsed.get("summary", ""))
            if (
                dup_id is not None
                and confidence >= self._settings.dedupe_confidence_threshold
            ):
                return str(dup_id), confidence, summary
            return None, None, None
        except Exception:  # noqa: BLE001
            _LOGGER.warning(
                "Dedupe check failed; proceeding without dedupe", exc_info=True
            )
            return None, None, None

    def _recompute_urgency_for_update(
        self,
        *,
        current: CommitmentRecord,
        due_by: datetime | None,
        due_date_changed: bool,
        importance: int | None,
        effort_provided: int | None,
    ) -> int | None:
        if not due_date_changed and importance is None and effort_provided is None:
            return None
        return _compute_urgency(
            importance=importance if importance is not None else current.importance,
            effort=(
                effort_provided
                if effort_provided is not None
                else current.effort_provided
            ),
            due_by=due_by,
            now=datetime.now(UTC),
        )

    def _is_substantive_update(self, request: UpdateCommitmentRequest) -> bool:
        fields = request.model_fields_set
        return bool(
            request.description is not None
            or request.importance is not None
            or request.effort_provided is not None
            or "due_by" in fields
            or "due_timezone" in fields
            or "effort_inferred" in fields
            or "provenance_reference" in fields
            or "ingestion_id" in fields
            or "source" in fields
        )

    def _review_item_message(
        self, *, category: ReviewCategory, commitment: CommitmentRecord
    ) -> str:
        if category == ReviewCategory.COMPLETED:
            return f"Completed: {commitment.description}"
        if category == ReviewCategory.MISSED:
            return f"Missed: {commitment.description}"
        if category == ReviewCategory.MODIFIED:
            return f"Modified: {commitment.description}"
        return f"No due date: {commitment.description}"

    def _render_review_message(
        self, *, run: CommitmentReviewRun, items: list[CommitmentReviewItem]
    ) -> str:
        lines = [
            "Commitment review",
            f"Completed: {run.completed_count}",
            f"Missed: {run.missed_count}",
            f"Modified: {run.modified_count}",
            f"No due date: {run.no_due_date_count}",
        ]
        for item in items:
            lines.append(f"- {item.message}")
        return "\n".join(lines)

    def _not_found(
        self, *, meta: EnvelopeMeta, entity: str, entity_id: str
    ) -> Envelope:
        return failure(
            meta=meta,
            errors=[
                not_found_error(
                    f"{entity} '{entity_id}' not found",
                    code=codes.NOT_FOUND,
                )
            ],
        )

    def _handle_exception(
        self, *, meta: EnvelopeMeta, operation: str, exc: Exception
    ) -> Envelope:
        if isinstance(exc, ValueError):
            return failure(
                meta=meta,
                errors=[validation_error(str(exc), code=codes.INVALID_ARGUMENT)],
            )
        error = normalize_postgres_error(exc)
        if error.code == codes.UNEXPECTED_EXCEPTION:
            _LOGGER.exception("Commitment Service %s failed", operation)
        return failure(meta=meta, errors=[error])


def _ensure_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        raise ValueError("datetime must be timezone-aware")
    return value.astimezone(UTC)


def _compute_urgency(
    *, importance: int, effort: int, due_by: datetime | None, now: datetime
) -> int:
    effective_due_by = due_by or (now + timedelta(days=7))
    effort_hours = {1: 0.5, 2: 2.0, 3: 8.0}.get(effort, float(effort))
    time_left_hours = max(0.0, (effective_due_by - now).total_seconds() / 3600.0)
    time_pressure = 1 - (time_left_hours / max(1.0, effort_hours * 4.0))
    time_pressure = max(0.0, min(1.0, time_pressure))
    urgency_raw = (
        (0.4 * (importance / 3)) + (0.4 * time_pressure) + (0.2 * (effort / 3))
    )
    urgency = round(1 + (urgency_raw * 99))
    return max(1, min(100, urgency))
