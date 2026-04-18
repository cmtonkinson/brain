# HTTP API
_This document is generated from `packages/brain_core/health_api.py` and `services/*/*/api.py`, with route intent from `docs/meta/http-routes.yaml`. Do not edit by hand._

------------------------------------------------------------------------
## `packages/brain_core/health_api.py`
`GET /health` &mdash; full-system diagnostic health check  
_Handler: `health`_
_Response: `_HealthResponse`_

------------------------------------------------------------------------
## `services/action/capability_engine/api.py`
`POST /capabilities/always-on` &mdash; return full descriptors for the configured always-on capabilities  
_Handler: `list_always_on_capabilities`_
_Response: `_DescribeResponse`_


`POST /capabilities/describe` &mdash; enumerate all active Capabilities  
_Handler: `describe_capabilities`_
_Response: `_DescribeResponse`_


`POST /capabilities/describe-one` &mdash; return one full Capability descriptor by capability_id  
_Handler: `describe_capability`_
_Response: `_DescribeOneResponse`_


`POST /capabilities/invoke` &mdash; execute tool calls  
_Handler: `invoke_capability`_
_Response: `_InvokeResponse`_


`POST /capabilities/search` &mdash; semantically search the enabled Capability catalog and return compact matches  
_Handler: `search_capabilities`_
_Response: `_SearchResponse`_

------------------------------------------------------------------------
## `services/action/language_model/api.py`
`POST /lms/chat` &mdash; direct access to model inference without CES/PS overhead  
_Handler: `lms_chat`_
_Response: `_ChatResponse`_


`POST /lms/chat-with-tools` &mdash; direct access to tool-capable model inference without CES/PS overhead  
_Handler: `lms_chat_with_tools`_
_Response: `_ChatWithToolsResponse`_

------------------------------------------------------------------------
## `services/action/switchboard/api.py`
`POST /switchboard/poll_operator_instruction` &mdash; dequeue the next queued operator instruction for the agent  
_Handler: `poll_operator_instruction`_
_Response: `_PollOperatorInstructionResponse`_
_Summary: Pop the next queued operator instruction, optionally long-polling._

------------------------------------------------------------------------
## `services/control/ingestion/api.py`
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
## `services/control/job/api.py`
`POST /jobs/cancel` &mdash; cancel a job and clear its next_run  
_Handler: `cancel_job`_


`POST /jobs/create` &mdash; create a job intent, job record, and initial audit entry  
_Handler: `create_job`_


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


`POST /jobs/resume` &mdash; transition a job from paused to active and recompute next_run  
_Handler: `resume_job`_


`POST /jobs/run-now` &mdash; immediately queue an execution for an active or paused job  
_Handler: `run_job_now`_

------------------------------------------------------------------------
## `services/state/memory_authority/api.py`
`POST /memory/assemble_context` &mdash; assemble MAS context for one inbound turn  
_Handler: `assemble_context`_
_Response: `_AssembleContextResponse`_
_Summary: Append one inbound message and return the assembled MAS context block._


`POST /memory/assemble_snapshot` &mdash; return the stable historical MAS snapshot without the live inbound turn  
_Handler: `assemble_snapshot`_
_Response: `_AssembleContextResponse`_
_Summary: Return the historical MAS context snapshot without the live turn._


`POST /memory/create_session` &mdash; create one new MAS session for the agent  
_Handler: `create_session`_
_Response: `_CreateSessionResponse`_
_Summary: Create one MAS session and return only the session identifier._


`POST /memory/get_latest_or_create_session` &mdash; return the latest MAS session id or create one for the agent  
_Handler: `get_latest_or_create_session`_
_Response: `_CreateSessionResponse`_
_Summary: Return the latest MAS session id or create one when none exist._


`POST /memory/record_inbound_turn` &mdash; persist one inbound MAS turn before prompt assembly  
_Handler: `record_inbound_turn`_
_Response: `_TurnResponse`_
_Summary: Persist one inbound turn and return the authoritative turn record._


`POST /memory/record_outbound_candidate` &mdash; persist one outbound MAS candidate turn before delivery  
_Handler: `record_outbound_candidate`_
_Response: `_TurnResponse`_
_Summary: Persist one outbound candidate turn and return the authoritative row._


`POST /memory/record_outbound_delivery` &mdash; persist the final delivery state for one outbound MAS turn  
_Handler: `record_outbound_delivery`_
_Response: `_BoolResponse`_
_Summary: Persist one outbound delivery result._


`POST /memory/record_response` &mdash; persist one outbound MAS response turn  
_Handler: `record_response`_
_Response: `_BoolResponse`_
_Summary: Append one outbound response turn with response metadata._


------------------------------------------------------------------------
_End of HTTP API_
