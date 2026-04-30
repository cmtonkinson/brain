# Service API
*This document is generated from `services/*/*/service.py`. Do not edit by hand.*

------------------------------------------------------------------------
## `ExecutionService`
* Module: `services/effect/execution/service.py`
* Summary: Public API for op invocation under policy governance.

`health(*, meta: EnvelopeMeta) -> Envelope[ExecutionHealthStatus]`  
*Return Execution readiness, registry counts, and invocation-audit counters.*

`list_always_on_ops(*, meta: EnvelopeMeta) -> Envelope[tuple[OpDescriptor, ...]]`  
*Return full descriptors for only the configured always-on ops.*

`list_dynamic_op_classifications(*, meta: EnvelopeMeta) -> Envelope[tuple[DynamicOpClassificationRow, ...]]`  
*Return observed dynamic op definitions and persisted classifications.*

`classify_dynamic_op(*, meta: EnvelopeMeta, op_id: str, effect: str | None = None, approval: str | None = None) -> Envelope[DynamicOpClassificationRow]`  
*Persist one operator-supplied classification for a dynamic op.*

`describe_op(*, meta: EnvelopeMeta, op_id: str) -> Envelope[OpDescriptor]`  
*Return the full descriptor for one registered op.*

`invoke_op(*, meta: EnvelopeMeta, op_id: str, input_payload: dict[str, object], invocation: OpInvocationMetadata) -> Envelope[OpInvokeResult]`  
*Invoke by package ``op_id`` (no version arg) and return normalized policy fields.*

`search_ops(*, meta: EnvelopeMeta, query: str, limit: int | None = None) -> Envelope[tuple[OpSearchHit, ...]]`  
*Return compact top-k semantic matches from the op catalog.*

`describe_ops(*, meta: EnvelopeMeta) -> Envelope[tuple[OpDescriptor, ...]]`  
*Return descriptors for all registered ops.*

`resolve_slash_command(*, meta: EnvelopeMeta, name: str) -> Envelope[OpDescriptor | None]`  
*Return the descriptor for a slash command by name or alias.*

`list_tool_system_hints(*, meta: EnvelopeMeta) -> Envelope[tuple[ToolSystemHint, ...]]`  
*Return compact orientation hints for systems reachable through tools.*

------------------------------------------------------------------------
## `LanguageService`
* Module: `services/effect/language/service.py`
* Summary: Public API for chat and embedding operations.

`chat(*, meta: EnvelopeMeta, system_prompt: str = '', prompt: str, profile: ReasoningLevel = ReasoningLevel.STANDARD) -> Envelope[ChatResponse]`  
*Generate one chat completion.*

`embed(*, meta: EnvelopeMeta, text: str, profile: EmbeddingProfile = EmbeddingProfile.DOCUMENT_EMBEDDING) -> Envelope[EmbeddingVector]`  
*Generate one embedding vector.*

`health(*, meta: EnvelopeMeta) -> Envelope[HealthStatus]`  
*Return Language and adapter health state.*

`chat_batch(*, meta: EnvelopeMeta, prompts: Sequence[str], profile: ReasoningLevel = ReasoningLevel.STANDARD) -> Envelope[list[ChatResponse]]`  
*Generate a batch of chat completions.*

`embed_batch(*, meta: EnvelopeMeta, texts: Sequence[str], profile: EmbeddingProfile = EmbeddingProfile.DOCUMENT_EMBEDDING) -> Envelope[list[EmbeddingVector]]`  
*Generate a batch of embedding vectors.*

`get_token_usage_by_trace(*, meta: EnvelopeMeta, trace_id: str) -> Envelope[TokenUsageTotals]`  
*Return aggregate token totals across all successful audited calls*

`chat_with_tools(*, meta: EnvelopeMeta, inference_request: InferenceRequest) -> Envelope[ChatWithToolsResponse]`  
*Generate one tool-capable chat completion.*

------------------------------------------------------------------------
## `RelayService`
* Module: `services/effect/relay/service.py`
* Summary: Public API for bidirectional operator comms (inbound + outbound + approval).

