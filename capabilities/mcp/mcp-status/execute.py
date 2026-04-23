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
        caps = tuple(
            item
            for item in brain_client.describe_capabilities()
            if getattr(item, "kind", "") == "mcp_op"
        )

    if server_id == "":
        return _render_servers(servers=servers)
    return _render_server_tools(server_id=server_id, servers=servers, capabilities=caps)


def _render_servers(*, servers: list[object]) -> str:
    """Render configured MCP server statuses."""
    if not servers:
        return "No MCP servers configured."
    rows: list[tuple[str, str]] = []
    for server in sorted(servers, key=lambda item: str(getattr(item, "system_id", ""))):
        server_id = str(getattr(server, "system_id", "")).strip()
        if server_id == "":
            continue
        ready = bool(getattr(server, "ready", False))
        tool_count = getattr(server, "tool_count", None)
        if ready:
            status = f"available, {int(tool_count or 0)} tools"
        else:
            status = "offline"
        rows.append((server_id, status))
    if not rows:
        return "No MCP servers configured."
    width = max(len(server_id) for server_id, _ in rows) + 2
    return "\n".join(f"{server_id.ljust(width)}{status}" for server_id, status in rows)


def _render_server_tools(
    *,
    server_id: str,
    servers: list[object],
    capabilities: tuple[object, ...],
) -> str:
    """Render MCP Ops for one server id."""
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
    status = "available" if ready else "offline"
    prefix = f"{server_id}--"
    tools = sorted(
        str(getattr(item, "capability_id", ""))
        for item in capabilities
        if str(getattr(item, "capability_id", "")).startswith(prefix)
    )
    lines = [f"Status: {status}", "", f"{len(tools)} Tools:"]
    lines.extend(tools)
    return "\n".join(lines)
