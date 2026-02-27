# CLI Actor
L2 Actor that exposes Brain Core gRPC operations as a Typer command-line interface.

------------------------------------------------------------------------
## What This Component Is
`actors/cli/main.py` is the Phase-1 Brain CLI, implemented with Typer.

Core module roles:
- `main.py`: entrypoint, Typer app, all command definitions, and rendering helpers

Sub-command groups:
- `health core` — reports Brain Core readiness across services and resources
- `lms chat` — submits a prompt to the Language Model Service
- `vault get` — retrieves a single vault file by path
- `vault list` — lists entries under a vault directory path
- `vault search` — searches vault entries by query string

Global options (`--grpc-target`, `--timeout`, `--principal`, `--source`,
`--json`, `--trace-id`, `--parent-id`) are parsed by the `main()` callback and
stored in a `CliConfig` dataclass on the Typer context object.

------------------------------------------------------------------------
## Boundary and Ownership
CLI Actor is a Layer 2 Actor. It owns no _Resource_ or _Service_ components.

Boundary rules:
- All Brain Core access is through `BrainSdkClient` (`packages/brain_sdk`).
- No direct gRPC calls or database access.
- The external boundary is stdin/stdout/stderr and process exit codes.

------------------------------------------------------------------------
## Interactions
Primary interactions:
- `BrainSdkClient` is constructed per command with envelope metadata
  (`principal`, `source`, `trace_id`, `parent_id`) forwarded on each SDK call.
- `packages/brain_sdk` exports `core_health`, `lms_chat`, `vault_get`,
  `vault_list`, `vault_search`, `DomainError`, `TransportError`.
- `packages/brain_sdk/config.py` provides `resolve_target` and
  `resolve_timeout_seconds` for default option resolution.

------------------------------------------------------------------------
## Operational Flow (High Level)
1. User invokes `brain [global opts] <domain> <action> [args]`.
2. `main()` callback populates a `CliConfig` and stores it on `ctx.obj`.
3. Domain/action command calls `_run_command(cfg, invoke)`.
4. `_run_command` opens a `BrainSdkClient` context, calls the SDK function via
   `invoke`, then calls `_emit_output` on the result.
5. `_emit_output` delegates to `_render_human` for recognized shapes or falls
   back to compact JSON; `--json` bypasses human rendering.
6. Errors from the SDK are caught and mapped: `DomainError` → exit 3,
   `TransportError` → exit 4, each with a message written to stderr.

------------------------------------------------------------------------
## Failure Modes and Error Semantics
- `DomainError` raised by SDK → exit code 3, message written to stderr.
- `TransportError` raised by SDK → exit code 4, message written to stderr.
- Typer validation/usage errors → exit code 2 (Typer default behavior).
- No retry logic; errors surface immediately.
- `--json` flag wraps error messages in `{"error": "..."}` JSON on stderr.

------------------------------------------------------------------------
## Configuration Surface
Global CLI options and their environment variable equivalents:

| Option | Env var | Default |
|--------|---------|---------|
| `--grpc-target` | `BRAIN_GRPC_TARGET` | `127.0.0.1:50051` |
| `--timeout` | `BRAIN_GRPC_TIMEOUT_SECONDS` | `10.0` |
| `--principal` | — | `operator` |
| `--source` | — | `cli` |
| `--json` | — | off |
| `--trace-id` | — | none |
| `--parent-id` | — | none |

See `packages/brain_sdk/config.py` for resolution logic and
`docs/configuration.md` for global environment override rules.

------------------------------------------------------------------------
## Testing and Validation
Component tests live in `actors/cli/tests/test_main.py`.

Test approach: a fake `packages.brain_sdk` module is injected via
`monkeypatch` and `importlib.reload` so no live gRPC connection is required.
Pure rendering-helper tests call `_serialize`, `_render_human`, and
`_render_*` helpers directly without invoking the CLI runner.

Project-wide validation command:
```bash
make test
```

------------------------------------------------------------------------
## Contributor Notes
- Keep all Brain Core access through `brain_sdk`; do not call gRPC directly.
- Keep rendering logic in `_render_human`, `_looks_like_*`, and `_render_*`
  helpers; do not inline rendering in command callbacks.
- Use `_run_command` for all SDK call dispatch; do not open `BrainSdkClient`
  outside of it.
- Add tests for any new commands: at minimum one CliRunner test verifying
  argument forwarding and one rendering-helper unit test.

------------------------------------------------------------------------
_End of CLI Actor README_
