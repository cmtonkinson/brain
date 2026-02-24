# Service API
_This document is generated from `services/*/*/service.py`. Do not edit by hand._

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
## `ObjectAuthorityService`
- Module: `services/state/object_authority/service.py`
- Summary: Public API for durable blob object operations.

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
