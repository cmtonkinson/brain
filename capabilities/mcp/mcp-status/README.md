# mcp-status
List configured MCP servers, or list MCP Ops exposed by one configured MCP server.

Bound to `/mcp`. With no arguments, it lists configured MCP servers with
availability and tool counts. With a server id argument, it lists MCP Ops whose
capability ids are derived from that server.

## Parameters
- `server_id` *(optional)*: MCP server id to inspect.

## Returns
A formatted text response suitable for operator display.
