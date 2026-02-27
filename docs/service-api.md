# Service API
_This document is generated from `services/*/*/service.py`. Do not edit by hand._

------------------------------------------------------------------------
## `AttentionRouterService`
- Module: `services/action/attention_router/service.py`
- Summary: Public API for policy-aware outbound notification routing.

`health(*, meta: EnvelopeMeta) -> Envelope[HealthStatus]`  
_Return Attention Router and adapter health state._

`correlate_approval_response(*, meta: EnvelopeMeta, actor: str, channel: str, message_text: str = '', approval_token: str = '', reply_to_proposal_token: str = '', reaction_to_proposal_token: str = '') -> Envelope[ApprovalCorrelationPayload]`  
_Normalize inbound approval-correlation fields for Policy Service._

`route_approval_notification(*, meta: EnvelopeMeta, approval: ApprovalNotificationPayload) -> Envelope[RouteNotificationResult]`  
_Route one token-only Policy->Attention approval notification._

`flush_batch(*, meta: EnvelopeMeta, batch_key: str, actor: str = 'operator', channel: str = '', recipient_e164: str = '', sender_e164: str = '', title: str = '') -> Envelope[RouteNotificationResult]`  
_Flush one pending batch by key and deliver consolidated summary._

`route_notification(*, meta: EnvelopeMeta, actor: str = 'operator', channel: str = '', title: str = '', message: str, recipient_e164: str = '', sender_e164: str = '', dedupe_key: str = '', batch_key: str = '', force: bool = False) -> Envelope[RouteNotificationResult]`  
_Route one outbound notification and decide suppress/send/batch._

------------------------------------------------------------------------
## `CapabilityEngineService`
- Module: `services/action/capability_engine/service.py`
- Summary: Public API for capability invocation under policy governance.

`health(*, meta: EnvelopeMeta) -> Envelope[CapabilityEngineHealthStatus]`  
_Return CES readiness, registry counts, and invocation-audit counters._

`describe_capabilities(*, meta: EnvelopeMeta) -> Envelope[tuple[CapabilityDescriptor, ...]]`  
_Return descriptors for all registered capabilities._

`invoke_capability(*, meta: EnvelopeMeta, capability_id: str, input_payload: dict[str, object], invocation: CapabilityInvocationMetadata) -> Envelope[CapabilityInvokeResult]`  
_Invoke by package ``capability_id`` (no version arg) and return normalized policy fields._

------------------------------------------------------------------------
## `LanguageModelService`
- Module: `services/action/language_model/service.py`
- Summary: Public API for chat and embedding operations.

`chat(*, meta: EnvelopeMeta, prompt: str, profile: ReasoningLevel = ReasoningLevel.STANDARD) -> Envelope[ChatResponse]`  
_Generate one chat completion._

`embed(*, meta: EnvelopeMeta, text: str, profile: EmbeddingProfile = EmbeddingProfile.EMBEDDING) -> Envelope[EmbeddingVector]`  
_Generate one embedding vector._

`health(*, meta: EnvelopeMeta) -> Envelope[HealthStatus]`  
_Return LMS and adapter health state._

`chat_batch(*, meta: EnvelopeMeta, prompts: Sequence[str], profile: ReasoningLevel = ReasoningLevel.STANDARD) -> Envelope[list[ChatResponse]]`  
_Generate a batch of chat completions._

`embed_batch(*, meta: EnvelopeMeta, texts: Sequence[str], profile: EmbeddingProfile = EmbeddingProfile.EMBEDDING) -> Envelope[list[EmbeddingVector]]`  
_Generate a batch of embedding vectors._

------------------------------------------------------------------------
## `PolicyService`
- Module: `services/action/policy_service/service.py`
- Summary: Public API for policy evaluation and callback-gated authorization.

`health(*, meta: EnvelopeMeta) -> Envelope[PolicyHealthStatus]`  
_Return Policy Service readiness and persistence-backed audit counters._

`authorize_and_execute(*, request: CapabilityInvocationRequest, execute: PolicyExecuteCallback) -> PolicyExecutionResult`  
_Return PolicyExecutionResult with allow/deny output, PolicyDecision, and ApprovalProposal._

------------------------------------------------------------------------
## `SwitchboardService`
- Module: `services/action/switchboard/service.py`
- Summary: Public API for webhook registration and inbound Signal ingestion.

`health(*, meta: EnvelopeMeta) -> Envelope[HealthStatus]`  
_Return Switchboard and dependency health state._

`ingest_signal_webhook(*, meta: EnvelopeMeta, raw_body_json: str, header_timestamp: str, header_signature: str) -> Envelope[IngestResult]`  
_Validate, normalize, and enqueue one Signal webhook payload._

`register_signal_webhook(*, meta: EnvelopeMeta, callback_url: str) -> Envelope[RegisterSignalWebhookResult]`  
_Register Signal webhook callback URI and shared secret._

------------------------------------------------------------------------
## `CacheAuthorityService`
- Module: `services/state/cache_authority/service.py`
- Summary: Public API for component-scoped cache and queue operations.

