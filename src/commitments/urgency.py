"""Urgency calculation per PRD §6.6.3 (experimental)."""

from __future__ import annotations

from datetime import datetime, timedelta

_EFFORT_HOURS = {
    1: 0.5,
    2: 2.0,
    3: 8.0,
}


def compute_urgency(
    importance: int,
    effort: int,
    due_by: datetime | None,
    now: datetime,
) -> int:
    """Compute a 1-100 urgency score from importance, effort, and time pressure."""
    effective_due_by = due_by or (now + timedelta(days=7))
    effort_hours = _EFFORT_HOURS.get(effort, float(effort))
    time_left_hours = max(0.0, (effective_due_by - now).total_seconds() / 3600.0)
    time_pressure = 1 - (time_left_hours / max(1.0, effort_hours * 4.0))
    time_pressure = max(0.0, min(1.0, time_pressure))

    base_importance = importance / 3
    base_effort = effort / 3
    urgency_raw = (0.4 * base_importance) + (0.4 * time_pressure) + (0.2 * base_effort)
    urgency = round(1 + (urgency_raw * 99))
    return max(1, min(100, urgency))
