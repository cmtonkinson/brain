<!--
Docblock:
- File: docs/scheduler-ops-runbook.md
- Purpose: Provide operational runbook for the Celery-based scheduler stack and its dependencies.
- Scope: Epic 10 ops and deployment validation / Milestone 05 hardening and validation.
-->
# Scheduler Ops Runbook

## Overview
- Scheduler responsibilities are described in `docs/prd-scheduled-timed-tasks.md`. The implementation adheres to
  the Celery + Redis decision recorded in `docs/scheduler-decision-record.md`.
- Brain ships two Scheduler containers (`celery-worker` and `celery-beat`) that execute scheduled tasks through
  `src/scheduler/celery_app.py`. These containers relay callbacks into the Brain domain via the Celery adapter
  (`src/scheduler/adapters/celery_adapter.py`) and respect attention routing, authorization context, and failure
  notification rules defined in `src/scheduler/execution_dispatcher.py` and `src/scheduler/failure_notifications.py`.
- This document covers prerequisites, configuration, startup/shutdown, health signals, troubleshooting, and rollback
  guardrails for the scheduler integration.

## Prerequisites
- Docker and Docker Compose configured per `README.md`.
- `~/.config/brain/brain.yml` (or `/config/brain.yml` in container) and `.env` populated before starting scheduler
  services.
- Postgres and Redis volumes (`./data/postgres`, `./data/redis`, `./data/scheduler`, `./data/signal`) available on host.
- Obsidian vault mounted read-only (`OBSIDIAN_VAULT_PATH`) so scheduled executions can read notes if needed.
- `signal-cli-rest-api`, LettA, and any external MCP services referenced by scheduled skills are reachable.

## Configuration Keys
### Environment variables (`.env` or runtime overrides)
- `POSTGRES_PASSWORD`: matches the credential in `config/brain.yml` / config override. Required for DB access.
- `OBSIDIAN_VAULT_PATH`: mount path shared with both scheduler containers for read-only knowledge access.
- `USER_TIMEZONE`: used by Celery Beat to seed the scheduler and default timezone when no schedule overrides exist.
- `CELERY_BROKER_URL` & `CELERY_RESULT_BACKEND`: typically `redis://redis:6379/1` and `redis://redis:6379/2`. Must resolve
  to the same Redis instance exposed to the containers defined in `docker-compose.yml`.
- `CELERY_QUEUE_NAME`: defaults to `scheduler`. The worker subscribes to this queue (`task_default_queue`) and the adapter
  enqueues callbacks with this tag.

> See `.env.sample` for the canonical defaults.

### Brain scheduler config block (`config/brain.yml`, override in `~/.config/brain/brain.yml`)
- `scheduler.default_max_attempts`: max retries the dispatcher will allow per execution.
- `scheduler.default_backoff_strategy`: `fixed`, `exponential`, or `none`.
- `scheduler.backoff_base_seconds`: base delay when computing exponential backoff.
- `scheduler.failure_notification_threshold`: number of consecutive failures before `FailureNotificationService`
  sends an outbound signal through `AttentionRouter`.
- `scheduler.failure_notification_throttle_seconds`: minimum delay between repeated failure notifications.

> Any change to these values must be done via the config file and evaluated before restarting scheduler containers.

## Components & Dependencies
- **Celery worker (`celery-worker`)**: runs `poetry run celery -A scheduler.celery_app worker --loglevel=info --queues scheduler`.
  It enqueues scheduled callbacks into `ExecutionDispatcher` via `CallbackBridge`. Look for `scheduler.dispatch` logs
  in `docker-compose` output.
- **Celery beat (`celery-beat`)**: runs `poetry run celery -A scheduler.celery_app beat --schedule /var/lib/brain/scheduler/beat-schedule`.
  The beat schedule is persisted at `./data/scheduler/beat-schedule` (Docker volume). Losing that file resets all cron
  and interval timing.
- **Postgres**: stores `task_intents`, `schedules`, `executions`, `schedule_audit_logs`, and `execution_audit_logs`.
  Use `psql` (or `poetry run alembic current -vv`) to confirm schema migrations `0016` and `0017` completed.
- **Redis**: Celery broker and result backend. Ensure `redis` container is healthy before starting scheduler workers.
- **Attention Router & Signal**: Scheduled executions run as the `scheduler` actor with limited autonomy. Notification
  content is throttled via `src/attention/router.py` and `FailureNotificationService`.

## Startup
1. `docker compose up -d redis postgres` (ensure `postgres` reports `healthy` via `pg_isready`).
2. `docker compose up -d signal-api letta agent` (optional but keeps dependencies warm).
3. `docker compose up -d celery-worker celery-beat`.
   - Use `docker compose logs --tail 40 celery-beat` to verify beat reads `beat-schedule`.
   - Use `docker compose logs --tail 40 celery-worker` to confirm `scheduler.dispatch` tasks are acknowledged.
4. For local debugging outside Compose:
   ```bash
   poetry run celery -A scheduler.celery_app worker --loglevel=info --queues scheduler
   poetry run celery -A scheduler.celery_app beat --loglevel=info --schedule /tmp/beat-schedule
   ```
   Ensure the same `.env` values are available and mount `./data/scheduler` if you want persistence.

