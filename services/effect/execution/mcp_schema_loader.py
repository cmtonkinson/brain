"""Load operator-supplied MCP per-tool overrides from disk.

Operators may pre-declare ``effect``, ``approval``, and/or ``output_schema``
for individual MCP tools by placing one JSON file per server at
``{root}/mcp-overrides/<server_id>.json`` for each configured discovery
root. Each file maps a tool name to a partial override object; any subset
of the three fields is allowed.

Example:

    {
      "list_calendars": {
        "effect": "read",
        "approval": "always",
        "output_schema": {"type": "object"}
      },
      "create_event": {"effect": "write", "approval": "never"}
    }

Multiple roots are scanned in order; later roots overlay earlier ones, so
a per-tool entry from a later root replaces the same ``(server_id,
tool_name)`` entry from an earlier root. New entries from any root add
cleanly. Precedence at sync time: persisted DB row > file override >
unset.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict

from lib.shared.op_classification import OpApproval, OpEffect

_MCP_OVERRIDES_DIR = "mcp-overrides"


class McpToolOverride(BaseModel):
    """One per-tool override entry; every field is optional."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    effect: OpEffect | None = None
    approval: OpApproval | None = None
    output_schema: dict[str, Any] | None = None


def load_mcp_overrides(
    roots: tuple[Path, ...],
) -> dict[str, dict[str, McpToolOverride]]:
    """Scan ``{root}/mcp-overrides/`` across multiple roots and merge.

    Returns a nested dict ``{server_id: {tool_name: McpToolOverride}}``.
    Roots are scanned in order; later roots overlay earlier ones at
    per-tool granularity (no field-level merging). Missing roots and
    invalid entries are skipped silently so a single bad file never
    blocks boot.
    """
    overrides: dict[str, dict[str, McpToolOverride]] = {}
    for root in roots:
        overrides_dir = root / _MCP_OVERRIDES_DIR
        if not overrides_dir.is_dir():
            continue
        for path in sorted(overrides_dir.glob("*.json")):
            server_id = path.stem
            if not server_id:
                continue
            raw = json.loads(path.read_text(encoding="utf-8"))
            if not isinstance(raw, dict):
                continue
            for tool_name, entry in raw.items():
                if not isinstance(tool_name, str) or not tool_name:
                    continue
                if not isinstance(entry, dict):
                    continue
                try:
                    parsed = McpToolOverride(**entry)
                except TypeError, ValueError:
                    continue
                overrides.setdefault(server_id, {})[tool_name] = parsed
    return overrides


def resolve_mcp_override(
    overrides: dict[str, dict[str, McpToolOverride]],
    server_id: str,
    tool_name: str,
) -> McpToolOverride | None:
    """Return the override for one (server_id, tool_name), or None."""
    return overrides.get(server_id, {}).get(tool_name)
