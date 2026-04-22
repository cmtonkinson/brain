"""Load operator-supplied MCP output schema overrides from disk."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

_MCP_RETURN_SCHEMA_DIR = "mcp-return-schema"


def load_mcp_output_schemas(root: Path) -> dict[str, dict[str, Any]]:
    """Scan ``{root}/mcp-return-schema/`` for per-server schema overrides.

    Returns a dict keyed by server_id (derived from filename without
    extension) mapping to the parsed JSON Schema object.

    File naming convention: ``<server_id>.json``
    """
    schema_dir = root / _MCP_RETURN_SCHEMA_DIR
    if not schema_dir.is_dir():
        return {}

    schemas: dict[str, dict[str, Any]] = {}
    for path in sorted(schema_dir.glob("*.json")):
        server_id = path.stem
        if not server_id:
            continue
        raw = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(raw, dict):
            continue
        schemas[server_id] = raw
    return schemas


def resolve_mcp_output_schema(
    schemas: dict[str, dict[str, Any]],
    server_id: str,
) -> dict[str, Any] | None:
    """Return the output schema override for a given server, or None."""
    return schemas.get(server_id)
