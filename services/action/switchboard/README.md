# Switchboard Service
Action _Service_ that owns inbound external event intake and durable buffering for downstream processing.

------------------------------------------------------------------------
## What This Component Is
`services/action/switchboard/` implements the Layer 1 Switchboard _Service_:
- `component.py`: `ServiceManifest` registration (`service_switchboard`)
- `service.py`: canonical _Public API_ contract
- `implementation.py`: concrete business logic (`DefaultSwitchboardService`)
- `api.py`: published Layer 2 HTTP routes
- `boot.py`: boot hook that registers an in-process inbound callback with `adapter_signal`

------------------------------------------------------------------------
## Boundary and Ownership
Switchboard owns inbound Signal intake policy and registration flow. The Signal
adapter itself is shared infrastructure used by both Switchboard (inbound) and
Attention Router (outbound).

Boundary rules:
- Inbound Signal payloads enter through Switchboard, not directly into other _Services_.
- Switchboard applies ingress acceptance rules and payload normalization.
- Accepted inbound events are durably buffered via CAS queue writes.
- Other _Services_ must consume Switchboard output through formal _Public APIs_ and queue semantics, not by importing internals.

------------------------------------------------------------------------
## Interactions
Primary interactions:
- Calls `resources/adapters/signal/` through `SignalAdapter` protocol for inbound registration.
- Calls `services/state/cache_authority/service.py` _Public API_ to persist inbound queue entries.
- Exposes internal-only callback registration and raw message ingest methods via `service.py`.

------------------------------------------------------------------------
## Operational Flow (High Level)
1. Core boot invokes `services/action/switchboard/boot.py`.
2. Boot calls `register_signal_callback(...)` on Switchboard.
3. Switchboard delegates registration to `adapter_signal` with an in-process callback method.
4. Signal adapter opens the Signal runtime receive websocket and forwards wrapped payloads in-process.
5. Switchboard normalizes payloads, applies sender policy, then enqueues accepted events to CAS.

------------------------------------------------------------------------
## Failure Modes and Error Semantics
Public API error behavior:
- Validation failures return structured validation errors.
- Adapter/CAS outages return dependency errors.
- Unexpected internal faults return internal errors.

------------------------------------------------------------------------
## Configuration Surface
Switchboard settings are sourced from:
- `components.service.switchboard` (service runtime)
- `profile.operator.signal_contact_e164` (operator identity)
- `profile.default_dial_code` (normalization fallback dial code, for example `+1`)

`components.service.switchboard` keys:
- `queue_name`
- `callback_register_max_retries`
- `callback_register_retry_delay_seconds`

Defaults and validation live in `services/action/switchboard/config.py`.

------------------------------------------------------------------------
## Testing and Validation
Primary tests:
- `services/action/switchboard/tests/test_switchboard_service.py`
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
- Do not publish internal-only methods to the SDK unless L2 access is explicitly required.
- Keep Signal-specific transport details in `adapter_signal`; Switchboard owns ingress policy and normalization.
- Maintain `public_api_instrumented(...)` decoration on all _Public API_ methods.


------------------------------------------------------------------------
_End of Switchboard Service README_
