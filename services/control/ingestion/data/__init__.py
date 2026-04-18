"""Ingestion Service data-layer exports."""

from services.control.ingestion.data.repository import PostgresIngestionRepository
from services.control.ingestion.data.runtime import IngestionPostgresRuntime

__all__ = ["IngestionPostgresRuntime", "PostgresIngestionRepository"]
