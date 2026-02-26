# Signal Adapter
Action _Adapter_ _Resource_ that integrates `signal-cli-rest-api` for Switchboard inbound message intake.

------------------------------------------------------------------------
## What This Component Is
`resources/adapters/signal/` implements Layer 0 Signal integration:
- `component.py`: `ResourceManifest` registration (`adapter_signal`)
- `adapter.py`: protocol, DTOs, and adapter error taxonomy
- `signal_adapter.py`: concrete HTTP polling + callback forwarding implementation (`HttpSignalAdapter`)
- `config.py`: adapter settings model and resolver
- `boot.py`: readiness hook that probes Signal container `/health`

------------------------------------------------------------------------
## Boundary and Ownership
This _Resource_ is shared infrastructure (`owner_service_id=None`) in
`resources/adapters/signal/component.py`.

Boundary rules:
- Adapter owns Signal transport mapping and retry/backoff behavior.
- Adapter does not apply Switchboard ingress policy decisions.
- Adapter does not normalize event payloads into Switchboard domain models.
- Adapter does not perform dedupe logic.

------------------------------------------------------------------------
## Interactions
Primary interactions:
- Receives registration input from Switchboard:
  - callback URL
  - shared secret
  - receive identity (from adapter config)
- Polls Signal runtime:
  - `GET /health`
  - `GET /v1/receive/{receive_e164}`
- Forwards each received message as signed JSON callback POST to Switchboard webhook endpoint.
- Sends outbound messages for Attention Router over `POST /v2/send`.

------------------------------------------------------------------------
## Operational Flow (High Level)
1. Switchboard calls `register_webhook(callback_url, shared_secret)`.
2. Adapter stores registration in memory and ensures polling worker is running.
3. Worker polls Signal runtime receive endpoint for inbound messages.
4. Adapter wraps each received item as `{"data": <message>}`.
5. Adapter computes HMAC SHA-256 signature over `<timestamp>.<raw_body_json>`.
6. Adapter POSTs signed payload to configured Switchboard callback with:
   - `X-Brain-Timestamp`
   - `X-Brain-Signature` (`sha256=<digest>`)
7. On forwarding/poll dependency failure, adapter retains pending messages and retries using exponential backoff with jitter.

------------------------------------------------------------------------
## Failure Modes and Error Semantics
Adapter-level failure classes:
- `SignalAdapterDependencyError`: upstream transport unavailable, non-2xx status, callback delivery failure.
- `SignalAdapterInternalError`: contract mismatch or invalid adapter-side state.

Behavioral semantics:
- Registration input validation failures raise internal adapter errors.
- Polling receive failures trigger retry + capped backoff.
- Callback delivery failures keep unsent payloads in pending in-memory queue for retry.
- Health reports Signal runtime readiness and callback/worker status detail.

------------------------------------------------------------------------
## Configuration Surface
Adapter settings are sourced from `components.adapter.signal`:
- `base_url`
- `receive_e164`
- `timeout_seconds`
- `max_retries`
- `poll_interval_seconds`
- `poll_receive_timeout_seconds`
- `poll_max_messages`
- `failure_backoff_initial_seconds`
- `failure_backoff_max_seconds`
- `failure_backoff_multiplier`
- `failure_backoff_jitter_ratio`

Defaults and validation live in `resources/adapters/signal/config.py`.

Deployment wiring:
- Signal container is `signal-api` in repository root `docker-compose.yaml`.
- Persistent Signal state directory mount defaults to:
  - host: `./data/signal-cli`
  - container: `/home/.local/share/signal-cli`

------------------------------------------------------------------------
## Testing and Validation
Primary tests:
- `resources/adapters/signal/tests/test_signal_adapter.py`

Cross-component boundary tests:
- `services/action/switchboard/tests/test_switchboard_service.py`
- `services/action/switchboard/tests/test_switchboard_http_ingress.py`
- `services/action/switchboard/tests/test_switchboard_boot.py`

Project-wide validation:
```bash
make test
```

------------------------------------------------------------------------
## Contributor Notes
- Keep adapter contract transport-focused and implementation-agnostic.
- Keep Switchboard policy/normalization logic out of adapter internals.
- Preserve in-memory callback registration behavior unless requirements change.
- Avoid adding gRPC surface for adapter-specific control methods.

------------------------------------------------------------------------
_End of Signal Adapter README_
