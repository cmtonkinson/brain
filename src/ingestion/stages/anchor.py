"""Stage 4 anchor runner that creates Obsidian notes and materializes visual attachments."""

from __future__ import annotations

import asyncio
import logging
from contextlib import closing
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath
from typing import Awaitable, Callable, TypeVar
from uuid import UUID

from sqlalchemy.orm import Session

from config import settings
from models import (
    AnchorNote,
    Artifact,
    ExtractionMetadata,
    Ingestion,
    IngestionArtifact,
    NormalizationMetadata,
)
from services.database import get_sync_session
from services.object_store import ObjectStore
from tools.obsidian import ObsidianClient

LOGGER = logging.getLogger(__name__)
T = TypeVar("T")


def _run_async(coro: Awaitable[T]) -> T:
    """Run an async coroutine with a fresh asyncio runner."""
    runner = asyncio.Runner()
    try:
        return runner.run(coro)
    finally:
        runner.close()


@dataclass(frozen=True)
class Stage4AnchorResult:
    """Summary of Stage 4 anchor execution outcomes."""

    ingestion_id: UUID
    anchored_artifacts: int
    failures: int
    errors: tuple[str, ...]


@dataclass(frozen=True)
class NormalizedAnchorCandidate:
    """Database-backed descriptor for normalized artifacts awaiting anchoring."""

    object_key: str
    mime_type: str | None
    created_at: datetime
    parent_object_key: str | None
    normalization_method: str | None
    normalization_confidence: float | None
    normalization_tool_metadata: dict[str, object] | None
    extraction_method: str | None
    extraction_confidence: float | None
    extraction_page_count: int | None
    extraction_tool_metadata: dict[str, object] | None