`health(*, meta: EnvelopeMeta) -> Envelope[RelayHealthStatus]`  
*Return overall Relay readiness across inbound/outbound/adapter.*

`correlate_approval_response(*, meta: EnvelopeMeta, actor: str, channel: str, message_text: str = '', approval_token: str = '', reply_to_proposal_token: str = '', reaction_to_proposal_token: str = '') -> Envelope[ApprovalCorrelationPayload]`  
*Normalize inbound approval-correlation fields for Policy Service.*

`resolve_approval_notification_proposal_token(*, meta: EnvelopeMeta, channel: str, target_timestamp_ms: int) -> Envelope[str | None]`  
*Resolve one outbound approval notification timestamp to a proposal token.*

`route_approval_notification(*, meta: EnvelopeMeta, approval: ApprovalNotificationPayload) -> Envelope[RouteNotificationResult]`  
*Route one token-only Policy->Relay approval notification.*

`flush_batch(*, meta: EnvelopeMeta, batch_key: str, actor: str = 'operator', channel: str = '', recipient_e164: str = '', sender_e164: str = '', title: str = '') -> Envelope[RouteNotificationResult]`  
*Flush one pending batch by key and deliver consolidated summary.*

`enqueue_console_message(*, meta: EnvelopeMeta, message_text: str) -> Envelope[ConsoleEnqueueResult]`  
*Normalize and enqueue one inbound console message.*

`poll_console_response(*, meta: EnvelopeMeta, wait_timeout_seconds: float = 0.0) -> Envelope[ConsoleResponseMessage | None]`  
*Pop the next queued console response, optionally long-polling.*

`route_notification(*, meta: EnvelopeMeta, actor: str = 'operator', channel: str = '', title: str = '', message: str, dedupe_key: str = '', batch_key: str = '', force: bool = False, conversational_memory: ConversationalMemoryContext | None = None) -> Envelope[RouteNotificationResult]`  
*Route one outbound notification and decide suppress/send/batch.*

`poll_operator_instruction(*, meta: EnvelopeMeta, wait_timeout_seconds: float = 0.0) -> Envelope[NormalizedOperatorMessage | None]`  
*Pop the next queued operator instruction, optionally long-polling.*

`ingest_signal_message(*, meta: EnvelopeMeta, raw_body_json: str) -> Envelope[IngestResult]`  
*Normalize and enqueue one raw inbound Signal payload.*

`register_signal_callback(*, meta: EnvelopeMeta) -> Envelope[RegisterSignalCallbackResult]`  
*Register one in-process Signal callback with the owned adapter.*

------------------------------------------------------------------------
## `CommitmentService`
* Module: `services/reason/commitment/service.py`
* Summary: Public API for commitment lifecycle, review, and loop closure.

`health(*, meta: EnvelopeMeta) -> Envelope[HealthStatus]`  
*Return Commitment Service readiness state.*

`get_commitment(*, meta: EnvelopeMeta, commitment_id: str) -> Envelope[CommitmentRecord]`  
*Read one commitment by id.*

`get_commitment_history(*, meta: EnvelopeMeta, commitment_id: str) -> Envelope[CommitmentHistoryResult]`  
*Return one commitment plus progress and transition history.*

`create_commitment(*, meta: EnvelopeMeta, **payload: object) -> Envelope[CommitmentMutationResult]`  
*Create one commitment or persist a creation proposal.*

`extract_commitment_candidates(*, meta: EnvelopeMeta, text: str, context: str = '') -> Envelope[ExtractCandidatesResult]`  
*Extract zero or more commitment candidate signals from arbitrary text.*

`ingest_commitment_candidate(*, meta: EnvelopeMeta, **payload: object) -> Envelope[CommitmentMutationResult]`  
*Accept one typed ingestion-derived commitment candidate.*

`transition_commitment(*, meta: EnvelopeMeta, **payload: object) -> Envelope[CommitmentMutationResult]`  
*Apply one lifecycle transition or persist a transition proposal.*

`update_commitment(*, meta: EnvelopeMeta, **payload: object) -> Envelope[CommitmentMutationResult]`  
*Update one commitment without changing lifecycle state.*

