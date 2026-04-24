"""List configured MCP servers or MCP Ops for one MCP server."""

from __future__ import annotations

from lib.sdk.client import BrainSdkClient


def execute(input_payload: dict[str, object] | None = None) -> str:
    """Return formatted MCP server status or server-specific MCP Ops."""
    payload = {} if input_payload is None else input_payload
    server_id = str(payload.get("server_id", "")).strip()
    with BrainSdkClient(source="mcp-status", principal="operator") as brain_client:
        servers = [
            item
            for item in brain_client.list_tool_system_hints()
            if getattr(item, "kind", "") == "mcp"
        ]
        if server_id == "":
            return _render_servers(servers=servers)
        ops = tuple(
            item
            for item in brain_client.describe_ops()
            if getattr(item, "kind", "") == "mcp"
        )
        classifications = tuple(
            item
            for item in brain_client.list_dynamic_op_classifications()
            if getattr(item, "source_kind", "") == "mcp"
        )
    return _render_server_tools(
        server_id=server_id,
        servers=servers,
        ops=ops,
        classifications=classifications,
    )


def _render_servers(*, servers: list[object]) -> str:
    """Render configured MCP server statuses."""
    if not servers:
        return "No MCP servers configured."
    rows: list[tuple[str, str]] = []
    any_pending = False
    for server in sorted(servers, key=lambda item: str(getattr(item, "system_id", ""))):
        server_id = str(getattr(server, "system_id", "")).strip()
        if server_id == "":
            continue
        ready = bool(getattr(server, "ready", False))
        active = int(getattr(server, "tool_count", 0) or 0)
        pending = int(getattr(server, "pending_tool_count", 0) or 0)
        if pending > 0:
            any_pending = True
        if not ready:
            status = "(offline)"
        else:
            status = f"(available) {active} tools active, {pending} unclassified"
        rows.append((server_id, status))
    if not rows:
        return "No MCP servers configured."
    width = max(len(server_id) for server_id, _ in rows) + 2
    lines = [f"{server_id.ljust(width)}{status}" for server_id, status in rows]
    if any_pending:
        lines.append("")
        lines.append(
            "Hint: classify pending tools with /op-classify <op_id> <effect-and-or-approval>"
        )
    return "\n".join(lines)


def _render_server_tools(
    *,
    server_id: str,
    servers: list[object],
    ops: tuple[object, ...],
    classifications: tuple[object, ...],
) -> str:
    """Render MCP Ops for one server id, split into active and unclassified."""
    server = next(
        (
            item
            for item in servers
            if str(getattr(item, "system_id", "")).strip() == server_id
        ),
        None,
    )
    if server is None:
        return f"Unknown MCP server: {server_id}"
    ready = bool(getattr(server, "ready", False))
    status = "(available)" if ready else "(offline)"

    prefix = f"{server_id}--"
    active_tools = sorted(
        str(getattr(item, "op_id", ""))
        for item in ops
        if str(getattr(item, "op_id", "")).startswith(prefix)
    )
    unclassified_tools = sorted(
        str(getattr(item, "op_id", ""))
        for item in classifications
        if str(getattr(item, "op_id", "")).startswith(prefix)
        and (
            getattr(item, "effect", None) is None
            or getattr(item, "approval", None) is None
        )
    )

    lines: list[str] = [f"Status: {status}", ""]
    lines.append(f"{len(active_tools)} Active Tools:")
    lines.extend(active_tools)
    lines.append("")
    lines.append(f"{len(unclassified_tools)} Unclassified Tools:")
    lines.extend(unclassified_tools)
    if unclassified_tools:
        lines.append("")
        lines.append("Hint: /op-classify <op_id> <words> — words drawn from")
        lines.append("  effects:   read | write | execute | external")
        lines.append("  approvals: always | never")
        lines.append("Example: /op-classify eventkit--list-events read never")
    return "\n".join(lines)
