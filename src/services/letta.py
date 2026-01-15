"""Letta (MemGPT) client integration."""

from __future__ import annotations

import logging
import warnings
from typing import Any

import httpx

from config import settings

logger = logging.getLogger(__name__)


def _get_attr(obj: Any, key: str) -> Any:
    if isinstance(obj, dict):
        return obj.get(key)
    return getattr(obj, key, None)


class LettaService:
    def __init__(self) -> None:
        self.base_url = (settings.letta.base_url or "").rstrip("/")
        self.api_key = settings.letta.api_key
        self.agent_name = settings.letta.agent_name
        self._agent_id: str | None = None

    @property
    def enabled(self) -> bool:
        return bool(self.base_url and self.api_key)

    def _headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self.api_key}"} if self.api_key else {}

    def _get_agent_id(self) -> str:
        if self._agent_id:
            return self._agent_id

        response = httpx.get(
            f"{self.base_url}/v1/agents",
            headers=self._headers(),
            timeout=settings.llm.timeout,
            follow_redirects=True,
        )
        response.raise_for_status()
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

    def _post_message_http(self, agent_id: str, message: str) -> str:
        url = f"{self.base_url}/v1/agents/{agent_id}/messages"
        payload = {"input": message, "streaming": False}
        response = httpx.post(
            url,
            headers=self._headers(),
            json=payload,
            timeout=settings.llm.timeout,
            follow_redirects=True,
        )
        response.raise_for_status()
        data = response.json()
        return self._extract_response_text(data)

    def _extract_response_text(self, data: Any) -> str:
        def _content_to_text(content: Any) -> str | None:
            if isinstance(content, str):
                return content
            if isinstance(content, list):
                parts = []
                for item in content:
                    if isinstance(item, dict) and item.get("type") == "text":
                        text = item.get("text")
                        if isinstance(text, str):
                            parts.append(text)
                return "\n".join(parts).strip() if parts else None
            return None

        if isinstance(data, dict):
            for key in ("message", "text", "content", "response"):
                value = data.get(key)
                text_value = _content_to_text(value)
                if text_value:
                    return text_value
            for key in ("messages", "data", "items"):
                value = data.get(key)
                if isinstance(value, list):
                    return self._extract_response_text(value)
        if isinstance(data, list):
            for item in reversed(data):
                if not isinstance(item, dict):
                    continue
                if item.get("role") == "assistant":
                    content = item.get("content") or item.get("message") or item.get("text")
                    text_value = _content_to_text(content)
                    if text_value:
                        return text_value
                if item.get("message_type") == "assistant_message":
                    content = item.get("content") or item.get("message")
                    text_value = _content_to_text(content)
                    if text_value:
                        return text_value
        raise ValueError("Letta response did not include assistant content.")

    def send_message(self, message: str) -> str:
        """Send a message to the Letta agent runtime (deprecated)."""
        warnings.warn(
            "LettaService.send_message is deprecated; use archival memory methods instead.",
            DeprecationWarning,
            stacklevel=2,
        )
        if not self.enabled:
            raise RuntimeError("Letta is not configured.")
        agent_id = self._get_agent_id()
        logger.info("Letta request: agent=%s chars=%s", self.agent_name, len(message))
        response = self._post_message_http(agent_id, message)
        logger.info("Letta response: agent=%s chars=%s", self.agent_name, len(response))
        return response

    def _post_with_fallbacks(
        self,
        attempts: list[tuple[str, dict[str, Any]]],
        timeout: float | None = None,
    ) -> Any:
        if timeout is None:
            timeout = settings.llm.timeout
        last_status: int | None = None
        last_body: str | None = None
        for url, payload in attempts:
            response = httpx.post(
                url,
                headers=self._headers(),
                json=payload,
                timeout=timeout,
                follow_redirects=True,
            )
            if response.status_code in (404, 422):
                last_status = response.status_code
                last_body = response.text
                continue
            response.raise_for_status()
            return response.json()
        detail = f" (last status={last_status}, body={last_body})" if last_status else ""
        raise RuntimeError(f"Letta memory endpoint not available{detail}")

    def _get_with_fallbacks(
        self,
        attempts: list[tuple[str, dict[str, Any]]],
        timeout: float | None = None,
    ) -> Any:
        if timeout is None:
            timeout = settings.llm.timeout
        last_status: int | None = None
        last_body: str | None = None
        for url, params in attempts:
            response = httpx.get(
                url,
                headers=self._headers(),
                params=params,
                timeout=timeout,
                follow_redirects=True,
            )
            if response.status_code in (404, 422):
                last_status = response.status_code
                last_body = response.text
                continue
            response.raise_for_status()
            return response.json()
        detail = f" (last status={last_status}, body={last_body})" if last_status else ""
        raise RuntimeError(f"Letta memory endpoint not available{detail}")

    def _extract_memory_results(self, data: Any) -> list[dict[str, Any]]:
        if isinstance(data, dict):
            for key in ("results", "memories", "data", "items"):
                value = data.get(key)
                if isinstance(value, list):
                    return [item for item in value if isinstance(item, dict)]
        if isinstance(data, list):
            return [item for item in data if isinstance(item, dict)]
        return []

    def _format_memory_results(self, data: Any) -> str:
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
            score_text = (
                f" (score {score:.3f})" if isinstance(score, (int, float)) else ""
            )
            lines.append(f"- {content}{score_text}")
        return "\n".join(lines)

    def search_archival_memory(self, query: str) -> str:
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
