# Signal Adapter
Action _Adapter_ _Resource_ that integrates Signal messaging through `signal-cli-rest-api` for the Switchboard _Service_.

------------------------------------------------------------------------
## What This Component Is
`resources/adapters/signal/` provides the concrete Layer 0 Signal integration:
- `component.py`: `ResourceManifest` registration (`adapter_signal`)
- `adapter.py`: adapter protocol, DTOs, and exception taxonomy
- `signal_adapter.py`: HTTP transport implementation (`SignalCliRestAdapter`)
- `config.py`: settings model and resolver for adapter + profile identity
- `validation.py`: webhook HMAC signing helpers

------------------------------------------------------------------------
## Boundary and Ownership
This _Resource_ is owned by `service_switchboard` via `owner_service_id` in
`resources/adapters/signal/component.py`.

Boundary rules:
- Adapter owns Signal HTTP endpoint mapping and transport error classification.
- Adapter does not own cross-channel event normalization.
- Adapter does not perform dedupe.

------------------------------------------------------------------------
## Inbound Contract
Inbound mode is webhook-only for v1 runtime behavior.

Switchboard registers callback settings through:
- `configure_inbound_webhook(callback_url, shared_secret) -> bool`

Default callback endpoint exposed by Switchboard:
- `POST /v1/inbound/signal/webhook`

Webhook signatures use:
- `X-Brain-Timestamp`
- `X-Brain-Signature: sha256=<hex(hmac_sha256(secret, timestamp + "." + raw_body))>`

------------------------------------------------------------------------
## Configuration Surface
Adapter settings are sourced from `components.adapter_signal`:
- `base_url`
- `timeout_seconds`
- `max_retries`

Top-level profile settings are projected into adapter runtime settings:
- `profile.operator.signal_e164`
- `profile.default_country_code`
- `profile.webhook_shared_secret`

------------------------------------------------------------------------
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
Component tests:
- `resources/adapters/signal/tests/test_signal_config.py`
- `resources/adapters/signal/tests/test_signal_adapter.py`

Project-wide validation command:
```bash
make test
```

------------------------------------------------------------------------
_End of Signal Adapter README_
