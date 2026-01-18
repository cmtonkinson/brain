"""Integration tests for attention decision record retrieval."""

from __future__ import annotations

from contextlib import closing

from sqlalchemy.orm import sessionmaker

from attention.decision_records import (
    DecisionRecordInput,
    get_decision_by_signal,
    persist_decision_record,
)


def test_decision_record_retrievable_by_signal_id(
    sqlite_session_factory: sessionmaker,
) -> None:
    """Ensure decision records are retrievable by signal reference."""
    session_factory = sqlite_session_factory
    with closing(session_factory()) as session:
        persist_decision_record(
            session,
            DecisionRecordInput(
                signal_reference="signal-1",
                channel="signal",
                base_assessment="NOTIFY",
                policy_outcome=None,
                final_decision="NOTIFY:signal",
                explanation="ok",
            ),
        )
        session.commit()

        record = get_decision_by_signal(session, "signal-1")

    assert record is not None
    assert record.signal_reference == "signal-1"
