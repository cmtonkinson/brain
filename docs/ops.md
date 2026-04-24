# Op Catalog
_This document is generated from `ops/**/op.json`. Do not edit by hand._

------------------------------------------------------------------------
## `Cache Service`
### `cache-delete-value`
Delete one component-scoped cache value.  
`native` `1.0.0` `effect: write` `approval: never`  
Native Op over `Cache Service delete_value()`  

**Inputs:**
- `component_id` _(string)_ The canonical component id namespace for the cache key.
- `key` _(string)_ The cache key within the component namespace.

**Outputs:**
- `boolean`: True when the cache delete operation completes.

### `cache-get-value`
Get one component-scoped cache value by key.  
`native` `1.0.0` `effect: read` `approval: never`  
Native Op over `Cache Service get_value()`  

**Inputs:**
- `component_id` _(string)_ The canonical component id namespace for the cache key.
- `key` _(string)_ The cache key within the component namespace.

**Outputs:**
- `object | null`

### `cache-peek-queue`
Peek next component-scoped queue value without removal.  
`native` `1.0.0` `effect: read` `approval: never`  
Native Op over `Cache Service peek_queue()`  

**Inputs:**
- `component_id` _(string)_ The canonical component id namespace for the queue.
- `queue` _(string)_ The queue name within the component namespace.

**Outputs:**
- `object | null`

### `cache-pop-queue`
Pop one component-scoped queue value using FIFO order.  
`native` `1.0.0` `effect: write` `approval: never`  
Native Op over `Cache Service pop_queue()`  

**Inputs:**
- `component_id` _(string)_ The canonical component id namespace for the queue.
- `queue` _(string)_ The queue name within the component namespace.

**Outputs:**
- `object | null`

### `cache-push-queue`
Push one component-scoped queue value.  
`native` `1.0.0` `effect: write` `approval: never`  
Native Op over `Cache Service push_queue()`  

**Inputs:**
- `component_id` _(string)_ The canonical component id namespace for the queue.
- `queue` _(string)_ The queue name within the component namespace.
- `value` _(object)_ The JSON-serializable value to enqueue.

**Outputs:**
- `component_id` _(string)_ The canonical component id namespace for the queue.
- `queue` _(string)_ The queue name within the component namespace.
- `size` _(integer)_ The queue depth after the enqueue operation.

### `cache-set-value`
Set one component-scoped cache value.  
`native` `1.0.0` `effect: write` `approval: never`  
Native Op over `Cache Service set_value()`  

**Inputs:**
- `component_id` _(string)_ The canonical component id namespace for the cache key.
- `key` _(string)_ The cache key within the component namespace.
- `value` _(object)_ The JSON-serializable value to persist.
- `ttl_seconds` _(integer | null, optional)_ Optional TTL override in seconds; null uses the service default.

**Outputs:**
- `component_id` _(string)_ The canonical component id namespace for the cache key.
- `key` _(string)_ The cache key within the component namespace.
- `value` _(object)_ The JSON value that was persisted.
- `ttl_seconds` _(integer | null)_ The effective TTL applied to the key; null means the key does not expire.

------------------------------------------------------------------------
## `Commitment Service`
### `commitment-extract-candidates`
Extract zero or more commitment candidate signals from arbitrary text.  
`native` `1.0.0` `effect: read` `approval: never`  
Native Op over `Commitment Service extract_commitment_candidates()`  

**Inputs:**
- `text` _(string)_ Arbitrary source text to scan for commitment signals.
- `context` _(string, optional)_ Optional background context (e.g. conversation metadata, speaker roles) that may help the model interpret the text.

**Outputs:**
- `candidates` _(array[object])_ Extracted commitment candidates, ordered by descending confidence.

### `commitment-run-miss-detection`
Run commitment miss detection for one commitment or all due commitments.  
`native` `1.0.0` `effect: execute` `approval: never`  
Native Op over `Commitment Service run_miss_detection()`  

**Inputs:**
- `commitment_id` _(string | null, optional)_ One commitment id to check; omitted scans all due commitments.

