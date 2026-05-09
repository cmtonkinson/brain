"""Shared busywait helper for background approval-gated op calls."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
import random
import time

from lib.sdk.errors import BrainPolicyError


@dataclass(frozen=True, slots=True)
class ApprovalRequired:
    """Approval proposal metadata extracted from a Policy error."""

    proposal_token: str
    expires_at: str


class ApprovalWaitRejected(RuntimeError):
    """Raised when an operator rejects an approval proposal."""


class ApprovalWaitExpired(RuntimeError):
    """Raised when approval waiting reaches expiry before approval."""


def approval_required_from_error(exc: BrainPolicyError) -> ApprovalRequired | None:
    """Return approval metadata when a Policy error requests approval."""
    for detail in exc.details:
        reason_codes = detail.metadata.get("reason_codes", "")
        token = detail.metadata.get("proposal_token", "").strip()
        if token and "approval_required" in reason_codes.split(","):
            return ApprovalRequired(
                proposal_token=token,
                expires_at=detail.metadata.get("expires_at", ""),
            )
    return None


def wait_for_approval(
    *,
    client: object,
    approval: ApprovalRequired,
    poll_interval_seconds: float = 2.0,
    poll_max_interval_seconds: float = 5.0,
) -> str:
    """Poll Policy until a proposal is approved, rejected, or expired."""
    deadline = _parse_deadline(approval.expires_at)
    interval = max(0.1, poll_interval_seconds)
    max_interval = max(interval, poll_max_interval_seconds)
    while True:
        status = client.policy_approval_status(  # type: ignore[attr-defined]
            proposal_token=approval.proposal_token
        )
        if status.status == "approved":
            return approval.proposal_token
        if status.status in {"rejected", "consumed"}:
            raise ApprovalWaitRejected(
                f"approval {status.status}: {approval.proposal_token}"
            )
        if status.status in {"expired", "missing"}:
            raise ApprovalWaitExpired(
                f"approval {status.status}: {approval.proposal_token}"
            )
        now = time.time()
        if deadline is not None and now >= deadline:
            raise ApprovalWaitExpired(f"approval expired: {approval.proposal_token}")
        sleep_seconds = min(interval, max_interval)
        if deadline is not None:
            sleep_seconds = min(sleep_seconds, max(0.0, deadline - now))
        time.sleep(sleep_seconds + random.uniform(0.0, min(0.25, sleep_seconds / 4)))
        interval = min(max_interval, interval * 1.25)


def _parse_deadline(value: str) -> float | None:
    if value.strip() == "":
        return None
    try:
        return datetime.fromisoformat(value).timestamp()
    except ValueError:
        return None
