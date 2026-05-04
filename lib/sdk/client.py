"""Synchronous Brain Core SDK client for CLI/agent callers."""

from __future__ import annotations

from lib.sdk.calls import (
    DelegationCancelOutcome,
    DelegationClaim,
    DelegationResult,
    DelegationStarted,
    DelegationStatusView,
    DelegationTurnDecision,
    DynamicOpClassification,
    OpDescriptor,
    OpInvokeResult,
    OpSearchHit,
    ConsoleEnqueueResult,
    ConsoleResponseMessage,
    CoreHealthResult,
    JobClaimResult,
    LmsChatResult,
    LmsToolChatResult,
    MemoryContextBlock,
    MemorySessionRef,
    MemoryTurnContext,
    MemoryTurnRecord,
    RelayOperatorInstruction,
    ToolSystemHint,
    call_delegation_cancel,
    call_delegation_claim_invocation,
    call_delegation_finalize_invocation,
    call_delegation_invoke,
    call_delegation_invoke_and_wait,
    call_delegation_record_turn,
    call_delegation_status,
    call_delegation_wait,
    call_ops_classify_dynamic,
    call_ops_describe,
    call_ops_list_always_on,
    call_ops_list_dynamic_classifications,
    call_ops_search,
    call_ops_tool_system_hints,
    call_op_describe,
    call_op_invoke,
    call_core_health,
    call_job_claim_execution,
    call_job_complete_execution,
    call_job_fail_execution,
    call_language_chat,
    call_language_chat_with_tools,
    call_memory_assemble_context,
    call_memory_assemble_snapshot,
    call_memory_compact_dialogue,
    call_memory_create_session,
    call_memory_get_latest_or_create_session,
    call_memory_record_inbound_turn,
    call_memory_record_outbound_candidate,
    call_memory_record_outbound_delivery,
    call_memory_record_response,
    call_slash_lookup,
    call_relay_enqueue_console,
    call_relay_poll_console_response,
    call_relay_poll_operator_instruction,
)
from lib.sdk.config import (
    BrainSdkConfig,
    resolve_host,
    resolve_port,
    resolve_timeout_seconds,
)
from lib.sdk.meta import MetaOverrides, build_envelope_meta
from lib.shared.auth.slash_authenticity import SlashAuthenticityProof
from lib.shared.language_model import InferenceRequest
from lib.shared.http.client import HttpClient