class Stage4AnchoringRunner:
    """Runner that converts normalized artifacts into Obsidian anchor notes."""

    def __init__(
        self,
        *,
        session_factory: Callable[[], Session] | None = None,
        object_store: ObjectStore | None = None,
        obsidian_client: ObsidianClient | None = None,
    ) -> None:
        """Initialize dependencies for database access, storage, and Obsidian integration."""
        self._session_factory = session_factory or get_sync_session
        self._object_store = object_store or ObjectStore(settings.objects.root_dir)
        self._obsidian_client = obsidian_client or ObsidianClient()

    def run(
        self,
        ingestion_id: UUID,
        *,
        now: datetime | None = None,
    ) -> Stage4AnchorResult:
        """Execute Stage 4 anchoring for every eligible normalized artifact."""
        timestamp = now or datetime.now(timezone.utc)
        ingestion = self._load_ingestion(ingestion_id)
        candidates = self._load_unanchored_normalized_artifacts(ingestion_id)
        if not candidates:
            return Stage4AnchorResult(
                ingestion_id=ingestion_id,
                anchored_artifacts=0,
                failures=0,
                errors=(),
            )

        note_path = self._note_path_for_ingestion(ingestion)
        note_exists = self._note_exists(note_path)
        note_created_this_run = False
        anchored = 0
        failures = 0
        errors: list[str] = []

        for index, candidate in enumerate(candidates, start=1):
            payload = self._object_store.read(candidate.object_key)
            try:
                section = self._build_artifact_section(
                    candidate=candidate,
                    ingestion=ingestion,
                    payload=payload,
                    sequence=index,
                )
                if not note_exists and not note_created_this_run:
                    content = f"{self._build_intro(ingestion, timestamp)}{section}"
                    self._create_note(note_path, content)
                    note_created_this_run = True
                    note_exists = True
                else:
                    appended = f"\n\n---\n\n{section}"
                    self._append_note(note_path, appended)
            except Exception as exc:
                message = f"artifact={candidate.object_key} error={exc}"
                LOGGER.exception("Failed to write anchor note section: %s", message)
                errors.append(message)
                failures += 1
                self._record_ingestion_failure(
                    ingestion_id, candidate.object_key, message, timestamp
                )
                continue
            try:
                self._persist_anchor_note(ingestion_id, candidate.object_key, note_path, timestamp)
                self._record_ingestion_success(ingestion_id, candidate.object_key, timestamp)
                anchored += 1
            except Exception as exc:
                message = f"artifact={candidate.object_key} error={exc}"
                LOGGER.exception("Failed to persist anchor metadata: %s", message)
                errors.append(message)
                failures += 1
                self._record_ingestion_failure(
                    ingestion_id, candidate.object_key, message, timestamp
                )
        return Stage4AnchorResult(
            ingestion_id=ingestion_id,
            anchored_artifacts=anchored,
            failures=failures,
            errors=tuple(errors),
        )

    def _load_ingestion(self, ingestion_id: UUID) -> Ingestion:
        """Load ingestion metadata used for note context."""
        with closing(self._session_factory()) as session:
            ingestion = session.query(Ingestion).filter(Ingestion.id == ingestion_id).first()
            if ingestion is None:
                raise ValueError(f"ingestion not found: {ingestion_id}")
            return ingestion

    def _load_unanchored_normalized_artifacts(
        self,
        ingestion_id: UUID,
    ) -> list[NormalizedAnchorCandidate]:
        """Return normalized artifacts that have not yet been anchored."""
        with closing(self._session_factory()) as session:
            rows = (
                session.query(
                    Artifact,
                    NormalizationMetadata,
                    ExtractionMetadata,
                )
                .join(
                    IngestionArtifact,
                    Artifact.object_key == IngestionArtifact.object_key,
                )
                .outerjoin(
                    AnchorNote,
                    AnchorNote.normalized_object_key == Artifact.object_key,
                )
                .outerjoin(
                    NormalizationMetadata,
                    NormalizationMetadata.object_key == Artifact.object_key,
                )
                .outerjoin(
                    ExtractionMetadata,
                    ExtractionMetadata.object_key == Artifact.parent_object_key,
                )
                .filter(
                    IngestionArtifact.ingestion_id == ingestion_id,
                    IngestionArtifact.stage == "normalize",
                    IngestionArtifact.status.in_(("success", "skipped")),
                    IngestionArtifact.object_key.is_not(None),
                    AnchorNote.normalized_object_key.is_(None),
                )
                .order_by(Artifact.created_at)
                .all()
            )
        candidates: list[NormalizedAnchorCandidate] = []
        for artifact, norm_meta, extraction_meta in rows:
            candidates.append(
                NormalizedAnchorCandidate(
                    object_key=artifact.object_key,
                    mime_type=artifact.mime_type,
                    created_at=artifact.created_at,
                    parent_object_key=artifact.parent_object_key,
                    normalization_method=(norm_meta.method if norm_meta else None),
                    normalization_confidence=(norm_meta.confidence if norm_meta else None),
                    normalization_tool_metadata=(norm_meta.tool_metadata if norm_meta else None),
                    extraction_method=(extraction_meta.method if extraction_meta else None),
                    extraction_confidence=(extraction_meta.confidence if extraction_meta else None),
                    extraction_page_count=(extraction_meta.page_count if extraction_meta else None),
                    extraction_tool_metadata=(
                        extraction_meta.tool_metadata if extraction_meta else None
                    ),
                )
            )
        return candidates

    def _note_path_for_ingestion(self, ingestion: Ingestion) -> str:
        """Return the deterministic anchor note path for the ingestion."""
        root = (settings.obsidian.root_folder or "").strip("/")
        anchor_folder = "anchors"
        base_segments = [segment for segment in (root, anchor_folder) if segment]
        base_path = "/".join(base_segments) if base_segments else anchor_folder
        return f"{base_path}/ingestion-{ingestion.id}.md"

    def _build_intro(self, ingestion: Ingestion, timestamp: datetime) -> str:
        """Build the anchor note introduction containing ingestion metadata."""
        created = ingestion.created_at.astimezone(timezone.utc).isoformat()
        rendered_timestamp = timestamp.astimezone(timezone.utc).isoformat()
        lines = [
            f"# Anchor Note: {ingestion.id}",
            f"**Source Type:** {ingestion.source_type}",
            f"**Source URI:** {ingestion.source_uri or 'unknown'}",
            f"**Source Actor:** {ingestion.source_actor or 'unknown'}",
            f"**Ingestion Created:** {created}",
            f"**Anchor Run:** {rendered_timestamp}",
            "",
            "---",
            "",
        ]
        return "\n".join(lines)

    def _build_artifact_section(
        self,
        *,
        candidate: NormalizedAnchorCandidate,
        ingestion: Ingestion,
        payload: bytes,
        sequence: int,
    ) -> str:
        """Render the Markdown section for a single normalized artifact."""
        sections: list[str] = []
        sections.append(f"## Artifact {sequence}")
        normalized_ts = candidate.created_at.astimezone(timezone.utc).isoformat()
        sections.append(f"**Normalized Object Key:** {candidate.object_key}")
        sections.append(f"**Normalized MIME Type:** {candidate.mime_type or 'unknown'}")
        sections.append(f"**Normalized At:** {normalized_ts}")
        sections.append(f"**Normalization Method:** {candidate.normalization_method or 'unknown'}")
        sections.append(
            f"**Normalization Confidence:** {self._format_confidence(candidate.normalization_confidence)}"
        )
        sections.append(f"**Extraction Method:** {candidate.extraction_method or 'unknown'}")
        sections.append(
            f"**Extraction Confidence:** {self._format_confidence(candidate.extraction_confidence)}"
        )
        if candidate.extraction_page_count is not None:
            sections.append(f"**Extraction Page Count:** {candidate.extraction_page_count}")
        tags = self._collect_tags(
            candidate.normalization_tool_metadata, candidate.extraction_tool_metadata
        )
        if tags:
            sections.append(f"**Tags/Categories:** {', '.join(tags)}")
        attachment_path = self._materialize_attachment(
            object_key=candidate.object_key,
            payload=payload,
            mime_type=candidate.mime_type,
        )
        text_body = self._render_text_body(payload, candidate.mime_type)
        sections.append(f"**Source Type:** {ingestion.source_type}")
        sections.append(f"**Source URI:** {ingestion.source_uri or 'unknown'}")
        sections.append(f"**Source Actor:** {ingestion.source_actor or 'unknown'}")
        if attachment_path:
            sections.append("")
            sections.append(f"![]({attachment_path})")
            sections.append(f"*Attachment: {attachment_path}*")
        if text_body:
            sections.append("")
            sections.append("**Normalized Content:**")
            sections.append("")
            sections.append(text_body)
        else:
            sections.append("")
            sections.append(
                "Normalized artifact content is not rendered inline. "
                f"Refer to object key: {candidate.object_key}"
            )
        return "\n".join(sections)

    def _render_text_body(self, payload: bytes, mime_type: str | None) -> str | None:
        """Decode payload bytes into UTF-8 text for rendering when safe."""
        if mime_type and mime_type.startswith("image/"):
            return None
        lower = (mime_type or "").lower()
        if lower in {"application/pdf", "application/octet-stream"}:
            return None
        if lower and not (lower.startswith("text/") or "json" in lower or "xml" in lower):
            return None
        try:
            decoded = payload.decode("utf-8")
        except UnicodeDecodeError:
            decoded = payload.decode("utf-8", errors="replace")
        normalized = decoded.strip()
        if not normalized:
            return None
        return normalized

    def _collect_tags(
        self,
        *metadatas: (dict[str, object] | None),
    ) -> tuple[str, ...]:
        """Collect tag/category values from the supplied metadata dictionaries."""
        seen: list[str] = []
        for metadata in metadatas:
            if not isinstance(metadata, dict):
                continue
            for key in ("tags", "categories", "labels"):
                value = metadata.get(key)
                if isinstance(value, str):
                    seen.append(value)
                elif isinstance(value, (list, tuple)):
                    for entry in value:
                        if entry is not None:
                            seen.append(str(entry))
        unique = []
        for value in seen:
            if value not in unique:
                unique.append(value)
        return tuple(unique)

    def _materialize_attachment(
        self,
        *,
        object_key: str,
        payload: bytes,
        mime_type: str | None,
    ) -> str | None:
        """Copy allowlisted visual artifacts into the vault attachments directory."""
        extension = self._extension_from_mime(mime_type)
        allowlist = {entry.lower().strip() for entry in settings.anchoring.visual_allowlist}
        if not extension or extension.lower() not in allowlist:
            return None
        vault_root = Path(settings.obsidian.vault_path)
        attachment_dir = settings.anchoring.attachments_dir.strip("/")
        target_dir = vault_root / attachment_dir
        target_dir.mkdir(parents=True, exist_ok=True)
        filename = f"{object_key}.{extension}"
        target_path = target_dir / filename
        target_path.write_bytes(payload)
        rel_dir = attachment_dir or "."
        rel_path = PurePosixPath(rel_dir) / filename
        return str(rel_path).lstrip("./")

    def _extension_from_mime(self, mime_type: str | None) -> str | None:
        """Derive a filename extension from the mime type."""
        if not mime_type:
            return None
        parts = mime_type.split("/")
        if len(parts) != 2:
            return None
        subtype = parts[1].split("+")[0].lower()
        return subtype

    def _format_confidence(self, value: float | None) -> str:
        """Format confidence values to two decimal places when available."""
        if value is None:
            return "unknown"
        return f"{value:.2f}"

    def _note_exists(self, path: str) -> bool:
        """Return True when the anchor note already exists in the vault."""
        return _run_async(self._obsidian_client.note_exists(path))

    def _create_note(self, path: str, content: str) -> None:
        """Create a new anchor note with the supplied content."""
        _run_async(self._obsidian_client.create_note(path, content))

    def _append_note(self, path: str, content: str) -> None:
        """Append content to an existing anchor note."""
        _run_async(self._obsidian_client.append_to_note(path, content))

    def _persist_anchor_note(
        self,
        ingestion_id: UUID,
        object_key: str,
        note_uri: str,
        timestamp: datetime,
    ) -> None:
        """Persist the anchor note mapping for the normalized artifact."""
        with closing(self._session_factory()) as session:
            existing = (
                session.query(AnchorNote)
                .filter(AnchorNote.normalized_object_key == object_key)
                .first()
            )
            if existing is None:
                record = AnchorNote(
                    normalized_object_key=object_key,
                    ingestion_id=ingestion_id,
                    note_uri=note_uri,
                    created_at=timestamp,
                    updated_at=timestamp,
                )
                session.add(record)
            else:
                existing.note_uri = note_uri
                existing.ingestion_id = ingestion_id
                existing.updated_at = timestamp
            session.commit()

    def _record_ingestion_success(
        self,
        ingestion_id: UUID,
        object_key: str,
        timestamp: datetime,
    ) -> None:
        """Record a successful anchor outcome for the ingestion."""
        with closing(self._session_factory()) as session:
            existing = (
                session.query(IngestionArtifact)
                .filter(
                    IngestionArtifact.ingestion_id == ingestion_id,
                    IngestionArtifact.stage == "anchor",
                    IngestionArtifact.object_key == object_key,
                )
                .first()
            )
            if existing is not None:
                return
            record = IngestionArtifact(
                ingestion_id=ingestion_id,
                stage="anchor",
                object_key=object_key,
                created_at=timestamp,
                status="success",
                error=None,
            )
            session.add(record)
            session.commit()

    def _record_ingestion_failure(
        self,
        ingestion_id: UUID,
        object_key: str | None,
        error: str,
        timestamp: datetime,
    ) -> None:
        """Persist failure metadata when anchoring cannot complete."""
        with closing(self._session_factory()) as session:
            record = IngestionArtifact(
                ingestion_id=ingestion_id,
                stage="anchor",
                object_key=object_key,
                created_at=timestamp,
                status="failed",
                error=error,
            )
            session.add(record)
            session.commit()


def parse_stage4_payload(payload: dict[str, object]) -> UUID:
    """Parse the ingestion identifier out of a Stage 4 payload."""
    ingestion_id_raw = payload.get("ingestion_id")
    if not isinstance(ingestion_id_raw, str):
        raise ValueError("ingestion_id is required for Stage 4 payload")
    return UUID(ingestion_id_raw)


def run_stage4_anchor(
    ingestion_id: UUID,
    *,
    session_factory: Callable[[], Session] | None = None,
    object_store: ObjectStore | None = None,
    obsidian_client: ObsidianClient | None = None,
    now: datetime | None = None,
) -> Stage4AnchorResult:
    """Execute Stage 4 anchoring for the ingestion."""
    runner = Stage4AnchoringRunner(
        session_factory=session_factory,
        object_store=object_store,
        obsidian_client=obsidian_client,
    )
    return runner.run(ingestion_id, now=now)
