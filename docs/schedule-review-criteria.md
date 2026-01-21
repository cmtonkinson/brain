# Schedule Review Criteria

This document defines the criteria and thresholds used to identify "orphaned", "failing", or "ignored" schedules. These definitions are used by the Schedule Review Job to surface items for human attention.

## 1. Terminology

- **Orphaned**: A schedule that appears to be active but is not pending execution within a reasonable window, or has lost its forward momentum (e.g. system downtime caused a missed window and no next run was calculated).
- **Failing**: A schedule that is attempting to run but consistently erroring out.
- **Ignored**: A schedule that requires human interaction (e.g., "Run Now") or maintenance but has been neglected for an extended period.

## 2. Criteria Definitions

### 2.1 Orphaned Schedules

A schedule is considered **Orphaned** if ALL of the following are true:
1. State is `active`.
2. `next_run_at` is in the past (older than `orphan_grace_period`).
3. `status` is NOT `running` (it is not currently executing).

**Rationale**: `active` schedules should always have a future `next_run_at` or be currently running. If `next_run_at` slips significantly into the past without an execution picking it up, the scheduler has likely dropped it.

### 2.2 Failing Schedules

A schedule is considered **Failing** if ANY of the following are true:
1. `last_run_status` is `failed` AND `failure_count` >= `consecutive_failure_threshold`.
2. `last_run_status` is `failed` AND `last_run_at` is older than `stale_failure_age` (it failed and hasn't tried again in a long time).

**Rationale**: Single failures happen. Repeated failures (`failure_count`) or failures that stall ("fail and forget") require intervention.

### 2.3 Ignored Schedules

A schedule is considered **Ignored** if:
1. State is `paused`.
2. `updated_at` (or `last_run_at`) is older than `ignored_pause_age`.

**Rationale**: Pausing a schedule is valid, but leaving it paused forever often means it should be archived or deleted to reduce clutter.

## 3. Configurable Parameters & Defaults

These parameters should be configurable in the Review Job.

| Parameter | Default | Description |
| :--- | :--- | :--- |
| `orphan_grace_period` | 24 hours | Time after `next_run_at` before an active schedule is flagged as orphaned. Allows for minor system downtimes or queue delays. |
| `consecutive_failure_threshold` | 3 | Number of consecutive failures before flagging. |
| `stale_failure_age` | 7 days | Time since a failed run after which it is considered "stuck" in a failed state without retry. |
| `ignored_pause_age` | 30 days | Time a schedule can remain paused without modification before being flagged for review (archive/delete). |

## 4. Derived Actions (Review Output)

When a schedule matches these criteria, the Review Job produces a `ReviewItem` (as defined in Epic 08 schemas) with:
- **Severity**:
    - Orphaned: `high` (system integrity issue)
    - Failing: `medium` (functional issue, likely retrying or stuck)
    - Ignored: `low` (hygiene issue)
- **Snapshot Usage**:
    - Include `schedule_id`, `task_intent_id`, and `last_error_message` (for failures).