`list_commitments(*, meta: EnvelopeMeta, state: str | None = None, limit: int = 50, cursor: str | None = None) -> Envelope[CommitmentListResult]`  
*List commitments with optional state filter and cursor pagination.*

`apply_creation_proposal_decision(*, meta: EnvelopeMeta, **payload: object) -> Envelope[CommitmentMutationResult]`  
*Approve or reject one pending creation proposal.*

`ensure_follow_up_job(*, meta: EnvelopeMeta, commitment_id: str) -> Envelope[CommitmentMutationResult]`  
*Ensure one active follow-up job exists for one commitment.*

`remove_follow_up_job(*, meta: EnvelopeMeta, commitment_id: str) -> Envelope[CommitmentMutationResult]`  
*Remove any active follow-up job for one commitment.*

`resolve_loop_closure_reply(*, meta: EnvelopeMeta, **payload: object) -> Envelope[LoopClosureResolutionResult]`  
*Resolve one normalized loop-closure reply.*

`run_miss_detection(*, meta: EnvelopeMeta, commitment_id: str | None = None) -> Envelope[MissDetectionResult]`  
*Detect and mark due open commitments as MISSED.*

`record_progress(*, meta: EnvelopeMeta, **payload: object) -> Envelope[CommitmentMutationResult]`  
*Record one progress entry and update last_progress_at atomically.*

`get_review_run(*, meta: EnvelopeMeta, review_run_id: str) -> Envelope[CommitmentReviewRun]`  
*Read one review run by id.*

`list_review_items(*, meta: EnvelopeMeta, review_run_id: str) -> Envelope[tuple[CommitmentReviewItem, ...]]`  
*List review items for one run.*

`list_review_runs(*, meta: EnvelopeMeta, limit: int = 50, cursor: str | None = None) -> Envelope[tuple[CommitmentReviewRun, ...]]`  
*List review runs.*

`build_review_sets(*, meta: EnvelopeMeta) -> Envelope[CommitmentReviewRun]`  
*Build and persist one review run and its items.*

`deliver_review(*, meta: EnvelopeMeta, review_run_id: str) -> Envelope[ReviewDeliveryResult]`  
*Deliver one review run through Relay outbound.*

`apply_transition_proposal_decision(*, meta: EnvelopeMeta, **payload: object) -> Envelope[CommitmentMutationResult]`  
*Approve or reject one pending transition proposal.*

------------------------------------------------------------------------
## `DelegationService`
* Module: `services/reason/delegation/service.py`
* Summary: Public API for the Delegation Service.

`cancel(*, meta: EnvelopeMeta, invocation_id: str, reason: CancelReason = CancelReason.manual) -> Envelope[CancelOutcome]`  
*Request cancellation of one running or queued invocation.*

`health(*, meta: EnvelopeMeta) -> Envelope[HealthStatus]`  
*Return Delegation Service and Postgres substrate readiness.*

`invoke(*, meta: EnvelopeMeta, prompt: str, context_text: str | None = None, context_object_refs: tuple[str, ...] = (), personality_id: str = 'subagent', tool_allowlist: tuple[str, ...] | None = None, max_turns: int = 8, budget_tokens: int | None = None, max_wallclock_seconds: int | None = None, parent_invocation_id: str | None = None) -> Envelope[InvocationStarted]`  
*Queue one delegated invocation for asynchronous execution.*

`wait(*, meta: EnvelopeMeta, invocation_id: str, timeout_seconds: float | None = None) -> Envelope[InvocationResult]`  
*Block until the named invocation reaches terminal state.*

`invoke_and_wait(*, meta: EnvelopeMeta, prompt: str, context_text: str | None = None, context_object_refs: tuple[str, ...] = (), personality_id: str = 'subagent', tool_allowlist: tuple[str, ...] | None = None, max_turns: int = 8, budget_tokens: int | None = None, max_wallclock_seconds: int | None = None, parent_invocation_id: str | None = None, timeout_seconds: float | None = None) -> Envelope[InvocationResult]`  
*Queue one delegated invocation and block until terminal state.*

