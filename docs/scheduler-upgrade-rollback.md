<!--
Docblock:
- File: docs/scheduler-upgrade-rollback.md
- Purpose: Upgrade and rollback runbook for the Celery-based scheduler stack with data integrity checks.
- Scope: Epic 10 (Ops and deployment validation) / Milestone 05 (Hardening and validation) covering work-jobs/task-37-upgrade-rollback-checklist.md.
-->
# Scheduler Upgrade & Rollback Checklist

## Context and alignment
- This checklist fulfils [work-jobs/task-37-upgrade-rollback-checklist.md](work-jobs/task-37-upgrade-rollback-checklist.md) and ties into the `Epic 10: Ops and Deployment Validation` objective alongside Milestone 05 documentation expectations.
- The procedures assume judgment in line with `docs/prd-scheduled-timed-tasks.md` (attention routing, actor context, auditability) and the data assumptions from `docs/architecture-doctrine.md` (Tier 1 durability for schedule, execution, and audit state).
- All scheduler upgrades must keep the Celery beat/worker pair and their supporting infra in sync so the `scheduler` actor maintains its bounded autonomy, and upgrades should never mutate Tier 1 data without prior backups.

## Pre-upgrade checklist
1. **Ground truth & release readiness**
   - Confirm the release tag/commit that contains scheduler changes, documenting the expected image/hash so `celery-beat`, `celery-worker`, and the agent code are aligned.
   - Review `.env.sample`, `config/brain.yml`, and any Scheduler-specific overrides to spot config changes that must roll out with the upgrade (e.g., backoff settings used in `failure_notifications` or the attention router).
   - Notify stakeholders and pause automation via the ScheduleCommandService (`schedules.state = 'paused'`) if the upgrade could interfere with mission-critical schedules.
2. **Tier 1 backup requirements**
   - `Postgres` (`./data/postgres`): run `PGPASSWORD=${POSTGRES_PASSWORD} pg_dump -Fc -h localhost -U brain brain > backups/scheduler-postgres-$(date +%Y%m%d%H%M).dump` and verify the backup file size and checksum before proceeding; this protects `task_intents`, `schedules`, `executions`, and audit tables described in `docs/architecture-doctrine.md`.
   - `Redis` (`./data/redis`): use `redis-cli BGSAVE` (or `SAVE` for immediate persistence) inside the Redis container and copy the latest `dump.rdb` (and `appendonly.aof` if configured) to `backups/` to preserve broker/result state that influences retries and notifications.
   - Scheduler persistence file (`./data/scheduler/beat-schedule`): copy the current file to `backups/beat-schedule-$(date +%s)` so beat metadata can be restored if the new release fails; this file is part of the scheduler stack’s durable state and must be kept in sync with Postgres data.
   - Document the backup locations and share them with the team so rollback actors know where to restore from.
3. **Service drain**
   - Stop `celery-beat` and `celery-worker` (`docker compose stop celery-beat celery-worker`) after a graceful pause to avoid killing inflight executions; confirm `docker compose ps` shows them as `Exit`/`Down`.
   - Use `docker compose logs celery-worker | tail -n 40` to ensure no long-running tasks remain and note any `retry`/`failure` messages for after-upgrade verification.
   - Record the current `beat-schedule` file timestamp (e.g., `stat ./data/scheduler/beat-schedule`) so you can verify the new release writes to it.
4. **Component grouping (must upgrade together)**
   - `celery-beat` and `celery-worker` share the same scheduler codebase (`src/scheduler`) and must be upgraded simultaneously to avoid dispatch failures (`docker compose build --pull scheduler`).
   - The scheduler containers rely on the same Postgres schema. If migrations are required, run `poetry run alembic upgrade head` (inside the agent container) **before** starting the new Celery containers so the worker can operate against the upgraded schema.
   - Any agent-local tooling or skill that interacts with scheduler data (e.g., review job logic in `src/scheduler/review_job.py`) should be deployed in lockstep; ideally, upgrade the `agent` container that exposes the Celery tasks in the same release so code and DB stay aligned.
   - Redis configuration (`CELERY_BROKER_URL`/`CELERY_RESULT_BACKEND`) should be validated after the upgrade because worker and beat must resolve to the same instance and queue.
5. **Upgrade execution**
   - Rebuild and deploy the new scheduler release: `docker compose build celery-beat celery-worker` followed by `docker compose up -d celery-worker celery-beat` (include `agent` if relevant).
   - Monitor the startup logs for `beat: Starting...`, `SchedulerDispatcher initialized`, and `task accepted` messages; log excerpts should match those captured during the pre-flight review.
   - After the containers report healthy, inspect `docker compose ls` to confirm they are `Up` and restart policy remains `unless-stopped`.