**Outputs:**
- `checked_count` _(integer)_ Number of due open commitments examined.
- `missed_count` _(integer)_ Number of commitments transitioned to MISSED.
- `notified_count` _(integer)_ Number of missed notifications delivered.
- `commitment_ids` _(array[string])_ Commitment ids transitioned during this run.

------------------------------------------------------------------------
## `Delegation Service`
### `subagent-async`
Queue one subagent invocation for asynchronous execution and return its identifier.  
`native` `1.0.0` `effect: execute` `approval: never`  
Native Op over `Delegation Service invoke()`  

**Inputs:**
- `prompt` _(string)_ The task instruction the subagent should accomplish.
- `context_text` _(string | null, optional)_ Optional inline scratch context appended to the subagent system prompt.
- `context_object_refs` _(array[string], optional, default=[])_ Object Service refs the subagent may resolve for additional context.
- `personality_id` _(string, optional, default='subagent')_ Personality template id under lib/sdk/personalities (default 'subagent').
- `tool_allowlist` _(array[string] | null, optional)_ Optional explicit allowlist of op_ids the subagent may invoke.
- `max_turns` _(integer, optional, default=8)_ Hard ceiling on tool-loop turns.
- `budget_tokens` _(integer | null, optional)_ Hard ceiling on total tokens consumed across all turns.
- `max_wallclock_seconds` _(integer | null, optional)_ Hard ceiling on wallclock seconds from claim to terminal.
- `parent_invocation_id` _(string | null, optional)_ Optional parent invocation id; cascade-cancel propagates here.

**Outputs:**
- `invocation_id` _(string)_

### `subagent-cancel`
Request cancellation of one queued or running subagent invocation.  
`native` `1.0.0` `effect: execute` `approval: never`  
Native Op over `Delegation Service cancel()`  

**Inputs:**
- `invocation_id` _(string)_ The ULID identifier of the invocation to cancel.
- `reason` _(string, optional)_ Cancel reason code (default 'manual').

**Outputs:**
- `accepted` _(boolean)_

### `subagent-status`
Read the current status projection for one subagent invocation.  
`native` `1.0.0` `effect: read` `approval: never`  
Native Op over `Delegation Service get_status()`  

**Inputs:**
- `invocation_id` _(string)_ The ULID identifier of the invocation.

**Outputs:**
- `invocation_id` _(string)_
- `status` _(string)_
- `cancel_reason` _(string | null, optional)_
- `tokens_in` _(integer)_
- `tokens_out` _(integer)_
- `turn_count` _(integer)_
- `started_at` _(string | null, optional)_
- `completed_at` _(string | null, optional)_

### `subagent-sync`
Spawn one subagent to accomplish a task and block until it returns a result.  
`native` `1.0.0` `effect: execute` `approval: never`  
Native Op over `Delegation Service invoke_and_wait()`  

**Inputs:**
- `prompt` _(string)_ The task instruction the subagent should accomplish.
- `context_text` _(string | null, optional)_ Optional inline scratch context appended to the subagent system prompt.
- `context_object_refs` _(array[string], optional, default=[])_ Object Service refs the subagent may resolve for additional context.
- `personality_id` _(string, optional, default='subagent')_ Personality template id under lib/sdk/personalities (default 'subagent').
- `tool_allowlist` _(array[string] | null, optional)_ Optional explicit allowlist of op_ids the subagent may invoke.
- `max_turns` _(integer, optional, default=8)_ Hard ceiling on tool-loop turns.
- `budget_tokens` _(integer | null, optional)_ Hard ceiling on total tokens consumed across all turns.
- `max_wallclock_seconds` _(integer | null, optional)_ Hard ceiling on wallclock seconds from claim to terminal.
- `parent_invocation_id` _(string | null, optional)_ Optional parent invocation id; cascade-cancel propagates here.
- `timeout_seconds` _(number | null, optional)_ Maximum seconds to block waiting for terminal state.

**Outputs:**
- `invocation_id` _(string)_
- `status` _(string)_
- `final_response` _(string | null, optional)_
- `cancel_reason` _(string | null, optional)_
- `tokens_in` _(integer)_
- `tokens_out` _(integer)_
- `turn_count` _(integer)_

