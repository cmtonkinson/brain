# Signal Adapter
Action *Adapter* *Resource* that integrates `signal-cli-rest-api` for Relay inbound message intake.

------------------------------------------------------------------------
## What This Component Is
`resources/adapters/signal/` implements Tier 1 Signal integration:
* `component.py`: `ResourceManifest` registration (`adapter_signal`)
* `adapter.py`: protocol, DTOs, and adapter error taxonomy
* `signal_adapter.py`: concrete websocket receive + in-process callback forwarding implementation (`SignalRestApiAdapter`)
* `config.py`: adapter settings model and resolver
* `boot.py`: no-op readiness hook (adapter is always locally ready)

------------------------------------------------------------------------
## Boundary and Ownership
This *Resource* is shared infrastructure (`owner_service_id=None`) in
`resources/adapters/signal/component.py`.

Boundary rules:
* Adapter owns Signal transport mapping and retry/backoff behavior.
* Adapter does not apply Relay inbound ingress policy decisions.
* Adapter does not normalize event payloads into Relay inbound domain models.
* Adapter does not perform dedupe logic.

------------------------------------------------------------------------
## Interactions
Primary interactions:
* Receives registration input from Relay inbound:
  * in-process callback method
  * receive identity (from adapter config)
* Talks to Signal runtime:
  * WebSocket `/v1/receive/{receive_e164}`
* Forwards each received message as an in-process callback invocation to Relay inbound.
* Sends outbound messages for Relay outbound over `POST /v2/send`.

------------------------------------------------------------------------
## Operational Flow (High Level)
1. Relay inbound calls `register_callback(callback)`.
2. Adapter stores registration in memory and ensures receive worker is running.
3. Worker opens Signal runtime receive websocket for inbound messages.
4. Adapter wraps each received item as `{"data": <message>}`.
5. Adapter invokes the configured Relay inbound callback directly.
6. On forwarding/receive dependency failure, adapter retains pending payloads and retries using exponential backoff with jitter.

------------------------------------------------------------------------
## Failure Modes and Error Semantics
Adapter-level failure classes:
* `SignalAdapterDependencyError`: upstream transport unavailable or callback dependency failure.
* `SignalAdapterInternalError`: contract mismatch or invalid adapter-side state.

Behavioral semantics:
* Registration input validation failures raise internal adapter errors.
* Receive websocket failures trigger retry + capped backoff.
* Callback delivery failures keep unsent payloads in pending in-memory queue for retry.
* Health reports Signal runtime readiness and callback/worker status detail.

------------------------------------------------------------------------
## Configuration Surface
Adapter settings are sourced from ` signal`:
* `base_url`
* `receive_e164`
* `receive_connect_timeout_seconds`
* `receive_heartbeat_seconds`
* `send_timeout_seconds`
* `max_retries`
* `failure_backoff_initial_seconds`
* `failure_backoff_max_seconds`
* `failure_backoff_multiplier`
* `failure_backoff_jitter_ratio`

Defaults and validation live in `resources/adapters/signal/config.py`.

Deployment wiring:
* Signal container is `signal-api` in repository root `docker-compose.yaml`.
* Persistent Signal state directory mount defaults to:
  * host: `./data/signal-cli`
  * container: `/home/.local/share/signal-cli`

------------------------------------------------------------------------
## Testing and Validation
Primary tests:
* `resources/adapters/signal/tests/test_signal_adapter.py`

Cross-component boundary tests:
* `services/effect/relay/_inbound/tests/test_inbound_service.py`
* `services/effect/relay/_inbound/tests/test_inbound_boot.py`

Project-wide validation:
```bash
make test
```

------------------------------------------------------------------------
## Contributor Notes
* Keep adapter contract transport-focused and implementation-agnostic.
* Keep Relay inbound policy/normalization logic out of adapter internals.
* Preserve in-memory callback registration behavior unless requirements change.


------------------------------------------------------------------------
_End of Signal Adapter README_
