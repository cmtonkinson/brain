"""Unit tests for CES invocation audit repository behavior."""

from __future__ import annotations

from datetime import UTC, datetime

from services.action.capability_engine.data.repository import (
    InMemoryCapabilityInvocationAuditRepository,
)
from services.action.capability_engine.domain import CapabilityInvocationAuditRow


def test_audit_repository_appends_rows_in_order() -> None:
    repo = InMemoryCapabilityInvocationAuditRepository()
    row1 = CapabilityInvocationAuditRow(
        audit_id="a1",
        envelope_id="e1",
        trace_id="t1",
        parent_id="",
        capability_id="cap-1",
        capability_version="1.0.0",
        policy_decision_id="d1",
        policy_regime_id="r1",
        allowed=True,
        reason_codes=(),
        proposal_token="",
        created_at=datetime.now(UTC),
    )
    row2 = row1.model_copy(update={"audit_id": "a2", "capability_id": "cap-2"})

    repo.append(row=row1)
    repo.append(row=row2)

    rows = repo.list_rows()
    assert rows[0].audit_id == "a1"
    assert rows[1].audit_id == "a2"
    assert repo.count() == 2
