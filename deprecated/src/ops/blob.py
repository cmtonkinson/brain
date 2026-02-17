"""Native op handlers for the local object store."""

from __future__ import annotations

from typing import Any

from services.object_store import ObjectStore
from skills.context import SkillContext


def _get_store(context: SkillContext) -> ObjectStore:
    """Return the object store from the skill context."""
    store = context.services.object_store
    if store is None:
        raise RuntimeError("Object store service not available")
    return store


def store(inputs: dict[str, Any], context: SkillContext) -> dict[str, Any]:
    """Store a blob payload and return its object key."""
    data = inputs["data"]
    if not isinstance(data, str):
        raise ValueError("blob_store expects 'data' to be a string payload.")
    store_client = _get_store(context)
    blob_id = store_client.write(data)
    return {"blob_id": blob_id}
