"""In-process LiteLLM adapter implementation."""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any, Mapping, Sequence

import litellm

from packages.brain_shared.logging import get_logger, public_api_instrumented
from resources.adapters.litellm.adapter import (
    AdapterChatResult,
    AdapterDependencyError,
    AdapterEmbeddingResult,
    AdapterHealthResult,
    AdapterInternalError,
    LiteLlmAdapter,
)
from resources.adapters.litellm.component import RESOURCE_COMPONENT_ID
from resources.adapters.litellm.config import (
    LiteLlmAdapterSettings,
    LiteLlmProviderSettings,
)

_LOGGER = get_logger(__name__)


@dataclass(frozen=True)
class _ResolvedProviderSettings:
    """Resolved per-provider call settings including merged defaults."""

    api_base: str
    api_key: str
    timeout_seconds: float
    max_retries: int
    options: dict[str, Any]


class LiteLlmLibraryAdapter(LiteLlmAdapter):
    """In-process LiteLLM adapter backed by the `litellm` Python package."""

    def __init__(self, *, settings: LiteLlmAdapterSettings) -> None:
        self._settings = settings

    @public_api_instrumented(
        logger=_LOGGER,
        component_id=str(RESOURCE_COMPONENT_ID),
    )
    def chat(
        self,
        *,
        provider: str,
        model: str,
        prompt: str,
    ) -> AdapterChatResult:
        """Generate one chat completion using the LiteLLM Python API."""
        response = self._call_completion(
            provider=provider,
            model=model,
            messages=[{"role": "user", "content": prompt}],
        )
        content = _extract_chat_content(response)
        return AdapterChatResult(text=content, provider=provider, model=model)

    @public_api_instrumented(
        logger=_LOGGER,
        component_id=str(RESOURCE_COMPONENT_ID),
    )
    def chat_batch(
        self,
        *,
        provider: str,
        model: str,
        prompts: Sequence[str],
    ) -> list[AdapterChatResult]:
        """Generate one chat completion per prompt in order."""
        return [
            self.chat(provider=provider, model=model, prompt=item) for item in prompts
        ]

    @public_api_instrumented(
        logger=_LOGGER,
        component_id=str(RESOURCE_COMPONENT_ID),
    )
    def embed(
        self,
        *,
        provider: str,
        model: str,
        text: str,
    ) -> AdapterEmbeddingResult:
        """Generate one embedding vector using the LiteLLM Python API."""
        payload = self.embed_batch(provider=provider, model=model, texts=[text])
        if len(payload) == 0:
            raise AdapterInternalError("embedding response payload is empty")
        return payload[0]

    @public_api_instrumented(
        logger=_LOGGER,
        component_id=str(RESOURCE_COMPONENT_ID),
    )
    def embed_batch(
        self,
        *,
        provider: str,
        model: str,
        texts: Sequence[str],
    ) -> list[AdapterEmbeddingResult]:
        """Generate embedding vectors from one batch request."""
        response = self._call_embedding(
            provider=provider,
            model=model,
            inputs=list(texts),
        )
        vectors = _extract_embedding_vectors(response)
        return [
            AdapterEmbeddingResult(values=item, provider=provider, model=model)
            for item in vectors
        ]

    @public_api_instrumented(
        logger=_LOGGER,
        component_id=str(RESOURCE_COMPONENT_ID),
    )
    def health(self) -> AdapterHealthResult:
        """Return adapter readiness based on library/provider configuration viability."""
        try:
            _load_litellm_module()
            for provider_name in self._settings.providers:
                self._resolve_provider_settings(provider=provider_name)
        except AdapterInternalError as exc:
            return AdapterHealthResult(adapter_ready=False, detail=str(exc))
        return AdapterHealthResult(adapter_ready=True, detail="ok")

    def _call_completion(
        self,
        *,
        provider: str,
        model: str,
        messages: list[dict[str, str]],
    ) -> object:
        """Invoke `litellm.completion` with resolved provider settings."""
        litellm = _load_litellm_module()
        resolved = self._resolve_provider_settings(provider=provider)
        kwargs = self._request_kwargs(provider=provider, model=model, resolved=resolved)
        kwargs["messages"] = messages
        try:
            return litellm.completion(**kwargs)
        except Exception as exc:
            self._raise_mapped_exception(exc)

    def _call_embedding(
        self,
        *,
        provider: str,
        model: str,
        inputs: list[str],
    ) -> object:
        """Invoke `litellm.embedding` with resolved provider settings."""
        litellm = _load_litellm_module()
        resolved = self._resolve_provider_settings(provider=provider)
        kwargs = self._request_kwargs(provider=provider, model=model, resolved=resolved)
        kwargs["input"] = inputs
        try:
            return litellm.embedding(**kwargs)
        except Exception as exc:
            self._raise_mapped_exception(exc)

    def _resolve_provider_settings(self, *, provider: str) -> _ResolvedProviderSettings:
        """Resolve provider-specific settings and enforce configuration validity."""
        provider_config = self._settings.providers.get(provider)
        if provider_config is None:
            raise AdapterInternalError(f"provider '{provider}' is not configured")

        api_key = self._resolve_api_key(
            provider=provider, provider_config=provider_config
        )
        return _ResolvedProviderSettings(
            api_base=provider_config.api_base.strip(),
            api_key=api_key,
            timeout_seconds=(
                self._settings.timeout_seconds
                if provider_config.timeout_seconds is None
                else provider_config.timeout_seconds
            ),
            max_retries=(
                self._settings.max_retries
                if provider_config.max_retries is None
                else provider_config.max_retries
            ),
            options=dict(provider_config.options),
        )

    def _resolve_api_key(
        self,
        *,
        provider: str,
        provider_config: LiteLlmProviderSettings,
    ) -> str:
        """Resolve provider API key from inline value or environment variable."""
        inline_key = provider_config.api_key.strip()
        if inline_key != "":
            return inline_key
        env_key = provider_config.api_key_env.strip()
        if env_key == "":
            return ""
        resolved = os.environ.get(env_key, "").strip()
        if resolved == "":
            raise AdapterInternalError(
                f"provider '{provider}' requires environment variable '{env_key}'"
            )
        return resolved

    def _request_kwargs(
        self,
        *,
        provider: str,
        model: str,
        resolved: _ResolvedProviderSettings,
    ) -> dict[str, Any]:
        """Build one LiteLLM request kwargs mapping."""
        kwargs: dict[str, Any] = {
            "model": _qualified_model(provider=provider, model=model),
            "timeout": resolved.timeout_seconds,
            "num_retries": resolved.max_retries,
        }
        if resolved.api_base != "":
            kwargs["api_base"] = resolved.api_base
        if resolved.api_key != "":
            kwargs["api_key"] = resolved.api_key
        kwargs.update(resolved.options)
        return kwargs

    def _raise_mapped_exception(self, exc: Exception) -> None:
        """Map third-party exceptions into adapter dependency/internal classes."""
        if _is_dependency_exception(exc):
            raise AdapterDependencyError(
                str(exc) or "litellm dependency failure"
            ) from None
        raise AdapterInternalError(
            str(exc) or "litellm adapter internal failure"
        ) from None


