# Console Adapter
Action *Adapter* *Resource* that owns the inbound surface from the Console actor and forwards parsed payloads to Relay inbound.

------------------------------------------------------------------------
## What This Component Is
`resources/adapters/console/` implements Tier 1 Console integration:
* `component.py`: `ResourceManifest` registration (`adapter_console`)
* `adapter.py`: protocol, DTOs, and adapter error taxonomy
* `console_adapter.py`: concrete in-process forwarding implementation (`InProcessConsoleAdapter`)
* `config.py`: adapter settings model and resolver
* `boot.py`: no-op readiness hook

------------------------------------------------------------------------
## Boundary and Ownership
This *Resource* is shared infrastructure (`owner_service_id=None`) in
`resources/adapters/console/component.py`. The Relay Service owns the adapter via its `owns_resources` declaration.

Boundary rules:
* Adapter owns the Console-actor wire-format parse and the callback dispatch.
* Adapter does **not** hold the slash authenticity HMAC secret. The Console
  actor mints proofs on the host; the adapter forwards them as opaque data.
* Adapter does not apply Relay inbound ingress policy decisions.
* Adapter does not perform dedupe logic.

------------------------------------------------------------------------
## Interactions
Primary interactions:
* Receives registration input from Relay inbound:
  * in-process callback method
* Receives inbound calls from the HTTP route layer (`/relay/enqueue_console_message`):
  * already-parsed `ConsoleInboundPayload` (message text + optional slash authenticity proof)
* Forwards each submission as an in-process callback invocation to Relay inbound.

------------------------------------------------------------------------
## Operational Flow (High Level)
1. Relay inbound calls `register_callback(callback)` at boot.
2. The HTTP route handler receives one Console-actor request and parses it into a `ConsoleInboundPayload`.
3. Route handler calls `adapter.submit(meta, payload)`.
4. Adapter invokes the registered Relay inbound callback synchronously.
5. Adapter returns the callback's result (queued state + queue name) to the route handler.

------------------------------------------------------------------------
## Failure Modes and Error Semantics
Adapter-level failure classes:
* `ConsoleAdapterInternalError`: contract mismatch (e.g., submit before any callback was registered).

Behavioral semantics:
* No retry/backoff: Console-actor inbound is request-response; the operator's HTTP client owns retry on transport failure.
* Health reports adapter readiness and callback registration state.

------------------------------------------------------------------------
## Configuration Surface
Adapter settings are sourced from `console_adapter`. The model is currently empty; future transport tunables would live here.


------------------------------------------------------------------------
_End of Console Adapter README_
