"""Unit tests for ingestion commitment hook source mapping and proposal routing."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from types import SimpleNamespace
from typing import Any, cast
from uuid import UUID, uuid4

import pytest
from sqlalchemy.orm import sessionmaker

from attention.router import AttentionRouter, RoutingResult
from commitments.creation_authority import CommitmentCreationSource, CreationApprovalProposal
from commitments.creation_service import (
    CommitmentCreationApprovalRequired,
    CommitmentCreationDedupeRequired,
    CommitmentCreationSuccess,
)
from commitments.dedupe import DedupeCandidate, DedupeProposal
from commitments.ingestion_hook import _build_ingest_source_context, _process_record
from commitments.notifications import CommitmentNotificationType
from models import Artifact, ProvenanceRecord, ProvenanceSource


@dataclass(frozen=True)
class _StubSource:
    """Test stub that mimics provenance source attributes used by the hook."""

    source_actor: str | None
    source_type: str
    source_uri: str | None


class _CreationServiceStub:
    """Creation service stub that returns pre-seeded results in order."""

    def __init__(self, results: list[object]) -> None:
        self._results = list(results)

    def create(self, request):  # noqa: ANN001
        """Return the next seeded creation result."""
        if not self._results:
            raise AssertionError("No seeded creation result available.")
        return self._results.pop(0)


class _ProgressServiceStub:
    """Progress service stub that records progress calls for assertions."""

    def __init__(self) -> None:
        self.calls: list[dict[str, object]] = []

    def record_progress(self, **kwargs: object) -> None:
        """Capture progress payloads."""
        self.calls.append(kwargs)


class _ObjectStoreStub:
    """Object store stub returning static bytes by key."""

    def __init__(self, payloads: dict[str, bytes]) -> None:
        self._payloads = payloads

    def read(self, object_key: str) -> bytes:
        """Return object bytes for the provided key."""
        return self._payloads[object_key]


def test_build_ingest_source_context_defaults_when_sources_missing() -> None:
    """Missing provenance sources should still set intake channel to ingest."""
    context = _build_ingest_source_context([])

    assert context.intake_channel == "ingest"
    assert context.source_actor is None
    assert context.source_medium is None
    assert context.source_uri is None


def test_build_ingest_source_context_uses_primary_source() -> None:
    """Primary provenance source should populate actor, medium, and URI."""
    context = _build_ingest_source_context(
        [
            _StubSource(
                source_actor="user@example.com",
                source_type="email",
                source_uri="mailto:user@example.com",
            )
        ]
    )

    assert context.intake_channel == "ingest"
    assert context.source_actor == "user@example.com"
    assert context.source_medium == "email"
    assert context.source_uri == "mailto:user@example.com"


def test_dedupe_required_routes_proposal_notification(
    sqlite_session_factory: sessionmaker,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Dedupe-required outcomes should route through commitment notifications."""
    ingestion_id, record = _seed_record(sqlite_session_factory)
    dedupe_result = CommitmentCreationDedupeRequired(
        status="dedupe_required",
        proposal=DedupeProposal(
            candidate=DedupeCandidate(
                commitment_id=11,
                description="Book dentist appointment",
            ),
            confidence=0.92,
            summary="Likely duplicate.",
            threshold=0.85,
        ),
    )
    captured_notifications: list[object] = []

    monkeypatch.setattr(
        "commitments.ingestion_hook.extract_commitments_from_text",
        lambda _text, client=None: [{"description": "Schedule dentist visit"}],  # noqa: ARG005
    )

    def _capture_submit(_router, notification, **_kwargs):  # noqa: ANN001
        captured_notifications.append(notification)
        return RoutingResult(decision="NOTIFY:signal", channel="signal")

    monkeypatch.setattr(
        "commitments.creation_proposal_notifications.submit_commitment_notification",
        _capture_submit,
    )

    _process_record(
        record=record,
        ingestion_id=ingestion_id,
        creation_service=_CreationServiceStub([dedupe_result]),
        progress_service=_ProgressServiceStub(),
        object_store=_ObjectStoreStub({str(record.object_key): b"Plan dentist follow-up."}),
        session_factory=sqlite_session_factory,
        llm_client=None,
        router=cast(AttentionRouter, object()),
    )

    assert len(captured_notifications) == 1
    notification = captured_notifications[0]
    assert notification.notification_type == CommitmentNotificationType.DEDUPE_PROPOSAL
    assert notification.signal_reference.startswith("commitment.dedupe_proposal:ingest:dedupe:")
    input_types = [item.input_type for item in notification.provenance]
    assert input_types == ["proposal_ref", "ingestion", "artifact"]
    assert notification.provenance[1].reference == str(ingestion_id)
    assert notification.provenance[2].reference == record.object_key


