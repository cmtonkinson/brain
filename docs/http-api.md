# HTTP API
_This document is generated from `lib/core/health_api.py` and `services/*/*/api.py`, with route intent from `docs/meta/http-routes.yaml`. Do not edit by hand._

------------------------------------------------------------------------
## `lib/core/health_api.py`
`GET /health` &mdash; full-system diagnostic health check  
_Handler: `health`_
_Response: `CoreHealthResult`_

------------------------------------------------------------------------
## `services/effect/execution/api.py`
`POST /ops/always-on` &mdash; return full descriptors for the configured always-on ops  
_Handler: `list_always_on_ops`_
_Response: `_DescribeResponse`_


`POST /ops/describe` &mdash; enumerate all active ops  
_Handler: `describe_ops`_
_Response: `_DescribeResponse`_


`POST /ops/describe-one` &mdash; return one full Op descriptor by op_id  
_Handler: `describe_op`_
_Response: `_DescribeOneResponse`_


`POST /ops/dynamic/classifications` &mdash; list observed dynamic ops and persisted classifications  
_Handler: `list_dynamic_op_classifications`_
_Response: `_DynamicOpClassificationListResponse`_


`POST /ops/dynamic/classify` &mdash; persist one operator-supplied dynamic op classification  
_Handler: `classify_dynamic_op`_
_Response: `_DynamicOpClassificationListResponse`_


`POST /ops/invoke` &mdash; execute tool calls  
_Handler: `invoke_op`_
_Response: `_InvokeResponse`_


`POST /ops/search` &mdash; semantically search the enabled Op catalog and return compact matches  
_Handler: `search_ops`_
_Response: `_SearchResponse`_


`POST /ops/slash-lookup` &mdash; resolve one op descriptor by slash command name or alias  
_Handler: `slash_lookup`_
_Response: `_SlashLookupResponse`_


`POST /ops/tool-system-hints` &mdash; return compact orientation hints for systems reachable through tools  
_Handler: `list_tool_system_hints`_
_Response: `_ToolSystemHintsResponse`_

------------------------------------------------------------------------
## `services/effect/language/api.py`
`POST /lms/chat` &mdash; direct access to model inference without Execution/Policy overhead  
_Handler: `language_chat`_
_Response: `_ChatResponse`_


`POST /lms/chat-with-tools` &mdash; direct access to tool-capable model inference without Execution/Policy overhead  
_Handler: `language_chat_with_tools`_
_Response: `_ChatWithToolsResponse`_

------------------------------------------------------------------------
## `services/reason/commitment/api.py`
`POST /commitment/create` &mdash; create a commitment directly or persist a creation proposal  
_Handler: `create_commitment`_


`POST /commitment/extract-candidates` &mdash; extract zero or more commitment candidate signals from arbitrary text  
_Handler: `extract_commitment_candidates`_


`POST /commitment/get` &mdash; read one commitment by id  
_Handler: `get_commitment`_


`POST /commitment/health` &mdash; return Commitment Service readiness status  
_Handler: `health`_


`POST /commitment/history` &mdash; return one commitment plus its progress and transition history  
_Handler: `get_history`_


`POST /commitment/list` &mdash; list commitments with optional state filter and cursor pagination  
_Handler: `list_commitments`_


`POST /commitment/progress` &mdash; record one progress event for a commitment  
_Handler: `record_progress`_


`POST /commitment/review-items` &mdash; list review items for one persisted review run  
_Handler: `get_review_items`_


`POST /commitment/review-run` &mdash; read one persisted commitment review run by id  
_Handler: `get_review_run`_


`POST /commitment/transition` &mdash; apply one commitment state transition or persist a transition proposal  
_Handler: `transition_commitment`_


`POST /commitment/update` &mdash; update one commitment without changing lifecycle state  
_Handler: `update_commitment`_

------------------------------------------------------------------------
## `services/reason/delegation/api.py`
`POST /delegation/cancel` &mdash; request cancellation of one queued or running subagent invocation  
_Handler: `cancel`_
_Response: `_CancelResponse`_
_Summary: Request cancellation of a queued or running invocation._


`POST /delegation/claim` &mdash; atomically claim the next queued subagent invocation for the Subagent Actor  
_Handler: `claim`_
_Response: `_ClaimResponse`_
_Summary: Claim the oldest queued invocation for a Subagent Actor._


`POST /delegation/finalize` &mdash; apply terminal status to one subagent invocation  
_Handler: `finalize`_
_Response: `_ResultResponse`_
_Summary: Apply terminal status to one invocation row._


`POST /delegation/invoke` &mdash; queue one delegated subagent invocation  
_Handler: `invoke`_
_Response: `_StartedResponse`_
_Summary: Queue one delegated invocation and return its identifier._


`POST /delegation/invoke-and-wait` &mdash; queue one delegated subagent invocation and block until terminal state  
_Handler: `invoke_and_wait`_
_Response: `_ResultResponse`_
_Summary: Queue one delegated invocation and block until terminal state._


`POST /delegation/record-turn` &mdash; increment per-turn counters and return whether to keep running  
_Handler: `record_turn`_
_Response: `_TurnDecisionResponse`_
_Summary: Bump turn count and re-evaluate budget for one invocation._


`POST /delegation/status` &mdash; return current status projection for one subagent invocation  
_Handler: `get_status`_
_Response: `_StatusResponse`_
_Summary: Return the current status projection for one invocation._