`finalize_invocation(*, meta: EnvelopeMeta, invocation_id: str, status: InvocationStatus, final_response: str | None = None, transcript_ref: str | None = None, cancel_reason: CancelReason | None = None) -> Envelope[InvocationResult]`  
*Apply terminal status to an invocation and unblock waiters.*

`claim_next_invocation(*, meta: EnvelopeMeta, claimed_by: str) -> Envelope[ClaimedInvocation | None]`  
*Atomic-claim the next queued invocation for a Subagent Actor.*

`get_status(*, meta: EnvelopeMeta, invocation_id: str) -> Envelope[InvocationStatusView]`  
*Return the current status projection for one invocation.*

`record_turn(*, meta: EnvelopeMeta, invocation_id: str) -> Envelope[TurnDecision]`  
*Bump turn count, refresh token totals from the audit trail, and*

------------------------------------------------------------------------
## `IngestionService`
* Module: `services/reason/ingestion/service.py`
* Summary: Public API for content ingestion, stage orchestration, and artifact lineage.

`health(*, meta: EnvelopeMeta) -> Envelope[HealthStatus]`  
*Return Ingestion Service readiness status.*

`run_anchor_stage(*, meta: EnvelopeMeta, ingestion_id: str) -> Envelope[AnchorStageResult]`  
*Execute the anchor stage for the named ingestion.*

`index_anchored_ingestion(*, meta: EnvelopeMeta, ingestion_id: str, indexing_run_id: str) -> Envelope[IndexAnchoredIngestionResult]`  
*Index anchored normalized artifacts through Utility, Language, and Embedding.*

`run_extract_stage(*, meta: EnvelopeMeta, ingestion_id: str) -> Envelope[FanOutStageResult]`  
*Execute the extraction stage for the named ingestion.*

`get_ingestion(*, meta: EnvelopeMeta, ingestion_id: str) -> Envelope[IngestionRecord]`  
*Read one ingestion record by id.*

`get_ingestion_results(*, meta: EnvelopeMeta, ingestion_id: str) -> Envelope[IngestionResultsView]`  
*Return the stage-ordered artifact outcomes view for one ingestion.*

`get_ingestion_status(*, meta: EnvelopeMeta, ingestion_id: str) -> Envelope[IngestionStatusResult]`  
*Return the current status snapshot for one ingestion.*

`advance_ingestion(*, meta: EnvelopeMeta, ingestion_id: str, from_stage: str, force_target: bool = False) -> Envelope[IngestionRecord]`  
*Advance one ingestion through the pipeline from the named stage onward.*

`replay_ingestion(*, meta: EnvelopeMeta, ingestion_id: str, from_stage: str) -> Envelope[IngestionRecord]`  
*Replay an ingestion from the named stage forward through the pipeline.*

`retry_ingestion_stage(*, meta: EnvelopeMeta, ingestion_id: str, stage: str) -> Envelope[IngestionRecord]`  
*Retry one named stage for an existing ingestion.*

`submit_ingestion(*, meta: EnvelopeMeta, source_type: str, source_uri: str | None = None, source_actor: str | None = None, payload: bytes | None = None, existing_object_key: str | None = None, capture_time: str, mime_type: str | None = None) -> Envelope[IngestionRecord]`  
*Validate and persist one ingestion submission.*

`list_ingestions(*, meta: EnvelopeMeta, status: str | None = None, limit: int = 50, cursor: str | None = None) -> Envelope[IngestionListResult]`  
*List ingestions with optional status filter and cursor pagination.*

`run_normalize_stage(*, meta: EnvelopeMeta, ingestion_id: str) -> Envelope[FanOutStageResult]`  
*Execute the normalization stage for the named ingestion.*

`run_store_stage(*, meta: EnvelopeMeta, ingestion_id: str) -> Envelope[StoreStageResult]`  
*Execute the store stage for the named ingestion.*

------------------------------------------------------------------------
## `JobService`
* Module: `services/reason/job/service.py`
* Summary: Public API for job scheduling, execution tracking, and audit.

`health(*, meta: EnvelopeMeta) -> Envelope[HealthStatus]`  
*Return Job Service and provider health state.*