def test_approval_required_routes_proposal_notification(
    sqlite_session_factory: sessionmaker,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Approval-required outcomes should route through commitment notifications."""
    ingestion_id, record = _seed_record(sqlite_session_factory)
    approval_result = CommitmentCreationApprovalRequired(
        status="approval_required",
        proposal=CreationApprovalProposal(
            source=CommitmentCreationSource.AGENT,
            confidence=0.35,
            threshold=0.8,
            reason="agent_suggested_below_threshold",
        ),
    )
    captured_notifications: list[object] = []

    monkeypatch.setattr(
        "commitments.ingestion_hook.extract_commitments_from_text",
        lambda _text, client=None: [{"description": "Remember this possible task"}],  # noqa: ARG005
    )

    def _capture_submit(_router, notification, **_kwargs):  # noqa: ANN001
        captured_notifications.append(notification)
        return RoutingResult(decision="NOTIFY:signal", channel="signal")

    monkeypatch.setattr(
        "commitments.creation_proposal_notifications.submit_commitment_notification",
        _capture_submit,
    )

    _process_record(
        record=record,
        ingestion_id=ingestion_id,
        creation_service=_CreationServiceStub([approval_result]),
        progress_service=_ProgressServiceStub(),
        object_store=_ObjectStoreStub(
            {str(record.object_key): b"An uncertain extracted commitment."}
        ),
        session_factory=sqlite_session_factory,
        llm_client=None,
        router=cast(AttentionRouter, object()),
    )

    assert len(captured_notifications) == 1
    notification = captured_notifications[0]
    assert notification.notification_type == CommitmentNotificationType.CREATION_APPROVAL_PROPOSAL
    assert notification.commitment_id is None
    assert notification.signal_reference.startswith(
        "commitment.creation_approval_proposal:ingest:approval:"
    )
    input_types = [item.input_type for item in notification.provenance]
    assert input_types == ["proposal_ref", "ingestion", "artifact"]


def test_notification_failure_does_not_abort_remaining_extractions(
    sqlite_session_factory: sessionmaker,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Routing failures for one extraction should not block later extraction processing."""
    ingestion_id, record = _seed_record(sqlite_session_factory)
    progress = _ProgressServiceStub()
    success_result = CommitmentCreationSuccess(
        status="success",
        commitment=SimpleNamespace(commitment_id=22, description="Second commitment"),
        schedule_id=None,
        provenance_id=None,
    )
    dedupe_result = CommitmentCreationDedupeRequired(
        status="dedupe_required",
        proposal=DedupeProposal(
            candidate=DedupeCandidate(commitment_id=10, description="Existing"),
            confidence=0.91,
            summary="duplicate",
            threshold=0.8,
        ),
    )

    monkeypatch.setattr(
        "commitments.ingestion_hook.extract_commitments_from_text",
        lambda _text, client=None: [  # noqa: ARG005
            {"description": "First extracted commitment"},
            {"description": "Second extracted commitment"},
        ],
    )

    def _raise_submit(_router, _notification, **_kwargs):  # noqa: ANN001
        raise RuntimeError("router unavailable")

    monkeypatch.setattr(
        "commitments.creation_proposal_notifications.submit_commitment_notification",
        _raise_submit,
    )

    _process_record(
        record=record,
        ingestion_id=ingestion_id,
        creation_service=_CreationServiceStub([dedupe_result, success_result]),
        progress_service=progress,
        object_store=_ObjectStoreStub({str(record.object_key): b"Two extracted commitments"}),
        session_factory=sqlite_session_factory,
        llm_client=None,
        router=cast(AttentionRouter, object()),
    )

    assert len(progress.calls) == 1
    assert progress.calls[0]["commitment_id"] == 22
    metadata = cast(dict[str, Any], progress.calls[0]["metadata"])
    assert metadata["intake_channel"] == "ingest"


def _seed_record(factory: sessionmaker) -> tuple[UUID, ProvenanceRecord]:
    """Seed minimal artifact and provenance rows for ingestion hook tests."""
    now = datetime(2026, 1, 1, 12, 0, tzinfo=timezone.utc)
    ingestion_id = uuid4()
    object_key = "ingest/object-1"
    with factory() as session:
        artifact = Artifact(
            object_key=object_key,
            size_bytes=12,
            mime_type="text/plain",
            checksum="abc123",
            artifact_type="raw",
            first_ingested_at=now,
            last_ingested_at=now,
        )
        record = ProvenanceRecord(
            object_key=object_key,
            created_at=now,
            updated_at=now,
        )
        session.add(artifact)
        session.add(record)
        session.flush()
        source = ProvenanceSource(
            provenance_id=record.id,
            ingestion_id=ingestion_id,
            source_type="email",
            source_uri="mailto:user@example.com",
            source_actor="user@example.com",
            captured_at=now,
        )
        session.add(source)
        session.commit()
        session.refresh(record)
        return ingestion_id, record
