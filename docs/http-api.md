# HTTP API
*This document is generated from `lib/core/health_api.py` and `services/*/*/api.py`, with route intent from `docs/meta/http-routes.yaml`. Do not edit by hand.*

------------------------------------------------------------------------
## `lib/core/health_api.py`
`GET /health` &mdash; full-system diagnostic health check
*Handler: `health`*
*Response: `CoreHealthResult`*

------------------------------------------------------------------------
## `services/effect/execution/api.py`
`POST /ops/always-on` &mdash; return full descriptors for the configured always-on ops
*Handler: `list_always_on_ops`*
*Response: `_DescribeResponse`*


`POST /ops/describe` &mdash; enumerate all active ops
*Handler: `describe_ops`*
*Response: `_DescribeResponse`*


`POST /ops/describe-one` &mdash; return one full Op descriptor by op_id
*Handler: `describe_op`*
*Response: `_DescribeOneResponse`*


`POST /ops/dynamic/classifications` &mdash; list observed dynamic ops and persisted classifications
*Handler: `list_dynamic_op_classifications`*
*Response: `_DynamicOpClassificationListResponse`*


`POST /ops/dynamic/classify` &mdash; persist one operator-supplied dynamic op classification
*Handler: `classify_dynamic_op`*
*Response: `_DynamicOpClassificationListResponse`*


`POST /ops/invoke` &mdash; execute tool calls
*Handler: `invoke_op`*
*Response: `_InvokeResponse`*


`POST /ops/search` &mdash; semantically search the enabled Op catalog and return compact matches
*Handler: `search_ops`*
*Response: `_SearchResponse`*


`POST /ops/slash-lookup` &mdash; resolve one op descriptor by slash command name or alias
*Handler: `slash_lookup`*
*Response: `_SlashLookupResponse`*


`POST /ops/tool-system-hints` &mdash; return compact orientation hints for systems reachable through tools
*Handler: `list_tool_system_hints`*
*Response: `_ToolSystemHintsResponse`*

------------------------------------------------------------------------
## `services/effect/language/api.py`
`POST /lms/chat` &mdash; direct access to model inference without Execution/Policy overhead
*Handler: `language_chat`*
*Response: `_ChatResponse`*


`POST /lms/chat-with-tools` &mdash; direct access to tool-capable model inference without Execution/Policy overhead
*Handler: `language_chat_with_tools`*
*Response: `_ChatWithToolsResponse`*

------------------------------------------------------------------------
## `services/reason/commitment/api.py`
`POST /commitment/create` &mdash; create a commitment directly or persist a creation proposal
*Handler: `create_commitment`*


`POST /commitment/extract-candidates` &mdash; extract zero or more commitment candidate signals from arbitrary text
*Handler: `extract_commitment_candidates`*


`POST /commitment/get` &mdash; read one commitment by id
*Handler: `get_commitment`*


`POST /commitment/health` &mdash; return Commitment Service readiness status
*Handler: `health`*


`POST /commitment/history` &mdash; return one commitment plus its progress and transition history
*Handler: `get_history`*


`POST /commitment/list` &mdash; list commitments with optional state filter and cursor pagination
*Handler: `list_commitments`*


`POST /commitment/progress` &mdash; record one progress event for a commitment
*Handler: `record_progress`*


`POST /commitment/review-items` &mdash; list review items for one persisted review run
*Handler: `get_review_items`*


`POST /commitment/review-run` &mdash; read one persisted commitment review run by id
*Handler: `get_review_run`*


`POST /commitment/transition` &mdash; apply one commitment state transition or persist a transition proposal
*Handler: `transition_commitment`*


`POST /commitment/update` &mdash; update one commitment without changing lifecycle state
*Handler: `update_commitment`*

------------------------------------------------------------------------
## `services/reason/delegation/api.py`
`POST /delegation/cancel` &mdash; request cancellation of one queued or running subagent invocation
*Handler: `cancel`*
*Response: `_CancelResponse`*
*Summary: Request cancellation of a queued or running invocation.*


`POST /delegation/claim` &mdash; atomically claim the next queued subagent invocation for the Subagent Actor
*Handler: `claim`*
*Response: `_ClaimResponse`*
*Summary: Claim the oldest queued invocation for a Subagent Actor.*


`POST /delegation/finalize` &mdash; apply terminal status to one subagent invocation
*Handler: `finalize`*
*Response: `_ResultResponse`*
*Summary: Apply terminal status to one invocation row.*


`POST /delegation/invoke` &mdash; queue one delegated subagent invocation
*Handler: `invoke`*
*Response: `_StartedResponse`*
*Summary: Queue one delegated invocation and return its identifier.*


`POST /delegation/invoke-and-wait` &mdash; queue one delegated subagent invocation and block until terminal state
*Handler: `invoke_and_wait`*
*Response: `_ResultResponse`*
*Summary: Queue one delegated invocation and block until terminal state.*


`POST /delegation/record-turn` &mdash; increment per-turn counters and return whether to keep running
*Handler: `record_turn`*
*Response: `_TurnDecisionResponse`*
*Summary: Bump turn count and re-evaluate budget for one invocation.*


`POST /delegation/status` &mdash; return current status projection for one subagent invocation
*Handler: `get_status`*
*Response: `_StatusResponse`*
*Summary: Return the current status projection for one invocation.*


`POST /delegation/wait` &mdash; block until a previously queued subagent invocation reaches terminal state
*Handler: `wait`*
*Response: `_ResultResponse`*
*Summary: Block until a previously queued invocation reaches terminal state.*

