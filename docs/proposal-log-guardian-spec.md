# Log Guardian Auto-Remediation Spec

## Goal
Design and implement an automated log-watching agent that detects error conditions in Docker services, invokes Codex CLI to diagnose and propose fixes, and safely rebuilds/restarts only the impacted container. The system must rate-limit actions, minimize context/token usage, and ensure rollback/blue-green stability to avoid bricking the environment.

## Non-Goals
- Full observability/metrics platform
- Human-in-the-loop approval UX
- General-purpose incident management system

## High-Level Architecture
1. **log-guardian** (daemon/sidecar)
   - Tails Docker events/logs and detects error incidents.
   - De-duplicates, rate-limits, and queues incidents.
   - Packages minimal context and invokes Codex CLI for remediation.
2. **codex-fixer** (Codex CLI invocation)
   - Strict prompt template with bounded context, command allowlist, and token limits.
   - Outputs a remediation plan + concrete commands.
3. **deployment controller**
   - Rebuilds and restarts only the impacted service.
   - Implements blue/green or rollback policy.
   - Validates healthchecks and rolls back on failure.

## Terminology
- **Incident**: A unique error signature detected in logs/events (service + signature + time window).
- **Signature**: Hash of normalized error text + service name.
- **Impact service**: The Docker Compose service that emitted the error or failed a healthcheck.
- **Attempt**: One Codex CLI run for an incident.

## Key Requirements
### Rate Limits / Token Utilization
- **Per-service attempt limit**: 3 attempts per 6 hours.
- **Global attempt limit**: 10 attempts per hour across all services.
- **Token budget**: Max 2k tokens per Codex CLI run.
- **Context size**: Include only relevant files and log excerpts.
- **Incident de-dupe**: Suppress identical signatures for 60 minutes after a failed attempt or until resolved.

### Stability / Rollback
- **Blue/green preference**: When possible, deploy to standby profile and switch traffic after successful healthchecks.
- **Fallback rollback**: Keep last known good image tag and restore on failure.
- **Circuit breaker**: Auto-fix disabled for a service after 2 consecutive failures within 2 hours.

### Safety
- Strict command allowlist for Codex CLI:
  - File edits inside repo
  - `docker compose build <service>`
  - `docker compose up -d <service>`
  - `docker compose ps`, `docker compose logs`, `docker compose config`
  - Local test commands in repo (if present)
- No destructive actions unless explicitly whitelisted.
- No external network access from Codex CLI.

## Data Flow
1. **Event ingestion**
   - Use `docker events` (preferred) + `docker logs -f` for error text.
   - Capture:
     - Timestamp
     - Service name
     - Container name
     - Event type (health_status, die, oom, etc.)
     - Log lines (last N lines around error)
2. **Error detection**
   - Regex include list: `ERROR`, `Exception`, `Traceback`, `panic`, `segfault`, `OOM`, `healthcheck failed`.
   - Regex exclude list: known transient warnings (configurable).
3. **Incident creation**
   - Normalize error text (strip timestamps/IDs).
   - Hash: `sha256(service + normalized_error)`.
   - Store incident record on disk.
4. **Queueing**
   - If rate-limit or circuit-breaker conditions met, skip.
   - If signature already in flight, merge log lines and skip new attempt.
5. **Codex invocation**
   - Build a minimal bundle of context and files.
   - Run Codex CLI with fixed prompt template and command allowlist.
6. **Remediation**
   - Apply patch, run limited tests if present.
   - Rebuild and restart impacted service.
   - Run healthchecks.
7. **Rollback**
   - If healthchecks fail, rollback to previous image or blue/green stable service.

## Detailed Design

### 1. log-guardian daemon
**Location**: `src/log_guardian.py`

**Responsibilities**
- Spawn `docker events` and/or `docker logs -f` for the Compose project.
- Parse events and log lines.
- Build incident records.
- Enforce rate limits and circuit breaker.
- Invoke Codex CLI and handle outcome.

**Config** (new config file suggested: `config/log_guardian.json`)
- `include_regex`: list of regex patterns
- `exclude_regex`: list of regex patterns
- `log_tail_lines`: default 200
- `incident_dedupe_minutes`: default 60
- `per_service_attempt_limit`: default 3
- `per_service_attempt_window_minutes`: default 360
- `global_attempt_limit`: default 10
- `global_attempt_window_minutes`: default 60
- `consecutive_failure_breaker`: default 2
- `breaker_window_minutes`: default 120
- `codex_max_tokens`: default 2000
- `codex_timeout_seconds`: default 300
- `docker_compose_project`: optional override
- `compose_service_allowlist`: optional list
- `compose_service_denylist`: optional list

