"""Letta (MemGPT) client integration."""

from __future__ import annotations

import logging
from typing import Any

from config import settings
from services.http_client import HttpClient

logger = logging.getLogger(__name__)


def _get_attr(obj: Any, key: str) -> Any:
    """Return attribute or mapping key values with a None fallback."""
    if isinstance(obj, dict):
        return obj.get(key)
    return getattr(obj, key, None)


class LettaService:
    """Client wrapper for Letta archival memory endpoints."""

    def __init__(self) -> None:
        """Initialize the service from settings."""
        self.base_url = (settings.letta.base_url or "").rstrip("/")
        self.api_key = settings.letta.api_key
        self.agent_name = settings.letta.agent_name
        self._agent_id: str | None = None

    @property
    def enabled(self) -> bool:
        """Return True when Letta is configured with URL and API key."""
        return bool(self.base_url and self.api_key)

    def _headers(self) -> dict[str, str]:
        """Build authorization headers for Letta requests."""
        return {"Authorization": f"Bearer {self.api_key}"} if self.api_key else {}

    def _get_agent_id(self) -> str:
        """Resolve and cache the Letta agent ID by name."""
        if self._agent_id:
            return self._agent_id

        client = HttpClient()
        response = client.get(
            f"{self.base_url}/v1/agents",
            headers=self._headers(),
            follow_redirects=True,
        )
        agents = response.json()
        if isinstance(agents, dict):
            agents = agents.get("agents") or agents.get("data") or agents.get("items") or []
        if not isinstance(agents, list):
            raise ValueError("Unexpected Letta agents response.")

        for agent in agents:
            if _get_attr(agent, "name") == self.agent_name:
                self._agent_id = str(_get_attr(agent, "id"))
                return self._agent_id

        raise ValueError(f"Letta agent not found: {self.agent_name}")

    def _post_with_fallbacks(
        self,
        attempts: list[tuple[str, dict[str, Any]]],
        timeout: float | None = None,
    ) -> Any:
        """POST to the first available endpoint from a fallback list."""
        import httpx

        if timeout is None:
            timeout = settings.http.timeout
        client = HttpClient(timeout=int(timeout))
        last_status: int | None = None
        last_body: str | None = None
        for url, payload in attempts:
            try:
                response = client.post(
                    url,
                    headers=self._headers(),
                    json=payload,
                    follow_redirects=True,
                )
                return response.json()
            except httpx.HTTPStatusError as e:
                if e.response.status_code in (404, 422):
                    last_status = e.response.status_code
                    last_body = e.response.text
                    continue
                raise
        detail = f" (last status={last_status}, body={last_body})" if last_status else ""
        raise RuntimeError(f"Letta memory endpoint not available{detail}")

    def _get_with_fallbacks(
        self,
        attempts: list[tuple[str, dict[str, Any]]],
        timeout: float | None = None,
    ) -> Any:
        """GET from the first available endpoint in a fallback list."""
        import httpx

        if timeout is None:
            timeout = settings.http.timeout
        client = HttpClient(timeout=int(timeout))
        last_status: int | None = None
        last_body: str | None = None
        for url, params in attempts:
            try:
                response = client.get(
                    url,
                    headers=self._headers(),
                    params=params,
                    follow_redirects=True,
                )
                return response.json()
            except httpx.HTTPStatusError as e:
                if e.response.status_code in (404, 422):
                    last_status = e.response.status_code
                    last_body = e.response.text
                    continue
                raise
        detail = f" (last status={last_status}, body={last_body})" if last_status else ""
        raise RuntimeError(f"Letta memory endpoint not available{detail}")

    def _extract_memory_results(self, data: Any) -> list[dict[str, Any]]:
        """Normalize memory search results into a list of dicts."""
        if isinstance(data, dict):
            for key in ("results", "memories", "data", "items"):
                value = data.get(key)
                if isinstance(value, list):
                    return [item for item in value if isinstance(item, dict)]
        if isinstance(data, list):
            return [item for item in data if isinstance(item, dict)]
        return []

    def _format_memory_results(self, data: Any) -> str:
        """Render memory search results into a human-readable list."""
        items = self._extract_memory_results(data)
        if not items:
            return "No memory results found."

        lines: list[str] = []
        for item in items:
            content = (
                item.get("content")
                or item.get("text")
                or item.get("memory")
                or item.get("document")
            )
            if isinstance(content, dict):
                content = content.get("text") or content.get("content") or str(content)
            if content is None:
                content = str(item)
            score = item.get("score") or item.get("similarity")
            score_text = f" (score {score:.3f})" if isinstance(score, (int, float)) else ""
            lines.append(f"- {content}{score_text}")
        return "\n".join(lines)

    def search_archival_memory(self, query: str) -> str:
        """Search archival memory for the query text."""
        if not self.enabled:
            raise RuntimeError("Letta is not configured.")
        agent_id = self._get_agent_id()
        logger.info("Letta archival search: agent=%s chars=%s", self.agent_name, len(query))
        attempts = [
            (
                f"{self.base_url}/v1/agents/{agent_id}/archival-memory/search",
                {"query": query},
            ),
            (
                f"{self.base_url}/v1/agents/{agent_id}/archival_memory/search",
                {"query": query},
            ),
            (
                f"{self.base_url}/v1/agents/{agent_id}/memory/search",
                {"query": query, "memory_type": "archival"},
            ),
        ]
        data = self._get_with_fallbacks(attempts)
        logger.info(
            "Letta archival search results: %s item(s)",
            len(self._extract_memory_results(data)),
        )
        return self._format_memory_results(data)

    def insert_to_archival(self, content: str) -> str:
        """Insert content into archival memory and return a status string."""
        if not self.enabled:
            raise RuntimeError("Letta is not configured.")
        agent_id = self._get_agent_id()
        logger.info("Letta archival insert: agent=%s chars=%s", self.agent_name, len(content))
        attempts = [
            (
                f"{self.base_url}/v1/agents/{agent_id}/archival-memory",
                {"text": content},
            ),
            (
                f"{self.base_url}/v1/agents/{agent_id}/archival-memory",
                {"content": content},
            ),
            (
                f"{self.base_url}/v1/agents/{agent_id}/archival_memory",
                {"text": content},
            ),
            (
                f"{self.base_url}/v1/agents/{agent_id}/archival_memory",
                {"content": content},
            ),
        ]
        data = self._post_with_fallbacks(attempts)
        memory_id = None
        if isinstance(data, dict):
            memory_id = data.get("id") or data.get("memory_id")
        if memory_id:
            return f"Saved to memory (id {memory_id})."
        return "Saved to memory."
