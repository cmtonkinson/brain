"""Code-Mode (UTCP) client integration for external tool access."""

from __future__ import annotations

import json
import logging
import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable

from utcp_code_mode import CodeModeUtcpClient

logger = logging.getLogger(__name__)

_DESTRUCTIVE_KEYWORDS: tuple[str, ...] = (
    "write",
    "delete",
    "remove",
    "rm",
    "move",
    "rename",
    "create",
    "mkdir",
    "rmdir",
    "copy",
    "commit",
    "push",
    "reset",
    "rebase",
    "merge",
    "checkout",
    "tag",
    "branch",
    "add",
)


def _expand_path(path: str) -> Path:
    return Path(os.path.expanduser(path)).resolve()


def _load_config(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def _detect_destructive_ops(code: str, keywords: Iterable[str]) -> list[str]:
    keyword_list = list(keywords)
    if not keyword_list:
        return []
    pattern = re.compile(
        r"\.\s*(?:" + "|".join(re.escape(word) for word in keyword_list) + r")\w*\s*\("
    )
    return pattern.findall(code)


@dataclass
class CodeModeManager:
    client: CodeModeUtcpClient | None
    config_path: Path | None
    timeout: int

    async def search_tools(self, query: str) -> str:
        if not self.client:
            return "Code-Mode is not configured. Set UTCP_CONFIG_PATH to enable external tools."

        try:
            tools = await self.client.search_tools(query)
        except Exception as exc:
            logger.error(f"Code-Mode search_tools failed: {exc}")
            return f"Code-Mode search failed: {exc}"

        if not tools:
            return f"No tools found for query '{query}'."

        lines = []
        for tool in tools:
            description = getattr(tool, "description", "") or ""
            lines.append(f"- {tool.name}: {description}".strip())
        return "Tools:\n" + "\n".join(lines)

    async def call_tool_chain(
        self,
        code: str,
        confirm_destructive: bool = False,
        timeout: int | None = None,
    ) -> str:
        if not self.client:
            return "Code-Mode is not configured. Set UTCP_CONFIG_PATH to enable external tools."

        detected = _detect_destructive_ops(code, _DESTRUCTIVE_KEYWORDS)
        if detected and not confirm_destructive:
            return (
                "Potentially destructive operations detected. "
                "Ask the user for confirmation, then retry with "
                "`confirm_destructive=True`."
            )

        try:
            result = await self.client.call_tool_chain(
                code, timeout=timeout or self.timeout
            )
        except Exception as exc:
            logger.error(f"Code-Mode call_tool_chain failed: {exc}")
            return f"Code-Mode execution failed: {exc}"

        logs = result.get("logs", [])
        output = result.get("result")

        response_lines = []
        if logs:
            response_lines.append("Logs:")
            response_lines.extend(str(entry) for entry in logs)
        response_lines.append(f"Result: {output}")
        return "\n".join(response_lines)


async def create_code_mode_manager(
    config_path: str,
    timeout: int,
) -> CodeModeManager:
    expanded = _expand_path(config_path)
    if not expanded.exists():
        logger.warning(f"UTCP config not found at {expanded}")
        return CodeModeManager(client=None, config_path=expanded, timeout=timeout)

    try:
        _load_config(expanded)
        client = await CodeModeUtcpClient.create(
            root_dir=str(expanded.parent),
            config=str(expanded),
        )
        return CodeModeManager(client=client, config_path=expanded, timeout=timeout)
    except Exception as exc:
        logger.error(f"Failed to initialize Code-Mode client: {exc}")
        return CodeModeManager(client=None, config_path=expanded, timeout=timeout)
