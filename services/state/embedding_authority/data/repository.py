"""Authoritative Postgres repository for Embedding Authority Service state."""

from __future__ import annotations

from collections.abc import Mapping
from datetime import UTC, datetime

from sqlalchemy import delete, desc, select
from sqlalchemy.dialects.postgresql import insert

from packages.brain_shared.ids import (
    generate_ulid_bytes,
    ulid_bytes_to_str,
    ulid_str_to_bytes,
)
from resources.substrates.postgres.schema_session import ServiceSchemaSessionProvider
from services.state.embedding_authority.domain import (
    ChunkRecord,
    EmbeddingRecord,
    EmbeddingSpec,
    EmbeddingStatus,
    SourceRecord,
)
from services.state.embedding_authority.interfaces import EmbeddingRepository

from .schema import chunks, embeddings, sources, specs


class PostgresEmbeddingRepository(EmbeddingRepository):
    """SQL repository over EAS-owned schema tables."""

    def __init__(self, sessions: ServiceSchemaSessionProvider) -> None:
        self._sessions = sessions

    def ensure_spec(
        self,
        *,
        provider: str,
        name: str,
        version: str,
        dimensions: int,
        hash_bytes: bytes,
        canonical_string: str,
    ) -> EmbeddingSpec:
        """Ensure one unique spec row exists for ``hash_bytes`` and return it."""
        with self._sessions.session() as session:
            stmt = insert(specs).values(
                id=generate_ulid_bytes(),
                provider=provider,
                name=name,
                version=version,
                dimensions=dimensions,
                canonical_string=canonical_string,
                hash=hash_bytes,
            )
            stmt = stmt.on_conflict_do_nothing(index_elements=[specs.c.hash])
            session.execute(stmt)

            row = (
                session.execute(select(specs).where(specs.c.hash == hash_bytes))
                .mappings()
                .one()
            )
            return _to_spec(row)

    def get_spec(self, *, spec_id: str) -> EmbeddingSpec | None:
        """Fetch one spec by id."""
        with self._sessions.session() as session:
            row = (
                session.execute(
                    select(specs).where(specs.c.id == ulid_str_to_bytes(spec_id))
                )
                .mappings()
                .one_or_none()
            )
            return _to_spec(row) if row is not None else None

    def list_specs(self, *, limit: int) -> list[EmbeddingSpec]:
        """List known specs sorted by creation time desc."""
        with self._sessions.session() as session:
            rows = (
                session.execute(
                    select(specs)
                    .order_by(desc(specs.c.created_at), desc(specs.c.id))
                    .limit(_bounded_limit(limit))
                )
                .mappings()
                .all()
            )
            return [_to_spec(row) for row in rows]

    def list_spec_ids(self) -> list[str]:
        """List all known spec ids."""
        with self._sessions.session() as session:
            rows = session.execute(select(specs.c.id)).all()
            return [ulid_bytes_to_str(row[0]) for row in rows]

    def upsert_source(
        self,
        *,
        canonical_reference: str,
        source_type: str,
        service: str,
        principal: str,
        metadata: Mapping[str, str],
    ) -> SourceRecord:
        """Create/update one source row and return current value."""
        with self._sessions.session() as session:
            stmt = insert(sources).values(
                id=generate_ulid_bytes(),
                source_type=source_type,
                canonical_reference=canonical_reference,
                service=service,
                principal=principal,
                metadata=dict(metadata),
            )
            stmt = stmt.on_conflict_do_update(
                constraint="uq_sources_reference_service_principal",
                set_={
                    "source_type": source_type,
                    "metadata": dict(metadata),
                    "updated_at": datetime.now(UTC),
                },
            )
            session.execute(stmt)

            row = (
                session.execute(
                    select(sources).where(
                        sources.c.canonical_reference == canonical_reference,
                        sources.c.service == service,
                        sources.c.principal == principal,
                    )
                )
                .mappings()
                .one()
            )
            return _to_source(row)

    def get_source(self, *, source_id: str) -> SourceRecord | None:
        """Fetch one source by id."""
        with self._sessions.session() as session:
            row = (
                session.execute(
                    select(sources).where(sources.c.id == ulid_str_to_bytes(source_id))
                )
                .mappings()
                .one_or_none()
            )
            return _to_source(row) if row is not None else None

    def list_sources(
        self,
        *,
        canonical_reference: str,
        service: str,
        principal: str,
        limit: int,
    ) -> list[SourceRecord]:
        """List sources by optional filters."""
        with self._sessions.session() as session:
            stmt = select(sources)
            if canonical_reference:
                stmt = stmt.where(sources.c.canonical_reference == canonical_reference)
            if service:
                stmt = stmt.where(sources.c.service == service)
            if principal:
                stmt = stmt.where(sources.c.principal == principal)
            stmt = stmt.order_by(desc(sources.c.updated_at), desc(sources.c.id)).limit(
                _bounded_limit(limit)
            )
            rows = session.execute(stmt).mappings().all()
            return [_to_source(row) for row in rows]

    def upsert_chunk(
        self,
        *,
        source_id: str,
        chunk_ordinal: int,
        reference_range: str,
        content_hash: str,
        text: str,
        metadata: Mapping[str, str],
    ) -> ChunkRecord:
        """Create/update one chunk row by stable ``(source_id, chunk_ordinal)``."""
        source_id_bytes = ulid_str_to_bytes(source_id)
        with self._sessions.session() as session:
            stmt = insert(chunks).values(
                id=generate_ulid_bytes(),
                source_id=source_id_bytes,
                chunk_ordinal=chunk_ordinal,
                reference_range=reference_range,
                content_hash=content_hash,
                text=text,
                metadata=dict(metadata),
            )
            stmt = stmt.on_conflict_do_update(
                constraint="uq_chunks_source_ordinal",
                set_={
                    "reference_range": reference_range,
                    "content_hash": content_hash,
                    "text": text,
                    "metadata": dict(metadata),
                    "updated_at": datetime.now(UTC),
                },
            )
            session.execute(stmt)

            row = (
                session.execute(
                    select(chunks).where(
                        chunks.c.source_id == source_id_bytes,
                        chunks.c.chunk_ordinal == chunk_ordinal,
                    )
                )
                .mappings()
                .one()
            )
            return _to_chunk(row)

    def get_chunk(self, *, chunk_id: str) -> ChunkRecord | None:
        """Fetch one chunk by id."""
        with self._sessions.session() as session:
            row = (
                session.execute(
                    select(chunks).where(chunks.c.id == ulid_str_to_bytes(chunk_id))
                )
                .mappings()
                .one_or_none()
            )
            return _to_chunk(row) if row is not None else None

    def list_chunks_by_source(self, *, source_id: str, limit: int) -> list[ChunkRecord]:
        """List chunks for one source ordered by ordinal."""
        source_id_bytes = ulid_str_to_bytes(source_id)
        with self._sessions.session() as session:
            rows = (
                session.execute(
                    select(chunks)
                    .where(chunks.c.source_id == source_id_bytes)
                    .order_by(chunks.c.chunk_ordinal.asc(), chunks.c.id.asc())
                    .limit(_bounded_limit(limit))
                )
                .mappings()
                .all()
            )
            return [_to_chunk(row) for row in rows]

    def upsert_embedding(
        self,
        *,
        chunk_id: str,
        spec_id: str,
        content_hash: str,
        status: EmbeddingStatus,
        error_detail: str,
    ) -> EmbeddingRecord:
        """Create/update one embedding state row for ``(chunk_id, spec_id)``."""
        chunk_id_bytes = ulid_str_to_bytes(chunk_id)
        spec_id_bytes = ulid_str_to_bytes(spec_id)
        with self._sessions.session() as session:
            stmt = insert(embeddings).values(
                chunk_id=chunk_id_bytes,
                spec_id=spec_id_bytes,
                content_hash=content_hash,
                status=status.value,
                error_detail=error_detail,
            )
            stmt = stmt.on_conflict_do_update(
                constraint="pk_embeddings_chunk_spec",
                set_={
                    "content_hash": content_hash,
                    "status": status.value,
                    "error_detail": error_detail,
                    "updated_at": datetime.now(UTC),
                },
            )
            session.execute(stmt)

            row = (
                session.execute(
                    select(embeddings).where(
                        embeddings.c.chunk_id == chunk_id_bytes,
                        embeddings.c.spec_id == spec_id_bytes,
                    )
                )
                .mappings()
                .one()
            )
            return _to_embedding(row)

    def get_embedding(self, *, chunk_id: str, spec_id: str) -> EmbeddingRecord | None:
        """Fetch one embedding row."""
        with self._sessions.session() as session:
            row = (
                session.execute(
                    select(embeddings).where(
                        embeddings.c.chunk_id == ulid_str_to_bytes(chunk_id),
                        embeddings.c.spec_id == ulid_str_to_bytes(spec_id),
                    )
                )
                .mappings()
                .one_or_none()
            )
            return _to_embedding(row) if row is not None else None

    def list_embeddings_by_source(
        self,
        *,
        source_id: str,
        spec_id: str,
        limit: int,
    ) -> list[EmbeddingRecord]:
        """List embeddings for chunks under one source, optionally scoped by spec."""
        source_id_bytes = ulid_str_to_bytes(source_id)
        with self._sessions.session() as session:
            stmt = (
                select(embeddings)
                .join(chunks, chunks.c.id == embeddings.c.chunk_id)
                .where(chunks.c.source_id == source_id_bytes)
            )
            if spec_id:
                stmt = stmt.where(embeddings.c.spec_id == ulid_str_to_bytes(spec_id))
            stmt = stmt.order_by(desc(embeddings.c.updated_at)).limit(
                _bounded_limit(limit)
            )
            rows = session.execute(stmt).mappings().all()
            return [_to_embedding(row) for row in rows]

    def list_embeddings_by_status(
        self,
        *,
        status: EmbeddingStatus,
        spec_id: str,
        limit: int,
    ) -> list[EmbeddingRecord]:
        """List embeddings by status and optional spec filter."""
        with self._sessions.session() as session:
            stmt = select(embeddings).where(embeddings.c.status == status.value)
            if spec_id:
                stmt = stmt.where(embeddings.c.spec_id == ulid_str_to_bytes(spec_id))
            stmt = stmt.order_by(desc(embeddings.c.updated_at)).limit(
                _bounded_limit(limit)
            )
            rows = session.execute(stmt).mappings().all()
            return [_to_embedding(row) for row in rows]

    def list_chunk_ids_for_source(self, *, source_id: str) -> list[str]:
        """List all chunk ids belonging to one source."""
        source_id_bytes = ulid_str_to_bytes(source_id)
        with self._sessions.session() as session:
            rows = session.execute(
                select(chunks.c.id).where(chunks.c.source_id == source_id_bytes)
            ).all()
            return [ulid_bytes_to_str(row[0]) for row in rows]

    def delete_chunk(self, *, chunk_id: str) -> bool:
        """Delete one chunk and all embedding rows for it."""
        chunk_id_bytes = ulid_str_to_bytes(chunk_id)
        with self._sessions.session() as session:
            session.execute(
                delete(embeddings).where(embeddings.c.chunk_id == chunk_id_bytes)
            )
            result = session.execute(
                delete(chunks).where(chunks.c.id == chunk_id_bytes)
            )
            return bool(result.rowcount)

    def delete_source(self, *, source_id: str) -> bool:
        """Delete source and all owned chunk/embedding rows."""
        source_id_bytes = ulid_str_to_bytes(source_id)
        with self._sessions.session() as session:
            chunk_rows = session.execute(
                select(chunks.c.id).where(chunks.c.source_id == source_id_bytes)
            ).all()
            chunk_ids = [row[0] for row in chunk_rows]
            if chunk_ids:
                session.execute(
                    delete(embeddings).where(embeddings.c.chunk_id.in_(chunk_ids))
                )
                session.execute(delete(chunks).where(chunks.c.id.in_(chunk_ids)))
            result = session.execute(
                delete(sources).where(sources.c.id == source_id_bytes)
            )
            return bool(result.rowcount)