def _load_litellm_module() -> Any:
    """Return the imported `litellm` module."""
    return litellm


def _qualified_model(*, provider: str, model: str) -> str:
    """Compose LiteLLM provider/model selector value."""
    return f"{provider}/{model}"


def _extract_chat_content(response: object) -> str:
    """Extract first chat message content from LiteLLM completion response."""
    choice = _first_item(
        _response_field(response=response, field="choices"), field="choices"
    )
    message = _response_field(response=choice, field="message")
    content = _response_field(response=message, field="content")
    if not isinstance(content, str):
        raise AdapterInternalError("chat response content is invalid")
    return content


def _extract_embedding_vectors(response: object) -> list[tuple[float, ...]]:
    """Extract embedding vectors from LiteLLM embedding response."""
    rows = _response_field(response=response, field="data")
    if not isinstance(rows, list):
        raise AdapterInternalError("embedding response missing data")
    vectors: list[tuple[float, ...]] = []
    for row in rows:
        embedding = _response_field(response=row, field="embedding")
        if not isinstance(embedding, list):
            raise AdapterInternalError("embedding values are missing")
        try:
            vectors.append(tuple(float(item) for item in embedding))
        except (TypeError, ValueError):
            raise AdapterInternalError("embedding values are invalid") from None
    return vectors


def _response_field(*, response: object, field: str) -> object:
    """Read one field from a response mapping or object."""
    if isinstance(response, Mapping):
        value = response.get(field)
    else:
        value = getattr(response, field, None)
    if value is None:
        raise AdapterInternalError(f"response missing {field}")
    return value


def _first_item(payload: object, *, field: str) -> object:
    """Return first item from a non-empty list payload."""
    if not isinstance(payload, list) or len(payload) == 0:
        raise AdapterInternalError(f"response missing {field}")
    return payload[0]


def _is_dependency_exception(exc: Exception) -> bool:
    """Heuristic mapping of LiteLLM/provider failures to dependency class."""
    if isinstance(exc, (TimeoutError, ConnectionError)):
        return True

    name = exc.__class__.__name__.lower()
    text = str(exc).lower()
    dependency_tokens = (
        "timeout",
        "connection",
        "network",
        "rate limit",
        "temporarily unavailable",
        "service unavailable",
        "unavailable",
        "http",
        "429",
        "502",
        "503",
        "504",
    )
    if any(token in name for token in ("timeout", "connection", "ratelimit")):
        return True
    if any(token in text for token in dependency_tokens):
        return True
    return False
