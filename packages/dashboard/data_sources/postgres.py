"""Read-only Postgres access for dashboard view models."""

from __future__ import annotations

from packages.dashboard.models import (
    HealthStatusItem,
    PolicyDecisionView,
    TraceEventView,
    TraceView,
    TurnView,
)


class PostgresDataSource:
    """Stub Postgres reader for dashboard state snapshots."""

    def fetch_health_items(self) -> tuple[HealthStatusItem, ...]:
        """Return placeholder health state derived from persisted runtime state."""
        return (
            HealthStatusItem(name="core", status="OK"),
            HealthStatusItem(name="agent", status="OK"),
            HealthStatusItem(name="pg", status="OK"),
        )

    def fetch_active_trace(self) -> TraceView:
        """Return one placeholder active trace summary."""
        return TraceView(
            trace_id="trace_stub",
            title="operator -> switchboard -> agent",
            current_step="language_model.chat_with_tools",
            events=(
                TraceEventView(
                    timestamp="14:31:58.102",
                    kind="event",
                    name="switchboard.ingest_signal",
                ),
                TraceEventView(
                    timestamp="14:31:58.140",
                    kind="call",
                    name="memory.assemble_context",
                ),
                TraceEventView(
                    timestamp="14:31:59.021",
                    kind="call",
                    name="language_model.chat_with_tools",
                ),
            ),
        )

    def fetch_turn_view(self) -> TurnView:
        """Return one placeholder turn summary."""
        return TurnView(
            inbound_text="text Chris back about tomorrow",
            phase="tool execution",
            model_name="gpt-5.4",
            provider="openai",
            context_turn_count=10,
            summary_count=24,
        )

    def fetch_policy_view(self) -> PolicyDecisionView:
        """Return one placeholder policy summary."""
        return PolicyDecisionView(
            capability_id="send-message-draft",
            autonomy_level="L1",
            decision="allowed",
            reason_codes=("in_policy", "reversible", "operator_owned"),
            approval_required=False,
        )