### `subagent-wait`
Block until a previously queued subagent invocation reaches terminal state.  
`native` `1.0.0` `effect: read` `approval: never`  
Native Op over `Delegation Service wait()`  

**Inputs:**
- `invocation_id` _(string)_ The ULID identifier of the invocation to wait on.
- `timeout_seconds` _(number | null, optional)_ Maximum seconds to block. Returns the latest snapshot at timeout.

**Outputs:**
- `invocation_id` _(string)_
- `status` _(string)_
- `final_response` _(string | null, optional)_
- `cancel_reason` _(string | null, optional)_
- `tokens_in` _(integer)_
- `tokens_out` _(integer)_
- `turn_count` _(integer)_

------------------------------------------------------------------------
## `Embedding Service`
### `embedding-upsert-document-batch`
Persist a batch of embedding vectors for chunk and spec pairs.  
`native` `1.0.0` `effect: write` `approval: never`  
Native Op over `Embedding Service upsert_embedding_vectors()`  

**Inputs:**
- `items` _(array[object])_ Batch of chunk/spec/vector inputs to persist.

**Outputs:**
- `array[object]`: Persisted embedding materialization records.

### `language-model-embed-chunks`
Generate embedding vectors for a batch of text chunks.  
`native` `1.0.0` `effect: read` `approval: never`  
Native Op over `Language Service embed_batch()`  

**Inputs:**
- `texts` _(array[string])_ The text chunks to embed.
- `profile` _(string, optional)_ Optional embedding profile override.

**Outputs:**
- `array[object]`: One embedding vector result per input text chunk.

------------------------------------------------------------------------
## `Ingestion Service`
### `ingestion-advance`
Advance one ingestion from a named stage through the remaining pipeline.  
`native` `1.0.0` `effect: execute` `approval: never`  
Native Op over `Ingestion Service advance_ingestion()`  

**Inputs:**
- `ingestion_id` _(string)_ The ingestion identifier to advance.
- `from_stage` _(string)_ The first stage to consider: store, extract, normalize, or anchor.
- `force_target` _(boolean, optional)_ Re-run the requested target stage even if its latest run succeeded.

**Outputs:**
- `id` _(string)_ The ingestion identifier.
- `status` _(string)_ The current ingestion lifecycle status.
- `source_type` _(string)_ The original source type.
- `source_uri` _(string | null)_ The original source URI, if any.
- `source_actor` _(string | null)_ The originating actor, if any.
- `capture_time` _(string)_ The timezone-aware capture timestamp.
- `mime_type` _(string | null)_ The source MIME type, if any.
- `last_error` _(string | null)_ The most recent ingestion error, if any.
- `created_at` _(string)_ The record creation timestamp.
- `updated_at` _(string)_ The record update timestamp.

### `ingestion-index-anchored`
Index anchored ingestion artifacts through derived embedding services.  
`native` `1.0.0` `effect: execute` `approval: never`  
Native Op over `Ingestion Service index_anchored_ingestion()`  

**Inputs:**
- `ingestion_id` _(string)_ The ingestion identifier whose anchored artifacts should be indexed.
- `indexing_run_id` _(string)_ The ingestion-owned indexing run identifier to update.

**Outputs:**
- `ingestion_id` _(string)_ The ingestion identifier that was indexed.
- `indexing_run_id` _(string)_ The ingestion-owned indexing run identifier.
- `source_count` _(integer)_ Number of Embedding sources created or updated.
- `chunk_count` _(integer)_ Number of chunks created or updated.
- `embedding_count` _(integer)_ Number of embedding vectors persisted.
- `failed_count` _(integer)_ Number of anchored artifacts that failed indexing.

------------------------------------------------------------------------
## `Object Service`
### `object-delete`
Delete one persisted object by canonical object key.  
`native` `1.0.0` `effect: write` `approval: always`  
Native Op over `Object Service delete_object()`  

**Inputs:**
- `object_key` _(string)_ The canonical object key to delete.

**Outputs:**
- `boolean`: True when the object delete operation completes.

### `object-stat`
Read metadata for one persisted object by canonical object key.  
`native` `1.0.0` `effect: read` `approval: never`  
Native Op over `Object Service stat_object()`  

**Inputs:**
- `object_key` _(string)_ The canonical object key to inspect.

