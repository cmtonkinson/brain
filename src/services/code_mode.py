"""Code-Mode (UTCP) client integration for external tool access."""

from __future__ import annotations

import json
import logging
import os
import re
from dataclasses import dataclass, field
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

def _preview_text(text: str, limit: int = 200) -> str:
    cleaned = " ".join(text.split())
    if len(cleaned) > limit:
        return cleaned[:limit] + "..."
    return cleaned


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
    _tools_cache: list[Any] = field(default_factory=list)
    _namespace_index: dict[str, list[Any]] = field(default_factory=dict)

    def _route_namespace(self, query: str) -> str | None:
        normalized = query.lower()
        if re.search(r"\b(file|files|filesystem|directory|folder|path|read|write|list)\b", normalized):
            return "filesystem"
        if re.search(r"\b(calendar|calendars|event|events|reminder|reminders)\b", normalized):
            return "eventkit"
        if re.search(r"\b(github|repo|repository|pr|pull request|issue|branch|commit|tag|release)\b", normalized):
            return "github"
        return None

    async def _ensure_tools_cache(self) -> list[Any]:
        if not self._tools_cache:
            self._tools_cache = await self.client.get_tools() if self.client else []
            index: dict[str, list[Any]] = {}
            for tool in self._tools_cache:
                name = getattr(tool, "name", "") or ""
                prefix = name.split(".", 1)[0] if "." in name else ""
                index.setdefault(prefix, []).append(tool)
            self._namespace_index = index
        return self._tools_cache

    def _rank_tools(self, tools: list[Any], query: str) -> list[Any]:
        terms = [term for term in re.split(r"\W+", query.lower()) if term]
        if not terms:
            return tools
        scored: list[tuple[int, Any]] = []
        for tool in tools:
            name = (getattr(tool, "name", "") or "").lower()
            description = (getattr(tool, "description", "") or "").lower()
            score = 0
            for term in terms:
                if term in name:
                    score += 2
                if term in description:
                    score += 1
            scored.append((score, tool))
        scored.sort(key=lambda item: item[0], reverse=True)
        return [tool for score, tool in scored if score > 0] or tools

    async def search_tools(self, query: str) -> str:
        if not self.client:
            return "Code-Mode is not configured. Set UTCP_CONFIG_PATH to enable external tools."

        logger.info("Code-Mode search_tools: %s", _preview_text(query, 160))
        try:
            namespace = self._route_namespace(query)
            if namespace:
                await self._ensure_tools_cache()
                tools = self._rank_tools(self._namespace_index.get(namespace, []), query)
            else:
                tools = await self.client.search_tools(query)
        except Exception as exc:
            logger.error(f"Code-Mode search_tools failed: {exc}")
            return f"Code-Mode search failed: {exc}"

        if not tools:
            return f"No tools found for query '{query}'."

        logger.info("Code-Mode search_tools results: %s", len(tools))
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
            logger.warning(
                "Code-Mode tool chain blocked (destructive=%s)",
                ", ".join(detected),
            )
            return (
                "Potentially destructive operations detected. "
                "Ask the user for confirmation, then retry with "
                "`confirm_destructive=True`."
            )

        logger.info(
            "Code-Mode call_tool_chain start (chars=%s timeout=%s)",
            len(code),
            timeout or self.timeout,
        )
        try:
            result = await self.client.call_tool_chain(
                code, timeout=timeout or self.timeout
            )
        except Exception as exc:
            logger.error(f"Code-Mode call_tool_chain failed: {exc}")
            return f"Code-Mode execution failed: {exc}"

        # Log raw response for debugging
        logger.info("Code-Mode raw response keys: %s", list(result.keys()) if isinstance(result, dict) else type(result))

        logs = result.get("logs", [])
        output = result.get("result")

        # Log what we got
        logger.info("Code-Mode output type: %s, is None: %s", type(output), output is None)
        if output is None:
            logger.warning("Code-Mode result is None. Full response: %s", result)

        logger.info(
            "Code-Mode call_tool_chain done (logs=%s result=%s)",
            len(logs),
            _preview_text(str(output), 160),
        )

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