**State storage**
- `var/log-guardian/incidents.jsonl` (append-only)
- `var/log-guardian/state.json` (rate limits, in-flight incidents)
- `var/log-guardian/last_good.json` (last known good image per service)

### 2. Codex CLI Integration
**Prompt template** (example)
- System:
  - You are an automated remediation agent.
  - Follow the command allowlist.
  - Keep changes minimal.
  - Provide a short plan, then commands.
- User:
  - Incident summary (service name, signature, timestamp)
  - Last N log lines (trimmed)
  - Relevant file list (only include files that matter)
  - Command allowlist
  - Required: rebuild only the impacted service

**Command allowlist enforcement**
- log-guardian validates proposed commands before executing.
- If any command outside allowlist, abort attempt and record incident.

**Context selection**
- Always include:
  - `docker-compose.yml` (or compose file used)
  - Service-specific config or Dockerfile if exists
- Optional:
  - App logs excerpt
  - Service-specific config directory
  - The file referenced by error path if log contains it
- Max total context size: 50KB.

### 3. Deployment Controller
**Preferred**: Blue/green via compose profiles.
- `green` profile = active
- `blue` profile = standby
- New builds go to standby
- Validate healthchecks
- Switch traffic by updating reverse proxy or `docker compose` service mapping

**Rollback strategy**
- Maintain `last_good.json` with image tag per service.
- On failure, re-deploy last known good image.

**Healthcheck policy**
- Wait up to 120 seconds for `healthy` status.
- If no healthcheck configured, run a minimal smoke test (optional).

### 4. Incident Dedupe and Rate Limiting
- Use signature hash to identify repeats.
- If same signature reappears within dedupe window, update incident logs but do not re-run Codex.
- Per-service and global counters are stored in `state.json`.

### 5. Circuit Breaker
- Track consecutive failed attempts per service in `state.json`.
- If threshold reached, disable auto-fix for that service for breaker window.
- Record a human-readable note in incidents log.

## Implementation Steps
1. **Create config and state storage**
   - Add `config/log_guardian.json` with defaults.
   - Add `var/log-guardian/` directory and state files.
2. **Implement log-guardian core**
   - Parse events/logs, build incidents, store state.
   - Implement rate limit checks and dedupe.
3. **Integrate Codex CLI**
   - Build prompt template and context packer.
   - Enforce allowlist and token cap.
4. **Implement deployment controller**
   - Blue/green via compose profiles or fallback rollback policy.
   - Healthcheck waiting and rollback handling.
5. **Add tests**
   - Unit tests for dedupe, rate limit, breaker logic.
   - Mock docker event/log parsing.
6. **Document operations**
   - How to enable/disable auto-fix per service.
   - How to inspect incident logs and state.

## Example Data Structures
**Incident record**
```
{
  "timestamp": "2025-01-01T12:00:00Z",
  "service": "api",
  "container": "api-123",
  "signature": "sha256:...",
  "error_excerpt": "Traceback ...",
  "event_type": "log_error",
  "attempted": true,
  "result": "failed",
  "notes": "rollback to last good"
}
```

**State**
```
{
  "service_attempts": {
    "api": ["2025-01-01T12:00:00Z", "2025-01-01T12:30:00Z"]
  },
  "global_attempts": ["2025-01-01T12:00:00Z"],
  "circuit_breaker": {
    "api": {"until": "2025-01-01T14:00:00Z", "failures": 2}
  },
  "in_flight": ["sha256:..."]
}
```

## Operational Notes
- Run log-guardian under a supervised process (systemd or docker compose service).
- If using blue/green, ensure reverse proxy routing can switch between profiles.
- Do not allow Codex CLI to modify files outside the repo.
- Keep log-guardian logs separate from app logs.

## Open Questions (Must Answer Before Build)
- Which services are eligible for auto-fix?
- Are healthchecks defined in compose for all services?
- Is there an existing reverse proxy that can switch between blue/green profiles?
- Preferred location for state files if `var/` is not acceptable?