**Outputs:**
- `ref` _(object)_
- `metadata` _(object)_

------------------------------------------------------------------------
## `Recall Service`
### `dialogue-compact`
Summarize all recent turns and compress context to summary-only.  
`native` `1.0.0` `effect: execute` `approval: never`  
Native Op over `Recall Service compact_dialogue()`  

**Inputs:**
- `session_id` _(string)_ The session to compact

**Outputs:**
- `id` _(string)_ Session ULID
- `dialogue_summary` _(string | null)_ Updated rolling summary
- `dialogue_summary_token_count` _(integer | null)_ Token count of new summary
- `dialogue_start_turn_id` _(string | null)_ Advanced frontier pointer

### `session-new`
Create a fresh Recall session.  
`native` `1.0.0` `effect: execute` `approval: never`  
Native Op over `Recall Service create_session()`  

**Inputs:** None

**Outputs:**
- `id` _(string)_ The new session ULID
- `focus` _(string | null)_ Always null for a fresh session
- `focus_token_count` _(integer | null)_ Always null for a fresh session
- `dialogue_summary` _(string | null)_ Always null for a fresh session
- `dialogue_summary_token_count` _(integer | null)_ Always null for a fresh session
- `dialogue_start_turn_id` _(string | null)_ Always null for a fresh session
- `created_at` _(string)_ ISO-8601 creation timestamp
- `updated_at` _(string)_ ISO-8601 update timestamp

------------------------------------------------------------------------
## `Relay Service`
### `relay-flush-batch`
Flush one pending batch by key and deliver consolidated summary.  
`native` `1.0.0` `effect: external` `approval: never`  
Native Op over `Relay Service flush_batch()`  

**Inputs:**
- `batch_key` _(string)_ The batch key to flush.
- `actor` _(string, optional)_ Actor identity for routing context. Defaults to 'operator'.
- `channel` _(string, optional)_ Channel identifier. Defaults to service routing default.
- `recipient_e164` _(string, optional)_ Explicit recipient E.164 override.
- `sender_e164` _(string, optional)_ Explicit sender E.164 override.
- `title` _(string, optional)_ Optional title for flushed summary notification.

**Outputs:**
- `decision` _(string)_ Router decision outcome: sent or suppressed.
- `delivered` _(boolean)_ Whether a message was delivered to channel.
- `detail` _(string)_ Human-readable routing detail.
- `suppressed_reason` _(string, optional)_ Suppression reason when no batch is available.
- `batched_count` _(integer, optional)_ Pending item count when relevant.
- `notification` _(object, optional)_ Normalized routed notification payload.

### `relay-notify`
Route one outbound notification and decide suppress/send/batch.  
`native` `1.0.0` `effect: external` `approval: never`  
Native Op over `Relay Service route_notification()`  

**Inputs:**
- `actor` _(string, optional)_ Actor identity for routing context. Defaults to 'operator'.
- `channel` _(string, optional)_ Channel identifier. Defaults to service routing default.
- `title` _(string, optional)_ Optional title rendered above message content.
- `message` _(string)_ The notification body to route.
- `dedupe_key` _(string, optional)_ Suppress duplicate sends within configured dedupe window.
- `batch_key` _(string, optional)_ Queue into batch instead of immediate send.
- `force` _(boolean, optional)_ Bypass dedupe, batch, and rate-limit suppression checks. Defaults to false.
- `conversational_memory` _(object | null, optional)_ Recall-owned conversational outbound metadata with session_id, model, provider, token_count, and reasoning_level. Persisted only when a conversational channel actually sends.

**Outputs:**
- `decision` _(string)_ Router decision outcome: sent, suppressed, or batched.
- `delivered` _(boolean)_ Whether a message was delivered to channel.
- `detail` _(string)_ Human-readable routing detail.
- `suppressed_reason` _(string, optional)_ Suppression reason when decision is suppressed.
- `batched_count` _(integer, optional)_ Pending item count when decision is batched.
- `notification` _(object, optional)_ Normalized routed notification payload.

------------------------------------------------------------------------
## `Utility Service`
### `chunk-text`
Split text into ordered chunks.  
`native` `1.0.0` `effect: execute` `approval: never`  
Native Op over `Utility Service chunk_text()`  

