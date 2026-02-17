"""Unit tests covering Stage 4 attachment materialization behavior."""

from datetime import datetime, timezone
from pathlib import Path

from config import settings
from ingestion.stages.anchor import run_stage4_anchor
from models import (
    Artifact,
    ExtractionMetadata,
    Ingestion,
    IngestionArtifact,
    NormalizationMetadata,
)
from services.object_store import ObjectStore


class _MockObsidianClient:
    """Simplified async Obsidian client for anchoring tests."""

    def __init__(self) -> None:
        self.notes: dict[str, str] = {}

    async def note_exists(self, path: str) -> bool:
        return path in self.notes

    async def create_note(self, path: str, content: str) -> dict[str, str]:
        self.notes[path] = content
        return {"path": path}

    async def append_to_note(self, path: str, content: str) -> dict[str, str]:
        if path not in self.notes:
            raise FileNotFoundError(path)
        self.notes[path] = self.notes[path] + content
        return {"path": path}


def _expected_note_path(ingestion_id) -> str:
    """Compute the anchor note path that Stage 4 uses for an ingestion."""
    root = (settings.obsidian.root_folder or "").strip("/")
    segments = [segment for segment in (root, "anchors") if segment]
    segments.append(f"ingestion-{ingestion_id}.md")
    return "/".join(segments)


def _create_ingestion(session_factory, *, now: datetime) -> Ingestion:
    with session_factory() as session:
        ingestion = Ingestion(
            source_type="test",
            source_uri="test://source",
            source_actor="actor",
            created_at=now,
            status="queued",
            last_error=None,
        )
        session.add(ingestion)
        session.commit()
        session.refresh(ingestion)
        return ingestion


def _insert_artifact(
    session_factory,
    object_key: str,
    *,
    artifact_type: str,
    mime_type: str | None,
    parent_object_key: str | None,
    parent_stage: str | None,
    created_at: datetime,
) -> None:
    with session_factory() as session:
        session.add(
            Artifact(
                object_key=object_key,
                created_at=created_at,
                size_bytes=0,
                mime_type=mime_type,
                checksum="deadbeef",
                artifact_type=artifact_type,
                first_ingested_at=created_at,
                last_ingested_at=created_at,
                parent_object_key=parent_object_key,
                parent_stage=parent_stage,
            )
        )
        session.commit()


def _insert_ingestion_artifact(
    session_factory,
    ingestion_id,
    *,
    object_key: str,
    stage: str,
    status: str,
    created_at: datetime,
) -> None:
    with session_factory() as session:
        session.add(
            IngestionArtifact(
                ingestion_id=ingestion_id,
                stage=stage,
                object_key=object_key,
                created_at=created_at,
                status=status,
                error=None,
            )
        )
        session.commit()


def _insert_normalization_metadata(
    session_factory,
    object_key: str,
    *,
    now: datetime,
) -> None:
    with session_factory() as session:
        session.add(
            NormalizationMetadata(
                object_key=object_key,
                method="canonical_markdown",
                confidence=0.9,
                tool_metadata={"tags": ["visual"]},
                created_at=now,
                updated_at=now,
            )
        )
        session.commit()


def _insert_extraction_metadata(
    session_factory,
    object_key: str,
    *,
    now: datetime,
) -> None:
    with session_factory() as session:
        session.add(
            ExtractionMetadata(
                object_key=object_key,
                method="ocr",
                confidence=0.8,
                page_count=1,
                tool_metadata={"categories": ["attachments"]},
                created_at=now,
                updated_at=now,
            )
        )
        session.commit()


def _run_anchor(
    *,
    tmp_path: Path,
    sqlite_session_factory,
    mime_type: str,
    payload: bytes,
) -> tuple[str, Path, dict[str, str]]:
    now = datetime(2025, 1, 2, 0, 0, tzinfo=timezone.utc)
    vault = tmp_path / "vault"
    vault.mkdir()
    original_vault_path = settings.obsidian.vault_path
    settings.obsidian.vault_path = str(vault)
    store = ObjectStore(tmp_path / "objects")
    try:
        ingestion = _create_ingestion(sqlite_session_factory, now=now)

        extracted_key = store.write(b"extracted")
        _insert_artifact(
            sqlite_session_factory,
            extracted_key,
            artifact_type="extracted",
            mime_type="text/plain",
            parent_object_key=None,
            parent_stage=None,
            created_at=now,
        )
        _insert_extraction_metadata(sqlite_session_factory, extracted_key, now=now)

        normalized_key = store.write(payload)
        _insert_artifact(
            sqlite_session_factory,
            normalized_key,
            artifact_type="normalized",
            mime_type=mime_type,
            parent_object_key=extracted_key,
            parent_stage="extract",
            created_at=now,
        )
        _insert_normalization_metadata(sqlite_session_factory, normalized_key, now=now)
        _insert_ingestion_artifact(
            sqlite_session_factory,
            ingestion.id,
            object_key=normalized_key,
            stage="normalize",
            status="success",
            created_at=now,
        )

        mock_obsidian = _MockObsidianClient()
        result = run_stage4_anchor(
            ingestion.id,
            session_factory=sqlite_session_factory,
            object_store=store,
            obsidian_client=mock_obsidian,
            now=now,
        )
    finally:
        settings.obsidian.vault_path = original_vault_path
    note_path = _expected_note_path(ingestion.id)
    return note_path, vault, (mock_obsidian.notes, normalized_key, result)


def test_attachment_materialization_embeds_visual(tmp_path, sqlite_session_factory):
    """Visual artifacts should be copied into the vault and embedded in the note."""
    note_path, vault, (notes, normalized_key, result) = _run_anchor(
        tmp_path=tmp_path,
        sqlite_session_factory=sqlite_session_factory,
        mime_type="image/png",
        payload=b"\x89PNG\r\n",
    )

    assert result.anchored_artifacts == 1
    assert result.failures == 0
    assert note_path in notes
    attachment = vault / "_attachments" / f"{normalized_key}.png"
    assert attachment.exists()
    assert f"![](_attachments/{normalized_key}.png)" in notes[note_path]


def test_attachment_materialization_skips_non_visual(tmp_path, sqlite_session_factory):
    """Non-visual artifacts are not copied but are still referenced in the anchor."""
    note_path, vault, (notes, normalized_key, result) = _run_anchor(
        tmp_path=tmp_path,
        sqlite_session_factory=sqlite_session_factory,
        mime_type="application/pdf",
        payload=b"%PDF-1.7",
    )

    assert result.anchored_artifacts == 1
    assert result.failures == 0
    assert note_path in notes
    attachment = vault / "_attachments" / f"{normalized_key}.pdf"
    assert not attachment.exists()
    assert f"object key: {normalized_key}" in notes[note_path]
