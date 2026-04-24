"""Policy data source: polls approvals and policy_decisions tables."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict

from lib.dashboard.data_sources.postgres import (
    BasePostgresDataSource,
    PostgresConnectionConfig,
)
from lib.dashboard.models.data_source import RetentionPolicy
from lib.dashboard.models.policy import (
    CurrentApprovalView,
    CurrentDecisionView,
    RecentPolicyItemView,
)

_RECENT_LIMIT = 20


class PolicySnapshot(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    approval: CurrentApprovalView | None = None
    decision: CurrentDecisionView | None = None
    recent: tuple[RecentPolicyItemView, ...] = ()


class PolicyDataSource(BasePostgresDataSource[PolicySnapshot]):
    def __init__(self, config: PostgresConnectionConfig, poll_interval: float) -> None:
        super().__init__(
            config=config,
            poll_interval=poll_interval,
            retention=RetentionPolicy(family="snapshot", max_items=50),
        )

    def _fetch(self) -> PolicySnapshot | None:  # type: ignore[override]
        conn = self._get_connection()
        with conn.cursor() as cur:
            # Newest pending approval
            cur.execute(
                """
                SELECT status, op_id, actor, channel, summary, created_at, expires_at
                FROM service_policy.approvals
                WHERE status = 'pending' AND expires_at > now()
                ORDER BY created_at DESC
                LIMIT 1
                """
            )
            approval_row = cur.fetchone()

            # Most recent policy decision
            cur.execute(
                """
                SELECT op_id, actor, channel, allowed, created_at
                FROM service_policy.policy_decisions
                ORDER BY created_at DESC
                LIMIT 1
                """
            )
            decision_row = cur.fetchone()

            # Recent list: union of approvals + decisions, newest first
            cur.execute(
                """
                SELECT created_at, status AS state, op_id
                FROM service_policy.approvals
                UNION ALL
                SELECT created_at,
                       CASE WHEN allowed THEN 'allowed' ELSE 'denied' END,
                       op_id
                FROM service_policy.policy_decisions
                ORDER BY created_at DESC
                LIMIT %s
                """,
                (_RECENT_LIMIT,),
            )
            recent_rows = cur.fetchall()

        approval: CurrentApprovalView | None = None
        if approval_row:
            approval = CurrentApprovalView(
                state=approval_row[0],
                op_id=approval_row[1],
                actor=approval_row[2],
                channel=approval_row[3],
                summary=approval_row[4],
                requested_at=approval_row[5],
                expires_at=approval_row[6],
            )

        decision: CurrentDecisionView | None = None
        if decision_row:
            cap_id, actor, channel, allowed, created_at = decision_row
            decision = CurrentDecisionView(
                op_id=cap_id,
                actor=actor,
                channel=channel,
                state="allowed" if allowed else "denied",
                decided_at=created_at,
            )

        recent = tuple(
            RecentPolicyItemView(
                timestamp=r[0],
                state=r[1],
                op_id=r[2],
            )
            for r in recent_rows
        )

        return PolicySnapshot(approval=approval, decision=decision, recent=recent)
