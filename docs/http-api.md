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
_End of HTTP API_