def _to_spec(row: Mapping[str, object]) -> EmbeddingSpec:
    """Map row mapping to ``EmbeddingSpec``."""
    return EmbeddingSpec(
        id=ulid_bytes_to_str(_row_bytes(row, "id")),
        provider=str(row["provider"]),
        name=str(row["name"]),
        version=str(row["version"]),
        dimensions=int(row["dimensions"]),
        hash=bytes(row["hash"]),
        canonical_string=str(row["canonical_string"]),
        created_at=_row_dt(row, "created_at"),
        updated_at=_row_dt(row, "updated_at"),
    )


def _to_source(row: Mapping[str, object]) -> SourceRecord:
    """Map row mapping to ``SourceRecord``."""
    metadata = row.get("metadata")
    metadata_map = dict(metadata) if isinstance(metadata, Mapping) else {}
    return SourceRecord(
        id=ulid_bytes_to_str(_row_bytes(row, "id")),
        source_type=str(row["source_type"]),
        canonical_reference=str(row["canonical_reference"]),
        service=str(row["service"]),
        principal=str(row["principal"]),
        metadata={str(k): str(v) for k, v in metadata_map.items()},
        created_at=_row_dt(row, "created_at"),
        updated_at=_row_dt(row, "updated_at"),
    )


def _to_chunk(row: Mapping[str, object]) -> ChunkRecord:
    """Map row mapping to ``ChunkRecord``."""
    metadata = row.get("metadata")
    metadata_map = dict(metadata) if isinstance(metadata, Mapping) else {}
    return ChunkRecord(
        id=ulid_bytes_to_str(_row_bytes(row, "id")),
        source_id=ulid_bytes_to_str(_row_bytes(row, "source_id")),
        chunk_ordinal=int(row["chunk_ordinal"]),
        reference_range=str(row["reference_range"]),
        content_hash=str(row["content_hash"]),
        text=str(row["text"]),
        metadata={str(k): str(v) for k, v in metadata_map.items()},
        created_at=_row_dt(row, "created_at"),
        updated_at=_row_dt(row, "updated_at"),
    )


