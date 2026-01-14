"""Bootstrap Letta tools and agent configuration."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

import httpx

from letta_client import Letta

from config import settings

logger = logging.getLogger(__name__)

_TOOLS = [
    {
        "name": "search_vault",
        "description": "Semantic search over indexed vault embeddings in Qdrant.",
        "path": Path(__file__).parent / "letta_tools" / "qdrant_search.py",
        "pip_requirements": [{"name": "qdrant-client"}, {"name": "httpx"}],
    },
    {
        "name": "read_note",
        "description": "Read a note from Obsidian Local REST by path.",
        "path": Path(__file__).parent / "letta_tools" / "obsidian_read.py",
        "pip_requirements": [{"name": "httpx"}],
    },
]


def _get_attr(obj: Any, key: str) -> Any:
    if isinstance(obj, dict):
        return obj.get(key)
    return getattr(obj, key, None)


def _index_by_name(items: list[Any]) -> dict[str, Any]:
    indexed: dict[str, Any] = {}
    for item in items:
        name = _get_attr(item, "name")
        if name:
            indexed[name] = item
    return indexed


def _ensure_tool(client: Letta, spec: dict[str, Any]) -> str | None:
    tools = client.tools.list()
    existing = _index_by_name(tools).get(spec["name"])
    if existing:
        return _get_attr(existing, "id")

    source_code = spec["path"].read_text(encoding="utf-8")
    create_kwargs = {
        "description": spec["description"],
        "source_type": "python",
        "source_code": source_code,
        "pip_requirements": spec["pip_requirements"],
    }
    try:
        tool = client.tools.create(**create_kwargs)
    except TypeError:
        create_kwargs.pop("source_type", None)
        create_kwargs["source"] = create_kwargs.pop("source_code")
        tool = client.tools.create(**create_kwargs)
    return _get_attr(tool, "id")


def _ensure_agent(client: Letta, tool_ids: list[str]) -> None:
    agents = client.agents.list()
    existing = _index_by_name(agents).get(settings.letta_agent_name)
    llm_config = _build_llm_config()
    embedding_config = _build_embedding_config()
    if existing:
        agent_id = _get_attr(existing, "id")
        update_kwargs = {}
        if llm_config:
            update_kwargs["llm_config"] = llm_config
        if embedding_config:
            update_kwargs["embedding_config"] = embedding_config
        if update_kwargs and agent_id:
            client.agents.update(agent_id, **update_kwargs)
            logger.info("Updated Letta agent config: %s", settings.letta_agent_name)
        else:
            logger.info("Letta agent already exists: %s", settings.letta_agent_name)
        return

    create_kwargs = {
        "name": settings.letta_agent_name,
        "tool_ids": tool_ids,
    }
    if llm_config:
        create_kwargs["llm_config"] = llm_config
    else:
        create_kwargs["model"] = settings.letta_model
    if embedding_config:
        create_kwargs["embedding_config"] = embedding_config
    else:
        create_kwargs["embedding"] = settings.letta_embed_model
    try:
        client.agents.create(**create_kwargs)
    except TypeError:
        create_kwargs["tools"] = create_kwargs.pop("tool_ids")
        client.agents.create(**create_kwargs)
    logger.info("Created Letta agent: %s", settings.letta_agent_name)


def bootstrap_letta() -> None:
    if not settings.letta_base_url:
        logger.warning("LETTA_BASE_URL not configured; skipping Letta bootstrap.")
        return
    if not settings.letta_api_key:
        logger.warning("LETTA_SERVER_PASSWORD/LETTA_API_KEY not configured.")
        return

    client = Letta(base_url=settings.letta_base_url, api_key=settings.letta_api_key)

    tool_ids: list[str] = []
    for spec in _TOOLS:
        tool_id = _ensure_tool(client, spec)
        if tool_id:
            tool_ids.append(tool_id)

    _ensure_agent(client, tool_ids)


def _strip_ollama_prefix(handle: str) -> str:
    if handle.startswith("ollama/"):
        return handle.split("/", 1)[1]
    return handle


def _build_llm_config() -> dict[str, object] | None:
    if not settings.letta_model or not settings.letta_base_url or not settings.letta_api_key:
        return None
    try:
        response = httpx.get(
            f"{settings.letta_base_url.rstrip('/')}/v1/models/",
            headers={"Authorization": f"Bearer {settings.letta_api_key}"},
            timeout=30.0,
            follow_redirects=True,
        )
        response.raise_for_status()
        models = response.json()
        if not isinstance(models, list):
            return None
    except Exception as exc:
        logger.warning("Failed to fetch Letta models: %s", exc)
        return None

    for model in models:
        handle = model.get("handle")
        if handle == settings.letta_model:
            endpoint = _normalize_openai_endpoint(model.get("model_endpoint"))
            return {
                "model": model.get("model") or _strip_ollama_prefix(handle),
                "model_endpoint_type": model.get("model_endpoint_type") or "openai",
                "model_endpoint": endpoint,
                "context_window": model.get("context_window") or 32768,
                "provider_name": model.get("provider_name"),
                "provider_category": model.get("provider_category"),
                "handle": handle,
                "temperature": model.get("temperature", 0.7),
                "max_tokens": model.get("max_tokens"),
                "enable_reasoner": model.get("enable_reasoner", True),
                "max_reasoning_tokens": model.get("max_reasoning_tokens", 0),
                "parallel_tool_calls": model.get("parallel_tool_calls", False),
                "response_format": model.get("response_format"),
            }

    logger.warning("Letta model handle not found in /v1/models: %s", settings.letta_model)
    return None


def _normalize_openai_endpoint(endpoint: str | None) -> str | None:
    if not endpoint:
        return endpoint
    trimmed = endpoint.rstrip("/")
    if trimmed.endswith("/v1"):
        return trimmed
    return f"{trimmed}/v1"


def _build_embedding_config() -> dict[str, object] | None:
    if not settings.ollama_url or not settings.letta_embed_model:
        return None
    model_name = _strip_ollama_prefix(settings.letta_embed_model)
    embedding_endpoint = _normalize_openai_endpoint(settings.ollama_url)
    try:
        response = httpx.post(
            f"{settings.ollama_url.rstrip('/')}/api/embeddings",
            json={"model": model_name, "prompt": "dimension probe"},
            timeout=60.0,
        )
        response.raise_for_status()
        payload = response.json()
        embedding = payload.get("embedding") or []
        embedding_dim = len(embedding)
        if not embedding_dim:
            raise ValueError("Empty embedding returned.")
    except Exception as exc:
        logger.warning("Failed to resolve embedding dim for %s: %s", model_name, exc)
        return None

    return {
        "embedding_dim": embedding_dim,
        "embedding_endpoint_type": "ollama",
        "embedding_model": model_name,
        "embedding_endpoint": embedding_endpoint,
        "batch_size": 1,
    }


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    bootstrap_letta()