`evaluate_conditional_job(*, meta: EnvelopeMeta, job_id: str) -> Envelope[PredicateEvaluationRecord]`  
*Evaluate the predicate for one conditional job and record audit.*

`get_execution(*, meta: EnvelopeMeta, execution_id: str) -> Envelope[ExecutionRecord]`  
*Read one execution by id.*

`complete_execution(*, meta: EnvelopeMeta, execution_id: str) -> Envelope[ExecutionRecord]`  
*Mark one running execution as succeeded and update job run-state.*

`fail_execution(*, meta: EnvelopeMeta, execution_id: str, error_message: str, error_code: str | None = None, is_retryable: bool = False) -> Envelope[ExecutionRecord]`  
*Mark one running execution failed or schedule it for retry.*

`list_executions(*, meta: EnvelopeMeta, job_id: str, limit: int = 50, cursor: str | None = None) -> Envelope[ExecutionListResult]`  
*List executions for one job with cursor pagination.*

`get_job(*, meta: EnvelopeMeta, job_id: str) -> Envelope[JobRecord]`  
*Read one job by id.*

`list_job_audits(*, meta: EnvelopeMeta, job_id: str, limit: int = 50, cursor: str | None = None) -> Envelope[JobAuditListResult]`  
*List mutation audit entries for one job.*

`cancel_job(*, meta: EnvelopeMeta, job_id: str) -> Envelope[JobMutationResult]`  
*Cancel a job and clear its next_run.*

`create_job(*, meta: EnvelopeMeta, summary: str, details: str | None = None, origin_reference: str | None = None, schedule_type: str, timezone: str, definition: dict[str, object], job_action: dict[str, object], start_state: str = JobState.draft.value) -> Envelope[JobMutationResult]`  
*Create a job intent, job record, and initial audit entry.*

`pause_job(*, meta: EnvelopeMeta, job_id: str, reason: str = '') -> Envelope[JobMutationResult]`  
*Transition a job from active to paused.*

`resume_job(*, meta: EnvelopeMeta, job_id: str) -> Envelope[JobMutationResult]`  
*Transition a job from paused to active and recompute next_run.*

`review_job_health(*, meta: EnvelopeMeta) -> Envelope[ReviewOutput]`  
*Detect orphaned, failing, and ignored jobs.*

`run_job_now(*, meta: EnvelopeMeta, job_id: str) -> Envelope[RunJobNowResult]`  
*Immediately queue an execution for an active or paused job.*

`update_job(*, meta: EnvelopeMeta, job_id: str, timezone: str | None = None, definition: dict[str, object] | None = None, notes: str | None = None) -> Envelope[JobMutationResult]`  
*Update a job definition and/or timezone.*

`list_jobs(*, meta: EnvelopeMeta, state: str | None = None, schedule_type: str | None = None, limit: int = 50, cursor: str | None = None) -> Envelope[JobListResult]`  
*List jobs with optional filters and cursor pagination.*

`claim_next_execution(*, meta: EnvelopeMeta, worker_id: str = 'worker') -> Envelope[ClaimExecutionResult | None]`  
*Atomically claim the next queued execution for a Worker Actor.*

`list_predicate_evaluations(*, meta: EnvelopeMeta, job_id: str, limit: int = 50, cursor: str | None = None) -> Envelope[PredicateEvaluationListResult]`  
*List predicate evaluation records for one conditional job.*

`handle_provider_callback(*, meta: EnvelopeMeta, job_id: str, scheduled_for: str, trace_id: str, trigger_source: str) -> Envelope[CallbackResult]`  
*Handle an idempotent provider callback for one job execution.*

`process_retry_due_jobs(*, meta: EnvelopeMeta) -> Envelope[list[str]]`  
*Re-queue retry-scheduled executions past their retry_after time.*

------------------------------------------------------------------------
## `PolicyService`
* Module: `services/reason/policy/service.py`
* Summary: Public API for policy evaluation and callback-gated authorization.

`health(*, meta: EnvelopeMeta) -> Envelope[PolicyHealthStatus]`  
*Return Policy Service readiness and persistence-backed audit counters.*

