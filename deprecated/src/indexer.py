"""Obsidian vault indexer for Qdrant vector database."""

import argparse
import hashlib
import logging
import sys
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable, Iterator

import threading
from qdrant_client import QdrantClient
from qdrant_client.http import models as qmodels

from config import settings
from models import IndexedChunk, IndexedNote
from services.database import get_sync_session, run_migrations_sync
from services.http_client import HttpClient

# Configure logging (when run standalone; agent.py overrides with force=True).
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
)

logger = logging.getLogger(__name__)

EXCLUDED_DIRS = {".smart-env", ".obsidian", ".trash", ".git"}
_LIST_PREFIXES = ("- ", "* ", "+ ")
_migrations_lock = threading.Lock()
_migrations_applied = False


def iter_markdown_files(vault: Path) -> Iterator[Path]:
    """Yield markdown files in the vault, skipping excluded directories."""
    for path in vault.rglob("*.md"):
        if any(part in EXCLUDED_DIRS for part in path.parts):
            continue
        yield path


def estimate_tokens(text: str) -> int:
    """Estimate token count using a simple character heuristic."""
    # TODO: Replace with a real tokenizer (e.g. tiktoken) once model-specific tokens matter.
    return max(1, len(text) // 4)


def _is_heading(line: str) -> tuple[int, str] | None:
    """Return the heading level and text if the line is a Markdown heading."""
    stripped = line.lstrip()
    if not stripped.startswith("#"):
        return None
    hashes = len(stripped) - len(stripped.lstrip("#"))
    if hashes < 1 or hashes > 6:
        return None
    if stripped[hashes : hashes + 1] != " ":
        return None
    return hashes, stripped.strip()


def _has_primary_heading(lines: list[str], level: int) -> bool:
    """Check whether a document contains a heading of the target level."""
    return any((_is_heading(line) or (0, ""))[0] == level for line in lines)


@dataclass
class Section:
    """Markdown section with a heading and content body."""

    heading: str
    content: str


def split_sections(text: str) -> list[Section]:
    """Split a document into top-level Markdown sections."""
    lines = text.splitlines()
    primary_level = (
        2 if _has_primary_heading(lines, 2) else 1 if _has_primary_heading(lines, 1) else None
    )
    sections: list[Section] = []
    current_heading: str | None = None
    current_lines: list[str] = []
    preamble: list[str] = []

    def flush() -> None:
        nonlocal current_heading, current_lines
        if current_heading is None:
            return
        content = "\n".join(current_lines).strip("\n")
        sections.append(Section(heading=current_heading, content=content))
        current_heading = None
        current_lines = []

    for line in lines:
        heading = _is_heading(line)
        if heading and primary_level and heading[0] == primary_level:
            if current_heading is None and preamble:
                current_lines.extend(preamble)
                preamble = []
            flush()
            current_heading = heading[1]
            continue
        if current_heading is None:
            preamble.append(line)
        else:
            current_lines.append(line)

    if current_heading is None:
        if any(line.strip() for line in preamble):
            sections.append(Section(heading="## Document", content="\n".join(preamble).strip("\n")))
    else:
        flush()
        if preamble:
            sections[-1].content = "\n".join([sections[-1].content, "\n".join(preamble)]).strip(
                "\n"
            )

    return sections


def split_by_subheadings(section: Section) -> list[Section]:
    """Split a section into level-3 subsections when present."""
    lines = section.content.splitlines()
    sub_sections: list[Section] = []
    current_heading: str | None = None
    current_lines: list[str] = []
    preamble: list[str] = []

    def flush() -> None:
        nonlocal current_heading, current_lines
        if current_heading is None:
            return
        content = "\n".join(current_lines).strip("\n")
        heading = f"{section.heading}\n\n{current_heading}"
        sub_sections.append(Section(heading=heading, content=content))
        current_heading = None
        current_lines = []

    for line in lines:
        heading = _is_heading(line)
        if heading and heading[0] == 3:
            if current_heading is None and preamble:
                current_lines.extend(preamble)
                preamble = []
            flush()
            current_heading = heading[1]
            continue
        if current_heading is None:
            preamble.append(line)
        else:
            current_lines.append(line)

    if current_heading is None:
        return [section]
    flush()
    if preamble and sub_sections:
        preamble_text = "\n".join(preamble).strip("\n")
        sub_sections[0].content = "\n\n".join([preamble_text, sub_sections[0].content]).strip("\n")
    return sub_sections


@dataclass
class Block:
    """Markdown block with an atomicity marker for chunking."""

    text: str
    atomic: bool


def _is_list_line(line: str) -> bool:
    """Return True if the line appears to be a Markdown list item."""
    stripped = line.lstrip()
    if stripped.startswith(_LIST_PREFIXES):
        return True
    if stripped[:1].isdigit() and "." in stripped:
        prefix = stripped.split(".", 1)[0]
        return prefix.isdigit() and stripped[len(prefix) :].startswith(". ")
    return False


def _is_table_header(line: str, next_line: str) -> bool:
    """Return True if the line pair looks like a Markdown table header."""
    if "|" not in line:
        return False
    stripped = next_line.strip()
    if "|" not in stripped:
        return False
    stripped = stripped.strip("|").strip()
    if not stripped:
        return False
    return all(ch in "-: " for ch in stripped)


def markdown_blocks(text: str) -> list[Block]:
    """Split Markdown into atomic and non-atomic blocks for chunking."""
    lines = text.splitlines()
    blocks: list[Block] = []
    i = 0
    while i < len(lines):
        line = lines[i]
        if not line.strip():
            i += 1
            continue
        if line.lstrip().startswith(("```", "~~~")):
            fence = line.lstrip()[:3]
            block_lines = [line]
            i += 1
            while i < len(lines):
                block_lines.append(lines[i])
                if lines[i].lstrip().startswith(fence):
                    i += 1
                    break
                i += 1
            blocks.append(Block(text="\n".join(block_lines), atomic=True))
            continue
        if i + 1 < len(lines) and _is_table_header(line, lines[i + 1]):
            block_lines = [line, lines[i + 1]]
            i += 2
            while i < len(lines) and "|" in lines[i]:
                block_lines.append(lines[i])
                i += 1
            blocks.append(Block(text="\n".join(block_lines), atomic=True))
            continue
        if line.lstrip().startswith(">"):
            block_lines = [line]
            i += 1
            while i < len(lines) and (lines[i].lstrip().startswith(">") or not lines[i].strip()):
                block_lines.append(lines[i])
                i += 1
            blocks.append(Block(text="\n".join(block_lines), atomic=True))
            continue
        if _is_list_line(line):
            block_lines = [line]
            i += 1
            while i < len(lines):
                if not lines[i].strip():
                    block_lines.append(lines[i])
                    i += 1
                    continue
                if _is_list_line(lines[i]) or lines[i].startswith(" "):
                    block_lines.append(lines[i])
                    i += 1
                    continue
                break
            blocks.append(Block(text="\n".join(block_lines), atomic=True))
            continue

        paragraph_lines = [line]
        i += 1
        while i < len(lines) and lines[i].strip():
            if _is_heading(lines[i]) or lines[i].lstrip().startswith(("```", "~~~")):
                break
            paragraph_lines.append(lines[i])
            i += 1
        blocks.append(Block(text="\n".join(paragraph_lines), atomic=False))

    return blocks


def split_section_by_paragraphs(section: Section, max_tokens: int) -> list[Section]:
    """Chunk a section into token-limited sections while preserving blocks."""
    prefix = section.heading.strip()
    blocks = markdown_blocks(section.content)
    chunks: list[Section] = []
    current_parts: list[str] = []
    current_tokens = estimate_tokens(prefix)

    for block in blocks:
        block_tokens = estimate_tokens(block.text)
        if current_parts and current_tokens + block_tokens > max_tokens:
            chunks.append(
                Section(
                    heading=prefix,
                    content="\n\n".join(current_parts).strip("\n"),
                )
            )
            current_parts = []
            current_tokens = estimate_tokens(prefix)

        if not current_parts and block_tokens > max_tokens and block.atomic:
            chunks.append(Section(heading=prefix, content=block.text))
            current_tokens = estimate_tokens(prefix)
            continue

        current_parts.append(block.text)
        current_tokens += block_tokens

    if current_parts:
        chunks.append(
            Section(
                heading=prefix,
                content="\n\n".join(current_parts).strip("\n"),
            )
        )
    return chunks


def chunk_markdown(text: str, max_tokens: int) -> list[str]:
    """Chunk Markdown into size-bounded strings suitable for embedding."""
    sections = split_sections(text)
    chunks: list[str] = []
    for section in sections:
        base_text = f"{section.heading}\n\n{section.content}".strip("\n")
        if estimate_tokens(base_text) <= max_tokens:
            chunks.append(base_text)
            continue

        sub_sections = split_by_subheadings(section)
        if sub_sections != [section]:
            for sub_section in sub_sections:
                sub_text = f"{sub_section.heading}\n\n{sub_section.content}".strip("\n")
                if estimate_tokens(sub_text) <= max_tokens:
                    chunks.append(sub_text)
                    continue
                for para_section in split_section_by_paragraphs(sub_section, max_tokens):
                    chunks.append(f"{para_section.heading}\n\n{para_section.content}".strip("\n"))
            continue

        for para_section in split_section_by_paragraphs(section, max_tokens):
            chunks.append(f"{para_section.heading}\n\n{para_section.content}".strip("\n"))

    return [chunk for chunk in chunks if chunk.strip()]


def file_hash(content: str) -> str:
    """Return a stable SHA-256 hash for content."""
    return hashlib.sha256(content.encode("utf-8")).hexdigest()


def embed_text(text: str, model: str) -> list[float]:
    """Fetch an embedding vector for text from the configured embedding API."""
    client = HttpClient(timeout=settings.llm.timeout)
    response = client.post(
        f"{settings.llm.embed_base_url.rstrip('/')}/api/embeddings",
        json={"model": model, "prompt": text},
    )
    payload = response.json()
    embedding = payload.get("embedding")
    if not embedding:
        raise ValueError("Ollama embeddings response missing 'embedding'.")
    return embedding


def ensure_collection(client: QdrantClient, collection: str, vector_size: int) -> None:
    """Create a Qdrant collection if it does not already exist."""
    if client.collection_exists(collection):
        return
    client.create_collection(
        collection_name=collection,
        vectors_config=qmodels.VectorParams(size=vector_size, distance=qmodels.Distance.COSINE),
    )


def delete_note_points(client: QdrantClient, collection: str, note_path: str) -> None:
    """Delete all vector points associated with a note path."""
    if not client.collection_exists(collection):
        return
    filter_obj = qmodels.Filter(
        must=[qmodels.FieldCondition(key="path", match=qmodels.MatchValue(value=note_path))]
    )
    client.delete(
        collection_name=collection,
        points_selector=qmodels.FilterSelector(filter=filter_obj),
    )


def make_point_id(note_path: str, chunk_index: int) -> str:
    """Create a deterministic UUID for a note chunk."""
    raw = f"{note_path}:{chunk_index}"
    digest = hashlib.sha256(raw.encode("utf-8")).digest()
    return str(uuid.UUID(bytes=digest[:16]))


def build_points(
    note_path: str,
    chunks: Iterable[str],
    content_hash: str,
    modified_at: float,
    embed_model: str,
) -> tuple[list[qmodels.PointStruct], list[tuple[int, str, int]]]:
    """Build Qdrant point structs and metadata for each chunk."""
    points: list[qmodels.PointStruct] = []
    chunk_meta: list[tuple[int, str, int]] = []
    chunk_list = list(chunks)
    total = len(chunk_list)
    for idx, chunk in enumerate(chunk_list):
        embedding = embed_text(chunk, embed_model)
        qdrant_id = make_point_id(note_path, idx)
        payload = {
            "path": note_path,
            "chunk_index": idx,
            "chunk_total": total,
            "content_hash": content_hash,
            "modified_at": modified_at,
            "text": chunk,
        }
        points.append(
            qmodels.PointStruct(
                id=qdrant_id,
                vector=embedding,
                payload=payload,
            )
        )
        chunk_meta.append((idx, qdrant_id, len(chunk)))
    return points, chunk_meta


def index_vault(
    vault_path: str,
    collection: str,
    embed_model: str,
    max_tokens: int,
    full_reindex: bool = False,
    run_migrations: bool = True,
) -> None:
    """Index Obsidian vault into Qdrant."""
    logger.info(f"Indexing vault: {vault_path}")

    vault = Path(vault_path)
    if not vault.exists():
        logger.error(f"Vault path does not exist: {vault_path}")
        return

    qdrant = QdrantClient(url=settings.qdrant.url)
    if run_migrations:
        global _migrations_applied
        with _migrations_lock:
            if not _migrations_applied:
                run_migrations_sync()
                _migrations_applied = True

    if full_reindex and qdrant.collection_exists(collection):
        logger.info(f"Deleting collection for full reindex: {collection}")
        qdrant.delete_collection(collection)

    markdown_files = list(iter_markdown_files(vault))
    logger.info(f"Found {len(markdown_files)} markdown files to index")

    indexed = 0
    skipped = 0
    updated = 0

    session = get_sync_session()
    current_paths: set[str] = set()
    try:
        if full_reindex:
            note_ids = [
                row[0]
                for row in session.query(IndexedNote.id)
                .filter(IndexedNote.collection == collection)
                .all()
            ]
            if note_ids:
                session.query(IndexedChunk).filter(IndexedChunk.note_id.in_(note_ids)).delete(
                    synchronize_session=False
                )
            session.query(IndexedNote).filter(IndexedNote.collection == collection).delete(
                synchronize_session=False
            )
            session.commit()

        for path in markdown_files:
            relative_path = str(path.relative_to(vault))
            current_paths.add(relative_path)
            try:
                content = path.read_text(encoding="utf-8", errors="ignore")
            except OSError as exc:
                logger.warning(f"Failed to read {relative_path}: {exc}")
                continue

            note = (
                session.query(IndexedNote)
                .filter(
                    IndexedNote.collection == collection,
                    IndexedNote.path == relative_path,
                )
                .one_or_none()
            )

            if not content.strip():
                if note:
                    delete_note_points(qdrant, collection, relative_path)
                    session.query(IndexedChunk).filter(IndexedChunk.note_id == note.id).delete(
                        synchronize_session=False
                    )
                    session.delete(note)
                    session.commit()
                    updated += 1
                else:
                    skipped += 1
                continue

            current_hash = file_hash(content)
            if note and note.content_hash == current_hash:
                skipped += 1
                continue

            if note:
                delete_note_points(qdrant, collection, relative_path)
                session.query(IndexedChunk).filter(IndexedChunk.note_id == note.id).delete(
                    synchronize_session=False
                )

            chunks = chunk_markdown(content, max_tokens=max_tokens)
            if not chunks:
                skipped += 1
                continue

            try:
                points, chunk_meta = build_points(
                    note_path=relative_path,
                    chunks=chunks,
                    content_hash=current_hash,
                    modified_at=path.stat().st_mtime,
                    embed_model=embed_model,
                )
            except Exception as exc:
                session.rollback()
                logger.warning(f"Embedding failed for {relative_path}: {exc}")
                continue

            ensure_collection(qdrant, collection, vector_size=len(points[0].vector))
            qdrant.upsert(collection_name=collection, points=points)

            modified_at = datetime.fromtimestamp(path.stat().st_mtime, timezone.utc)
            now = datetime.now(timezone.utc)
            if note:
                note.content_hash = current_hash
                note.modified_at = modified_at
                note.chunk_count = len(chunks)
                note.last_indexed_at = now
                updated += 1
            else:
                note = IndexedNote(
                    path=relative_path,
                    collection=collection,
                    content_hash=current_hash,
                    modified_at=modified_at,
                    chunk_count=len(chunks),
                    last_indexed_at=now,
                )
                session.add(note)
                indexed += 1

            session.flush()
            for chunk_index, qdrant_id, chunk_chars in chunk_meta:
                session.add(
                    IndexedChunk(
                        note_id=note.id,
                        chunk_index=chunk_index,
                        qdrant_id=qdrant_id,
                        chunk_chars=chunk_chars,
                    )
                )

            session.commit()

            if (indexed + updated) % 50 == 0:
                logger.info(f"Indexed {indexed}, updated {updated} notes...")

        db_notes = session.query(IndexedNote).filter(IndexedNote.collection == collection).all()
        for note in db_notes:
            if note.path in current_paths:
                continue
            delete_note_points(qdrant, collection, note.path)
            session.query(IndexedChunk).filter(IndexedChunk.note_id == note.id).delete(
                synchronize_session=False
            )
            session.delete(note)
            updated += 1

        session.commit()
    finally:
        session.close()

    logger.info(
        "Indexing complete: indexed=%s updated=%s skipped=%s",
        indexed,
        updated,
        skipped,
    )


def main() -> None:
    """CLI entry point."""
    parser = argparse.ArgumentParser(description="Index Obsidian vault")
    parser.add_argument(
        "--vault-path",
        default=settings.obsidian.vault_path,
        help="Path to Obsidian vault",
    )
    parser.add_argument(
        "--collection",
        default=settings.indexer.collection,
        help="Qdrant collection name",
    )
    parser.add_argument(
        "--embed-model",
        default=settings.llm.embed_model,
        help="Embedding model name",
    )
    parser.add_argument(
        "--max-tokens",
        type=int,
        default=settings.indexer.chunk_tokens,
        help="Maximum estimated tokens per chunk",
    )
    parser.add_argument(
        "--full-reindex",
        action="store_true",
        help="Clear existing index and rebuild",
    )
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="Enable verbose logging",
    )

    args = parser.parse_args()

    if args.verbose:
        logging.getLogger().setLevel(logging.DEBUG)

    index_vault(
        vault_path=args.vault_path,
        collection=args.collection,
        embed_model=args.embed_model,
        max_tokens=args.max_tokens,
        full_reindex=args.full_reindex,
        run_migrations=True,
    )


if __name__ == "__main__":
    main()