------------------------------------------------------------------------
## `services/reason/ingestion/api.py`
`POST /ingestion/get` &mdash; read one ingestion record by id
*Handler: `get_ingestion`*


`POST /ingestion/health` &mdash; return Ingestion Service readiness status
*Handler: `health`*


`POST /ingestion/list` &mdash; list ingestions with optional status filter and cursor pagination
*Handler: `list_ingestions`*


`POST /ingestion/replay` &mdash; replay an ingestion from the named stage forward
*Handler: `replay_ingestion`*


`POST /ingestion/results` &mdash; return stage-ordered artifact outcomes for one ingestion
*Handler: `get_ingestion_results`*


`POST /ingestion/retry-stage` &mdash; retry one named stage for an existing ingestion
*Handler: `retry_ingestion_stage`*


`POST /ingestion/status` &mdash; return current status snapshot for one ingestion
*Handler: `get_ingestion_status`*


`POST /ingestion/submit` &mdash; validate and submit one ingestion attempt; runs store stage inline
*Handler: `submit_ingestion`*

------------------------------------------------------------------------
## `services/reason/job/api.py`
`POST /jobs/audits/list` &mdash; list audit entries for one job with cursor pagination
*Handler: `list_job_audits`*


`POST /jobs/cancel` &mdash; cancel a job and clear its next_run
*Handler: `cancel_job`*


`POST /jobs/create` &mdash; create a job intent, job record, and initial audit entry
*Handler: `create_job`*


`POST /jobs/executions/claim` &mdash; atomically claim the next queued execution for a Worker Actor
*Handler: `claim_next_execution`*


`POST /jobs/executions/complete` &mdash; report a successful execution result from a Worker Actor
*Handler: `complete_execution`*


`POST /jobs/executions/fail` &mdash; report a failed execution result from a Worker Actor
*Handler: `fail_execution`*


`POST /jobs/executions/get` &mdash; read one job execution by id
*Handler: `get_execution`*


`POST /jobs/executions/list` &mdash; list executions for one job with cursor pagination
*Handler: `list_executions`*


`POST /jobs/get` &mdash; read one job by id
*Handler: `get_job`*


`POST /jobs/health` &mdash; return Job Service and provider health state
*Handler: `health`*


`POST /jobs/list` &mdash; list jobs with optional filters and cursor pagination
*Handler: `list_jobs`*


`POST /jobs/pause` &mdash; transition a job from active to paused
*Handler: `pause_job`*


`POST /jobs/predicate-evaluations/list` &mdash; list predicate evaluation records for one job
*Handler: `list_predicate_evaluations`*


`POST /jobs/resume` &mdash; transition a job from paused to active and recompute next_run
*Handler: `resume_job`*


`POST /jobs/run-now` &mdash; immediately queue an execution for an active or paused job
*Handler: `run_job_now`*


`POST /jobs/update` &mdash; update mutable fields on an existing job
*Handler: `update_job`*

------------------------------------------------------------------------
## `services/reason/policy/api.py`
`POST /policy/approval_response` &mdash; record an operator approval or rejection for a pending Policy proposal
*Handler: `approval_response`*
*Response: `_ApprovalStatusResponse`*


`POST /policy/approval_status` &mdash; return current status for one Policy approval proposal
*Handler: `approval_status`*
*Response: `_ApprovalStatusResponse`*

------------------------------------------------------------------------
## `services/reason/recall/api.py`
`POST /memory/assemble_context` &mdash; assemble Recall context for one inbound turn
*Handler: `assemble_context`*
*Response: `_AssembleContextResponse`*
*Summary: Append one inbound message and return the assembled Recall context block.*


`POST /memory/assemble_snapshot` &mdash; return the stable historical Recall snapshot without the live inbound turn
*Handler: `assemble_snapshot`*
*Response: `_AssembleSnapshotResponse`*
*Summary: Return the historical Recall context snapshot without the live turn.*


`POST /memory/compact_dialogue` &mdash; force-summarize all visible turns and advance dialogue frontier
*Handler: `compact_dialogue`*
*Response: `_SessionResponse`*
*Summary: Force-summarize all visible turns and advance dialogue frontier.*


`POST /memory/create_session` &mdash; create one new Recall session for the Assistant
*Handler: `create_session`*
*Response: `_CreateSessionResponse`*
*Summary: Create one Recall session and return only the session identifier.*


`POST /memory/get_latest_or_create_session` &mdash; return the latest Recall session id or create one for the Assistant
*Handler: `get_latest_or_create_session`*
*Response: `_CreateSessionResponse`*
*Summary: Return the latest Recall session id or create one when none exist.*


`POST /memory/record_inbound_turn` &mdash; persist one inbound Recall turn before prompt assembly
*Handler: `record_inbound_turn`*
*Response: `_TurnResponse`*
*Summary: Persist one inbound turn and return the authoritative turn record.*


`POST /memory/record_outbound_candidate` &mdash; persist one outbound Recall candidate turn before delivery
*Handler: `record_outbound_candidate`*
*Response: `_TurnResponse`*
*Summary: Persist one outbound candidate turn and return the authoritative row.*


`POST /memory/record_outbound_delivery` &mdash; persist the final delivery state for one outbound Recall turn
*Handler: `record_outbound_delivery`*
*Response: `_BoolResponse`*
*Summary: Persist one outbound delivery result.*


`POST /memory/record_response` &mdash; persist one outbound Recall response turn
*Handler: `record_response`*
*Response: `_BoolResponse`*
*Summary: Append one outbound response turn with response metadata.*


------------------------------------------------------------------------
_End of HTTP API_
