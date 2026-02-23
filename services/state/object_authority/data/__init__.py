"""Data-layer exports for Object Authority Service."""

from services.state.object_authority.data.repository import PostgresObjectRepository
from services.state.object_authority.data.runtime import ObjectPostgresRuntime

__all__ = ["ObjectPostgresRuntime", "PostgresObjectRepository"]