`health(*, meta: EnvelopeMeta) -> Envelope[HealthStatus]`  
_Return CAS and Redis substrate readiness._

`peek_queue(*, meta: EnvelopeMeta, component_id: str, queue: str) -> Envelope[QueueEntry | None]`  
_Peek next component-scoped queue value without removal._

`pop_queue(*, meta: EnvelopeMeta, component_id: str, queue: str) -> Envelope[QueueEntry | None]`  
_Pop one component-scoped queue value using FIFO order._

`push_queue(*, meta: EnvelopeMeta, component_id: str, queue: str, value: JsonValue) -> Envelope[QueueDepth]`  
_Push one component-scoped queue value._

`get_value(*, meta: EnvelopeMeta, component_id: str, key: str) -> Envelope[CacheEntry | None]`  
_Get one component-scoped cache value by key._

`delete_value(*, meta: EnvelopeMeta, component_id: str, key: str) -> Envelope[bool]`  
_Delete one component-scoped cache value._

`set_value(*, meta: EnvelopeMeta, component_id: str, key: str, value: JsonValue, ttl_seconds: int | None = None) -> Envelope[CacheEntry]`  
_Set one component-scoped cache value._

------------------------------------------------------------------------
## `EmbeddingAuthorityService`
- Module: `services/state/embedding_authority/service.py`
- Summary: Public API for the Embedding Authority Service.

`health(*, meta: EnvelopeMeta) -> Envelope[HealthStatus]`  
_Return EAS and owned dependency readiness status._

`upsert_chunk(*, meta: EnvelopeMeta, source_id: str, chunk_ordinal: int, reference_range: str, content_hash: str, text: str, metadata: Mapping[str, str]) -> Envelope[ChunkRecord]`  
_Create or update one chunk._

`get_chunk(*, meta: EnvelopeMeta, chunk_id: str) -> Envelope[ChunkRecord]`  
_Read one chunk by id._

`delete_chunk(*, meta: EnvelopeMeta, chunk_id: str) -> Envelope[bool]`  
_Hard-delete one chunk and derived embedding rows._

`upsert_chunks(*, meta: EnvelopeMeta, items: Sequence[UpsertChunkInput]) -> Envelope[list[ChunkRecord]]`  
_Batch convenience API for chunk upserts._

`list_chunks_by_source(*, meta: EnvelopeMeta, source_id: str, limit: int) -> Envelope[list[ChunkRecord]]`  
_List chunks for one source._

`upsert_embedding_vector(*, meta: EnvelopeMeta, chunk_id: str, spec_id: str, vector: Sequence[float]) -> Envelope[EmbeddingRecord]`  
_Persist one vector point and indexed embedding status row._

`upsert_embedding_vectors(*, meta: EnvelopeMeta, items: Sequence[UpsertEmbeddingVectorInput]) -> Envelope[list[EmbeddingRecord]]`  
_Batch convenience API for vector upserts._

`get_embedding(*, meta: EnvelopeMeta, chunk_id: str, spec_id: str = '') -> Envelope[EmbeddingRecord]`  
_Read one embedding row; default ``spec_id`` is active spec._

`list_embeddings_by_source(*, meta: EnvelopeMeta, source_id: str, spec_id: str, limit: int) -> Envelope[list[EmbeddingRecord]]`  
_List embedding rows for chunks under one source._

`list_embeddings_by_status(*, meta: EnvelopeMeta, status: EmbeddingStatus, spec_id: str, limit: int) -> Envelope[list[EmbeddingRecord]]`  
_List embedding rows by status, optionally scoped to one spec._

`search_embeddings(*, meta: EnvelopeMeta, query_vector: Sequence[float], source_id: str, spec_id: str, limit: int) -> Envelope[list[SearchEmbeddingMatch]]`  
_Search derived embeddings by semantic similarity._

`upsert_source(*, meta: EnvelopeMeta, canonical_reference: str, source_type: str, service: str, principal: str, metadata: Mapping[str, str]) -> Envelope[SourceRecord]`  
_Create or update one source._

`get_source(*, meta: EnvelopeMeta, source_id: str) -> Envelope[SourceRecord]`  
_Read one source by id._

`delete_source(*, meta: EnvelopeMeta, source_id: str) -> Envelope[bool]`  
_Hard-delete one source and all owned chunks/embeddings._

`list_sources(*, meta: EnvelopeMeta, canonical_reference: str, service: str, principal: str, limit: int) -> Envelope[list[SourceRecord]]`  
_List sources by optional filters._

`upsert_spec(*, meta: EnvelopeMeta, provider: str, name: str, version: str, dimensions: int) -> Envelope[EmbeddingSpec]`  
_Create or return one embedding spec by canonical identity._

`get_spec(*, meta: EnvelopeMeta, spec_id: str) -> Envelope[EmbeddingSpec]`  
_Read one spec by id._

`get_active_spec(*, meta: EnvelopeMeta) -> Envelope[EmbeddingSpec]`  
_Return persisted active spec used for defaulted operations._