## Post-upgrade validation
1. **Data integrity verification**
   - Run `PGPASSWORD=${POSTGRES_PASSWORD} psql -h localhost -U brain -d brain -c "SELECT count(*) FROM schedules WHERE state IN ('active','paused');"` and compare the count to the pre-upgrade snapshot to ensure no rows were lost.
   - Check audit linkage: `SELECT job_name, status, created_at FROM execution_audit_logs ORDER BY created_at DESC LIMIT 5;` – the newest entries should reflect the upgraded release version/time and not include schema errors.
   - Validate that the `beat-schedule` file is being rewritten (`stat ./data/scheduler/beat-schedule` timestamp is fresh) so Celery beat still persists schedule definitions as expected.
2. **Schedule survivability checks**
   - Restart `celery-beat` and `celery-worker` (`docker compose restart celery-beat celery-worker`) and watch `docker compose logs --tail 20 celery-beat` to confirm beat reloads the schedule without `ValueError` or `schedule file corrupted` errors.
   - Query the schedules table: `SELECT id, next_run_at FROM schedules WHERE state = 'active' ORDER BY next_run_at LIMIT 10;` ensuring `next_run_at` remains populated and moves forward after the restart.
   - Trigger a known `run-now` command or use the `ScheduleCommandService` (if available in test) to force a single task, then confirm the worker picks it up (`docker compose logs celery-worker | tail -n 40 | grep scheduler.dispatch`) and that the execution status transitions from `queued` to `completed` in Postgres.
   - Validate attention-routing preservation by inspecting `execution_audit_logs` for the most recent entries and confirming they still include the `scheduler` actor context and do not exceed autonomy boundaries.
3. **Observability and documentation**
   - Update `docs/scheduler-ops-runbook.md` and `docs/scheduler-deployment-checklist.md` if any new commands, ports, or file paths were introduced by the upgrade.
   - Record the upgrade (date, commit, backup identifiers) in your preferred change log so the next operator can reference the rollout.

## Rollback checklist (documentation-only)
1. **Rollback readiness**
   - Confirm you still have the Tier 1 backups created before the upgrade; if not, stop and rebuild the upgrade process before proceeding.
   - Pause all schedules or stop the scheduler containers so they do not mutate database state during rollback.
2. **Restore durable state**
   - Postgres: `PGPASSWORD=${POSTGRES_PASSWORD} pg_restore -c -h localhost -U brain -d brain backups/scheduler-postgres-YYYYmmddHHMM.dump` to restore the schema and rows to the pre-upgrade snapshot. Use `-c` to clean and replace table contents.
   - Redis: stop the Redis container, replace `./data/redis/dump.rdb` (and `appendonly.aof` if applicable) with the backup copy, then start Redis so the broker/result store reflects the previous release’s queue state.
   - Beat schedule file: copy the backed-up `beat-schedule-<timestamp>` back to `./data/scheduler/beat-schedule` and ensure ownership/permissions match the container user.
3. **Deploy the prior release**
   - Checkout or redeploy the commit/tag that preceded the failing upgrade, rebuild the Celery containers, and start them (`docker compose up -d celery-worker celery-beat`).
   - If migrations were rolled forward, run the downgrade path documented in your Alembic history (e.g., `poetry run alembic downgrade -1`) **before** starting the old containers to keep schema and code version aligned.
   - Confirm that Redis and Postgres are reachable by the rollback release and that the scheduler volume still mounts.
4. **Post-rollback verification**
   - Repeat the data integrity steps from the post-upgrade validation to ensure `schedules`, `executions`, and audit logs return to known-good values and no residual schema drift remains.
   - Check that the beat schedule file timestamp matches the restored backup and that the worker processes can dispatch tasks (the `next_run_at` values should align with the rollback snapshot).
   - Review logs for any `IntegrityError` or mismatched schema exceptions before resuming normal operations.
   - Notify stakeholders with the rollback summary, highlight any manual actions taken, and schedule a follow-up upgrade attempt once the blockers are resolved.

## References
- `docs/prd-scheduled-timed-tasks.md` (authorization context, attention routing, execution guarantees).
- `docs/architecture-doctrine.md` (Tier 1 durability that drives the backup requirements here).
- `docs/scheduler-ops-runbook.md` and `docs/scheduler-deployment-checklist.md` for startup/validation context.
- `work-jobs/epic-10-ops-and-deployment-validation.md` and `work-jobs/milestone-05-hardening-and-validation.md` for alignment with the broader milestone goals.
