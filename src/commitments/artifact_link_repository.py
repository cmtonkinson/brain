"""Repository for commitment-artifact relationship management."""

from __future__ import annotations

from contextlib import closing
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Callable, Literal

from sqlalchemy.orm import Session

from models import CommitmentArtifact
from time_utils import to_utc


RelationshipType = Literal["evidence", "context", "reference", "progress", "related"]
ActorType = Literal["user", "system"]


@dataclass(frozen=True)
class CommitmentArtifactLinkInput:
    """Input payload for creating a commitment-artifact link."""

    commitment_id: int
    object_key: str
    relationship_type: RelationshipType
    added_by: ActorType
    notes: str | None = None
    added_at: datetime | None = None


class CommitmentArtifactLinkRepository:
    """Repository for managing commitment-artifact relationships."""

    def __init__(self, session_factory: Callable[[], Session]) -> None:
        """Initialize repository with a SQLAlchemy session factory."""
        self._session_factory = session_factory

    def create_link(
        self,
        payload: CommitmentArtifactLinkInput,
    ) -> CommitmentArtifact:
        """Create a link between a commitment and an artifact.

        Args:
            payload: Link creation parameters

        Returns:
            Created CommitmentArtifact record

        Raises:
            IntegrityError: If link already exists or references are invalid
        """
        with closing(self._session_factory()) as session:
            session.expire_on_commit = False
            try:
                timestamp = to_utc(payload.added_at or datetime.now(timezone.utc))
                link = CommitmentArtifact(
                    commitment_id=payload.commitment_id,
                    object_key=payload.object_key,
                    relationship_type=payload.relationship_type,
                    added_by=payload.added_by,
                    added_at=timestamp,
                    notes=payload.notes,
                )
                session.add(link)
                session.commit()
            except Exception:
                session.rollback()
                raise
        return link

    def remove_link(
        self,
        commitment_id: int,
        object_key: str,
    ) -> bool:
        """Remove a link between a commitment and an artifact.

        Args:
            commitment_id: Commitment ID
            object_key: Artifact object key

        Returns:
            True if link was removed, False if it didn't exist
        """
        with closing(self._session_factory()) as session:
            try:
                deleted = (
                    session.query(CommitmentArtifact)
                    .filter(
                        CommitmentArtifact.commitment_id == commitment_id,
                        CommitmentArtifact.object_key == object_key,
                    )
                    .delete()
                )
                session.commit()
                return deleted > 0
            except Exception:
                session.rollback()
                raise

    def list_artifacts_for_commitment(
        self,
        commitment_id: int,
    ) -> list[CommitmentArtifact]:
        """Get all artifacts linked to a commitment.

        Args:
            commitment_id: Commitment ID

        Returns:
            List of CommitmentArtifact records ordered by added_at descending
        """
        with closing(self._session_factory()) as session:
            session.expire_on_commit = False
            try:
                links = (
                    session.query(CommitmentArtifact)
                    .filter(CommitmentArtifact.commitment_id == commitment_id)
                    .order_by(CommitmentArtifact.added_at.desc())
                    .all()
                )
                session.commit()
            except Exception:
                session.rollback()
                raise
        return links

    def list_commitments_for_artifact(
        self,
        object_key: str,
    ) -> list[CommitmentArtifact]:
        """Get all commitments linked to an artifact.

        Args:
            object_key: Artifact object key

        Returns:
            List of CommitmentArtifact records ordered by added_at descending
        """
        with closing(self._session_factory()) as session:
            session.expire_on_commit = False
            try:
                links = (
                    session.query(CommitmentArtifact)
                    .filter(CommitmentArtifact.object_key == object_key)
                    .order_by(CommitmentArtifact.added_at.desc())
                    .all()
                )
                session.commit()
            except Exception:
                session.rollback()
                raise
        return links

    def link_exists(
        self,
        commitment_id: int,
        object_key: str,
    ) -> bool:
        """Check if a link exists between a commitment and an artifact.

        Args:
            commitment_id: Commitment ID
            object_key: Artifact object key

        Returns:
            True if link exists, False otherwise
        """
        with closing(self._session_factory()) as session:
            exists = (
                session.query(CommitmentArtifact)
                .filter(
                    CommitmentArtifact.commitment_id == commitment_id,
                    CommitmentArtifact.object_key == object_key,
                )
                .first()
                is not None
            )
        return exists


__all__ = [
    "CommitmentArtifactLinkInput",
    "CommitmentArtifactLinkRepository",
    "RelationshipType",
    "ActorType",
]