`authorize_and_execute(*, request: OpInvocationRequest, execute: PolicyExecuteCallback) -> PolicyExecutionResult`  
*Return PolicyExecutionResult with allow/deny output, PolicyDecision, and ApprovalProposal.*

------------------------------------------------------------------------
## `RecallService`
* Module: `services/reason/recall/service.py`
* Summary: Public API for Recall Service context and session operations.

`health(*, meta: EnvelopeMeta) -> Envelope[HealthStatus]`  
*Return Recall and Postgres substrate readiness.*

`assemble_context(*, meta: EnvelopeMeta, session_id: str, message: str, instruction: InboundInstructionRecord | None = None) -> Envelope[TurnContext]`  
*Resolve the active session, record inbound turn, and assemble context.*

`compact_dialogue(*, meta: EnvelopeMeta, session_id: str) -> Envelope[SessionRecord]`  
*Force-summarize all visible turns and advance dialogue frontier to latest.*

`update_focus(*, meta: EnvelopeMeta, session_id: str, content: str) -> Envelope[FocusRecord]`  
*Persist explicit focus content with budget-aware compaction semantics.*

`record_inbound_turn(*, meta: EnvelopeMeta, session_id: str, message: str, instruction: InboundInstructionRecord | None = None) -> Envelope[TurnRecord]`  
*Persist one inbound turn and return the recorded turn row.*

`get_latest_or_create_session(*, meta: EnvelopeMeta) -> Envelope[SessionRecord]`  
*Return latest Recall session or create one when none exist.*

`record_outbound_candidate(*, meta: EnvelopeMeta, session_id: str, content: str, model: str, provider: str, token_count: int, reasoning_level: str) -> Envelope[TurnRecord]`  
*Persist one outbound candidate turn and return the recorded row.*

`record_outbound_delivery(*, meta: EnvelopeMeta, session_id: str, turn_id: str, delivered: bool) -> Envelope[bool]`  
*Record delivery status for one outbound turn.*

`record_response(*, meta: EnvelopeMeta, session_id: str, content: str, model: str, provider: str, token_count: int, reasoning_level: str) -> Envelope[bool]`  
*Persist one outbound response turn and mark it delivered.*

`get_session(*, meta: EnvelopeMeta, session_id: str) -> Envelope[SessionRecord]`  
*Read one Recall session by id.*

`clear_session(*, meta: EnvelopeMeta, session_id: str) -> Envelope[bool]`  
*Advance dialogue pointer and clear focus without deleting historical data.*

`create_session(*, meta: EnvelopeMeta) -> Envelope[SessionRecord]`  
*Create and return one new Recall session.*

`assemble_snapshot(*, meta: EnvelopeMeta, session_id: str, exclude_latest: bool = True) -> Envelope[ContextBlock]`  
*Return the historical Recall context snapshot for one session.*

------------------------------------------------------------------------
## `UtilityService`
* Module: `services/reason/utility/service.py`
* Summary: Public API for lightweight reusable utility operations.

`health(*, meta: EnvelopeMeta) -> Envelope[HealthStatus]`  
*Return Utility Service readiness state.*

`current_datetime(*, meta: EnvelopeMeta) -> Envelope[CurrentDateTime]`  
*Return current UTC and operator-local datetimes.*

`chunk_text(*, meta: EnvelopeMeta, text: str) -> Envelope[list[TextChunk]]`  
*Return one or more chunks for the provided text content.*

------------------------------------------------------------------------
## `CacheService`
* Module: `services/state/cache/service.py`
* Summary: Public API for component-scoped cache and queue operations.

`health(*, meta: EnvelopeMeta) -> Envelope[HealthStatus]`  
*Return Cache and Valkey substrate readiness.*

`peek_queue(*, meta: EnvelopeMeta, component_id: str, queue: str) -> Envelope[QueueEntry | None]`  
*Peek next component-scoped queue value without removal.*

`pop_queue(*, meta: EnvelopeMeta, component_id: str, queue: str) -> Envelope[QueueEntry | None]`  
*Pop one component-scoped queue value using FIFO order.*

`push_queue(*, meta: EnvelopeMeta, component_id: str, queue: str, value: JsonValue) -> Envelope[QueueDepth]`  
*Push one component-scoped queue value.*