def _to_embedding(row: Mapping[str, object]) -> EmbeddingRecord:
    """Map row mapping to ``EmbeddingRecord``."""
    status = EmbeddingStatus(str(row["status"]))
    return EmbeddingRecord(
        chunk_id=ulid_bytes_to_str(_row_bytes(row, "chunk_id")),
        spec_id=ulid_bytes_to_str(_row_bytes(row, "spec_id")),
        content_hash=str(row["content_hash"]),
        status=status,
        error_detail=str(row.get("error_detail") or ""),
        created_at=_row_dt(row, "created_at"),
        updated_at=_row_dt(row, "updated_at"),
    )


def _row_dt(row: Mapping[str, object], key: str) -> datetime:
    """Return UTC-aware datetime from row key with strict type enforcement."""
    value = row.get(key)
    if not isinstance(value, datetime):
        raise ValueError(f"expected datetime column for {key}")
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def _row_bytes(row: Mapping[str, object], key: str) -> bytes:
    """Return bytes value for one row key."""
    value = row.get(key)
    if isinstance(value, (bytes, bytearray)):
        return bytes(value)
    raise ValueError(f"expected bytes column for {key}")


def _bounded_limit(limit: int) -> int:
    """Clamp potentially invalid limits to a safe positive range."""
    if limit <= 0:
        return 100
    return min(limit, 5_000)