`POST /delegation/wait` &mdash; block until a previously queued subagent invocation reaches terminal state  
_Handler: `wait`_
_Response: `_ResultResponse`_
_Summary: Block until a previously queued invocation reaches terminal state._

------------------------------------------------------------------------
## `services/reason/ingestion/api.py`
`POST /ingestion/get` &mdash; read one ingestion record by id  
_Handler: `get_ingestion`_


`POST /ingestion/health` &mdash; return Ingestion Service readiness status  
_Handler: `health`_


`POST /ingestion/list` &mdash; list ingestions with optional status filter and cursor pagination  
_Handler: `list_ingestions`_


`POST /ingestion/replay` &mdash; replay an ingestion from the named stage forward  
_Handler: `replay_ingestion`_


`POST /ingestion/results` &mdash; return stage-ordered artifact outcomes for one ingestion  
_Handler: `get_ingestion_results`_


`POST /ingestion/retry-stage` &mdash; retry one named stage for an existing ingestion  
_Handler: `retry_ingestion_stage`_


`POST /ingestion/status` &mdash; return current status snapshot for one ingestion  
_Handler: `get_ingestion_status`_


`POST /ingestion/submit` &mdash; validate and submit one ingestion attempt; runs store stage inline  
_Handler: `submit_ingestion`_

------------------------------------------------------------------------
## `services/reason/job/api.py`
`POST /jobs/audits/list` &mdash; list audit entries for one job with cursor pagination  
_Handler: `list_job_audits`_


`POST /jobs/cancel` &mdash; cancel a job and clear its next_run  
_Handler: `cancel_job`_


`POST /jobs/create` &mdash; create a job intent, job record, and initial audit entry  
_Handler: `create_job`_


`POST /jobs/executions/claim` &mdash; atomically claim the next queued execution for a Worker Actor  
_Handler: `claim_next_execution`_


`POST /jobs/executions/complete` &mdash; report a successful execution result from a Worker Actor  
_Handler: `complete_execution`_


`POST /jobs/executions/fail` &mdash; report a failed execution result from a Worker Actor  
_Handler: `fail_execution`_


`POST /jobs/executions/get` &mdash; read one job execution by id  
_Handler: `get_execution`_


`POST /jobs/executions/list` &mdash; list executions for one job with cursor pagination  
_Handler: `list_executions`_


`POST /jobs/get` &mdash; read one job by id  
_Handler: `get_job`_


`POST /jobs/health` &mdash; return Job Service and provider health state  
_Handler: `health`_


`POST /jobs/list` &mdash; list jobs with optional filters and cursor pagination  
_Handler: `list_jobs`_


`POST /jobs/pause` &mdash; transition a job from active to paused  
_Handler: `pause_job`_


`POST /jobs/predicate-evaluations/list` &mdash; list predicate evaluation records for one job  
_Handler: `list_predicate_evaluations`_


`POST /jobs/resume` &mdash; transition a job from paused to active and recompute next_run  
_Handler: `resume_job`_


`POST /jobs/run-now` &mdash; immediately queue an execution for an active or paused job  
_Handler: `run_job_now`_


`POST /jobs/update` &mdash; update mutable fields on an existing job  
_Handler: `update_job`_

------------------------------------------------------------------------
## `services/reason/recall/api.py`
`POST /memory/assemble_context` &mdash; assemble Recall context for one inbound turn  
_Handler: `assemble_context`_
_Response: `_AssembleContextResponse`_
_Summary: Append one inbound message and return the assembled Recall context block._


`POST /memory/assemble_snapshot` &mdash; return the stable historical Recall snapshot without the live inbound turn  
_Handler: `assemble_snapshot`_
_Response: `_AssembleSnapshotResponse`_
_Summary: Return the historical Recall context snapshot without the live turn._


`POST /memory/compact_dialogue` &mdash; force-summarize all visible turns and advance dialogue frontier  
_Handler: `compact_dialogue`_
_Response: `_SessionResponse`_
_Summary: Force-summarize all visible turns and advance dialogue frontier._


`POST /memory/create_session` &mdash; create one new Recall session for the Assistant  
_Handler: `create_session`_
_Response: `_CreateSessionResponse`_
_Summary: Create one Recall session and return only the session identifier._


`POST /memory/get_latest_or_create_session` &mdash; return the latest Recall session id or create one for the Assistant  
_Handler: `get_latest_or_create_session`_
_Response: `_CreateSessionResponse`_
_Summary: Return the latest Recall session id or create one when none exist._


`POST /memory/record_inbound_turn` &mdash; persist one inbound Recall turn before prompt assembly  
_Handler: `record_inbound_turn`_
_Response: `_TurnResponse`_
_Summary: Persist one inbound turn and return the authoritative turn record._


`POST /memory/record_outbound_candidate` &mdash; persist one outbound Recall candidate turn before delivery  
_Handler: `record_outbound_candidate`_
_Response: `_TurnResponse`_
_Summary: Persist one outbound candidate turn and return the authoritative row._


`POST /memory/record_outbound_delivery` &mdash; persist the final delivery state for one outbound Recall turn  
_Handler: `record_outbound_delivery`_
_Response: `_BoolResponse`_
_Summary: Persist one outbound delivery result._


`POST /memory/record_response` &mdash; persist one outbound Recall response turn  
_Handler: `record_response`_
_Response: `_BoolResponse`_
_Summary: Append one outbound response turn with response metadata._


------------------------------------------------------------------------
_End of HTTP API_
