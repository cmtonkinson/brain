"""Ingestion Service data-layer exports."""

from services.reason.ingestion.data.repository import PostgresIngestionRepository
from services.reason.ingestion.data.runtime import IngestionPostgresRuntime

__all__ = ["IngestionPostgresRuntime", "PostgresIngestionRepository"]