**Inputs:**
- `text` _(string)_ The text to chunk.

**Outputs:**
- `array[object]`: Ordered chunks derived from the input text.

### `current-datetime`
Return the current UTC and operator-local datetimes.  
`native` `1.0.0` `effect: read` `approval: never`  
Native Op over `Utility Service current_datetime()`  

**Inputs:** None

**Outputs:**
- `utc_timestamp` _(date-time)_ The current UTC datetime in ISO 8601 format.
- `local_timestamp` _(date-time)_ The current datetime in the operator's preferred timezone.
- `local_timezone` _(string)_ The operator's preferred IANA timezone name.

------------------------------------------------------------------------
## `Vault Service`
### `vault-append-file`
Append content to one markdown file.  
`native` `1.0.0` `effect: write` `approval: never`  
Native Op over `Vault Service append_file()`  

**Inputs:**
- `file_path` _(string)_ The full path of the file to append to.
- `content` _(string)_ The content to append to the file.
- `if_revision` _(string, optional)_ Only append to the file if its current revision matches this value.
- `force` _(boolean, optional)_ Force the append, ignoring revision conflicts. Defaults to false.

**Outputs:**
- `path` _(string)_ The full path of the file.
- `content` _(string)_ The content of the file.
- `size_bytes` _(integer)_ The size of the file in bytes.
- `created_at` _(date-time | null, optional)_ The timestamp when the file was created.
- `updated_at` _(date-time | null, optional)_ The timestamp when the file was last updated.
- `revision` _(string)_ The revision identifier for the file.

### `vault-create-directory`
Create one directory in the vault.  
`native` `1.0.0` `effect: write` `approval: never`  
Native Op over `Vault Service create_directory()`  

**Inputs:**
- `directory_path` _(string)_ The full path of the directory to create.
- `recursive` _(boolean, optional)_ Create parent directories if they don't exist. Defaults to false.

**Outputs:**
- `path` _(string)_ The full path of the created directory.
- `name` _(string)_ The name of the created directory.
- `entry_type` _(string)_ The type of the entry (will be 'directory').
- `size_bytes` _(integer)_ The size of the entry in bytes (will be 0).
- `created_at` _(date-time | null, optional)_ The timestamp when the directory was created.
- `updated_at` _(date-time | null, optional)_ The timestamp when the directory was last updated.
- `revision` _(string)_ The revision identifier for the entry.

### `vault-create-file`
Create one markdown file; fails when it already exists.  
`native` `1.0.0` `effect: write` `approval: never`  
Native Op over `Vault Service create_file()`  

**Inputs:**
- `file_path` _(string)_ The full path of the file to create.
- `content` _(string)_ The initial content of the file.

**Outputs:**
- `path` _(string)_ The full path of the file.
- `content` _(string)_ The content of the file.
- `size_bytes` _(integer)_ The size of the file in bytes.
- `created_at` _(date-time | null, optional)_ The timestamp when the file was created.
- `updated_at` _(date-time | null, optional)_ The timestamp when the file was last updated.
- `revision` _(string)_ The revision identifier for the file.

### `vault-delete-directory`
Delete one directory, optionally recursively.  
`native` `1.0.0` `effect: write` `approval: always`  
Native Op over `Vault Service delete_directory()`  

**Inputs:**
- `directory_path` _(string)_ The full path of the directory to delete.
- `recursive` _(boolean, optional)_ Delete the directory even if it is not empty. Defaults to false.
- `missing_ok` _(boolean, optional)_ If true, do not raise an error if the directory does not exist. Defaults to false.
- `use_trash` _(boolean, optional)_ If true, move the directory to a trash folder instead of permanently deleting. Defaults to true.

**Outputs:**
- `boolean`: True if the directory was deleted, False otherwise.

### `vault-delete-file`
Delete one markdown file.  
`native` `1.0.0` `effect: write` `approval: always`  
Native Op over `Vault Service delete_file()`  

