# Brain Worker
The Brain Worker is a T3 actor process that claims queued job executions
from the Job Service and runs them by invoking ops through the
Brain SDK.

------------------------------------------------------------------------
## Execution Model
The worker runs a single-threaded poll loop that dispatches work to a
bounded `ThreadPoolExecutor`. Each loop iteration:
1. Writes a liveness heartbeat file.
2. Reaps completed futures, logging any uncaught thread exceptions.
3. Back-pressures when the pool is saturated (all `max_workers` slots
   occupied) by sleeping `_SATURATION_BACKOFF_SECONDS` before retrying.
4. Calls `job_claim_execution` on the main thread to atomically claim the
   next queued execution. Returns `None` when the queue is empty, causing
   the loop to sleep `poll_interval_seconds` before polling again.
5. Submits the claimed execution to the pool via `_dispatch`.

Each pool thread owns a dedicated `BrainClient` instance stored in
thread-local storage (`_thread_local`). Clients are created on first use
and reused for all subsequent executions on the same thread, avoiding
per-execution HTTP connection overhead.

------------------------------------------------------------------------
## Per-Execution Flow
For each claimed execution, `_run_execution` is called with the
per-thread client and the `JobClaimResult`:

1. `client.invoke_op` — runs the op identified in the
   claim using the input payload, actor, and trace context from the job.
2. On success: `client.job_complete_execution` — marks the execution done.
3. On failure: `_safe_fail` calls `client.job_fail_execution` with the
   error message and a `is_retryable` flag derived from the error type:

| Error type | `is_retryable` |
|---|---|
| `BrainDependencyError` | `True` |
| `BrainDomainError` | `False` |
| `BrainTransportError` | Mirrors `exc.retryable` |
| Any other `Exception` | `False` |

`_safe_fail` swallows any secondary error that occurs while reporting
the failure, logging it but never raising to the pool thread.

------------------------------------------------------------------------
## Heartbeat
The worker writes a heartbeat file on every poll iteration so that an
external health monitor (e.g. Docker `HEALTHCHECK`) can detect a stalled
process. The heartbeat path resolves as:

1. `BRAIN_WORKER_HEARTBEAT_FILE` env var, if non-blank.
2. `/run/brain/worker-heartbeat` (default).

Parent directories are created automatically on first write.

------------------------------------------------------------------------
## Shutdown
`SIGINT` and `SIGTERM` both set `_RUNNING = False` and wake the
`_SHUTDOWN_EVENT`. The poll loop exits after the current iteration. The
`ThreadPoolExecutor` context manager then blocks until all in-flight
executions complete before the process exits.

------------------------------------------------------------------------
## Configuration
All settings are loaded by `load_actor_settings()` from the shared
config layer. Worker-specific keys live under the `worker` section.

| Setting | Description |
|---|---|
| `worker.max_workers` | Maximum concurrent executions (pool size) |
| `worker.poll_interval_seconds` | Sleep duration when queue is empty |
| `worker.channel` | Channel field stamped on `invoke_op` calls |
| `worker.source` | SDK envelope `source` field (worker identity) |
| `core.host` | Brain Core HTTP host |
| `core.port` | Brain Core HTTP port |
| `core.timeout_seconds` | SDK request timeout |

------------------------------------------------------------------------
## Boundary and Ownership
Worker Actor is a Tier 3 Actor. It owns no Service or Resource
components.

Boundary rules:
* All Brain Core access is through `BrainClient` (`lib/sdk`).
* No direct HTTP calls or database access.
* The external boundary is the Job Service queue and the heartbeat file.

------------------------------------------------------------------------
## Testing
Tests live in `actors/worker/tests/test_main.py`.

Test approach: `_run_execution` and `_safe_fail` accept an injected
`BrainClient` so tests replace it with a lightweight fake (`_FakeClient`)
that records calls and can raise configured errors. No live Core
connection is required.

Coverage:
* Success path: `invoke_op` then `job_complete_execution` called.
* All four failure categories with correct `is_retryable` mapping.
* `_safe_fail` swallowing secondary errors from `job_fail_execution`.
* `_resolve_heartbeat_path` env var resolution (default, override, blank).
* `_write_heartbeat` creating nested directories and touching the file.

Run the worker tests:
```bash
pytest actors/worker/tests/
```


------------------------------------------------------------------------
_End of Brain Worker README_
