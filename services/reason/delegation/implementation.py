"""Concrete Delegation Service implementation."""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass
from datetime import UTC, datetime

from lib.shared.config import CoreRuntimeSettings
from lib.shared.envelope import (
    Envelope,
    EnvelopeKind,
    EnvelopeMeta,
    failure,
    new_meta,
    success,
    validate_meta,
)
from lib.shared.errors import (
    not_found_error,
    validation_error,
)
from lib.shared.ids import ulid_str_to_bytes
from lib.shared.logging import get_logger, public_api_instrumented
from services.effect.language.service import LanguageService
from services.reason.delegation.component import SERVICE_COMPONENT_ID
from services.reason.delegation.data import (
    DelegationPostgresRuntime,
    DelegationRepository,
)
from services.reason.delegation.domain import (
    CancelOutcome,
    CancelReason,
    ClaimedInvocation,
    HealthStatus,
    InvocationRequest,
    InvocationResult,
    InvocationStarted,
    InvocationStatus,
    InvocationStatusView,
    TurnDecision,
)
from services.reason.delegation.service import DelegationService

_LOGGER = get_logger(__name__)
_COMPONENT_ID = str(SERVICE_COMPONENT_ID)

_TERMINAL_STATES = frozenset(
    {
        InvocationStatus.succeeded,
        InvocationStatus.failed,
        InvocationStatus.canceled,
    }
)


