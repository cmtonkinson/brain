"""Error types for ingestion intake and status surfaces."""

from __future__ import annotations

from uuid import UUID


class IngestionNotFound(KeyError):
    """Raised when an ingestion attempt cannot be located."""

    def __init__(self, ingestion_id: UUID) -> None:
        """Initialize the error with the missing ingestion identifier."""
        super().__init__(f"ingestion not found: {ingestion_id}")
        self.ingestion_id = ingestion_id


class IngestionRequestRejected(ValueError):
    """Raised when an ingestion submission is rejected."""

    def __init__(self, message: str, ingestion_id: UUID) -> None:
        """Initialize the error with rejection details and ingestion id."""
        super().__init__(message)
        self.ingestion_id = ingestion_id
