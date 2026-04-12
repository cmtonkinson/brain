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
