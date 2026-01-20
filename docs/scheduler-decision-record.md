<!--
Docblock:
- File: docs/scheduler-decision-record.md
- Purpose: Record the scheduler backend selection decision with rationale, constraints, and revisit triggers.
- Scope: Epic 02 scheduler selection and decoupling; Milestone 01 scheduling foundations.
-->
# Scheduler Decision Record

## Status
- Decision: Accepted
- Date: 2026-01-20

## Context
The Scheduled & Timed Task Execution PRD requires a dynamic, inspectable scheduling system that is decoupled from any
single provider while supporting one-time, interval, calendar-rule, and conditional schedules. Epic 02 requires an
initial scheduler choice that fits containerized deployment, OSS constraints, and the Python stack without entangling
core Brain logic with provider-specific semantics.

The evaluation in `docs/scheduler-options-evaluation.md` compared Celery + Redis, APScheduler, and RQ Scheduler against
schedule type support, operational footprint, reliability, and adapter leakage risks.

## Decision
Select **Celery + Redis (Celery Beat + worker)** as the initial scheduler backend.

## Rationale
- Maturity and reliability: Celery offers established retry/backoff semantics and task state visibility needed for audit
  and failure handling.
- Container fit: Redis broker + Celery worker + Celery Beat align with the existing Docker-first operational model.
- Python compatibility: Celery integrates cleanly with the Python service stack already used in Brain.
- Trade-offs vs alternatives:
  - APScheduler is simpler but couples scheduling to the app process and raises adapter leakage risk.
  - RQ Scheduler is lighter but weaker for cron expressiveness and has fewer built-in failure semantics.

## Constraints and Non-Goals
- This decision does not imply immediate operational deployment changes.
- No schema or API changes beyond Epic 01 scope are introduced here.
- Conditional scheduling remains a first-party responsibility (predicate evaluation + evaluation cadence), not a provider
  feature.
- The scheduler integration must remain OSS and containerized.

## Coupling Risks and Mitigations
- Risk: Celery task semantics (ETA, task IDs, queue names) leaking into Brain domain logic.
  - Mitigation: enforce a strict adapter boundary that translates between Brain schedule/execution models and Celery
    primitives.
- Risk: Celery Beat single-scheduler assumption influences architecture.
  - Mitigation: treat scheduler HA constraints as an implementation detail behind the adapter; document provider-specific
    limits in config and operational notes, not in core models.

## Adapter Boundary Constraints
The adapter interface must:
- accept provider-agnostic schedule definitions and execution callbacks
- shield Brain logic from Celery-specific constructs
- allow replacement with another provider without modifying domain models or API contracts

## Revisit Triggers
Re-evaluate this decision if any of the following occur:
- Need for HA scheduling beyond what Celery Beat can reasonably support.
- Requirement for native conditional scheduling or richer calendar semantics not supported through adapter translation.
- Operational constraints change (non-Redis broker, non-Python runtime, or different container orchestration model).
- Evidence of unacceptable adapter leakage or domain coupling in implementation reviews.

## References
- `docs/prd-scheduled-timed-tasks.md`
- `docs/scheduler-options-evaluation.md`
- `work-jobs/epic-02-scheduler-selection-and-decoupling.md`
