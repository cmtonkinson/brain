<!--
Docblock:
- File: docs/scheduler-deployment-checklist.md
- Purpose: Operational validation checklist for the scheduler containers defined in docker-compose.
- Scope: Epic 10 (Ops and deployment validation) for PRD Scheduled & Timed Task Execution.
-->
# Scheduler Deployment Checklist

## Context and scope
- Validate the `celery-worker` and `celery-beat` services implemented by `docker-compose.yml` for the scheduler adapters and execution dispatcher (`work-jobs/epic-10-ops-and-deployment-validation.md`).
- Ensure deployments start clean, stay healthy, restart quietly, and preserve the beat schedule state recorded in `./data/scheduler/beat-schedule`.
- Reference `docs/prd-scheduled-timed-tasks.md` for authorization context, attention routing, and audit expectations that the scheduler must honor.

## Manual validation steps (compose-focused)

### 1. Pre-flight compose review
- Run `docker compose config --services` to confirm the scheduler services (`celery-beat`, `celery-worker`) are defined on the active Compose project.
- Inspect `docker compose config` or `docker-compose.yml` directly to verify both services use `scheduler.celery_app`, mount the Prompts directory, the read-only `OBSIDIAN_VAULT_PATH`, and the scheduler data volume (`./data/scheduler:/var/lib/brain/scheduler`) so the beat schedule persists.
- Confirm `restart: unless-stopped` is set for both services and that `.env.sample` documents `CELERY_BROKER_URL`, `CELERY_RESULT_BACKEND`, and `CELERY_QUEUE_NAME` to make the required environment explicit.

### 2. Startup and readiness
- `docker compose up -d redis celery-worker celery-beat` (optionally include the full stack) and then `docker compose ps` / `docker ps` to show all scheduler containers `Up` and healthy.
- Use `docker compose logs --tail 20 celery-beat` and `docker compose logs --tail 20 celery-worker` to confirm the beat scheduler logs `beat: Starting...` and the worker reports `Ready`/`task accepted` messages, ensuring the queue and broker loaded successfully.
- If you rely on Compose health checks, wait until services report `healthy` before moving to the next step.

### 3. Broker and port validation
- From inside the scheduler containers, run `docker compose exec celery-worker redis-cli -h redis -p 6379 ping` to ensure the Redis broker port is reachable and answers `PONG`.
- Confirm the effective `CELERY_BROKER_URL`/`CELERY_RESULT_BACKEND` (visible via `docker compose exec celery-worker env | grep CELERY_`) resolves to the Compose `redis` service so queue and result traffic stay inside the bridge network.
- Use `docker network inspect brain-network` if you need to assert that port `6379` routes properly across scheduler containers.

### 4. Log-based verification
- Tail recent logs during a known schedule run with `docker compose logs --since 10s celery-beat celery-worker` and confirm no `Error`/`Traceback` entries appear; focus on keywords like `schedule`, `task accepted`, `task succeeded`, and the scheduler dispatch payload.
- Archive a representative log excerpt to `logs/validation/` (e.g., `docker compose logs celery-beat --since 1m > logs/validation/celery-beat.log`) so future deployments can compare expected output.

### 5. Restart and persistence
- Restart the scheduler containers: `docker compose restart celery-beat celery-worker`.
- After restart, rerun `docker compose ps` and re-check the logs to ensure the beat scheduler reloads without dropping entries and the worker reconnects to Redis.
- Inspect `ls -l ./data/scheduler/beat-schedule` before and after the restart to record timestamp/size, confirming the file rewrites and is persisted across restarts without manual re-creation.

### 6. Recovery and resilience checks
- Simulate a recovery: `docker compose rm -f celery-beat` then `docker compose up -d celery-beat` with `./data/scheduler` still mounted, and verify the beat resumes without requiring schedule re-registration.
- Check that `restart: unless-stopped` is honored by running `docker inspect celery-beat | jq .HostConfig.RestartPolicy` and confirming `Name` remains `unless-stopped`, ensuring the service can recover from transient failures.

### 7. Documentation and observability checkpoints
- Record your validation run (commands executed, log excerpts, observed health) and link it to `docs/scheduler-ops-runbook.md` so operators understand how these Compose-based steps relate to the broader workflow.
- Keep the `docs/prd-scheduled-timed-tasks.md` and this checklist in sync so attention/authorization guarantees remain clear when the scheduler configuration evolves.

_Refs:_ `docs/prd-scheduled-timed-tasks.md`, `docs/scheduler-ops-runbook.md`, `docker-compose.yml`, `.env.sample`
