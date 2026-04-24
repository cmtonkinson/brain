# Brain Subagent
A long-running T3 actor that drains the Delegation Service's queued invocation
queue and runs the headless agent loop (`lib/agent`) for each one.
------------------------------------------------------------------------
## Lifecycle
1. Poll `delegation-claim` (via SDK `client.delegation_claim_invocation`).
2. If no work, sleep `subagent.poll_interval_seconds`; otherwise dispatch to a
   thread pool worker.
3. Each worker thread:
   - Renders system prompt blocks for the requested `personality_id`.
   - Resolves any `context_object_refs` via `object-get-text` ops.
   - Runs `lib.agent.run(...)` with cooperative cancel hooks wired to
     `delegation-status` (turn-start) and `delegation-record-turn` (post-Language).
   - Finalizes the row via `delegation-finalize` with `succeeded`, `failed`, or
     `canceled`.
------------------------------------------------------------------------
## Threading
Mirrors the Worker pattern:

- Single poll thread (the main loop).
- Thread pool size = `subagent.max_workers` (default `1`).
- Per-thread `BrainClient` via `threading.local`.
- Backpressure on saturation: 0.25s wait until a slot frees.
- Signal-driven shutdown (`SIGINT`/`SIGTERM`), waits for in-flight work.
------------------------------------------------------------------------
## Configuration
Settings live under `actors.subagent` in `actors.yaml`:

| Key | Default |
|---|---|
| `source` | `subagent` |
| `principal` | `subagent` |
| `channel` | `subagent` |
| `max_workers` | `1` |
| `poll_interval_seconds` | `2.0` |
| `default_personality` | `subagent` |
| `default_max_turns` | `8` |
| `default_budget_tokens` | `200000` |

Environment overrides use the standard `BRAIN_SUBAGENT__*` shape.
------------------------------------------------------------------------
## Heartbeat
Touches `BRAIN_SUBAGENT_HEARTBEAT_FILE` (default `/run/brain/subassistant-heartbeat`)
once per poll iteration. The container healthcheck script
(`scripts/healthcheck-subagent.sh`) compares its mtime against
`BRAIN_SUBAGENT_HEARTBEAT_MAX_AGE_SECONDS` (default `90`).
------------------------------------------------------------------------
## Cancellation
The actor's loop is cooperatively cancelable. Two checkpoints fire per turn:

- **Turn-start**: `client.delegation_status(...)` returns `canceling` → the
  loop raises `CancellationError`.
- **Post-Language**: `client.delegation_record_turn(...)` returns
  `should_stop=True` (e.g. budget breach) → same.

In both cases the actor finalizes the invocation with status `canceled` and
the original `cancel_reason`.


------------------------------------------------------------------------
_End of Brain Subagent README_