`get_value(*, meta: EnvelopeMeta, component_id: str, key: str) -> Envelope[CacheEntry | None]`  
*Get one component-scoped cache value by key.*

`delete_value(*, meta: EnvelopeMeta, component_id: str, key: str) -> Envelope[bool]`  
*Delete one component-scoped cache value.*

`set_value(*, meta: EnvelopeMeta, component_id: str, key: str, value: JsonValue, ttl_seconds: int | None = None) -> Envelope[CacheEntry]`  
*Set one component-scoped cache value.*

------------------------------------------------------------------------
## `EmbeddingService`
* Module: `services/state/embedding/service.py`
* Summary: Public API for the Embedding Service.

`health(*, meta: EnvelopeMeta) -> Envelope[HealthStatus]`  
*Return Embedding and owned dependency readiness status.*

`upsert_chunk(*, meta: EnvelopeMeta, source_id: str, chunk_ordinal: int, reference_range: str, content_hash: str, text: str, metadata: Mapping[str, str]) -> Envelope[ChunkRecord]`  
*Create or update one chunk.*

`get_chunk(*, meta: EnvelopeMeta, chunk_id: str) -> Envelope[ChunkRecord]`  
*Read one chunk by id.*

`delete_chunk(*, meta: EnvelopeMeta, chunk_id: str) -> Envelope[bool]`  
*Hard-delete one chunk and derived embedding rows.*

`upsert_chunks(*, meta: EnvelopeMeta, items: Sequence[UpsertChunkInput]) -> Envelope[list[ChunkRecord]]`  
*Batch convenience API for chunk upserts.*

`list_chunks_by_source(*, meta: EnvelopeMeta, source_id: str, limit: int) -> Envelope[list[ChunkRecord]]`  
*List chunks for one source.*

`upsert_embedding_vector(*, meta: EnvelopeMeta, chunk_id: str, spec_id: str, vector: Sequence[float]) -> Envelope[EmbeddingRecord]`  
*Persist one vector point and indexed embedding status row.*

`upsert_embedding_vectors(*, meta: EnvelopeMeta, items: Sequence[UpsertEmbeddingVectorInput]) -> Envelope[list[EmbeddingRecord]]`  
*Batch convenience API for vector upserts.*

`get_embedding(*, meta: EnvelopeMeta, chunk_id: str, spec_id: str = '') -> Envelope[EmbeddingRecord]`  
*Read one embedding row; default ``spec_id`` is active spec.*

`list_embeddings_by_source(*, meta: EnvelopeMeta, source_id: str, spec_id: str, limit: int) -> Envelope[list[EmbeddingRecord]]`  
*List embedding rows for chunks under one source.*

`list_embeddings_by_status(*, meta: EnvelopeMeta, status: EmbeddingStatus, spec_id: str, limit: int) -> Envelope[list[EmbeddingRecord]]`  
*List embedding rows by status, optionally scoped to one spec.*

`search_embeddings(*, meta: EnvelopeMeta, query_vector: Sequence[float], source_id: str, spec_id: str, limit: int) -> Envelope[list[SearchEmbeddingMatch]]`  
*Search derived embeddings by semantic similarity.*

`upsert_source(*, meta: EnvelopeMeta, canonical_reference: str, source_type: str, service: str, principal: str, metadata: Mapping[str, str]) -> Envelope[SourceRecord]`  
*Create or update one source.*

`get_source(*, meta: EnvelopeMeta, source_id: str) -> Envelope[SourceRecord]`  
*Read one source by id.*

`delete_source(*, meta: EnvelopeMeta, source_id: str) -> Envelope[bool]`  
*Hard-delete one source and all owned chunks/embeddings.*

`list_sources(*, meta: EnvelopeMeta, canonical_reference: str, service: str, principal: str, limit: int) -> Envelope[list[SourceRecord]]`  
*List sources by optional filters.*

`upsert_spec(*, meta: EnvelopeMeta, provider: str, name: str, version: str, dimensions: int) -> Envelope[EmbeddingSpec]`  
*Create or return one embedding spec by canonical identity.*

