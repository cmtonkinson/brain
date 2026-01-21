<!--
Docblock:
- File: docs/scheduler-deployment-checklist.md
- Purpose: Operational validation checklist for the scheduler containers defined in docker-compose.
- Scope: Epic 10 (Ops and deployment validation) for PRD Scheduled & Timed Task Execution.
-->
# Scheduler Deployment Checklist

## Context and scope
- Validate the `celery-worker` and `celery-beat` services that implement the scheduler adapters and execution dispatcher from `docker-compose.yml` (see `work-jobs/epic-10-ops-and-deployment-validation.md`).
- Confirm deployments start clean, stay healthy, restart quietly, and persist the beat schedule state recorded in `./data/scheduler/beat-schedule`.
- Reference `docs/prd-scheduled-timed-tasks.md` for the intent/authorization constraints that the scheduler must honor.

## 1. Pre-flight
- **Service definitions:** Inspect `docker-compose.yml` to confirm `celery-worker` and `celery-beat` both run `scheduler.celery_app` (worker + beat) and the restart policy is `unless-stopped` to keep the scheduler task loop resilient.
- **Volumes:** Ensure both services mount `./prompts`, the read-only Obsidian vault path, and the scheduler data volume (`./data/scheduler:/var/lib/brain/scheduler`) so `beat-schedule` persists across deployments.
- **Environment variables:** Verify `.env.sample` declares the scheduler variables `CELERY_BROKER_URL`, `CELERY_RESULT_BACKEND`, and `CELERY_QUEUE_NAME` (no additional updates required; use placeholders to keep secrets out of version control).

## 2. Startup and readiness
- `docker compose up -d celery-worker celery-beat redis` (or bring up the full stack) and then `docker compose ps`/`docker ps` to confirm both scheduler containers reach `Up` state with healthy status.
- Check service health via `docker compose logs --tail 20 celery-beat` and `celery-worker`; look for lines like `beat: Starting...` and `worker: Ready` to confirm they loaded the queue and broker.
- If using health-checking tooling, ensure Compose sees the services as healthy before declaring the deployment validated.

## 3. Port and broker validation
- From the scheduler containers, verify Redis connectivity: `docker compose exec celery-worker redis-cli -h redis -p 6379 ping` returns `PONG` and `CELERY_BROKER_URL`/`CELERY_RESULT_BACKEND` are reachable.
- Ensure no other firewall rules prevent `redis` port `6379` from being accessed within the `brain-network` bridge (use `docker network inspect brain-network` for diagnostics if needed).

## 4. Log-based verification
- Tail the most recent logs while a dummy scheduled job runs: `docker compose logs --since 10s celery-beat celery-worker` and confirm no `Error`/`Traceback` patterns appear. Focus on keywords such as `schedule` (beat) and `task accepted`/`task succeeded` (worker).
- Save a sample log excerpt for the deployment validation run (for example `docker compose logs celery-beat --since 1m > logs/validation/celery-beat.log`).

## 5. Restart and persistence
- Restart the scheduler containers: `docker compose restart celery-beat celery-worker`.
- After restart, verify `docker compose ps` still shows them `Up` and re-check the logs to confirm the beat schedule reloads without dropping entries.
- Inspect the persisted schedule file: `ls -l ./data/scheduler/beat-schedule` and record the timestamp/size before and after restart to confirm it was written and preserved.
- Optionally simulate a failure (stop > start) and ensure `beat-schedule` still contains the prior schedule definitions so no jobs are forgotten.

## 6. Persistence and recovery checks
- Remove a scheduler container (`docker compose rm -f celery-beat`), then `docker compose up -d celery-beat` while keeping `./data/scheduler` mounted, and confirm the beat scheduler resumes without needing to re-create schedules.
- Confirm the `restart: unless-stopped` policy allows the service to recover from transient crashes by checking `docker inspect celery-beat | jq .HostConfig.RestartPolicy` returns `"Name": "unless-stopped"`.

## 7. Documentation and observability checkpoints
- Update or confirm documentation references (this checklist plus `docs/prd-scheduled-timed-tasks.md`) so future operators understand why the scheduler must honor authorization context and attention routing.
- Capture the log-based validation steps in an ops runbook or monitoring alert so repeated deployments can follow the same checklist.

_Refs:_ `docs/prd-scheduled-timed-tasks.md` (overall PRD), `docker-compose.yml` service definitions, and `.env.sample` for scheduler env vars.
