"""Functional tests for the indexer pipeline with stubbed services."""

from __future__ import annotations

from collections.abc import Generator
from dataclasses import dataclass
from pathlib import Path

import pytest
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import sessionmaker

from indexer import chunk_markdown, file_hash, index_vault
from models import Base, IndexedChunk, IndexedNote


@dataclass
class UpsertCall:
    """Captured Qdrant upsert call payload."""

    collection: str
    points: list[object]


class StubQdrantClient:
    """Qdrant stub capturing collections and upserts."""

    def __init__(self) -> None:
        """Initialize stub storage."""
        self.collections: set[str] = set()
        self.upserts: list[UpsertCall] = []
        self.deleted_collections: list[str] = []
        self.deleted_points: list[tuple[str, object]] = []

    def collection_exists(self, collection: str) -> bool:
        """Return True if the collection exists."""
        return collection in self.collections

    def create_collection(self, collection_name: str, vectors_config: object) -> None:
        """Create a collection in the stub."""
        self.collections.add(collection_name)

    def delete_collection(self, collection: str) -> None:
        """Delete a collection in the stub."""
        self.deleted_collections.append(collection)
        self.collections.discard(collection)

    def upsert(self, collection_name: str, points: list[object]) -> None:
        """Store upsert calls and mark collection as present."""
        self.collections.add(collection_name)
        self.upserts.append(UpsertCall(collection=collection_name, points=points))

    def delete(self, collection_name: str, points_selector: object) -> None:
        """Record deletions for note points."""
        self.deleted_points.append((collection_name, points_selector))


def _write_note(vault: Path, name: str, content: str) -> None:
    """Write a markdown note into the vault."""
    note_path = vault / name
    note_path.parent.mkdir(parents=True, exist_ok=True)
    note_path.write_text(content, encoding="utf-8")


@pytest.fixture()
def sqlite_session_factory(tmp_path: Path) -> Generator[sessionmaker, None, None]:
    """Provide a sqlite session factory backed by a temp file."""
    db_path = tmp_path / "indexer.db"
    engine = create_engine(f"sqlite:///{db_path}")
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine)
    yield factory
    engine.dispose()


def _patch_indexer(monkeypatch, session_factory: sessionmaker, qdrant: StubQdrantClient) -> None:
    """Patch indexer dependencies to use sqlite and a stubbed Qdrant client."""
    monkeypatch.setattr("indexer.get_sync_session", lambda: session_factory())
    monkeypatch.setattr("indexer.QdrantClient", lambda url: qdrant)
    monkeypatch.setattr("indexer.embed_text", lambda client, text, model: [0.1, 0.2, 0.3])


def test_indexer_indexes_notes_and_chunks(
    tmp_path: Path,
    monkeypatch,
    sqlite_session_factory: sessionmaker,
) -> None:
    """Indexing writes Qdrant points and DB metadata for a note."""
    vault = tmp_path / "vault"
    vault.mkdir()
    content = "# Title\n\nParagraph one.\n\nParagraph two."
    _write_note(vault, "Note.md", content)

    session_factory = sqlite_session_factory
    qdrant = StubQdrantClient()
    _patch_indexer(monkeypatch, session_factory, qdrant)

    index_vault(
        vault_path=str(vault),
        collection="test",
        embed_model="embed-model",
        max_tokens=100,
        full_reindex=False,
        run_migrations=False,
    )

    chunks = chunk_markdown(content, max_tokens=100)
    assert qdrant.upserts
    points = qdrant.upserts[0].points
    assert len(points) == len(chunks)
    payload = points[0].payload
    assert payload["path"] == "Note.md"
    assert payload["chunk_total"] == len(chunks)
    assert payload["text"]

    session = session_factory()
    try:
        note = session.scalar(select(IndexedNote).where(IndexedNote.path == "Note.md"))
        assert note is not None
        assert note.chunk_count == len(chunks)
        assert note.content_hash == file_hash(content)
        chunk_count = session.scalar(
            select(func.count()).select_from(IndexedChunk).where(IndexedChunk.note_id == note.id)
        )
        assert chunk_count == len(chunks)
    finally:
        session.close()


def test_indexer_skips_unchanged_notes(
    tmp_path: Path,
    monkeypatch,
    sqlite_session_factory: sessionmaker,
) -> None:
    """Reindexing unchanged content avoids additional upserts."""
    vault = tmp_path / "vault"
    vault.mkdir()
    content = "# Title\n\nSame content."
    _write_note(vault, "Note.md", content)

    session_factory = sqlite_session_factory
    qdrant = StubQdrantClient()
    _patch_indexer(monkeypatch, session_factory, qdrant)

    index_vault(
        vault_path=str(vault),
        collection="test",
        embed_model="embed-model",
        max_tokens=100,
        full_reindex=False,
        run_migrations=False,
    )
    index_vault(
        vault_path=str(vault),
        collection="test",
        embed_model="embed-model",
        max_tokens=100,
        full_reindex=False,
        run_migrations=False,
    )

    assert len(qdrant.upserts) == 1


def test_indexer_full_reindex_deletes_collection(
    tmp_path: Path,
    monkeypatch,
    sqlite_session_factory: sessionmaker,
) -> None:
    """Full reindex deletes the existing collection before rebuilding."""
    vault = tmp_path / "vault"
    vault.mkdir()
    _write_note(vault, "Note.md", "# Title\n\nContent.")

    session_factory = sqlite_session_factory
    qdrant = StubQdrantClient()
    _patch_indexer(monkeypatch, session_factory, qdrant)

    index_vault(
        vault_path=str(vault),
        collection="test",
        embed_model="embed-model",
        max_tokens=100,
        full_reindex=False,
        run_migrations=False,
    )
    index_vault(
        vault_path=str(vault),
        collection="test",
        embed_model="embed-model",
        max_tokens=100,
        full_reindex=True,
        run_migrations=False,
    )

    assert "test" in qdrant.deleted_collections