## Shutdown
- `docker compose stop celery-beat celery-worker`.
- For a full teardown: `docker compose down --volumes` (be aware this removes `./data/postgres` and `./data/redis` unless you mount them separately).
- When modifying `beat-schedule`, stop beat first, edit or replace `./data/scheduler/beat-schedule`, then restart.
- To temporarily prevent new executions, pause schedules via the `ScheduleCommandService` (preferred) or manually:
  ```sql
  UPDATE schedules SET state = 'paused' WHERE state = 'active';
  ```
  (Do this only from a trusted SQL client after notifying stakeholders.)

## Health Checks
- `docker compose ps celery-worker celery-beat` – both services should show `Up` with healthy status once dependencies are ready.
- `docker compose exec celery-worker celery -A scheduler.celery_app inspect ping`; expect `{"scheduler_worker@scheduler-worker": "pong"}` (worker node name may vary).
- `docker compose exec celery-worker celery -A scheduler.celery_app inspect active` – shows running tasks and queue depth.
- `docker compose logs --tail 50 celery-worker | grep scheduler.dispatch` – verify recent callbacks completed.
- `docker compose logs --tail 50 celery-beat | grep scheduler.dispatch` – ensures beat is still emitting tasks.
- `PGPASSWORD=${POSTGRES_PASSWORD} psql -h localhost -U brain -d brain -c "SELECT id, state, next_run_at FROM schedules WHERE state='active' ORDER BY next_run_at NULLS LAST LIMIT 20;"`.
- `PGPASSWORD=${POSTGRES_PASSWORD} psql -h localhost -U brain -d brain -c "SELECT id, status, last_error_message FROM executions ORDER BY updated_at DESC LIMIT 20;"`.
- Inspect audit tables for recent changes:
  - `schedule_audit_logs` – confirms who paused/resumed schedules.
  - `execution_audit_logs` – shows execution outcomes wired into attention and failure logging.
- Watch failure notifications in the Signal inbox configured via `~/.config/brain/secrets.yml` (the `scheduler` actor sends alerts only after
  `scheduler.failure_notification_threshold` consecutive failures).
- Check `./data/scheduler/beat-schedule` timestamp to ensure beat is writing to disk after restarts.

## Troubleshooting
1. **Redis broker unavailable**
   - Symptoms: Celery worker log repeatedly shows `ConnectionRefusedError` or `broker unavailable`.
   - Fix: `docker compose logs redis`, restart Redis (`docker compose restart redis`), confirm `CELERY_BROKER_URL` matches the service name.
2. **Beat says schedule file is corrupted**
   - Symptom: `Local file contains corrupted entry` or `ValueError`.
   - Fix: stop beat, move `/data/scheduler/beat-schedule` aside, start beat; Celery regenerates the file. Reconcile any custom cron entries manually.
3. **Executions stay in `failed` or `retry_scheduled`**
   - Check `executions` / `execution_audit_logs` for `last_error_message`.
   - The dispatcher populates `FailureNotificationService`; failure emails/signal alerts include the most recent `trace_id`.
   - Consider adjusting `scheduler.default_max_attempts` or `backoff_base_seconds` before restarting worker.
4. **Active schedule never fires**
   - Verify `schedules.next_run_at` is not null and is within a reasonable window.
   - Confirm `celery-worker` log contains `scheduler.dispatch completed` entries shortly after the expected time.
   - If `next_run_at` keeps moving backward, ensure upstream process is not resetting the schedule (`ScheduleCommandServiceImpl` and `review_job` can mark schedules as `archived` or `paused`).
5. **Conditional schedules report `unsupported`**
   - `scheduler.evaluate_predicate` is a stub (logs `Conditional schedule evaluation is not yet implemented`).
   - Until predicate evaluation is implemented, conditional schedules cannot execute; rely on manual review (see `docs/schedule-review-ops.md`).
6. **Attention router blocks notifications**
   - If scheduled tasks seem to execute (check `executions` table) but no signal is delivered, inspect `logs/scheduler` entries and `policy-core` roles (`docs/policy-core.md`) to confirm the `scheduler` actor kept autonomy within allowed scopes.

## Rollback & Disable Strategies
- **Short-term disable:** `docker compose stop celery-worker celery-beat` and optionally `docker compose rm -f celery-worker celery-beat`.
- **Pause schedule activity:** use the Python interface (`ScheduleCommandServiceImpl`) or manually run the SQL update above to leave schedules in `paused` state until you are ready to restart.
- **Restore a known-good scheduler release:**
  1. `git checkout <tag/commit>` that paired with the previously working `docker-compose.yml`.
  2. `docker compose build celery-worker celery-beat`.
  3. `docker compose up -d --force-recreate celery-worker celery-beat`.
  4. Verify schedule tables and beat file using the health checks above.
- **Beat schedule corruption**: replace `./data/scheduler/beat-schedule` from a backup archive before starting `celery-beat`.

## Related References
- `docs/prd-scheduled-timed-tasks.md` – PRD describing goals, authorization context, and success criteria.
- `docs/scheduler-decision-record.md` – rationale for selecting Celery + Redis.
- `docs/scheduler-adapter-config-boundary.md` – boundary between Brain domain models and provider configuration.
- `docs/schedule-review-ops.md` – review job operations referenced by the scheduler review workflow.
- `docs/policy-core.md` – authorization policies governing the `scheduler` actor and attention router.
