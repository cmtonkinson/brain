# Signal Adapter
Action _Adapter_ _Resource_ that integrates Signal messaging through `signal-cli-rest-api` for the Switchboard _Service_.

------------------------------------------------------------------------
## What This Component Is
`resources/adapters/signal/` provides the concrete Layer 0 Signal integration:
- `component.py`: `ResourceManifest` registration (`adapter_signal`)
- `adapter.py`: adapter protocol, DTOs, and exception taxonomy
- `signal_adapter.py`: HTTP transport implementation (`HttpSignalAdapter`)
- `config.py`: settings model and resolver for adapter runtime settings

------------------------------------------------------------------------
## Boundary and Ownership
This _Resource_ is owned by `service_switchboard` via `owner_service_id` in
`resources/adapters/signal/component.py`.

Boundary rules:
- Adapter owns Signal HTTP endpoint mapping and transport error classification.
- Adapter does not own cross-channel event normalization.
- Adapter does not perform dedupe.

------------------------------------------------------------------------
## Adapter Contract
This adapter exposes:
- `register_webhook(callback_url, shared_secret, operator_e164) -> SignalWebhookRegistrationResult`
- `health() -> SignalAdapterHealthResult`

Current HTTP mappings:
- `GET /v1/receive/{operator_e164}` for inbound polling
- `GET /health` for runtime health checks
- `POST <callback_url>` to forward signed webhook payloads to Switchboard

Inbound flow:
1. Switchboard registers callback URL + secret + operator identity.
2. Adapter polls Signal runtime `/v1/receive/{operator_e164}`.
3. Adapter signs each forwarded body and POSTs to Switchboard callback.
4. Switchboard verifies signature and applies ingress policy/normalization.

Webhook signature verification remains owned by Switchboard.

------------------------------------------------------------------------
## Configuration Surface
Adapter settings are sourced from `components.adapter_signal`:
- `base_url`
- `timeout_seconds`
- `max_retries`

## Deployment Wiring
Signal runtime is wired through the repository root `docker-compose.yaml` with
the `signal-api` service (`bbernhard/signal-cli-rest-api`) and defaults in
`.env.sample`.

Compose/runtime defaults:
- `SIGNAL_CLI_REST_API_IMAGE=bbernhard/signal-cli-rest-api:latest`
- `SIGNAL_CLI_REST_API_MODE=native`
- `SIGNAL_CLI_REST_API_PORT=8080`
- `SIGNAL_CLI_CONFIG_DIR=./data/signal-cli`

Persistent Signal account state is mounted at:
- host: `./data/signal-cli`
- container: `/home/.local/share/signal-cli`

If you are bringing forward an existing signal-cli state dir, copy it into
`./data/signal-cli` before starting Compose.

Example:
```bash
mkdir -p ./data/signal-cli
cp -R /path/to/existing/signal-cli/. ./data/signal-cli/
```

Do not move the original directory until webhook delivery and account state are
verified in the new deployment.

This deployment path does not use anything under `deprecated/`; that directory
remains human reference only.

------------------------------------------------------------------------
## Testing and Validation
Switchboard behavior tests exercise Signal adapter integration boundaries:
- `services/action/switchboard/tests/test_switchboard_service.py`
- `services/action/switchboard/tests/test_switchboard_api.py`

Project-wide validation command:
```bash
make test
```

------------------------------------------------------------------------
_End of Signal Adapter README_