`set_active_spec(*, meta: EnvelopeMeta, spec_id: str) -> Envelope[EmbeddingSpec]`  
_Persist and return the active spec used for defaulted spec operations._

`list_specs(*, meta: EnvelopeMeta, limit: int) -> Envelope[list[EmbeddingSpec]]`  
_List known specs._

------------------------------------------------------------------------
## `MemoryAuthorityService`
- Module: `services/state/memory_authority/service.py`
- Summary: Public API for Memory Authority Service context and session operations.

`health(*, meta: EnvelopeMeta) -> Envelope[HealthStatus]`  
_Return MAS and Postgres substrate readiness._

`assemble_context(*, meta: EnvelopeMeta, session_id: str, message: str) -> Envelope[ContextBlock]`  
_Append inbound message and return assembled Profile/Focus/Dialogue context._

`update_focus(*, meta: EnvelopeMeta, session_id: str, content: str) -> Envelope[FocusRecord]`  
_Persist explicit focus content with budget-aware compaction semantics._

`record_response(*, meta: EnvelopeMeta, session_id: str, content: str, model: str, provider: str, token_count: int, reasoning_level: str) -> Envelope[bool]`  
_Append one outbound dialogue turn with response metadata._

`get_session(*, meta: EnvelopeMeta, session_id: str) -> Envelope[SessionRecord]`  
_Read one MAS session by id._

`clear_session(*, meta: EnvelopeMeta, session_id: str) -> Envelope[bool]`  
_Advance dialogue pointer and clear focus without deleting historical data._

`create_session(*, meta: EnvelopeMeta) -> Envelope[SessionRecord]`  
_Create and return one new MAS session._

------------------------------------------------------------------------
## `ObjectAuthorityService`
- Module: `services/state/object_authority/service.py`
- Summary: Public API for durable blob object operations.

`health(*, meta: EnvelopeMeta) -> Envelope[HealthStatus]`  
_Return OAS and owned dependency readiness status._

`put_object(*, meta: EnvelopeMeta, content: bytes, extension: str, content_type: str, original_filename: str, source_uri: str) -> Envelope[ObjectRecord]`  
_Persist one blob and return authoritative object record._

`get_object(*, meta: EnvelopeMeta, object_key: str) -> Envelope[ObjectGetResult]`  
_Read one blob and metadata by canonical object key._

`delete_object(*, meta: EnvelopeMeta, object_key: str) -> Envelope[bool]`  
_Delete one blob by canonical object key with idempotent semantics._

`stat_object(*, meta: EnvelopeMeta, object_key: str) -> Envelope[ObjectRecord]`  
_Read metadata for one blob by canonical object key._

------------------------------------------------------------------------
## `VaultAuthorityService`
- Module: `services/state/vault_authority/service.py`
- Summary: Public API for markdown vault file and directory operations.

`health(*, meta: EnvelopeMeta) -> Envelope[HealthStatus]`  
_Return VAS and owned dependency readiness status._

`list_directory(*, meta: EnvelopeMeta, directory_path: str) -> Envelope[list[VaultEntry]]`  
_List file and directory entries under one vault-relative path._

`delete_directory(*, meta: EnvelopeMeta, directory_path: str, recursive: bool = False, missing_ok: bool = False, use_trash: bool = True) -> Envelope[bool]`  
_Delete one directory, optionally recursively and missing-ok._

`create_directory(*, meta: EnvelopeMeta, directory_path: str, recursive: bool = False) -> Envelope[VaultEntry]`  
_Create one directory._

`get_file(*, meta: EnvelopeMeta, file_path: str) -> Envelope[VaultFileRecord]`  
_Read one markdown file by path._

`delete_file(*, meta: EnvelopeMeta, file_path: str, missing_ok: bool = False, use_trash: bool = True, if_revision: str = '', force: bool = False) -> Envelope[bool]`  
_Delete one markdown file._

`append_file(*, meta: EnvelopeMeta, file_path: str, content: str, if_revision: str = '', force: bool = False) -> Envelope[VaultFileRecord]`  
_Append content to one markdown file._

`create_file(*, meta: EnvelopeMeta, file_path: str, content: str) -> Envelope[VaultFileRecord]`  
_Create one markdown file and fail when it already exists._

`edit_file(*, meta: EnvelopeMeta, file_path: str, edits: Sequence[FileEdit], if_revision: str = '', force: bool = False) -> Envelope[VaultFileRecord]`  
_Apply one or more line-range edits to a markdown file._

`update_file(*, meta: EnvelopeMeta, file_path: str, content: str, if_revision: str = '', force: bool = False) -> Envelope[VaultFileRecord]`  
_Replace markdown file content with optional optimistic precondition._

`search_files(*, meta: EnvelopeMeta, query: str, directory_scope: str = '', limit: int = 20) -> Envelope[list[SearchFileMatch]]`  
_Search markdown files lexically through Obsidian Local REST API._

`move_path(*, meta: EnvelopeMeta, source_path: str, target_path: str, if_revision: str = '', force: bool = False) -> Envelope[VaultEntry]`  
_Move one file or directory path._

------------------------------------------------------------------------
_End of Service API_