**Inputs:**
- `file_path` _(string)_ The full path of the file to delete.
- `missing_ok` _(boolean, optional)_ If true, do not raise an error if the file does not exist. Defaults to false.
- `use_trash` _(boolean, optional)_ If true, move the file to a trash folder instead of permanently deleting. Defaults to true.
- `if_revision` _(string, optional)_ Only delete the file if its current revision matches this value.
- `force` _(boolean, optional)_ Bypass the trash folder and delete immediately. Defaults to false.

**Outputs:**
- `boolean`: True if the file was deleted, False otherwise.

### `vault-edit-file`
Apply one or more line-range edits to a markdown file.  
`native` `1.0.0` `effect: write` `approval: never`  
Native Op over `Vault Service edit_file()`  

**Inputs:**
- `file_path` _(string)_ The full path of the file to edit.
- `edits` _(array[object])_ A sequence of line-range edits to apply to the file.
- `if_revision` _(string, optional)_ Only edit the file if its current revision matches this value.
- `force` _(boolean, optional)_ Force the edit, ignoring revision conflicts. Defaults to false.

**Outputs:**
- `path` _(string)_ The full path of the file.
- `content` _(string)_ The content of the file.
- `size_bytes` _(integer)_ The size of the file in bytes.
- `created_at` _(date-time | null, optional)_ The timestamp when the file was created.
- `updated_at` _(date-time | null, optional)_ The timestamp when the file was last updated.
- `revision` _(string)_ The revision identifier for the file.

### `vault-get-file`
Read one markdown file by path.  
`native` `1.0.0` `effect: read` `approval: never`  
Native Op over `Vault Service get_file()`  

**Inputs:**
- `file_path` _(string)_ The full path of the file to read.

**Outputs:**
- `path` _(string)_ The full path of the file.
- `content` _(string)_ The content of the file.
- `size_bytes` _(integer)_ The size of the file in bytes.
- `created_at` _(date-time | null, optional)_ The timestamp when the file was created.
- `updated_at` _(date-time | null, optional)_ The timestamp when the file was last updated.
- `revision` _(string)_ The revision identifier for the file.

### `vault-list-directory`
List file and directory entries under one vault-relative path.  
`native` `1.0.0` `effect: read` `approval: never`  
Native Op over `Vault Service list_directory()`  

**Inputs:**
- `directory_path` _(string)_ The path of the directory to list. Use '.' for the vault root.

**Outputs:**
- `array[object]`: A list of files and directories in the specified path.

### `vault-move-path`
Move one file or directory path.  
`native` `1.0.0` `effect: write` `approval: always`  
Native Op over `Vault Service move_path()`  

**Inputs:**
- `source_path` _(string)_ The full path of the file or directory to move.
- `target_path` _(string)_ The new full path for the file or directory.
- `if_revision` _(string, optional)_ Only move if the source's current revision matches this value.
- `force` _(boolean, optional)_ Force the move, overwriting the target if it exists. Defaults to false.

**Outputs:**
- `path` _(string)_ The full path of the moved entry.
- `name` _(string)_ The name of the moved entry.
- `entry_type` _(string)_ The type of the entry ('directory' or 'file').
- `size_bytes` _(integer)_ The size of the entry in bytes.
- `created_at` _(date-time | null, optional)_ The timestamp when the entry was created.
- `updated_at` _(date-time | null, optional)_ The timestamp when the entry was last updated.
- `revision` _(string)_ The revision identifier for the entry.

### `vault-search-files`
Search markdown files lexically through Obsidian Local REST API.  
`native` `1.0.0` `effect: read` `approval: never`  
Native Op over `Vault Service search_files()`  

**Inputs:**
- `query` _(string)_ The search query.
- `directory_scope` _(string, optional)_ A directory path to limit the search to.
- `limit` _(integer, optional)_ The maximum number of results to return. Defaults to a system-wide setting.

**Outputs:**
- `array[object]`: A list of files matching the search query.

### `vault-update-file`
Replace markdown file content with optional optimistic precondition.  
`native` `1.0.0` `effect: write` `approval: never`  
Native Op over `Vault Service update_file()`  

**Inputs:**
- `file_path` _(string)_ The full path of the file to update.
- `content` _(string)_ The new content to write to the file.
- `if_revision` _(string, optional)_ Only update the file if its current revision matches this value.
- `force` _(boolean, optional)_ Force the update, ignoring revision conflicts. Defaults to false.