class BrainClient:
    """Thin HTTP client for selected Core operations."""

    def __init__(
        self,
        *,
        config: BrainSdkConfig | None = None,
        http: HttpClient | None = None,
    ) -> None:
        """Accept an optional HttpClient for testing; build one from config otherwise."""
        self._config = BrainSdkConfig() if config is None else config
        self._owns_http = http is None
        self._http = http if http is not None else self._new_http_client()

    def close(self) -> None:
        """Release the underlying HTTP client only when this instance owns it."""
        if self._owns_http:
            self._http.close()

    def __enter__(self) -> BrainClient:
        return self

    def __exit__(self, *_: object) -> None:
        self.close()

    def core_health(self, *, meta: MetaOverrides | None = None) -> CoreHealthResult:
        """Return aggregate Core health status."""
        return call_core_health(
            http=self._http,
            metadata=self._meta(meta),
            timeout_seconds=self._config.timeout_seconds,
        )

    def describe_ops(
        self, *, meta: MetaOverrides | None = None
    ) -> tuple[OpDescriptor, ...]:
        """Return all active Op descriptors."""
        return call_ops_describe(
            http=self._http,
            metadata=self._meta(meta),
            timeout_seconds=self._config.timeout_seconds,
        )

    def list_always_on_ops(
        self, *, meta: MetaOverrides | None = None
    ) -> tuple[OpDescriptor, ...]:
        """Return full descriptors for configured always-on ops."""
        return call_ops_list_always_on(
            http=self._http,
            metadata=self._meta(meta),
            timeout_seconds=self._config.timeout_seconds,
        )

    def search_ops(
        self,
        *,
        query: str,
        limit: int | None = None,
        meta: MetaOverrides | None = None,
    ) -> tuple[OpSearchHit, ...]:
        """Search the Execution op catalog."""
        return call_ops_search(
            http=self._http,
            metadata=self._meta(meta),
            timeout_seconds=self._config.timeout_seconds,
            query=query,
            limit=limit,
        )

    def list_tool_system_hints(
        self, *, meta: MetaOverrides | None = None
    ) -> tuple[ToolSystemHint, ...]:
        """Return compact orientation hints for systems reachable through tools."""
        return call_ops_tool_system_hints(
            http=self._http,
            metadata=self._meta(meta),
            timeout_seconds=self._config.timeout_seconds,
        )

    def classify_dynamic_op(
        self,
        *,
        op_id: str,
        effect: str | None = None,
        approval: str | None = None,
        meta: MetaOverrides | None = None,
    ) -> DynamicOpClassification:
        """Persist operator-supplied classification for a dynamic op."""
        return call_ops_classify_dynamic(
            http=self._http,
            metadata=self._meta(meta),
            timeout_seconds=self._config.timeout_seconds,
            op_id=op_id,
            effect=effect,
            approval=approval,
        )

    def list_dynamic_op_classifications(
        self, *, meta: MetaOverrides | None = None
    ) -> tuple[DynamicOpClassification, ...]:
        """Return all observed dynamic op classification rows."""
        return call_ops_list_dynamic_classifications(
            http=self._http,
            metadata=self._meta(meta),
            timeout_seconds=self._config.timeout_seconds,
        )

    def describe_op(
        self,
        *,
        op_id: str,
        meta: MetaOverrides | None = None,
    ) -> OpDescriptor:
        """Return one full op descriptor by id."""
        return call_op_describe(
            http=self._http,
            metadata=self._meta(meta),
            timeout_seconds=self._config.timeout_seconds,
            op_id=op_id,
        )

    def resolve_slash_command(
        self,
        *,
        name: str,
        meta: MetaOverrides | None = None,
    ) -> OpDescriptor | None:
        """Return the op descriptor bound to a slash command name or alias."""
        return call_slash_lookup(
            http=self._http,
            metadata=self._meta(meta),
            timeout_seconds=self._config.timeout_seconds,
            name=name,
        )

    def invoke_op(
        self,
        *,
        op_id: str,
        input_payload: dict[str, object] | None = None,
        actor: str = "",
        channel: str = "",
        invocation_id: str = "",
        parent_invocation_id: str = "",
        confirmed: bool = False,
        approval_token: str = "",
        reply_to_proposal_token: str = "",
        reaction_to_proposal_token: str = "",
        message_text: str = "",
        slash_authenticity: SlashAuthenticityProof | None = None,
        meta: MetaOverrides | None = None,
    ) -> OpInvokeResult:
        """Invoke one Op via the Execution route surface."""
        return call_op_invoke(
            http=self._http,
            metadata=self._meta(meta),
            timeout_seconds=self._config.timeout_seconds,
            op_id=op_id,
            input_payload=input_payload,
            actor=actor,
            channel=channel,
            invocation_id=invocation_id,
            parent_invocation_id=parent_invocation_id,
            confirmed=confirmed,
            approval_token=approval_token,
            reply_to_proposal_token=reply_to_proposal_token,
            reaction_to_proposal_token=reaction_to_proposal_token,
            message_text=message_text,
            slash_authenticity=slash_authenticity,
        )

    def language_chat(
        self,
        *,
        system_prompt: str = "",
        prompt: str,
        profile: str = "standard",
        timeout_seconds: float | None = None,
        meta: MetaOverrides | None = None,
    ) -> LmsChatResult:
        """Execute one direct Language chat request."""
        return call_language_chat(
            http=self._http,
            metadata=self._meta(meta),
            timeout_seconds=(
                self._config.timeout_seconds
                if timeout_seconds is None
                else timeout_seconds
            ),
            system_prompt=system_prompt,
            prompt=prompt,
            profile=profile,
        )

    def language_chat_with_tools(
        self,
        *,
        inference_request: InferenceRequest,
        timeout_seconds: float | None = None,
        meta: MetaOverrides | None = None,
    ) -> LmsToolChatResult:
        """Execute one tool-capable Language chat request."""
        return call_language_chat_with_tools(
            http=self._http,
            metadata=self._meta(meta),
            timeout_seconds=(
                self._config.timeout_seconds
                if timeout_seconds is None
                else timeout_seconds
            ),
            inference_request=inference_request,
        )

    def memory_assemble_context(
        self,
        *,
        session_id: str,
        message: str,
        instruction: RelayOperatorInstruction | None = None,
        meta: MetaOverrides | None = None,
    ) -> MemoryTurnContext:
        """Resolve active Recall session, record inbound turn, and return context."""
        return call_memory_assemble_context(
            http=self._http,
            metadata=self._meta(meta),
            timeout_seconds=self._config.timeout_seconds,
            session_id=session_id,
            message=message,
            instruction=instruction,
        )

    def memory_record_inbound_turn(
        self,
        *,
        session_id: str,
        message: str,
        instruction: RelayOperatorInstruction | None = None,
        meta: MetaOverrides | None = None,
    ) -> MemoryTurnRecord:
        """Persist one inbound turn and return the recorded turn payload."""
        return call_memory_record_inbound_turn(
            http=self._http,
            metadata=self._meta(meta),
            timeout_seconds=self._config.timeout_seconds,
            session_id=session_id,
            message=message,
            instruction=instruction,
        )

    def memory_assemble_snapshot(
        self,
        *,
        session_id: str,
        exclude_latest: bool = True,
        meta: MetaOverrides | None = None,
    ) -> MemoryContextBlock:
        """Return the historical Recall snapshot for one session."""
        return call_memory_assemble_snapshot(
            http=self._http,
            metadata=self._meta(meta),
            timeout_seconds=self._config.timeout_seconds,
            session_id=session_id,
            exclude_latest=exclude_latest,
        )

    def memory_create_session(
        self,
        *,
        meta: MetaOverrides | None = None,
    ) -> MemorySessionRef:
        """Create one Recall session and return the new session identifier."""
        return call_memory_create_session(
            http=self._http,
            metadata=self._meta(meta),
            timeout_seconds=self._config.timeout_seconds,
        )

    def memory_get_latest_or_create_session(
        self,
        *,
        meta: MetaOverrides | None = None,
    ) -> MemorySessionRef:
        """Return the latest Recall session id or create one when none exist."""
        return call_memory_get_latest_or_create_session(
            http=self._http,
            metadata=self._meta(meta),
            timeout_seconds=self._config.timeout_seconds,
        )

    def memory_compact_dialogue(
        self,
        *,
        session_id: str,
        meta: MetaOverrides | None = None,
    ) -> MemorySessionRef:
        """Force-summarize all visible turns and advance dialogue frontier."""
        return call_memory_compact_dialogue(
            http=self._http,
            metadata=self._meta(meta),
            timeout_seconds=self._config.timeout_seconds,
            session_id=session_id,
        )

    def memory_record_response(
        self,
        *,
        session_id: str,
        content: str,
        model: str,
        provider: str,
        token_count: int,
        reasoning_level: str,
        meta: MetaOverrides | None = None,
    ) -> bool:
        """Append one outbound Recall response turn."""
        return call_memory_record_response(
            http=self._http,
            metadata=self._meta(meta),
            timeout_seconds=self._config.timeout_seconds,
            session_id=session_id,
            content=content,
            model=model,
            provider=provider,
            token_count=token_count,
            reasoning_level=reasoning_level,
        )

    def memory_record_outbound_candidate(
        self,
        *,
        session_id: str,
        content: str,
        model: str,
        provider: str,
        token_count: int,
        reasoning_level: str,
        meta: MetaOverrides | None = None,
    ) -> MemoryTurnRecord:
        """Persist one outbound candidate turn."""
        return call_memory_record_outbound_candidate(
            http=self._http,
            metadata=self._meta(meta),
            timeout_seconds=self._config.timeout_seconds,
            session_id=session_id,
            content=content,
            model=model,
            provider=provider,
            token_count=token_count,
            reasoning_level=reasoning_level,
        )

    def memory_record_outbound_delivery(
        self,
        *,
        session_id: str,
        turn_id: str,
        delivered: bool,
        meta: MetaOverrides | None = None,
    ) -> bool:
        """Record outbound delivery status."""
        return call_memory_record_outbound_delivery(
            http=self._http,
            metadata=self._meta(meta),
            timeout_seconds=self._config.timeout_seconds,
            session_id=session_id,
            turn_id=turn_id,
            delivered=delivered,
        )

    def relay_poll_operator_instruction(
        self,
        *,
        wait_timeout_seconds: float = 0.0,
        meta: MetaOverrides | None = None,
    ) -> RelayOperatorInstruction | None:
        """Poll Relay inbound for the next queued operator instruction."""
        return call_relay_poll_operator_instruction(
            http=self._http,
            metadata=self._meta(meta),
            timeout_seconds=self._config.timeout_seconds,
            wait_timeout_seconds=wait_timeout_seconds,
        )

    def relay_enqueue_console(
        self,
        *,
        message_text: str,
        slash_authenticity: SlashAuthenticityProof | None = None,
        meta: MetaOverrides | None = None,
    ) -> ConsoleEnqueueResult:
        """Submit one console operator message to Relay inbound."""
        return call_relay_enqueue_console(
            http=self._http,
            metadata=self._meta(meta),
            timeout_seconds=self._config.timeout_seconds,
            message_text=message_text,
            slash_authenticity=slash_authenticity,
        )

    def job_claim_execution(
        self,
        *,
        worker_id: str = "worker",
        meta: MetaOverrides | None = None,
    ) -> JobClaimResult | None:
        """Claim the next queued job execution.  Returns None when nothing queued."""
        return call_job_claim_execution(
            http=self._http,
            metadata=self._meta(meta),
            timeout_seconds=self._config.timeout_seconds,
            worker_id=worker_id,
        )

    def job_complete_execution(
        self,
        *,
        execution_id: str,
        meta: MetaOverrides | None = None,
    ) -> None:
        """Report a successful execution result to the Job Service."""
        call_job_complete_execution(
            http=self._http,
            metadata=self._meta(meta),
            timeout_seconds=self._config.timeout_seconds,
            execution_id=execution_id,
        )

    def job_fail_execution(
        self,
        *,
        execution_id: str,
        error_message: str,
        error_code: str | None = None,
        is_retryable: bool = False,
        meta: MetaOverrides | None = None,
    ) -> None:
        """Report a failed execution result to the Job Service."""
        call_job_fail_execution(
            http=self._http,
            metadata=self._meta(meta),
            timeout_seconds=self._config.timeout_seconds,
            execution_id=execution_id,
            error_message=error_message,
            error_code=error_code,
            is_retryable=is_retryable,
        )

    def relay_poll_console_response(
        self,
        *,
        wait_timeout_seconds: float = 0.0,
        meta: MetaOverrides | None = None,
    ) -> ConsoleResponseMessage | None:
        """Poll Relay inbound for the next queued console response."""
        return call_relay_poll_console_response(
            http=self._http,
            metadata=self._meta(meta),
            timeout_seconds=self._config.timeout_seconds,
            wait_timeout_seconds=wait_timeout_seconds,
        )

    def delegation_invoke(
        self,
        *,
        prompt: str,
        context_text: str | None = None,
        context_object_refs: tuple[str, ...] = (),
        personality_id: str = "subagent",
        tool_allowlist: tuple[str, ...] | None = None,
        max_turns: int = 8,
        budget_tokens: int | None = None,
        max_wallclock_seconds: int | None = None,
        parent_invocation_id: str | None = None,
        meta: MetaOverrides | None = None,
    ) -> DelegationStarted:
        """Queue one delegated invocation and return its identifier."""
        return call_delegation_invoke(
            http=self._http,
            metadata=self._meta(meta),
            timeout_seconds=self._config.timeout_seconds,
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

    def delegation_invoke_and_wait(
        self,
        *,
        prompt: str,
        context_text: str | None = None,
        context_object_refs: tuple[str, ...] = (),
        personality_id: str = "subagent",
        tool_allowlist: tuple[str, ...] | None = None,
        max_turns: int = 8,
        budget_tokens: int | None = None,
        max_wallclock_seconds: int | None = None,
        parent_invocation_id: str | None = None,
        wait_timeout_seconds: float | None = None,
        timeout_seconds: float | None = None,
        meta: MetaOverrides | None = None,
    ) -> DelegationResult:
        """Queue one delegated invocation and block until terminal state."""
        return call_delegation_invoke_and_wait(
            http=self._http,
            metadata=self._meta(meta),
            timeout_seconds=(
                self._config.timeout_seconds
                if timeout_seconds is None
                else timeout_seconds
            ),
            prompt=prompt,
            context_text=context_text,
            context_object_refs=context_object_refs,
            personality_id=personality_id,
            tool_allowlist=tool_allowlist,
            max_turns=max_turns,
            budget_tokens=budget_tokens,
            max_wallclock_seconds=max_wallclock_seconds,
            parent_invocation_id=parent_invocation_id,
            wait_timeout_seconds=wait_timeout_seconds,
        )

    def delegation_wait(
        self,
        *,
        invocation_id: str,
        wait_timeout_seconds: float | None = None,
        timeout_seconds: float | None = None,
        meta: MetaOverrides | None = None,
    ) -> DelegationResult:
        """Block until the named invocation reaches terminal state."""
        return call_delegation_wait(
            http=self._http,
            metadata=self._meta(meta),
            timeout_seconds=(
                self._config.timeout_seconds
                if timeout_seconds is None
                else timeout_seconds
            ),
            invocation_id=invocation_id,
            wait_timeout_seconds=wait_timeout_seconds,
        )

    def delegation_status(
        self,
        *,
        invocation_id: str,
        meta: MetaOverrides | None = None,
    ) -> DelegationStatusView:
        """Return the current status projection for one invocation."""
        return call_delegation_status(
            http=self._http,
            metadata=self._meta(meta),
            timeout_seconds=self._config.timeout_seconds,
            invocation_id=invocation_id,
        )

    def delegation_cancel(
        self,
        *,
        invocation_id: str,
        reason: str = "manual",
        meta: MetaOverrides | None = None,
    ) -> DelegationCancelOutcome:
        """Request cancellation of one queued or running invocation."""
        return call_delegation_cancel(
            http=self._http,
            metadata=self._meta(meta),
            timeout_seconds=self._config.timeout_seconds,
            invocation_id=invocation_id,
            reason=reason,
        )

    def delegation_claim_invocation(
        self,
        *,
        claimed_by: str = "subagent",
        meta: MetaOverrides | None = None,
    ) -> DelegationClaim | None:
        """Claim the oldest queued invocation for the Subagent Actor."""
        return call_delegation_claim_invocation(
            http=self._http,
            metadata=self._meta(meta),
            timeout_seconds=self._config.timeout_seconds,
            claimed_by=claimed_by,
        )

    def delegation_record_turn(
        self,
        *,
        invocation_id: str,
        meta: MetaOverrides | None = None,
    ) -> DelegationTurnDecision:
        """Bump turn count for one invocation; budget is re-evaluated on the server."""
        return call_delegation_record_turn(
            http=self._http,
            metadata=self._meta(meta),
            timeout_seconds=self._config.timeout_seconds,
            invocation_id=invocation_id,
        )

    def delegation_finalize_invocation(
        self,
        *,
        invocation_id: str,
        status: str,
        final_response: str | None = None,
        transcript_ref: str | None = None,
        cancel_reason: str | None = None,
        meta: MetaOverrides | None = None,
    ) -> DelegationResult:
        """Apply a terminal status transition for one invocation."""
        return call_delegation_finalize_invocation(
            http=self._http,
            metadata=self._meta(meta),
            timeout_seconds=self._config.timeout_seconds,
            invocation_id=invocation_id,
            status=status,
            final_response=final_response,
            transcript_ref=transcript_ref,
            cancel_reason=cancel_reason,
        )

    def _meta(self, overrides: MetaOverrides | None) -> dict[str, object]:
        value = MetaOverrides() if overrides is None else overrides
        return build_envelope_meta(
            source=self._config.source if value.source is None else value.source,
            principal=(
                self._config.principal if value.principal is None else value.principal
            ),
            trace_id=value.trace_id,
            parent_id=value.parent_id,
            envelope_id=value.envelope_id,
            timestamp=value.timestamp,
        )

    def _new_http_client(self) -> HttpClient:
        return HttpClient(
            base_url=f"http://{self._config.host}:{self._config.port}",
            timeout_seconds=self._config.timeout_seconds,
        )


class BrainSdkClient(BrainClient):
    """CLI-friendly SDK client with constructor aliases for host/port args."""

    def __init__(
        self,
        *,
        host: str | None = None,
        port: int | None = None,
        timeout: float | None = None,
        timeout_seconds: float | None = None,
        source: str = "cli",
        principal: str = "operator",
        http: HttpClient | None = None,
    ) -> None:
        """Create one SDK client from direct constructor fields."""
        resolved_timeout = resolve_timeout_seconds(
            timeout if timeout is not None else timeout_seconds
        )
        super().__init__(
            config=BrainSdkConfig(
                host=resolve_host(host),
                port=resolve_port(port),
                timeout_seconds=resolved_timeout,
                source=source,
                principal=principal,
            ),
            http=http,
        )
