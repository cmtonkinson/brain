"""Policy pane for decision, reasons, and approval state."""

from __future__ import annotations

from packages.dashboard.data_sources import PostgresDataSource
from packages.dashboard.panes.base import DashboardPane


class PolicyPane(DashboardPane):
    """Pane showing the current or selected policy decision summary."""

    pane_title = "Policy"
    pane_id = "policy"
    toggle_key = "3"

    def __init__(self, *, postgres: PostgresDataSource | None = None, **kwargs) -> None:
        """Initialize the pane with one optional Postgres reader."""
        super().__init__(**kwargs)
        self._postgres = postgres or PostgresDataSource()

    def body_text(self) -> str:
        """Render one placeholder policy summary."""
        policy = self._postgres.fetch_policy_view()
        reasons = "\n".join(f"- {reason}" for reason in policy.reason_codes)
        approval = "yes" if policy.approval_required else "no"
        return (
            f"Capability: {policy.capability_id}\n"
            f"Autonomy: {policy.autonomy_level}\n"
            f"Decision: {policy.decision}\n"
            f"Approval required: {approval}\n"
            "Reasons:\n"
            f"{reasons}"
        )