**Outputs:**
- `path` _(string)_ The full path of the file.
- `content` _(string)_ The content of the file.
- `size_bytes` _(integer)_ The size of the file in bytes.
- `created_at` _(date-time | null, optional)_ The timestamp when the file was created.
- `updated_at` _(date-time | null, optional)_ The timestamp when the file was last updated.
- `revision` _(string)_ The revision identifier for the file.

------------------------------------------------------------------------
## `Logic Ops`
### `demo-echo`
Returns the static string 'Hello, World!'.  
`logic` `1.0.0` `effect: read` `approval: never`  
Logic Op  

**Inputs:** None

**Outputs:**
- `string`: Returns the static string 'Hello, World!'.

### `mcp-status`
List configured MCP servers or MCP Ops for one server.  
`logic` `1.0.0` `effect: read` `approval: never`  
Logic Op  

**Inputs:**
- `server_id` _(string, optional)_ MCP server id whose MCP Ops should be listed.

**Outputs:**
- `string`: Formatted MCP server or tool status.

### `object-get-base64`
Read one object and return metadata plus base64-encoded content.  
`logic` `1.0.0` `effect: read` `approval: never`  
Logic Op  

**Inputs:**
- `object_key` _(string)_ The canonical object key to read.

**Outputs:**
- `object` _(object)_ The authoritative object record.
- `content_base64` _(string)_ The base64-encoded blob content.

### `object-get-text`
Read one text object and return metadata plus decoded content.  
`logic` `1.0.0` `effect: read` `approval: never`  
Logic Op  

**Inputs:**
- `object_key` _(string)_ The canonical object key to read.
- `encoding` _(string, optional)_ Text encoding used to decode stored bytes. Defaults to 'utf-8'.

**Outputs:**
- `object` _(object)_ The authoritative object record.
- `content` _(string)_ The decoded text content.
- `encoding` _(string)_ The text encoding used for decoding.

### `object-put-base64`
Persist one base64-encoded blob and return object metadata plus dedupe disposition.  
`logic` `1.0.0` `effect: write` `approval: never`  
Logic Op  

**Inputs:**
- `content_base64` _(string)_ The base64-encoded blob content to persist.
- `extension` _(string)_ The file extension recorded for the object.
- `content_type` _(string)_ The MIME type recorded for the object.
- `original_filename` _(string, optional)_ Optional original filename metadata.
- `source_uri` _(string, optional)_ Optional source URI metadata.

**Outputs:**
- `object` _(object)_
- `write_disposition` _(string)_

### `object-put-text`
Persist one text blob and return object metadata plus dedupe disposition.  
`logic` `1.0.0` `effect: write` `approval: never`  
Logic Op  

**Inputs:**
- `content` _(string)_ The text content to persist.
- `extension` _(string, optional)_ File extension recorded for the object. Defaults to 'txt'.
- `content_type` _(string, optional)_ MIME type recorded for the object. Defaults to 'text/plain; charset=utf-8'.
- `original_filename` _(string, optional)_ Optional original filename metadata.
- `source_uri` _(string, optional)_ Optional source URI metadata.
- `encoding` _(string, optional)_ Text encoding used before persistence. Defaults to 'utf-8'.

**Outputs:**
- `object` _(object)_
- `write_disposition` _(string)_

### `op-classify`
Classify one dynamic op by setting its effect and/or approval.  
`logic` `1.0.0` `effect: write` `approval: always`  
Logic Op  

**Inputs:**
- `op_id` _(string)_ dynamic op id to classify (e.g. eventkit--list-events).
- `words` _(array[string])_ one or more words drawn from the effect set (read|write|execute|external) and/or the approval set (always|never).

**Outputs:**
- `string`: Confirmation message describing the persisted classification.

### `slash-help`
List all slash commands available via operator channels.  
`logic` `1.0.0` `effect: read` `approval: never`  
Logic Op  

**Inputs:** None

**Outputs:**
- `string`: Formatted list of registered slash commands with descriptions.


------------------------------------------------------------------------
_End of Op Catalog_
