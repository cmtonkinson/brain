"""Policy pane: current approval/decision state and recent history."""

from __future__ import annotations

from textual.app import ComposeResult
from textual.widgets import Static

from packages.dashboard.data_sources.policy import PolicyDataSource
from packages.dashboard.models.policy import (
    CurrentApprovalView,
    CurrentDecisionView,
    RecentPolicyItemView,
)
from packages.dashboard.panes.base import BaseView

_RECENT_MAX = 8
_MIN_HEIGHT_FOR_RECENT = 12


class PolicyPane(BaseView):
    """Current approval/decision state with compact recent history."""

    view_id = "policy"
    view_title = "Policy"

    DEFAULT_CSS = """
    PolicyPane { layout: vertical; height: 1fr; }
    PolicyPane > #policy-current { height: auto; }
    PolicyPane > #policy-recent { height: 1fr; }
    """

    def __init__(
        self,
        policy_source: PolicyDataSource | None = None,
        approval: CurrentApprovalView | None = None,
        decision: CurrentDecisionView | None = None,
        recent: list[RecentPolicyItemView] | None = None,
        **kwargs,
    ) -> None:
        super().__init__(**kwargs)
        self._policy_source = policy_source
        self._approval = approval
        self._decision = decision
        self._recent: list[RecentPolicyItemView] = recent or []

    def compose(self) -> ComposeResult:
        yield Static(self._render_current(), id="policy-current")
        yield Static(self._render_recent(), id="policy-recent")

    def on_mount(self) -> None:
        self.set_interval(2.0, self._refresh_from_source)

    def _refresh_from_source(self) -> None:
        if self._policy_source is None:
            return
        snapshot = self._policy_source.get_current()
        if snapshot is None:
            return
        self.refresh_data(
            approval=snapshot.approval,
            decision=snapshot.decision,
            recent=snapshot.recent,
        )

    def refresh_data(
        self,
        approval: CurrentApprovalView | None,
        decision: CurrentDecisionView | None,
        recent: list[RecentPolicyItemView],
    ) -> None:
        self._approval = approval
        self._decision = decision
        self._recent = recent
        try:
            self.query_one("#policy-current", Static).update(self._render_current())
            self.query_one("#policy-recent", Static).update(self._render_recent())
        except Exception:
            pass

    def _render_current(self) -> str:
        if self._approval is not None:
            a = self._approval
            req = a.requested_at.strftime("%H:%M:%S")
            exp = a.expires_at.strftime("%H:%M:%S")
            return (
                "Current\n"
                f"State       {a.state}\n"
                f"Capability  {a.capability_id}\n"
                f"Actor       {a.actor}\n"
                f"Channel     {a.channel}\n"
                f"Summary     {a.summary}\n"
                f"Requested   {req}\n"
                f"Expires     {exp}"
            )
        if self._decision is not None:
            d = self._decision
            ts = d.decided_at.strftime("%H:%M:%S")
            return (
                "Current\n"
                f"State       {d.state}\n"
                f"Capability  {d.capability_id}\n"
                f"Actor       {d.actor}\n"
                f"Channel     {d.channel}\n"
                f"Decided     {ts}"
            )
        return "Current\n—"

    def _render_recent(self) -> str:
        if not self._recent:
            return ""
        lines = ["Recent"]
        for item in self._recent[:_RECENT_MAX]:
            ts = item.timestamp.strftime("%H:%M:%S")
            cap = item.capability_id[:30]
            lines.append(f"{ts}  {item.state:<8}  {cap}")
        return "\n".join(lines)
