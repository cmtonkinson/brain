<!--
Docblock:
- File: docs/scheduler-options-evaluation.md
- Purpose: Evaluate scheduler backend options against project constraints to inform selection.
- Scope: Epic 02 scheduler selection and decoupling.
-->
# Scheduler Options Evaluation

## Context
This evaluation supports Epic 02 and the PRD "Scheduled & Timed Task Execution" by comparing candidate OSS schedulers
against required schedule types, operational footprint, and adapter-boundary decoupling requirements.

## Evaluation Criteria
- Schedule types: one-time, interval, calendar-rule (cron-like), conditional (predicate-based).
- Reliability: maturity, failure modes, support for retries/visibility.
- Operational footprint: services required, container fit, persistence needs.
- Adapter leakage risk: likelihood provider-specific concepts bleed into first-party logic.
- Constraints discovered: missing features, drift risk, or incompatibilities.

## Evaluation Matrix
| Candidate | One-time | Interval | Calendar-rule | Conditional | Reliability Notes | Operational Footprint | Adapter Leakage Risk | Constraints Discovered |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| Celery + Redis (Celery Beat) | Yes | Yes | Yes (crontab) | Not native; implement via predicate evaluator + polling schedule | Mature, widely used; robust retry/backoff; visibility via task states | Redis broker + Celery worker + Beat scheduler containers; optional result backend | Medium: Celery task/ETA semantics could leak if adapter is not strict | Requires worker/beat coordination; Beat is single scheduler unless made HA; conditional logic must live outside Celery |
| APScheduler | Yes (date trigger) | Yes | Yes (cron trigger) | Not native; implement via predicate evaluator + polling schedule | Stable for in-process scheduling; less proven for distributed/HA | In-process scheduler; optional persistent job store (SQLAlchemy/Redis); typically same service as app | High: in-process job store and trigger model likely entangles app lifecycle | Not designed for distributed execution; HA requires custom coordination; persistence optional not default |
| RQ Scheduler (Redis Queue) | Yes (enqueue_at) | Yes (interval) | Partial (cron via rq-scheduler, less expressive than full cron) | Not native; implement via predicate evaluator + polling schedule | Simple, battle-tested for background jobs; scheduler is single process | Redis broker + RQ worker + rq-scheduler container | Medium: job IDs and queue semantics can leak | Limited cron expressiveness; single scheduler process; fewer built-in retry semantics than Celery |

## Additional Notes on Conditional Scheduling
No evaluated scheduler offers first-class predicate-based scheduling. All candidates require:
- A dedicated predicate evaluation service or periodic evaluation job.
- A schedule type that triggers evaluation cadence (interval or cron).
- First-party logic to decide when a predicate flips and to emit the execution.

This supports the adapter boundary principle: conditional logic should live in Brain services, not in scheduler provider code.

## Recommendation Inputs (for Decision Record)
- Celery + Redis best aligns with containerized, distributed execution and offers the most mature scheduling + retry
  capabilities; it is also the most compatible with later scale-out.
- APScheduler is simplest but couples scheduling to application process lifecycle; it increases adapter leakage risk and
  complicates HA or multi-worker behavior.
- RQ Scheduler is lightweight and Redis-aligned but offers weaker cron expressiveness and fewer built-in semantics for
  retries/backoff; acceptable for minimal workloads but less robust than Celery.
- Conditional scheduling remains a first-party concern regardless of provider; adapter boundary should treat it as
  Brain-owned logic with a provider-agnostic evaluation cadence.

## Constraints Discovered
- All providers lack native predicate-based scheduling; requires dedicated evaluation and a schedule to trigger it.
- HA and failover for schedulers vary; Celery Beat and rq-scheduler are singletons without extra coordination.
- In-process schedulers (APScheduler) undermine the decoupling boundary and complicate container orchestration.

## References
- `docs/prd-scheduled-timed-tasks.md`
- `work-jobs/epic-01-scheduling-architecture-contracts.md`
- `work-jobs/epic-02-scheduler-selection-and-decoupling.md`
