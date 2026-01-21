<!--
Docblock:
- File: docs/schedule-review-ops.md
- Purpose: Operational guidance for schedule review cadence, thresholds, and response workflow.
- Scope: Epic 08 review and orphaned schedules.
-->
# Schedule Review Operations

## Purpose
Provide operational guidance for running the schedule review job, interpreting outputs, and
responding to findings while honoring attention routing and authorization boundaries.

## Review Cadence
The review job must be scheduled by the scheduler provider (e.g., Celery Beat) as a periodic
operation. Brain does not hard-code a cadence, so operators must configure one.

**Default cadence (recommended):** run once every 24 hours during off-peak hours.

If the review job is not scheduled, no review outputs will be produced.

## Default Thresholds
Review criteria and default thresholds are defined in `docs/schedule-review-criteria.md` and
implemented by `ReviewJobConfig` in `src/scheduler/review_job.py`.

Defaults:
- orphan_grace_period: 24 hours
- consecutive_failure_threshold: 3
- stale_failure_age: 7 days
- ignored_pause_age: 30 days

Severity mapping (per criteria):
- orphaned: high
- failing: medium
- ignored: low

## Adjusting Thresholds
The review job accepts a `ReviewJobConfig` at invocation time. If your job runner supports
configuration injection (env or YAML), map those values to the config fields without changing
code. If no runtime config surface is wired yet, adjusting thresholds requires updating the
review job runner to pass a custom `ReviewJobConfig` and redeploying.

## Accessing Review Outputs
Review outputs are persisted in Postgres (`review_outputs` and `review_items`) and exposed via the
schedule inspection query surface (Python service interface, not HTTP).

Primary inspection methods:
- `list_review_outputs` (filter by severity and time window)
- `get_review_output` (detail with review items)

Example (Python):
```python
from scheduler.schedule_query_service import ScheduleQueryServiceImpl
from scheduler.schedule_service_interface import ReviewOutputGetRequest, ReviewOutputListRequest

service = ScheduleQueryServiceImpl(session_factory)
summary = service.list_review_outputs(ReviewOutputListRequest(severity="high", limit=50))
output = service.get_review_output(ReviewOutputGetRequest(review_output_id=summary.review_outputs[0].id))
```

## Review Output Fields
Review output summary fields (ReviewOutputView):
- id: review output id
- job_execution_id: execution id for the review job run (if tracked)
- window_start/window_end: review evaluation window
- criteria: thresholds used for detection
- orphaned_count/failing_count/ignored_count: total findings per class
- created_at: persistence timestamp

Review item fields (ReviewItemView):
- schedule_id/task_intent_id/execution_id: linkage to schedule and execution context
- issue_type: orphaned | failing | ignored
- severity: high | medium | low
- description: human-readable reason
- last_error_message: only for failing schedules (if available)
- created_at: item timestamp

Example output (abridged):
```json
{
  "review_output": {
    "id": 42,
    "job_execution_id": 1087,
    "window_start": "2025-03-01T10:00:00Z",
    "window_end": "2025-03-01T10:00:00Z",
    "criteria": {
      "orphan_grace_period_seconds": 86400,
      "consecutive_failure_threshold": 3,
      "stale_failure_age_seconds": 604800,
      "ignored_pause_age_seconds": 2592000
    },
    "orphaned_count": 1,
    "failing_count": 2,
    "ignored_count": 0,
    "created_at": "2025-03-01T10:00:01Z"
  },
  "review_items": [
    {
      "id": 913,
      "review_output_id": 42,
      "schedule_id": 77,
      "task_intent_id": 55,
      "execution_id": 901,
      "issue_type": "failing",
      "severity": "medium",
      "description": "Schedule failing. Count: 3, Last status: failed",
      "last_error_message": "Downstream error",
      "created_at": "2025-03-01T10:00:01Z"
    }
  ]
}
```

## Response Workflow
1. Start with the latest review output summary and note the criteria values used.
2. Inspect each review item and open linked schedule/execution records via the inspection API.
3. Respond based on issue type:
   - Orphaned (high): verify scheduler health, check `next_run_at`, and consider rescheduling or
     run-now to restore forward progress.
   - Failing (medium): review execution audit logs and `last_error_message`, then fix root cause
     before resuming or re-running.
   - Ignored (low): decide whether to resume, archive, or delete the paused schedule.
4. Any outbound notifications or reminders must go through the Attention Router and respect
   quiet hours and batching. No automatic remediation is performed by the review job.

## Security and Attention Notes
- Review outputs are read-only artifacts; they do not mutate schedules.
- Schedule changes require a human or system actor context (never the scheduled actor).
- Notifications derived from review findings must be routed through attention policies.
