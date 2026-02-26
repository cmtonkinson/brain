# Switchboard Service
Action _Service_ that owns inbound external event intake and durable buffering for downstream processing.

------------------------------------------------------------------------
## What This Component Is
`services/action/switchboard/` implements the Layer 1 Switchboard _Service_:
- `component.py`: `ServiceManifest` registration (`service_switchboard`)
- `service.py`: canonical _Public API_ contract
- `implementation.py`: concrete business logic (`DefaultSwitchboardService`)
- `http_ingress.py`: HTTP webhook ingress server for inbound Signal callbacks
- `boot.py`: boot hook that starts ingress server and registers callback with `adapter_signal`
- `api.py`: gRPC transport adapter exposing only published SDK surface

------------------------------------------------------------------------
## Boundary and Ownership
Switchboard owns inbound Signal intake policy and registration flow. The Signal
adapter itself is shared infrastructure used by both Switchboard (inbound) and
Attention Router (outbound).

Boundary rules:
- Inbound Signal payloads enter through Switchboard, not directly into other _Services_.
- Switchboard verifies webhook authenticity and applies ingress acceptance rules.
- Accepted inbound events are durably buffered via CAS queue writes.
- Other _Services_ must consume Switchboard output through formal _Public APIs_ and queue semantics, not by importing internals.

------------------------------------------------------------------------
## Interactions
Primary interactions:
- Calls `resources/adapters/signal/` through `SignalAdapter` protocol for inbound registration.
- Calls `services/state/cache_authority/service.py` _Public API_ to persist inbound queue entries.
- Exposes health over gRPC (`api.py`) for L2 clients.
- Exposes internal-only webhook registration and webhook ingest methods via `service.py` (not published on gRPC SDK).

------------------------------------------------------------------------
## Operational Flow (High Level)
1. Core boot invokes `services/action/switchboard/boot.py`.
2. Boot starts `SwitchboardWebhookHttpServer` on configured bind host/port/path.
3. Boot computes callback URL from `webhook_public_base_url + webhook_path`.
4. Boot calls `register_signal_webhook(...)` on Switchboard.
5. Switchboard delegates registration to `adapter_signal` with callback URL, shared secret, and operator identity.
6. Signal adapter polls Signal runtime receive endpoint and forwards signed callback POSTs to Switchboard ingress.
7. Switchboard verifies timestamp/signature, normalizes payload, applies sender policy, then enqueues accepted events to CAS.

------------------------------------------------------------------------
## Failure Modes and Error Semantics
Public API error behavior:
- Validation failures return structured validation errors.
- Signature mismatch or stale timestamp returns policy errors.
- Adapter/CAS outages return dependency errors.
- Unexpected internal faults return internal errors.

Webhook ingress HTTP mapping (`http_ingress.py`):
- `400` for malformed body/missing headers/validation issues
- `403` for policy failures
- `503` for dependency failures
- `500` for internal failures
- `202` for accepted and queued inbound message
- `200` for syntactically valid but intentionally ignored payload (for example, non-message payload or non-operator sender)

------------------------------------------------------------------------
## Configuration Surface
Switchboard settings are sourced from:
- `components.service.switchboard` (service runtime)
- `profile.operator.signal_contact_e164` (operator identity)
- `profile.default_dial_code` (normalization fallback dial code, for example `+1`)
- `profile.webhook_shared_secret` (HMAC verification and registration secret)

`components.service.switchboard` keys:
- `queue_name`
- `signature_tolerance_seconds`
- `webhook_bind_host`
- `webhook_bind_port`
- `webhook_path`
- `webhook_public_base_url`
- `webhook_register_max_retries`
- `webhook_register_retry_delay_seconds`

Defaults and validation live in `services/action/switchboard/config.py`.

------------------------------------------------------------------------
## Testing and Validation
Primary tests:
- `services/action/switchboard/tests/test_switchboard_service.py`
- `services/action/switchboard/tests/test_switchboard_http_ingress.py`
- `services/action/switchboard/tests/test_switchboard_boot.py`
- `services/action/switchboard/tests/test_switchboard_api.py`
- `services/action/switchboard/tests/test_switchboard_config.py`

Project-wide validation:
```bash
make test
```

------------------------------------------------------------------------
## Contributor Notes
- Keep `service.py` as the canonical in-process contract.
- Do not publish internal-only methods to gRPC unless L2 access is explicitly required.
- Keep Signal-specific transport details in `adapter_signal`; Switchboard owns ingress policy and normalization.
- Maintain `public_api_instrumented(...)` decoration on all _Public API_ methods.

------------------------------------------------------------------------
_End of Switchboard Service README_