`get_spec(*, meta: EnvelopeMeta, spec_id: str) -> Envelope[EmbeddingSpec]`  
*Read one spec by id.*

`get_active_spec(*, meta: EnvelopeMeta) -> Envelope[EmbeddingSpec]`  
*Return persisted active spec used for defaulted operations.*

`set_active_spec(*, meta: EnvelopeMeta, spec_id: str) -> Envelope[EmbeddingSpec]`  
*Persist and return the active spec used for defaulted spec operations.*

`list_specs(*, meta: EnvelopeMeta, limit: int) -> Envelope[list[EmbeddingSpec]]`  
*List known specs.*

------------------------------------------------------------------------
## `ObjectService`
* Module: `services/state/object/service.py`
* Summary: Public API for durable blob object operations.

`health(*, meta: EnvelopeMeta) -> Envelope[HealthStatus]`  
*Return Object and owned dependency readiness status.*

`put_object(*, meta: EnvelopeMeta, content: bytes, extension: str, content_type: str, original_filename: str, source_uri: str) -> Envelope[ObjectPutResult]`  
*Persist one blob and return object metadata plus dedupe disposition.*

`get_object(*, meta: EnvelopeMeta, object_key: str) -> Envelope[ObjectGetResult]`  
*Read one blob and metadata by canonical object key.*

`delete_object(*, meta: EnvelopeMeta, object_key: str) -> Envelope[bool]`  
*Delete one blob by canonical object key with idempotent semantics.*

`stat_object(*, meta: EnvelopeMeta, object_key: str) -> Envelope[ObjectRecord]`  
*Read metadata for one blob by canonical object key.*

------------------------------------------------------------------------
## `VaultService`
* Module: `services/state/vault/service.py`
* Summary: Public API for markdown vault file and directory operations.

`health(*, meta: EnvelopeMeta) -> Envelope[HealthStatus]`  
*Return Vault and owned dependency readiness status.*

`list_directory(*, meta: EnvelopeMeta, directory_path: str) -> Envelope[list[VaultEntry]]`  
*List file and directory entries under one vault-relative path.*

`delete_directory(*, meta: EnvelopeMeta, directory_path: str, recursive: bool = False, missing_ok: bool = False, use_trash: bool = True) -> Envelope[bool]`  
*Delete one directory, optionally recursively and missing-ok.*

`create_directory(*, meta: EnvelopeMeta, directory_path: str, recursive: bool = False) -> Envelope[VaultEntry]`  
*Create one directory.*

`get_file(*, meta: EnvelopeMeta, file_path: str) -> Envelope[VaultFileRecord]`  
*Read one markdown file by path.*

`delete_file(*, meta: EnvelopeMeta, file_path: str, missing_ok: bool = False, use_trash: bool = True, if_revision: str = '', force: bool = False) -> Envelope[bool]`  
*Delete one markdown file.*

`append_file(*, meta: EnvelopeMeta, file_path: str, content: str, if_revision: str = '', force: bool = False) -> Envelope[VaultFileRecord]`  
*Append content to one markdown file.*

`create_file(*, meta: EnvelopeMeta, file_path: str, content: str) -> Envelope[VaultFileRecord]`  
*Create one markdown file and fail when it already exists.*

`edit_file(*, meta: EnvelopeMeta, file_path: str, edits: Sequence[FileEdit], if_revision: str = '', force: bool = False) -> Envelope[VaultFileRecord]`  
*Apply one or more line-range edits to a markdown file.*

`update_file(*, meta: EnvelopeMeta, file_path: str, content: str, if_revision: str = '', force: bool = False) -> Envelope[VaultFileRecord]`  
*Replace markdown file content with optional optimistic precondition.*

`search_files(*, meta: EnvelopeMeta, query: str, directory_scope: str = '', limit: int = 20) -> Envelope[list[SearchFileMatch]]`  
*Search markdown files lexically through Obsidian Local REST API.*

`move_path(*, meta: EnvelopeMeta, source_path: str, target_path: str, if_revision: str = '', force: bool = False) -> Envelope[VaultEntry]`  
*Move one file or directory path.*


------------------------------------------------------------------------
_End of Service API_
