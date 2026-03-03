# HTTP API
_This document is generated from `packages/brain_core/health_api.py` and `services/*/*/api.py`, with route intent from `docs/meta/http-routes.yaml`. Do not edit by hand._

------------------------------------------------------------------------
## `packages/brain_core/health_api.py`
`GET /health` &mdash; full-system diagnostic health check  
_Handler: `health`_
_Response: `_HealthResponse`_

------------------------------------------------------------------------
## `services/action/capability_engine/api.py`
`POST /capabilities/describe` &mdash; enumerate all active Capabilities  
_Handler: `describe_capabilities`_
_Response: `_DescribeResponse`_


`POST /capabilities/invoke` &mdash; execute tool calls  
_Handler: `invoke_capability`_
_Response: `_InvokeResponse`_

------------------------------------------------------------------------
## `services/action/language_model/api.py`
`POST /lms/chat` &mdash; direct access to model inference without CES/PS overhead  
_Handler: `lms_chat`_
_Response: `_ChatResponse`_

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


`POST /memory/record_response` &mdash; persist one outbound MAS response turn  
_Handler: `record_response`_
_Response: `_RecordResponseResponse`_
_Summary: Append one outbound response turn with response metadata._


------------------------------------------------------------------------
_End of HTTP API_