class DefaultDelegationService(DelegationService):
    """In-process Delegation implementation backed by Postgres."""

    def __init__(
        self,
        *,
        runtime: DelegationPostgresRuntime,
        repository: DelegationRepository,
        language_model: LanguageService,
        max_recursion_depth: int = 4,
        sweeper_interval_seconds: float = 30.0,
    ) -> None:
        self._runtime = runtime
        self._repository = repository
        self._language_model = language_model
        self._max_recursion_depth = max_recursion_depth
        self._sweeper_interval = sweeper_interval_seconds
        self._waiters_lock = threading.Lock()
        self._waiters: dict[str, threading.Event] = {}
        self._stop_event = threading.Event()
        self._sweeper_thread: threading.Thread | None = None

    @classmethod
    def from_settings(
        cls,
        *,
        settings: CoreRuntimeSettings,
        language_model: LanguageService,
    ) -> "DefaultDelegationService":
        """Build a default Delegation service backed by shared Postgres."""
        from services.reason.delegation.config import resolve_delegation_settings

        runtime = DelegationPostgresRuntime.from_settings(settings)
        repository = DelegationRepository(runtime.schema_sessions)
        delegation_settings = resolve_delegation_settings(settings)
        instance = cls(
            runtime=runtime,
            repository=repository,
            language_model=language_model,
            max_recursion_depth=delegation_settings.max_recursion_depth,
            sweeper_interval_seconds=delegation_settings.sweeper_interval_seconds,
        )
        instance._start_sweeper()
        return instance

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def _start_sweeper(self) -> None:
        """Spawn the wallclock sweeper daemon thread."""
        if self._sweeper_thread is not None:
            return
        thread = threading.Thread(
            target=self._sweep_loop,
            name="delegation-sweeper",
            daemon=True,
        )
        thread.start()
        self._sweeper_thread = thread

    def shutdown(self) -> None:
        """Signal the sweeper loop to stop. Tests use this for clean teardown."""
        self._stop_event.set()
        if self._sweeper_thread is not None:
            self._sweeper_thread.join(timeout=2.0)

    def _sweep_loop(self) -> None:
        """Periodically reap wallclock-exceeded running invocations."""
        while not self._stop_event.wait(self._sweeper_interval):
            try:
                affected = self._repository.sweep_wallclock(now=datetime.now(UTC))
                if affected:
                    _LOGGER.info(
                        "delegation wallclock sweep canceled invocations",
                        extra={"invocation_count": len(affected)},
                    )
            except Exception:  # noqa: BLE001
                _LOGGER.exception("delegation sweeper iteration failed")

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    @public_api_instrumented(logger=_LOGGER, component_id=_COMPONENT_ID)
    def invoke(
        self,
        *,
        meta: EnvelopeMeta,
        prompt: str,
        context_text: str | None = None,
        context_object_refs: tuple[str, ...] = (),
        personality_id: str = "subagent",
        tool_allowlist: tuple[str, ...] | None = None,
        max_turns: int = 8,
        budget_tokens: int | None = None,
        max_wallclock_seconds: int | None = None,
        parent_invocation_id: str | None = None,
    ) -> Envelope[InvocationStarted]:
        depth_error = self._validate_recursion_depth(parent_invocation_id)
        if depth_error is not None:
            return failure(meta=meta, errors=[depth_error])
        request = self._build_request(
            prompt=prompt,
            context_text=context_text,
            context_object_refs=context_object_refs,
            personality_id=personality_id,
            tool_allowlist=tool_allowlist,
            max_turns=max_turns,
            budget_tokens=budget_tokens,
            max_wallclock_seconds=max_wallclock_seconds,
            parent_invocation_id=parent_invocation_id,
        )
        invocation_id = self._enqueue(meta=meta, request=request)
        return success(
            meta=meta,
            payload=InvocationStarted(invocation_id=invocation_id),
        )

    @public_api_instrumented(logger=_LOGGER, component_id=_COMPONENT_ID)
    def invoke_and_wait(
        self,
        *,
        meta: EnvelopeMeta,
        prompt: str,
        context_text: str | None = None,
        context_object_refs: tuple[str, ...] = (),
        personality_id: str = "subagent",
        tool_allowlist: tuple[str, ...] | None = None,
        max_turns: int = 8,
        budget_tokens: int | None = None,
        max_wallclock_seconds: int | None = None,
        parent_invocation_id: str | None = None,
        timeout_seconds: float | None = None,
    ) -> Envelope[InvocationResult]:
        depth_error = self._validate_recursion_depth(parent_invocation_id)
        if depth_error is not None:
            return failure(meta=meta, errors=[depth_error])
        request = self._build_request(
            prompt=prompt,
            context_text=context_text,
            context_object_refs=context_object_refs,
            personality_id=personality_id,
            tool_allowlist=tool_allowlist,
            max_turns=max_turns,
            budget_tokens=budget_tokens,
            max_wallclock_seconds=max_wallclock_seconds,
            parent_invocation_id=parent_invocation_id,
        )
        invocation_id = self._enqueue(meta=meta, request=request)
        return self._wait_for_terminal(
            meta=meta,
            invocation_id=invocation_id,
            timeout_seconds=timeout_seconds,
        )

    @public_api_instrumented(logger=_LOGGER, component_id=_COMPONENT_ID)
    def health(self, *, meta: EnvelopeMeta) -> Envelope[HealthStatus]:
        """Return Delegation Service and Postgres substrate readiness."""
        try:
            validate_meta(meta)
        except ValueError as exc:
            return failure(
                meta=meta,
                errors=[validation_error(str(exc))],
            )
        try:
            substrate_ready = self._runtime.is_healthy()
        except Exception as exc:  # noqa: BLE001
            return success(
                meta=meta,
                payload=HealthStatus(
                    service_ready=True,
                    substrate_ready=False,
                    detail=f"health() raised {type(exc).__name__}",
                ),
            )
        return success(
            meta=meta,
            payload=HealthStatus(
                service_ready=True,
                substrate_ready=substrate_ready,
                detail="ok" if substrate_ready else "postgres ping returned false",
            ),
        )

    @staticmethod
    def _build_request(
        *,
        prompt: str,
        context_text: str | None,
        context_object_refs: tuple[str, ...],
        personality_id: str,
        tool_allowlist: tuple[str, ...] | None,
        max_turns: int,
        budget_tokens: int | None,
        max_wallclock_seconds: int | None,
        parent_invocation_id: str | None,
    ) -> InvocationRequest:
        return InvocationRequest(
            prompt=prompt,
            context_text=context_text,
            context_object_refs=tuple(context_object_refs),
            personality_id=personality_id,
            tool_allowlist=(None if tool_allowlist is None else tuple(tool_allowlist)),
            max_turns=max_turns,
            budget_tokens=budget_tokens,
            max_wallclock_seconds=max_wallclock_seconds,
            parent_invocation_id=parent_invocation_id,
        )

    @public_api_instrumented(
        logger=_LOGGER, component_id=_COMPONENT_ID, id_fields=("invocation_id",)
    )
    def wait(
        self,
        *,
        meta: EnvelopeMeta,
        invocation_id: str,
        timeout_seconds: float | None = None,
    ) -> Envelope[InvocationResult]:
        if not self._is_valid_ulid(invocation_id):
            return failure(
                meta=meta,
                errors=[validation_error("invocation_id must be a valid ULID")],
            )
        return self._wait_for_terminal(
            meta=meta,
            invocation_id=invocation_id,
            timeout_seconds=timeout_seconds,
        )

    @public_api_instrumented(
        logger=_LOGGER, component_id=_COMPONENT_ID, id_fields=("invocation_id",)
    )
    def get_status(
        self,
        *,
        meta: EnvelopeMeta,
        invocation_id: str,
    ) -> Envelope[InvocationStatusView]:
        if not self._is_valid_ulid(invocation_id):
            return failure(
                meta=meta,
                errors=[validation_error("invocation_id must be a valid ULID")],
            )
        view = self._repository.read_status(invocation_id=invocation_id)
        if view is None:
            return failure(
                meta=meta,
                errors=[not_found_error("invocation not found")],
            )
        return success(meta=meta, payload=view)

    @public_api_instrumented(
        logger=_LOGGER, component_id=_COMPONENT_ID, id_fields=("invocation_id",)
    )
    def cancel(
        self,
        *,
        meta: EnvelopeMeta,
        invocation_id: str,
        reason: CancelReason = CancelReason.manual,
    ) -> Envelope[CancelOutcome]:
        if not self._is_valid_ulid(invocation_id):
            return failure(
                meta=meta,
                errors=[validation_error("invocation_id must be a valid ULID")],
            )
        view = self._repository.read_status(invocation_id=invocation_id)
        if view is None:
            return failure(
                meta=meta,
                errors=[not_found_error("invocation not found")],
            )
        accepted = self._repository.mark_canceling(
            invocation_id=invocation_id,
            reason=reason,
        )
        # Cascade cancel to all descendants. Reuse parent_canceled reason for them.
        for child_id in self._collect_descendants(invocation_id):
            self._repository.mark_canceling(
                invocation_id=child_id,
                reason=CancelReason.parent_canceled,
            )
        return success(meta=meta, payload=CancelOutcome(accepted=accepted))

    @public_api_instrumented(logger=_LOGGER, component_id=_COMPONENT_ID)
    def claim_next_invocation(
        self,
        *,
        meta: EnvelopeMeta,
        claimed_by: str,
    ) -> Envelope[ClaimedInvocation | None]:
        normalized_claimed_by = (claimed_by or "subagent").strip() or "subagent"
        claim = self._repository.claim_next_queued(
            now=datetime.now(UTC),
            claimed_by=normalized_claimed_by,
        )
        return success(meta=meta, payload=claim)

    @public_api_instrumented(
        logger=_LOGGER, component_id=_COMPONENT_ID, id_fields=("invocation_id",)
    )
    def record_turn(
        self,
        *,
        meta: EnvelopeMeta,
        invocation_id: str,
    ) -> Envelope[TurnDecision]:
        if not self._is_valid_ulid(invocation_id):
            return failure(
                meta=meta,
                errors=[validation_error("invocation_id must be a valid ULID")],
            )
        totals = self._fetch_token_totals(invocation_id=invocation_id)
        view = self._repository.bump_turn_with_totals(
            invocation_id=invocation_id,
            tokens_in=totals[0],
            tokens_out=totals[1],
        )
        if view is None:
            return failure(
                meta=meta,
                errors=[not_found_error("invocation not found")],
            )
        decision = self._evaluate_turn_budget(invocation_id=invocation_id, view=view)
        return success(meta=meta, payload=decision)

    def _fetch_token_totals(self, *, invocation_id: str) -> tuple[int, int]:
        """Read aggregate input/output tokens from the Language audit by trace.

        The invocation id doubles as the Language trace id (the loop seeds it as
        ``parent_invocation_id`` on each ``language_chat_with_tools`` call). When
        the audit query fails the call is treated as zero spend so a
        downstream provider hiccup does not falsely trigger budget cancel.
        """
        audit_meta = new_meta(
            kind=EnvelopeKind.COMMAND,
            source=str(SERVICE_COMPONENT_ID),
            principal=str(SERVICE_COMPONENT_ID),
        )
        try:
            envelope = self._language_model.get_token_usage_by_trace(
                meta=audit_meta,
                trace_id=invocation_id,
            )
        except Exception:  # noqa: BLE001
            _LOGGER.exception(
                "delegation token audit query raised; treating as zero spend",
                extra={"invocation_id": invocation_id},
            )
            return 0, 0
        if not envelope.ok or envelope.payload is None:
            return 0, 0
        totals = envelope.payload.value
        return int(totals.input_tokens), int(totals.output_tokens)

    @public_api_instrumented(
        logger=_LOGGER, component_id=_COMPONENT_ID, id_fields=("invocation_id",)
    )
    def finalize_invocation(
        self,
        *,
        meta: EnvelopeMeta,
        invocation_id: str,
        status: InvocationStatus,
        final_response: str | None = None,
        transcript_ref: str | None = None,
        cancel_reason: CancelReason | None = None,
    ) -> Envelope[InvocationResult]:
        if not self._is_valid_ulid(invocation_id):
            return failure(
                meta=meta,
                errors=[validation_error("invocation_id must be a valid ULID")],
            )
        if status not in _TERMINAL_STATES:
            return failure(
                meta=meta,
                errors=[validation_error(f"status {status} is not terminal")],
            )
        result = self._repository.finalize(
            invocation_id=invocation_id,
            status=status,
            final_response=final_response,
            transcript_ref=transcript_ref,
            cancel_reason=cancel_reason,
        )
        if result is None:
            return failure(
                meta=meta,
                errors=[not_found_error("invocation not found")],
            )
        self._notify_waiter(invocation_id)
        return success(meta=meta, payload=result)

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    def _enqueue(
        self,
        *,
        meta: EnvelopeMeta,
        request: InvocationRequest,
    ) -> str:
        """Insert one queued invocation row and return its ULID.

        Computes ``depth`` from the parent's recorded depth (or 0 for top-
        level invocations). The recursion-depth ceiling is enforced upstream
        by the caller via :meth:`_resolve_depth_or_raise`.
        """
        return self._repository.insert_invocation(
            request=request,
            principal=str(meta.principal),
            channel=str(meta.source),
            depth=self._resolve_depth(parent_id=request.parent_invocation_id),
        )

    def _validate_recursion_depth(
        self, parent_invocation_id: str | None
    ) -> "object | None":
        """Return a validation error when this invocation would exceed depth.

        Computes the prospective depth one level below the parent and rejects
        before any DB write when ``max_recursion_depth`` is exceeded. The
        ceiling is inclusive: a value of 4 admits depths ``0..4``.
        """
        prospective_depth = self._resolve_depth(parent_id=parent_invocation_id)
        if prospective_depth > self._max_recursion_depth:
            return validation_error(
                "subagent recursion depth limit exceeded",
                metadata={
                    "depth": str(prospective_depth),
                    "max_recursion_depth": str(self._max_recursion_depth),
                },
            )
        return None

    def _resolve_depth(self, *, parent_id: str | None) -> int:
        """Return the depth one level below the parent's recorded depth.

        Top-level invocations have depth 0. Missing parent rows are treated
        as depth 0 to avoid blocking on a stale or pruned parent reference;
        the recursion ceiling check (in the public ``invoke`` path) still
        rejects deep chains.
        """
        if parent_id is None:
            return 0
        if not self._is_valid_ulid(parent_id):
            return 0
        parent_depth = self._repository.read_depth(invocation_id=parent_id)
        if parent_depth is None:
            return 0
        return parent_depth + 1

    def _wait_for_terminal(
        self,
        *,
        meta: EnvelopeMeta,
        invocation_id: str,
        timeout_seconds: float | None,
    ) -> Envelope[InvocationResult]:
        """Block on a per-invocation event until terminal state, with polling fallback."""
        event = self._get_or_create_waiter(invocation_id)
        deadline = (
            None if timeout_seconds is None else time.monotonic() + timeout_seconds
        )
        # Poll every 0.5s as a backstop in case the in-process notify is missed
        # (e.g., when finalize happened in another process). The condition variable
        # path is the fast happy case; the poll is a safety net.
        while True:
            current = self._repository.read_result(invocation_id=invocation_id)
            if current is None:
                return failure(
                    meta=meta,
                    errors=[not_found_error("invocation not found")],
                )
            if current.status in _TERMINAL_STATES:
                self._discard_waiter(invocation_id)
                return success(meta=meta, payload=current)
            remaining = (
                None if deadline is None else max(0.0, deadline - time.monotonic())
            )
            wait_for = 0.5 if remaining is None else min(0.5, remaining)
            event.wait(timeout=wait_for)
            event.clear()
            if deadline is not None and time.monotonic() >= deadline:
                # Return the latest non-terminal snapshot under the timeout.
                self._discard_waiter(invocation_id)
                return success(meta=meta, payload=current)

    def _get_or_create_waiter(self, invocation_id: str) -> threading.Event:
        """Return the per-invocation Event used by sync waiters."""
        with self._waiters_lock:
            event = self._waiters.get(invocation_id)
            if event is None:
                event = threading.Event()
                self._waiters[invocation_id] = event
            return event

    def _notify_waiter(self, invocation_id: str) -> None:
        """Wake any thread blocked on this invocation's terminal transition."""
        with self._waiters_lock:
            event = self._waiters.get(invocation_id)
        if event is not None:
            event.set()

    def _discard_waiter(self, invocation_id: str) -> None:
        """Drop the waiter event once consumed."""
        with self._waiters_lock:
            self._waiters.pop(invocation_id, None)

    def _evaluate_turn_budget(
        self,
        *,
        invocation_id: str,
        view: InvocationStatusView,
    ) -> TurnDecision:
        """Inspect post-turn counters and decide whether to continue."""
        # Cancel pre-empts everything.
        if view.status == InvocationStatus.canceling:
            return TurnDecision(
                should_stop=True,
                reason=view.cancel_reason or CancelReason.manual,
            )
        # Fetch the configured ceilings (load via repository if we want; keep simple
        # for v1 by reading the row again).
        # Note: we reuse read_status to avoid cluttering the API surface; for v1
        # the config knobs (budget_tokens, max_turns) are enforced by re-reading
        # the row. Optimization opportunity if this ever becomes hot.
        return _compare_against_ceilings(
            view=view,
            ceilings=self._read_ceilings(invocation_id=invocation_id),
        )

    def _read_ceilings(self, *, invocation_id: str) -> "_BudgetCeilings":
        """Return budget ceilings for one invocation (denormalized snapshot)."""
        ceilings = self._repository.read_ceilings(invocation_id=invocation_id)
        if ceilings is None:
            return _BudgetCeilings(max_turns=0, budget_tokens=None)
        max_turns, budget_tokens = ceilings
        return _BudgetCeilings(max_turns=max_turns, budget_tokens=budget_tokens)

    def _collect_descendants(self, invocation_id: str) -> list[str]:
        """Return all transitive children of one invocation (for cascade cancel)."""
        seen: set[str] = set()
        frontier = [invocation_id]
        descendants: list[str] = []
        while frontier:
            current = frontier.pop()
            if current in seen:
                continue
            seen.add(current)
            children = self._repository.list_children(parent_invocation_id=current)
            for child in children:
                if child in seen:
                    continue
                descendants.append(child)
                frontier.append(child)
        return descendants

    @staticmethod
    def _is_valid_ulid(value: str) -> bool:
        """Return True when ``value`` parses as a canonical ULID."""
        try:
            ulid_str_to_bytes(value)
        except ValueError, TypeError:
            return False
        return True


# ----------------------------------------------------------------------
# Helpers
# ----------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class _BudgetCeilings:
    """Per-invocation budget ceilings cached for evaluation."""

    max_turns: int
    budget_tokens: int | None


def _compare_against_ceilings(
    *,
    view: InvocationStatusView,
    ceilings: _BudgetCeilings,
) -> TurnDecision:
    """Compare current counters to ceilings and return a turn decision."""
    if ceilings.max_turns > 0 and view.turn_count >= ceilings.max_turns:
        return TurnDecision(should_stop=True, reason=CancelReason.budget_turns)
    if ceilings.budget_tokens is not None:
        consumed = view.tokens_in + view.tokens_out
        if consumed >= ceilings.budget_tokens:
            return TurnDecision(should_stop=True, reason=CancelReason.budget_tokens)
    return TurnDecision(should_stop=False, reason=None)
