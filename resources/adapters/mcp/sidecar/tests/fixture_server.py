"""Minimal MCP server that adapter tests launch over stdio or Streamable HTTP.

Usage: ``fixture_server.py`` (stdio) or ``fixture_server.py http PORT``.
"""

from __future__ import annotations

import sys

from mcp.server.mcpserver import Context, MCPServer
from mcp.types import ImageContent

server = MCPServer("fixture")


@server.tool()
def echo(text: str) -> str:
    """Return the given text."""
    return text


@server.tool()
def pixel() -> ImageContent:
    """Return a tiny image."""
    return ImageContent(data="AAAA", mime_type="image/png")


@server.tool()
def fail() -> str:
    """Always fail."""
    raise ValueError("boom")


@server.tool()
def test_header(ctx: Context) -> str:
    """Return the X-Test request header, or an empty string."""
    return (ctx.headers or {}).get("x-test", "")


if __name__ == "__main__":
    if sys.argv[1:2] == ["http"]:
        server.run("streamable-http", host="127.0.0.1", port=int(sys.argv[2]))
    else:
        server.run()
