"""Native LLM adapter implementation."""

from __future__ import annotations

import json
import os
import re
from random import random
from dataclasses import dataclass
from http import HTTPStatus
from pathlib import Path
from time import perf_counter, sleep
from typing import Any, Mapping, Sequence

import httpx

from lib.shared.language_model import (
    CachePointContentPart,
    ChatContentPart,
    ConversationSummaryContentPart,
    DialogueTurnContentPart,
    EnvironmentContextContentPart,
    FocusContentPart,
    InferenceAssistantTextEvent,
    InferenceCache,
    InferenceCurrentTurn,
    InferenceEnvironmentContext,
    InferenceLiveEvent,
    InferenceMemoryContext,
    InferenceOperatorMessage,
    InferenceParallelToolCalls,
    InferenceRequest,
    InferenceSystemBlock,
    InferenceToolCall,
    InferenceToolCallBatchEvent,
    InferenceToolChoice,
    InferenceToolDefinition,
    InferenceToolResult,
    InferenceToolResultBatchEvent,
    InferenceToolResultPayload,
    MetadataFieldContentPart,
    OperatorMessageContentPart,
    ReferenceSnippetContentPart,
    TextContentPart,
)
from lib.shared.logging import get_logger, public_api_instrumented
from resources.adapters.llm.adapter import (
    AdapterChatResult,
    AdapterChatMessage,
    AdapterChatToolCall,
    AdapterChatToolDefinition,
    AdapterDependencyError,
    AdapterEmbeddingResult,
    AdapterHealthResult,
    AdapterInternalError,
    AdapterProviderCallAudit,
    AdapterToolChatResult,
    LlmAdapter,
)
from resources.adapters.llm.component import RESOURCE_COMPONENT_ID
from resources.adapters.llm.config import (
    LlmAdapterSettings,
    LlmProviderSettings,
    timeout_retry_backoff_schedule_seconds,
)

_LOGGER = get_logger(__name__)
_VOYAGE_API_BASE = "https://api.voyageai.com"
_OLLAMA_API_BASE = "http://host.docker.internal:11434"
_ANTHROPIC_API_BASE = "https://api.anthropic.com"
_ANTHROPIC_VERSION = "2023-06-01"
_DEFAULT_ANTHROPIC_MAX_TOKENS = 1024
_MAX_ANTHROPIC_CACHE_CONTROL_BLOCKS = 4
_CHAT_PROVIDERS = frozenset({"anthropic"})
_EMBEDDING_PROVIDERS = frozenset({"voyage", "ollama"})
_RESOURCE_DIR = Path(__file__).resolve().parent
_PROMPTS_DIR = _RESOURCE_DIR / "prompts"
_FOCUS_TEMPLATE_PATH = _PROMPTS_DIR / "focus-template.txt"
_CONVERSATION_SUMMARY_TEMPLATE_PATH = _PROMPTS_DIR / "conversation-summary-template.txt"
_ENVIRONMENT_CONTEXT_TEMPLATE_PATH = _PROMPTS_DIR / "environment-context-template.txt"
_DIALOGUE_TEMPLATE_PATH = _PROMPTS_DIR / "dialogue-template.txt"
_REFERENCE_CONTEXT_TEMPLATE_PATH = _PROMPTS_DIR / "reference-context-template.txt"
_METADATA_FIELD_TEMPLATE_PATH = _PROMPTS_DIR / "metadata-field-template.txt"
_OPERATOR_MESSAGE_TEMPLATE_PATH = _PROMPTS_DIR / "operator-message-template.txt"
_PROMPT_TEMPLATE_VAR_RE = re.compile(r"\{\{\s*([a-z_][a-z0-9_]*)\s*\}\}")


def _load_prompt_file(path: Path) -> str:
    """Load one prompt text file from disk without altering its contents."""
    return path.read_text(encoding="utf-8")


def _render_prompt_template(template: str, /, **values: str) -> str:
    """Render one prompt template and reject unresolved placeholders."""

    def _replace(match: re.Match[str]) -> str:
        key = match.group(1)
        if key not in values:
            return match.group(0)
        return values[key]

    rendered = _PROMPT_TEMPLATE_VAR_RE.sub(_replace, template)
    unresolved = _PROMPT_TEMPLATE_VAR_RE.findall(rendered)
    if unresolved:
        raise ValueError(
            f"unresolved prompt template placeholders: {', '.join(sorted(unresolved))}"
        )
    return rendered


_FOCUS_TEMPLATE = _load_prompt_file(_FOCUS_TEMPLATE_PATH)
_CONVERSATION_SUMMARY_TEMPLATE = _load_prompt_file(_CONVERSATION_SUMMARY_TEMPLATE_PATH)
_ENVIRONMENT_CONTEXT_TEMPLATE = _load_prompt_file(_ENVIRONMENT_CONTEXT_TEMPLATE_PATH)
_DIALOGUE_TEMPLATE = _load_prompt_file(_DIALOGUE_TEMPLATE_PATH)
_REFERENCE_CONTEXT_TEMPLATE = _load_prompt_file(_REFERENCE_CONTEXT_TEMPLATE_PATH)
_METADATA_FIELD_TEMPLATE = _load_prompt_file(_METADATA_FIELD_TEMPLATE_PATH)
_OPERATOR_MESSAGE_TEMPLATE = _load_prompt_file(_OPERATOR_MESSAGE_TEMPLATE_PATH)

if frozenset(_PROMPT_TEMPLATE_VAR_RE.findall(_FOCUS_TEMPLATE)) != {"text"}:
    raise ValueError("focus-template.txt must contain exactly {{ text }}")
if frozenset(_PROMPT_TEMPLATE_VAR_RE.findall(_CONVERSATION_SUMMARY_TEMPLATE)) != {
    "text"
}:
    raise ValueError(
        "conversation-summary-template.txt must contain exactly {{ text }}"
    )
if frozenset(_PROMPT_TEMPLATE_VAR_RE.findall(_ENVIRONMENT_CONTEXT_TEMPLATE)) != {
    "capability_blocks"
}:
    raise ValueError(
        "environment-context-template.txt must contain exactly {{ capability_blocks }}"
    )
if frozenset(_PROMPT_TEMPLATE_VAR_RE.findall(_DIALOGUE_TEMPLATE)) != {"turns"}:
    raise ValueError("dialogue-template.txt must contain exactly {{ turns }}")
if frozenset(_PROMPT_TEMPLATE_VAR_RE.findall(_REFERENCE_CONTEXT_TEMPLATE)) != {
    "snippets"
}:
    raise ValueError(
        "reference-context-template.txt must contain exactly {{ snippets }}"
    )
if frozenset(_PROMPT_TEMPLATE_VAR_RE.findall(_METADATA_FIELD_TEMPLATE)) != {
    "name",
    "value",
}:
    raise ValueError(
        "metadata-field-template.txt must contain exactly {{ name }} and {{ value }}"
    )
if frozenset(_PROMPT_TEMPLATE_VAR_RE.findall(_OPERATOR_MESSAGE_TEMPLATE)) != {
    "metadata",
    "message_text",
}:
    raise ValueError(
        "operator-message-template.txt must contain exactly "
        "{{ metadata }} and {{ message_text }}"
    )


@dataclass(frozen=True)
class _LoweredToolInferenceRequest:
    """Provider-ready request payload derived from one inference request."""

    messages: list[dict[str, Any]]
    tools: list[dict[str, Any]]
    tool_choice: str | dict[str, object] | None
    parallel_tool_calls: bool | None
    extra_kwargs: dict[str, Any]


@dataclass(frozen=True)
class _ResolvedProviderSettings:
    """Resolved per-provider call settings including merged defaults."""

    api_base: str
    api_key: str
    timeout_seconds: float
    max_retries: int
    options: dict[str, Any]


class HttpLlmAdapter(LlmAdapter):
    """HTTP-backed native provider adapter."""

    def __init__(self, *, settings: LlmAdapterSettings) -> None:
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
        system_prompt: str = "",
        prompt: str,
    ) -> AdapterChatResult:
        """Generate one chat completion."""
        self._require_supported_provider(provider=provider, operation="chat")
        messages, extra_kwargs = _serialize_simple_prompt_for_provider(
            provider=provider,
            system_prompt=system_prompt,
            prompt=prompt,
        )
        response, raw_call = self._call_anthropic_messages(
            model=model,
            messages=messages,
            tools=None,
            tool_choice=None,
            parallel_tool_calls=None,
            extra_kwargs=extra_kwargs,
        )
        content = _extract_anthropic_text_content(response)
        return AdapterChatResult(
            text=content,
            provider=provider,
            model=model,
            raw_call=raw_call,
        )

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
    def chat_with_tools(
        self,
        *,
        provider: str,
        model: str,
        inference_request: InferenceRequest,
    ) -> AdapterToolChatResult:
        """Generate one tool-capable completion."""
        self._require_supported_provider(provider=provider, operation="chat_with_tools")
        lowered = _lower_inference_request_for_provider(
            provider=provider,
            inference_request=inference_request,
        )
        response, raw_call = self._call_anthropic_messages(
            model=model,
            messages=lowered.messages,
            tools=lowered.tools,
            tool_choice=lowered.tool_choice,
            parallel_tool_calls=lowered.parallel_tool_calls,
            extra_kwargs=lowered.extra_kwargs,
        )
        return AdapterToolChatResult(
            text=_extract_optional_anthropic_text_content(response),
            tool_calls=tuple(_extract_anthropic_tool_calls(response)),
            provider=provider,
            model=model,
            finish_reason=_extract_anthropic_finish_reason(response),
            raw_call=raw_call,
        )

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
        dimensions: int | None = None,
    ) -> AdapterEmbeddingResult:
        """Generate one embedding vector."""
        payload = self._embed_many(
            provider=provider,
            model=model,
            texts=[text],
            input_type="query",
            dimensions=dimensions,
        )
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
        dimensions: int | None = None,
    ) -> list[AdapterEmbeddingResult]:
        """Generate embedding vectors from one batch request."""
        return self._embed_many(
            provider=provider,
            model=model,
            texts=texts,
            input_type="document",
            dimensions=dimensions,
        )

    def _embed_many(
        self,
        *,
        provider: str,
        model: str,
        texts: Sequence[str],
        input_type: str | None,
        dimensions: int | None,
    ) -> list[AdapterEmbeddingResult]:
        """Generate embedding vectors from one batch request with provider hints."""
        self._require_supported_provider(provider=provider, operation="embed_batch")
        resolved = self._resolve_provider_settings(provider=provider)
        body: dict[str, Any] = {
            "model": model,
            "input": list(texts),
        }
        if provider == "voyage" and input_type is not None:
            body["input_type"] = input_type
        if dimensions is not None:
            if provider == "voyage":
                body["output_dimension"] = dimensions
            elif provider == "ollama":
                body["dimensions"] = dimensions
        for key, value in resolved.options.items():
            if (
                provider == "voyage"
                and key == "output_dimension"
                and dimensions is not None
            ):
                continue
            if provider == "ollama" and key == "dimensions" and dimensions is not None:
                continue
            body.setdefault(key, value)
        if provider == "ollama":
            path = "/api/embed"
            headers = {"content-type": "application/json"}
        elif provider == "voyage":
            path = "/v1/embeddings"
            headers = _voyage_headers(api_key=resolved.api_key)
        else:
            self._raise_provider_not_implemented(
                provider=provider,
                operation="embed_batch",
            )
        payload, raw_call = self._post_json(
            provider=provider,
            model=model,
            operation="embed_batch",
            resolved=resolved,
            path=path,
            headers=headers,
            body=body,
        )
        if provider == "ollama":
            embeddings = _extract_ollama_embedding_vectors(
                payload=payload,
                expected_count=len(texts),
            )
            response_model = _extract_ollama_response_model(
                payload=payload,
                fallback=model,
            )
        else:
            embeddings = _extract_voyage_embedding_vectors(
                payload=payload,
                expected_count=len(texts),
            )
            response_model = _extract_voyage_response_model(
                payload=payload,
                fallback=model,
            )
        return [
            AdapterEmbeddingResult(
                values=vector,
                provider=provider,
                model=response_model,
                raw_call=raw_call,
            )
            for vector in embeddings
        ]

    @public_api_instrumented(
        logger=_LOGGER,
        component_id=str(RESOURCE_COMPONENT_ID),
    )
    def health(self) -> AdapterHealthResult:
        """Return adapter readiness based on configuration viability."""
        try:
            for provider_name in self._settings.providers:
                if (
                    provider_name in _CHAT_PROVIDERS
                    or provider_name in _EMBEDDING_PROVIDERS
                ):
                    self._resolve_provider_settings(provider=provider_name)
        except AdapterInternalError as exc:
            return AdapterHealthResult(adapter_ready=False, detail=str(exc))
        return AdapterHealthResult(adapter_ready=True, detail="ok")

    def _call_anthropic_messages(
        self,
        *,
        model: str,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None,
        tool_choice: str | dict[str, object] | None,
        parallel_tool_calls: bool | None,
        extra_kwargs: dict[str, Any] | None,
    ) -> tuple[object, AdapterProviderCallAudit | None]:
        """Invoke Anthropic's native Messages API."""
        provider = "anthropic"
        resolved = self._resolve_provider_settings(provider=provider)
        body: dict[str, Any] = {"model": model, "messages": messages}
        if tools is not None:
            body["tools"] = tools
        if tool_choice is not None:
            body["tool_choice"] = tool_choice
        if parallel_tool_calls is not None:
            body["parallel_tool_calls"] = parallel_tool_calls
        if extra_kwargs is not None:
            body.update(extra_kwargs)
        for key, value in resolved.options.items():
            body.setdefault(key, value)
        body.setdefault("max_tokens", _DEFAULT_ANTHROPIC_MAX_TOKENS)
        return self._post_json(
            provider=provider,
            model=model,
            operation="messages",
            resolved=resolved,
            path="/v1/messages",
            headers=_anthropic_headers(api_key=resolved.api_key),
            body=body,
        )

    def _post_json(
        self,
        *,
        provider: str,
        model: str,
        operation: str,
        resolved: _ResolvedProviderSettings,
        path: str,
        headers: dict[str, str],
        body: dict[str, Any],
    ) -> tuple[object, AdapterProviderCallAudit]:
        """POST one provider JSON request with audit and retry handling."""
        api_base = resolved.api_base or _default_api_base_for_provider(provider)
        url = f"{api_base.rstrip('/')}{path}"
        timeout_schedule = timeout_retry_backoff_schedule_seconds(self._settings)
        timeout_attempt = 0
        dependency_attempt = 0
        started_at = perf_counter()
        audit = AdapterProviderCallAudit(
            request_api_base=api_base,
            request_headers=_sanitize_request_headers(headers),
            request_body=_json_safe_value(body),
            response_body=None,
        )
        while True:
            _LOGGER.debug(
                "LLM provider request starting",
                extra={
                    "provider": provider,
                    "model": model,
                    "operation": operation,
                    "api_base": api_base,
                },
            )
            try:
                response = httpx.post(
                    url,
                    headers=headers,
                    json=body,
                    timeout=resolved.timeout_seconds,
                )
            except Exception as exc:
                failed_audit = audit.model_copy(
                    update={"response_body": _response_body_from_exception(exc)}
                )
                if _is_timeout_exception(exc) and timeout_attempt < len(
                    timeout_schedule
                ):
                    delay = _jittered_delay(
                        base_delay=timeout_schedule[timeout_attempt],
                        jitter_ratio=self._settings.timeout_retry_jitter_ratio,
                    )
                    timeout_attempt += 1
                    _log_retry(
                        provider=provider,
                        model=model,
                        operation=operation,
                        reason="timeout",
                        attempt=timeout_attempt,
                        delay=delay,
                    )
                    if delay > 0:
                        sleep(delay)
                    continue
                if (
                    _is_dependency_exception(exc)
                    and dependency_attempt < resolved.max_retries
                ):
                    delay = _dependency_retry_delay_seconds(
                        attempt_index=dependency_attempt,
                        settings=self._settings,
                    )
                    dependency_attempt += 1
                    _log_retry(
                        provider=provider,
                        model=model,
                        operation=operation,
                        reason="dependency",
                        attempt=dependency_attempt,
                        delay=delay,
                    )
                    if delay > 0:
                        sleep(delay)
                    continue
                self._raise_mapped_exception(exc, raw_call=failed_audit)

            response_body = _response_payload_from_httpx(response)
            current_audit = audit.model_copy(update={"response_body": response_body})
            if (
                _is_retryable_status_code(response.status_code)
                and dependency_attempt < resolved.max_retries
            ):
                delay = _dependency_retry_delay_seconds(
                    attempt_index=dependency_attempt,
                    settings=self._settings,
                )
                dependency_attempt += 1
                _log_retry(
                    provider=provider,
                    model=model,
                    operation=operation,
                    reason=f"http_{response.status_code}",
                    attempt=dependency_attempt,
                    delay=delay,
                )
                if delay > 0:
                    sleep(delay)
                continue
            if response.status_code >= 400:
                self._raise_http_error(
                    provider=provider,
                    response=response,
                    raw_call=current_audit,
                )
            try:
                payload = response.json()
            except Exception as exc:
                raise AdapterInternalError(
                    f"provider '{provider}' returned invalid JSON",
                    raw_call=current_audit,
                ) from exc
            _LOGGER.debug(
                "LLM provider request completed",
                extra={
                    "provider": provider,
                    "model": model,
                    "operation": operation,
                    "duration_ms": round((perf_counter() - started_at) * 1000, 3),
                },
            )
            return payload, current_audit

    def _resolve_provider_settings(self, *, provider: str) -> _ResolvedProviderSettings:
        """Resolve provider-specific settings and enforce configuration validity."""
        provider_config = self._settings.providers.get(provider)
        if provider_config is None:
            raise AdapterInternalError(f"provider '{provider}' is not configured")

        api_key = self._resolve_api_key(
            provider=provider, provider_config=provider_config
        )
        if provider == "voyage" and api_key == "":
            raise AdapterInternalError("provider 'voyage' requires an API key")
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
        provider_config: LlmProviderSettings,
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

    def _require_supported_provider(self, *, provider: str, operation: str) -> None:
        """Fail fast for providers that are intentionally out of scope."""
        if operation in {"chat", "chat_with_tools"}:
            if provider not in _CHAT_PROVIDERS:
                self._raise_provider_not_implemented(
                    provider=provider,
                    operation=operation,
                )
            return
        if operation == "embed_batch":
            if provider not in _EMBEDDING_PROVIDERS:
                self._raise_provider_not_implemented(
                    provider=provider,
                    operation=operation,
                )
            return
        self._raise_provider_not_implemented(
            provider=provider,
            operation=operation,
        )

    def _raise_provider_not_implemented(
        self,
        *,
        provider: str,
        operation: str,
    ) -> None:
        """Raise the standard unsupported-provider error."""
        raise AdapterInternalError(
            f"provider '{provider}' is not yet implemented in adapter_llm for {operation}"
        )

    def _raise_http_error(
        self,
        *,
        provider: str,
        response: httpx.Response,
        raw_call: AdapterProviderCallAudit,
    ) -> None:
        """Raise one mapped error from a non-success HTTP response."""
        message = _provider_error_message(provider=provider, response=response)
        if _is_retryable_status_code(response.status_code):
            raise AdapterDependencyError(message, raw_call=raw_call) from None
        raise AdapterInternalError(message, raw_call=raw_call) from None

    def _raise_mapped_exception(
        self, exc: Exception, *, raw_call: AdapterProviderCallAudit | None = None
    ) -> None:
        """Map third-party exceptions into adapter dependency/internal classes."""
        if _is_dependency_exception(exc):
            raise AdapterDependencyError(
                str(exc) or "llm dependency failure",
                raw_call=raw_call,
            ) from None
        raise AdapterInternalError(
            str(exc) or "llm adapter internal failure",
            raw_call=raw_call,
        ) from None


def _mapping_get(value: object, key: str, default: object) -> object:
    """Return ``value[key]`` when ``value`` is mapping-shaped, else ``default``."""
    if isinstance(value, Mapping):
        return value.get(key, default)
    return default


def _json_safe_value(value: object) -> object:
    """Convert arbitrary objects into JSON-serializable log payloads."""
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, Mapping):
        return {str(k): _json_safe_value(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_safe_value(item) for item in value]
    model_dump = getattr(value, "model_dump", None)
    if callable(model_dump):
        return _json_safe_value(model_dump())
    to_dict = getattr(value, "dict", None)
    if callable(to_dict):
        return _json_safe_value(to_dict())
    return str(value)


def _coerce_json_object(value: object) -> dict[str, object]:
    """Return mapping-shaped JSON payloads as ``dict[str, object]``."""
    if isinstance(value, Mapping):
        return {str(key): _json_safe_value(item) for key, item in value.items()}
    return {}


def _default_api_base_for_provider(provider: str) -> str:
    """Return the default API base for one supported provider."""
    if provider == "voyage":
        return _VOYAGE_API_BASE
    if provider == "ollama":
        return _OLLAMA_API_BASE
    if provider == "anthropic":
        return _ANTHROPIC_API_BASE
    raise AdapterInternalError(f"provider '{provider}' has no default api_base")


def _anthropic_headers(*, api_key: str) -> dict[str, str]:
    """Return native Anthropic request headers."""
    headers = {
        "anthropic-version": _ANTHROPIC_VERSION,
        "content-type": "application/json",
    }
    if api_key != "":
        headers["x-api-key"] = api_key
    return headers


def _voyage_headers(*, api_key: str) -> dict[str, str]:
    """Return Voyage embeddings request headers."""
    headers = {
        "content-type": "application/json",
    }
    if api_key != "":
        headers["authorization"] = f"Bearer {api_key}"
    return headers


def _sanitize_request_headers(headers: Mapping[str, str]) -> dict[str, object]:
    """Redact sensitive request headers before audit persistence."""
    redacted: dict[str, object] = {}
    for key, value in headers.items():
        lowered = key.lower()
        redacted[key] = "***" if lowered in {"authorization", "x-api-key"} else value
    return redacted


def _dependency_retry_delay_seconds(
    *,
    attempt_index: int,
    settings: LlmAdapterSettings,
) -> float:
    """Return the bounded delay for one dependency retry attempt."""
    schedule = timeout_retry_backoff_schedule_seconds(settings)
    if attempt_index < len(schedule):
        base_delay = schedule[attempt_index]
    elif schedule:
        base_delay = schedule[-1]
    else:
        base_delay = 0.5
    return _jittered_delay(
        base_delay=base_delay,
        jitter_ratio=settings.timeout_retry_jitter_ratio,
    )


def _log_retry(
    *,
    provider: str,
    model: str,
    operation: str,
    reason: str,
    attempt: int,
    delay: float,
) -> None:
    """Log one retry event."""
    _LOGGER.warning(
        "LLM provider request retrying",
        extra={
            "provider": provider,
            "model": model,
            "operation": operation,
            "reason": reason,
            "attempt": attempt,
            "delay_seconds": round(delay, 3),
        },
    )


def _is_retryable_status_code(status_code: int) -> bool:
    """Return True when one HTTP status should be retried as a dependency failure."""
    return status_code == 429 or status_code >= 500


def _provider_error_message(*, provider: str, response: httpx.Response) -> str:
    """Extract one stable provider-facing error message from a failed response."""
    payload = _response_payload_from_httpx(response)
    if provider == "voyage" and isinstance(payload, Mapping):
        error = payload.get("error")
        if isinstance(error, Mapping):
            message = error.get("message")
            if isinstance(message, str) and message.strip() != "":
                return message
        if isinstance(error, str) and error.strip() != "":
            return error
    if provider == "ollama" and isinstance(payload, Mapping):
        error = payload.get("error")
        if isinstance(error, str) and error.strip() != "":
            return error
    if provider == "anthropic" and isinstance(payload, Mapping):
        error = payload.get("error")
        if isinstance(error, Mapping):
            message = error.get("message")
            if isinstance(message, str) and message.strip() != "":
                return message
    text = response.text.strip()
    if text != "":
        return text
    return f"{provider} request failed with status {response.status_code}"


def _extract_ollama_response_model(*, payload: object, fallback: str) -> str:
    """Return the model name recorded in one Ollama embedding response."""
    response_model = _mapping_get(payload, "model", fallback)
    if isinstance(response_model, str) and response_model.strip() != "":
        return response_model
    return fallback


def _extract_voyage_response_model(*, payload: object, fallback: str) -> str:
    """Return the model name recorded in one Voyage embeddings response."""
    response_model = _mapping_get(payload, "model", fallback)
    if isinstance(response_model, str) and response_model.strip() != "":
        return response_model
    return fallback


def _extract_ollama_embedding_vectors(
    *,
    payload: object,
    expected_count: int,
) -> list[tuple[float, ...]]:
    """Parse and validate embedding vectors from one Ollama response payload."""
    embeddings = _mapping_get(payload, "embeddings", None)
    if isinstance(embeddings, Sequence) and not isinstance(embeddings, (str, bytes)):
        vectors = [
            _coerce_embedding_vector(item, index=index)
            for index, item in enumerate(embeddings)
        ]
    else:
        embedding = _mapping_get(payload, "embedding", None)
        if (
            expected_count == 1
            and isinstance(embedding, Sequence)
            and not isinstance(embedding, (str, bytes))
        ):
            vectors = [_coerce_embedding_vector(embedding, index=0)]
        else:
            raise AdapterInternalError("ollama embedding response payload is invalid")
    if len(vectors) != expected_count:
        raise AdapterInternalError("ollama embedding response size mismatch")
    return vectors


def _extract_voyage_embedding_vectors(
    *,
    payload: object,
    expected_count: int,
) -> list[tuple[float, ...]]:
    """Parse and validate embedding vectors from one Voyage response payload."""
    items = _mapping_get(payload, "data", None)
    if not isinstance(items, Sequence) or isinstance(items, (str, bytes)):
        raise AdapterInternalError("voyage embedding response payload is invalid")
    vectors: list[tuple[float, ...]] = []
    for index, item in enumerate(items):
        if not isinstance(item, Mapping):
            raise AdapterInternalError(
                f"voyage embedding record at index {index} is invalid"
            )
        vectors.append(_coerce_embedding_vector(item.get("embedding"), index=index))
    if len(vectors) != expected_count:
        raise AdapterInternalError("voyage embedding response size mismatch")
    return vectors


def _coerce_embedding_vector(value: object, *, index: int) -> tuple[float, ...]:
    """Coerce one embedding vector into a stable float tuple."""
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)):
        raise AdapterInternalError(
            f"embedding vector at index {index} is not a numeric array"
        )
    vector: list[float] = []
    for item in value:
        if not isinstance(item, (int, float)):
            raise AdapterInternalError(
                f"embedding vector at index {index} contains a non-numeric value"
            )
        vector.append(float(item))
    return tuple(vector)


def _fallback_request_audit(*, kwargs: Mapping[str, Any]) -> AdapterProviderCallAudit:
    """Build one sanitized fallback request audit from adapter call kwargs."""
    api_base = kwargs.get("api_base")
    headers = kwargs.get("headers")
    excluded_body_keys = {"api_base", "api_key", "logger_fn", "num_retries", "timeout"}
    request_body = {
        key: _json_safe_value(value)
        for key, value in kwargs.items()
        if key not in excluded_body_keys
    }
    return AdapterProviderCallAudit(
        request_api_base="" if not isinstance(api_base, str) else api_base,
        request_headers=_coerce_json_object(headers),
        request_body=request_body,
        response_body=None,
    )


def _finalize_exception_raw_call(
    exc: Exception,
    *,
    capture: "_RawCallCapture",
    fallback_request: AdapterProviderCallAudit,
) -> AdapterProviderCallAudit:
    """Return the richest raw-call audit available for one failed provider call."""
    request_api_base = capture.request_api_base or fallback_request.request_api_base
    request_headers = (
        fallback_request.request_headers
        if capture.request_headers is None
        else capture.request_headers
    )
    request_body = (
        fallback_request.request_body
        if capture.request_body is None
        else capture.request_body
    )
    response_body = capture.response_body
    if response_body is None:
        response_body = _response_body_from_exception(exc)
    return AdapterProviderCallAudit(
        request_api_base=request_api_base,
        request_headers=request_headers,
        request_body=request_body,
        response_body=response_body,
    )


def _finalize_success_raw_call(
    *,
    response: object,
    capture: "_RawCallCapture",
    fallback_request: AdapterProviderCallAudit,
) -> AdapterProviderCallAudit:
    """Return one normalized success audit using local request kwargs as baseline."""
    request_api_base = capture.request_api_base or fallback_request.request_api_base
    request_headers = _prefer_nonempty_mapping(
        capture.request_headers,
        fallback_request.request_headers,
    )
    request_body = _prefer_nonempty_value(
        capture.request_body,
        fallback_request.request_body,
    )
    response_body = _prefer_nonempty_value(
        capture.response_body,
        _json_safe_value(response),
    )
    return AdapterProviderCallAudit(
        request_api_base=request_api_base,
        request_headers=request_headers,
        request_body=request_body,
        response_body=response_body,
    )


def _prefer_nonempty_mapping(
    primary: dict[str, object] | None,
    fallback: dict[str, object],
) -> dict[str, object]:
    """Prefer one mapping when it carries any keys, else return the fallback."""
    if primary:
        return primary
    return fallback


def _prefer_nonempty_value(
    primary: object | None, fallback: object | None
) -> object | None:
    """Prefer one value when it is meaningfully populated, else return fallback."""
    if primary is None:
        return fallback
    if isinstance(primary, (dict, list, tuple, str)) and len(primary) == 0:
        return fallback
    return primary


def _response_body_from_exception(exc: Exception) -> object | None:
    """Extract one JSON-safe upstream error payload from a native LLM exception."""
    body = _json_safe_value(getattr(exc, "body", None))
    if body is not None:
        return body
    response = getattr(exc, "response", None)
    payload = _response_payload_from_httpx(response)
    if payload is not None:
        return payload
    debug_info = getattr(exc, "llm_debug_info", None)
    if isinstance(debug_info, str) and debug_info.strip() != "":
        return {"llm_debug_info": debug_info}
    return {"error": str(exc) or exc.__class__.__name__}


def _response_payload_from_httpx(response: object) -> object | None:
    """Extract one JSON-safe payload from a response-like object when possible."""
    if response is None:
        return None
    json_method = getattr(response, "json", None)
    if callable(json_method):
        try:
            return _json_safe_value(json_method())
        except Exception:
            pass
    text = getattr(response, "text", None)
    if isinstance(text, str) and text.strip() != "":
        try:
            return json.loads(text)
        except Exception:
            return {"text": text}
    status_code = getattr(response, "status_code", None)
    headers = _coerce_json_object(getattr(response, "headers", None))
    if status_code is None and not headers:
        return None
    reason = ""
    if isinstance(status_code, int):
        try:
            reason = HTTPStatus(status_code).phrase
        except ValueError:
            reason = ""
    return {
        "status_code": _json_safe_value(status_code),
        "reason": reason,
        "headers": headers,
    }


def _jittered_delay(*, base_delay: float, jitter_ratio: float) -> float:
    """Return one bounded delay with optional symmetric jitter."""
    if base_delay <= 0 or jitter_ratio <= 0:
        return max(0.0, base_delay)
    jitter = base_delay * jitter_ratio * (random() * 2 - 1)
    return max(0.0, base_delay + jitter)


def _is_timeout_exception(exc: Exception) -> bool:
    """Return True when one provider exception represents a timeout."""
    if isinstance(exc, TimeoutError):
        return True
    if isinstance(exc, httpx.TimeoutException):
        return True
    class_names = [cls.__name__.lower() for cls in type(exc).mro()]
    if any("timeout" in name for name in class_names):
        return True
    message = str(exc).lower()
    return "timed out" in message or "timeout" in message


@dataclass
class _RawCallCapture:
    """Mutable per-call raw provider payload capture populated by native LLM hooks."""

    request_api_base: str = ""
    request_headers: dict[str, object] | None = None
    request_body: object | None = None
    response_body: object | None = None

    def to_model(self) -> AdapterProviderCallAudit | None:
        """Return immutable audit payload when any raw call data was captured."""
        if (
            self.request_api_base == ""
            and self.request_headers is None
            and self.request_body is None
            and self.response_body is None
        ):
            return None
        return AdapterProviderCallAudit(
            request_api_base=self.request_api_base,
            request_headers={}
            if self.request_headers is None
            else self.request_headers,
            request_body=self.request_body,
            response_body=self.response_body,
        )


def _extract_anthropic_text_content(response: object) -> str:
    """Extract required assistant text from an Anthropic Messages response."""
    content = _extract_optional_anthropic_text_content(response)
    if content is None:
        raise AdapterInternalError("anthropic response did not include text content")
    return content


def _extract_optional_anthropic_text_content(response: object) -> str | None:
    """Extract optional assistant text from an Anthropic Messages response."""
    blocks = _response_field(response=response, field="content")
    if not isinstance(blocks, list):
        raise AdapterInternalError("anthropic response content is invalid")
    text_parts = [
        str(item.get("text", ""))
        for item in blocks
        if isinstance(item, Mapping) and item.get("type") == "text"
    ]
    text = "".join(text_parts)
    return None if text == "" else text


def _extract_anthropic_tool_calls(response: object) -> list[AdapterChatToolCall]:
    """Extract normalized tool calls from an Anthropic Messages response."""
    blocks = _response_field(response=response, field="content")
    if not isinstance(blocks, list):
        raise AdapterInternalError("anthropic response content is invalid")
    result: list[AdapterChatToolCall] = []
    for item in blocks:
        if not isinstance(item, Mapping) or item.get("type") != "tool_use":
            continue
        tool_name = item.get("name")
        tool_call_id = item.get("id")
        arguments = item.get("input", {})
        if not isinstance(tool_name, str) or not isinstance(tool_call_id, str):
            raise AdapterInternalError("anthropic tool call payload is invalid")
        result.append(
            AdapterChatToolCall(
                tool_name=tool_name,
                args_json=json.dumps(arguments, sort_keys=True),
                tool_call_id=tool_call_id,
            )
        )
    return result


def _extract_anthropic_finish_reason(response: object) -> str:
    """Extract the normalized finish reason from an Anthropic Messages response."""
    value = _response_value(response=response, field="stop_reason")
    if value == "tool_use":
        return "tool_call"
    if isinstance(value, str) and value != "":
        return value
    return "stop"


def _response_field(*, response: object, field: str) -> object:
    """Read one field from a response mapping or object."""
    if isinstance(response, Mapping):
        value = response.get(field)
    else:
        value = getattr(response, field, None)
    if value is None:
        raise AdapterInternalError(f"response missing {field}")
    return value


def _response_value(*, response: object, field: str) -> object | None:
    """Read one optional field from a response mapping or object."""
    if isinstance(response, Mapping):
        return response.get(field)
    return getattr(response, field, None)


def _first_item(payload: object, *, field: str) -> object:
    """Return first item from a non-empty list payload."""
    if not isinstance(payload, list) or len(payload) == 0:
        raise AdapterInternalError(f"response missing {field}")
    return payload[0]


def _is_dependency_exception(exc: Exception) -> bool:
    """Heuristic mapping of native LLM/provider failures to dependency class."""
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


def _to_llm_tool(value: AdapterChatToolDefinition) -> dict[str, Any]:
    """Convert one normalized tool definition into native LLM/OpenAI tool shape."""
    function: dict[str, Any] = {
        "name": value.name,
        "parameters": value.parameters_json_schema,
    }
    if value.description is not None:
        function["description"] = value.description
    if value.strict is not None:
        function["strict"] = value.strict
    return {"type": "function", "function": function}


def _to_llm_message(value: AdapterChatMessage) -> dict[str, Any]:
    """Convert one normalized chat message into native LLM/OpenAI message shape."""
    content = _render_content_parts(value.content_parts)
    if value.role == "assistant":
        payload: dict[str, Any] = {"role": "assistant"}
        payload["content"] = None if content == "" else content
        if value.tool_calls:
            payload["tool_calls"] = [
                {
                    "id": item.tool_call_id,
                    "type": "function",
                    "function": {
                        "name": item.tool_name,
                        "arguments": item.args_json,
                    },
                }
                for item in value.tool_calls
            ]
        return payload
    if value.role == "tool":
        return {
            "role": "tool",
            "tool_call_id": value.tool_call_id,
            "content": content,
        }
    return {"role": value.role, "content": content}


def _serialize_simple_prompt_for_provider(
    *,
    provider: str,
    system_prompt: str,
    prompt: str,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Serialize one direct chat prompt into provider-specific completion kwargs."""
    if provider == "anthropic":
        messages = [
            {
                "role": "user",
                "content": [{"type": "text", "text": prompt}],
            }
        ]
        extra_kwargs: dict[str, Any] = {}
        if system_prompt != "":
            extra_kwargs["system"] = [{"type": "text", "text": system_prompt}]
        return messages, extra_kwargs
    if provider == "openai":
        messages: list[dict[str, Any]] = []
        if system_prompt != "":
            messages.append(
                {
                    "role": "system",
                    "content": [{"type": "text", "text": system_prompt}],
                }
            )
        messages.append({"role": "user", "content": [{"type": "text", "text": prompt}]})
        return messages, {}
    if provider == "gemini":
        messages: list[dict[str, Any]] = []
        if system_prompt != "":
            messages.append(
                {
                    "role": "system",
                    "content": [{"type": "text", "text": system_prompt}],
                }
            )
        messages.append({"role": "user", "content": [{"type": "text", "text": prompt}]})
        return messages, {}

    messages: list[dict[str, Any]] = []
    if system_prompt != "":
        messages.append({"role": "system", "content": system_prompt})
    messages.append({"role": "user", "content": prompt})
    return messages, {}


def _lower_inference_request_for_provider(
    *,
    provider: str,
    inference_request: InferenceRequest,
) -> _LoweredToolInferenceRequest:
    """Lower one canonical inference request into provider-ready native LLM kwargs."""
    if provider == "anthropic":
        return _lower_anthropic_inference_request(inference_request)

    adapter_messages = _inference_request_to_adapter_messages(inference_request)
    adapter_tools = _inference_tools_to_adapter_tools(inference_request.tools)
    serialized_messages, extra_kwargs = _serialize_messages_for_provider(
        provider=provider,
        messages=adapter_messages,
    )
    serialized_tools = _serialize_tools_for_provider(
        provider=provider,
        tools=adapter_tools,
    )
    serialized_tool_choice, serialized_parallel_tool_calls = (
        _serialize_tool_selection_for_provider(
            provider=provider,
            tool_choice=_tool_choice_to_generic_selector(
                inference_request.controls.tool_choice
            ),
            parallel_tool_calls=_parallel_tool_calls_to_generic_flag(
                inference_request.controls.parallel_tool_calls
            ),
        )
    )
    return _LoweredToolInferenceRequest(
        messages=serialized_messages,
        tools=serialized_tools,
        tool_choice=serialized_tool_choice,
        parallel_tool_calls=serialized_parallel_tool_calls,
        extra_kwargs=extra_kwargs,
    )


def _lower_anthropic_inference_request(
    inference_request: InferenceRequest,
) -> _LoweredToolInferenceRequest:
    """Lower one canonical inference request into Anthropic Messages API kwargs."""
    system_blocks = _serialize_anthropic_system_blocks(
        inference_request.system.blocks,
        cache=inference_request.cache,
    )
    messages = _serialize_anthropic_inference_messages(inference_request)
    system_blocks, messages = _enforce_anthropic_cache_control_limit(
        system_blocks=system_blocks,
        messages=messages,
    )
    extra_kwargs: dict[str, Any] = {}
    if len(system_blocks) > 0:
        extra_kwargs["system"] = system_blocks
    if inference_request.cache.mode == "automatic":
        extra_kwargs["cache_control"] = _anthropic_cache_control(
            ttl=inference_request.cache.ttl
        )
    return _LoweredToolInferenceRequest(
        messages=messages,
        tools=[
            _to_anthropic_tool(item)
            for item in _inference_tools_to_adapter_tools(inference_request.tools)
        ],
        tool_choice=_to_anthropic_tool_choice(
            tool_choice=_tool_choice_to_generic_selector(
                inference_request.controls.tool_choice
            ),
            parallel_tool_calls=_parallel_tool_calls_to_generic_flag(
                inference_request.controls.parallel_tool_calls
            ),
        ),
        parallel_tool_calls=None,
        extra_kwargs=extra_kwargs,
    )


def _inference_request_to_adapter_messages(
    inference_request: InferenceRequest,
) -> tuple[AdapterChatMessage, ...]:
    """Convert one inference request into normalized helper transcript messages."""
    messages: list[AdapterChatMessage] = []
    system_parts = _system_blocks_to_content_parts(
        inference_request.system.blocks,
        cache=inference_request.cache,
    )
    if len(system_parts) > 0:
        messages.append(
            AdapterChatMessage(role="system", content_parts=tuple(system_parts))
        )
    messages.append(
        AdapterChatMessage(
            role="user",
            content_parts=_context_to_content_parts(
                memory_context=inference_request.memory_context,
                environment_context=inference_request.environment_context,
                current_turn=inference_request.current_turn,
                cache=inference_request.cache,
            ),
        )
    )
    messages.extend(_live_events_to_adapter_messages(inference_request.live_events))
    return tuple(messages)


def _live_events_to_adapter_messages(
    events: Sequence[InferenceLiveEvent],
) -> list[AdapterChatMessage]:
    """Convert the ordered live event stream into helper transcript messages."""
    messages: list[AdapterChatMessage] = []
    pending_assistant_parts: list[ChatContentPart] = []

    def flush_assistant() -> None:
        if len(pending_assistant_parts) == 0:
            return
        messages.append(
            AdapterChatMessage(
                role="assistant",
                content_parts=tuple(pending_assistant_parts),
            )
        )
        pending_assistant_parts.clear()

    for event in events:
        if isinstance(event, InferenceAssistantTextEvent):
            pending_assistant_parts.append(TextContentPart(text=event.text))
            if event.cache_after:
                pending_assistant_parts.append(CachePointContentPart())
            continue
        if isinstance(event, InferenceToolCallBatchEvent):
            if event.cache_after and len(pending_assistant_parts) > 0:
                pending_assistant_parts.append(CachePointContentPart())
            messages.append(
                AdapterChatMessage(
                    role="assistant",
                    content_parts=tuple(pending_assistant_parts),
                    tool_calls=tuple(
                        _inference_tool_call_to_adapter_tool_call(item)
                        for item in event.calls
                    ),
                )
            )
            pending_assistant_parts.clear()
            continue
        if isinstance(event, InferenceToolResultBatchEvent):
            flush_assistant()
            for item in event.results:
                tool_parts = _tool_result_payload_to_content_parts(item.result)
                if event.cache_after:
                    tool_parts = (*tool_parts, CachePointContentPart())
                messages.append(
                    AdapterChatMessage(
                        role="tool",
                        content_parts=tool_parts,
                        tool_name=item.tool_name,
                        tool_call_id=item.call_id,
                    )
                )
            continue
        raise TypeError(f"unsupported inference live event: {type(event)!r}")

    flush_assistant()
    return messages


def _inference_tools_to_adapter_tools(
    tools: Sequence[InferenceToolDefinition],
) -> tuple[AdapterChatToolDefinition, ...]:
    """Convert canonical tools into normalized helper tool definitions."""
    return tuple(
        AdapterChatToolDefinition(
            name=item.name,
            description=item.description,
            parameters_json_schema=item.input_schema,
            strict=item.strict_schema,
            sequential=item.execution_hints.sequential,
        )
        for item in tools
    )


def _inference_tool_call_to_adapter_tool_call(
    value: InferenceToolCall,
) -> AdapterChatToolCall:
    """Convert one canonical tool call into helper transcript form."""
    return AdapterChatToolCall(
        tool_name=value.tool_name,
        args_json=json.dumps(value.arguments, sort_keys=True),
        tool_call_id=value.call_id,
    )


def _tool_choice_to_generic_selector(
    value: InferenceToolChoice,
) -> str | dict[str, object] | None:
    """Convert canonical tool-choice policy into generic adapter selector form."""
    if value.mode == "auto":
        return "auto"
    if value.mode == "none":
        return "none"
    if value.mode == "require_any":
        return "required"
    if value.mode == "require_one":
        return {"type": "function", "function": {"name": value.tool_name}}
    raise ValueError(f"unsupported tool choice mode: {value.mode!r}")


def _parallel_tool_calls_to_generic_flag(
    value: InferenceParallelToolCalls,
) -> bool | None:
    """Convert canonical parallel-tool policy into generic adapter boolean form."""
    if value.mode == "allow":
        return True
    if value.mode == "forbid":
        return False
    raise ValueError(f"unsupported parallel tool mode: {value.mode!r}")


def _system_blocks_to_content_parts(
    blocks: Sequence[InferenceSystemBlock],
    *,
    cache: InferenceCache,
) -> tuple[ChatContentPart, ...]:
    """Convert canonical system blocks into helper content parts."""
    parts: list[ChatContentPart] = []
    for block in blocks:
        parts.append(TextContentPart(text=block.text))
        if cache.mode == "explicit" and block.cache_after:
            parts.append(CachePointContentPart())
    return tuple(parts)


def _context_to_content_parts(
    *,
    memory_context: InferenceMemoryContext,
    environment_context: InferenceEnvironmentContext,
    current_turn: InferenceCurrentTurn,
    cache: InferenceCache,
) -> tuple[ChatContentPart, ...]:
    """Convert canonical memory + current-turn state into helper content parts."""
    parts: list[ChatContentPart] = [
        FocusContentPart(
            text=""
            if memory_context.current_focus is None
            else memory_context.current_focus
        ),
        ConversationSummaryContentPart(text=memory_context.recent_conversation_summary),
    ]
    if cache.mode == "explicit":
        parts.append(CachePointContentPart())
    if len(environment_context.items) > 0:
        parts.append(EnvironmentContextContentPart(items=environment_context.items))
    parts.extend(
        DialogueTurnContentPart(
            role=item.role,
            text=item.text,
            is_summary=item.is_summary,
        )
        for item in memory_context.recent_turns
    )
    parts.extend(
        ReferenceSnippetContentPart(text=item.text)
        for item in memory_context.reference_snippets
    )
    parts.append(_operator_message_to_content_part(current_turn.operator_message))
    return tuple(parts)


def _operator_message_to_content_part(
    value: InferenceOperatorMessage,
) -> OperatorMessageContentPart:
    """Convert one canonical operator message into helper content-part form."""
    return OperatorMessageContentPart(
        channel=value.channel,
        sender_e164=value.sender_e164,
        message_text=value.message_text,
        approval_intent=value.approval_intent,
        reaction_emoji=value.reaction_emoji,
        quote_target_timestamp_ms=value.quote_target_timestamp_ms,
        reaction_target_timestamp_ms=value.reaction_target_timestamp_ms,
        reply_to_proposal_token=value.reply_to_proposal_token,
        reaction_to_proposal_token=value.reaction_to_proposal_token,
    )


def _tool_result_payload_to_content_parts(
    value: InferenceToolResultPayload,
) -> tuple[ChatContentPart, ...]:
    """Convert one canonical tool-result payload into helper content parts."""
    if value.text is not None:
        return (TextContentPart(text=value.text),)
    if value.data is not None:
        return (TextContentPart(text=_json_dumps_or_str(value.data)),)
    return ()


def _json_dumps_or_str(value: object) -> str:
    """Return canonical JSON text when possible, otherwise a stable string form."""
    try:
        return json.dumps(value, sort_keys=True)
    except TypeError:
        return str(value)


def _serialize_messages_for_provider(
    *,
    provider: str,
    messages: Sequence[AdapterChatMessage],
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Serialize one chat history into provider-specific message kwargs."""
    if provider == "openai":
        return _serialize_openai_messages(messages), {}
    if provider == "gemini":
        return _serialize_gemini_messages(messages), {}
    if provider == "anthropic":
        return _serialize_anthropic_compat_messages(messages)
    return ([_to_llm_message(item) for item in messages], {})


def _serialize_tools_for_provider(
    *,
    provider: str,
    tools: Sequence[AdapterChatToolDefinition],
) -> list[dict[str, Any]]:
    """Serialize one tool set into provider-specific tool definitions."""
    return [_to_llm_tool(item) for item in tools]


def _serialize_tool_selection_for_provider(
    *,
    provider: str,
    tool_choice: str | dict[str, object] | None,
    parallel_tool_calls: bool | None,
) -> tuple[str | dict[str, object] | None, bool | None]:
    """Serialize tool-choice and parallelism settings for one provider."""
    return tool_choice, parallel_tool_calls


def _serialize_anthropic_inference_messages(
    inference_request: InferenceRequest,
) -> list[dict[str, Any]]:
    """Lower one canonical inference request into Anthropic message blocks."""
    messages: list[dict[str, Any]] = [
        {
            "role": "user",
            "content": _serialize_anthropic_context_message(
                memory_context=inference_request.memory_context,
                environment_context=inference_request.environment_context,
                current_turn=inference_request.current_turn,
                cache=inference_request.cache,
            ),
        }
    ]
    pending_assistant_parts: list[ChatContentPart] = []

    def flush_assistant() -> None:
        if len(pending_assistant_parts) == 0:
            return
        messages.append(
            {
                "role": "assistant",
                "content": _serialize_anthropic_content_parts(
                    pending_assistant_parts,
                    ttl=inference_request.cache.ttl,
                ),
            }
        )
        pending_assistant_parts.clear()

    for event in inference_request.live_events:
        if isinstance(event, InferenceAssistantTextEvent):
            pending_assistant_parts.append(TextContentPart(text=event.text))
            if inference_request.cache.mode == "explicit" and event.cache_after:
                pending_assistant_parts.append(CachePointContentPart())
            continue
        if isinstance(event, InferenceToolCallBatchEvent):
            content = _serialize_anthropic_content_parts(
                pending_assistant_parts,
                ttl=inference_request.cache.ttl,
            )
            pending_assistant_parts.clear()
            content.extend(
                _to_anthropic_tool_use(_inference_tool_call_to_adapter_tool_call(item))
                for item in event.calls
            )
            if inference_request.cache.mode == "explicit" and event.cache_after:
                content.append(
                    _anthropic_cache_breaker_block(ttl=inference_request.cache.ttl)
                )
            messages.append({"role": "assistant", "content": content})
            continue
        if isinstance(event, InferenceToolResultBatchEvent):
            flush_assistant()
            content = [_to_anthropic_tool_result(item) for item in event.results]
            if inference_request.cache.mode == "explicit" and event.cache_after:
                content.append(
                    _anthropic_cache_breaker_block(ttl=inference_request.cache.ttl)
                )
            messages.append({"role": "user", "content": content})
            continue
        raise TypeError(f"unsupported inference live event: {type(event)!r}")

    flush_assistant()
    return messages


def _serialize_anthropic_context_message(
    *,
    memory_context: InferenceMemoryContext,
    environment_context: InferenceEnvironmentContext,
    current_turn: InferenceCurrentTurn,
    cache: InferenceCache,
) -> list[dict[str, Any]]:
    """Serialize the canonical memory + current-turn context for Anthropic."""
    return _serialize_anthropic_content_parts(
        _context_to_content_parts(
            memory_context=memory_context,
            environment_context=environment_context,
            current_turn=current_turn,
            cache=cache,
        ),
        ttl=cache.ttl,
    )


def _serialize_anthropic_system_blocks(
    blocks: Sequence[InferenceSystemBlock],
    *,
    cache: InferenceCache,
) -> list[dict[str, Any]]:
    """Serialize canonical system blocks into Anthropic top-level system blocks."""
    return _serialize_anthropic_content_parts(
        _system_blocks_to_content_parts(blocks, cache=cache),
        ttl=cache.ttl,
    )


def _enforce_anthropic_cache_control_limit(
    *,
    system_blocks: list[dict[str, Any]],
    messages: list[dict[str, Any]],
    max_blocks: int = _MAX_ANTHROPIC_CACHE_CONTROL_BLOCKS,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Keep Anthropic cache-control blocks within the provider hard limit."""
    references: list[tuple[str, int, int | None]] = []
    for index, block in enumerate(system_blocks):
        if isinstance(block, dict) and "cache_control" in block:
            references.append(("system", index, None))
    for message_index, message in enumerate(messages):
        content = message.get("content")
        if not isinstance(content, list):
            continue
        for block_index, block in enumerate(content):
            if isinstance(block, dict) and "cache_control" in block:
                references.append(("message", message_index, block_index))
    if len(references) <= max_blocks:
        return system_blocks, messages

    keep = {references[0]}
    keep.update(references[-(max_blocks - 1) :])

    def _strip_cache_control(block: dict[str, Any]) -> dict[str, Any]:
        if "cache_control" not in block:
            return block
        stripped = dict(block)
        stripped.pop("cache_control", None)
        return stripped

    updated_system_blocks = [
        block if ("system", index, None) in keep else _strip_cache_control(block)
        for index, block in enumerate(system_blocks)
    ]
    updated_messages: list[dict[str, Any]] = []
    for message_index, message in enumerate(messages):
        content = message.get("content")
        if not isinstance(content, list):
            updated_messages.append(message)
            continue
        updated_content = []
        for block_index, block in enumerate(content):
            if not isinstance(block, dict):
                updated_content.append(block)
                continue
            if ("message", message_index, block_index) in keep:
                updated_content.append(block)
            else:
                updated_content.append(_strip_cache_control(block))
        updated_messages.append({**message, "content": updated_content})
    return updated_system_blocks, updated_messages


def _serialize_anthropic_messages(
    messages: Sequence[AdapterChatMessage],
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Serialize chat history into Anthropic Messages API shape."""
    system_blocks: list[dict[str, Any]] = []
    serialized_messages: list[dict[str, Any]] = []
    pending_tool_result_blocks: list[dict[str, Any]] = []

    def flush_pending_tool_results() -> None:
        if len(pending_tool_result_blocks) == 0:
            return
        serialized_messages.append(
            {"role": "user", "content": list(pending_tool_result_blocks)}
        )
        pending_tool_result_blocks.clear()

    for message in messages:
        if message.role == "system":
            system_blocks.extend(
                _serialize_anthropic_content_parts(message.content_parts)
            )
            continue
        if message.role == "tool":
            pending_tool_result_blocks.append(
                {
                    "type": "tool_result",
                    "tool_use_id": message.tool_call_id,
                    "content": _render_content_parts(message.content_parts),
                }
            )
            continue
        flush_pending_tool_results()
        content = _serialize_anthropic_content_parts(message.content_parts)
        if message.role == "assistant" and message.tool_calls:
            content.extend(_to_anthropic_tool_use(item) for item in message.tool_calls)
        serialized_messages.append({"role": message.role, "content": content})
    flush_pending_tool_results()
    extra_kwargs: dict[str, Any] = {}
    if system_blocks:
        extra_kwargs["system"] = system_blocks
    return serialized_messages, extra_kwargs


def _serialize_openai_messages(
    messages: Sequence[AdapterChatMessage],
) -> list[dict[str, Any]]:
    """Serialize chat history into OpenAI Chat Completions native shape."""
    serialized_messages: list[dict[str, Any]] = []
    for message in messages:
        if message.role == "assistant":
            payload: dict[str, Any] = {"role": "assistant"}
            content = _serialize_openai_content_parts(message.content_parts)
            payload["content"] = None if len(content) == 0 else content
            if message.tool_calls:
                payload["tool_calls"] = [
                    {
                        "id": item.tool_call_id,
                        "type": "function",
                        "function": {
                            "name": item.tool_name,
                            "arguments": item.args_json,
                        },
                    }
                    for item in message.tool_calls
                ]
            serialized_messages.append(payload)
            continue
        if message.role == "tool":
            content = _serialize_openai_content_parts(message.content_parts)
            text = (
                ""
                if len(content) == 0
                else "".join(
                    str(item.get("text", ""))
                    for item in content
                    if isinstance(item, dict)
                )
            )
            serialized_messages.append(
                {
                    "role": "tool",
                    "tool_call_id": message.tool_call_id,
                    "content": text,
                }
            )
            continue
        content = _serialize_openai_content_parts(message.content_parts)
        serialized_messages.append(
            {
                "role": message.role,
                "content": [] if len(content) == 0 else content,
            }
        )
    return serialized_messages


def _serialize_gemini_messages(
    messages: Sequence[AdapterChatMessage],
) -> list[dict[str, Any]]:
    """Serialize chat history into Gemini-friendly structured chat messages."""
    serialized_messages: list[dict[str, Any]] = []
    for message in messages:
        if message.role == "assistant":
            payload: dict[str, Any] = {"role": "assistant"}
            content = _serialize_gemini_content_parts(message.content_parts)
            payload["content"] = "" if len(content) == 0 else content
            if message.tool_calls:
                payload["tool_calls"] = [
                    {
                        "id": item.tool_call_id,
                        "type": "function",
                        "function": {
                            "name": item.tool_name,
                            "arguments": item.args_json,
                        },
                    }
                    for item in message.tool_calls
                ]
            serialized_messages.append(payload)
            continue
        if message.role == "tool":
            content = _serialize_gemini_content_parts(message.content_parts)
            text = (
                ""
                if len(content) == 0
                else "".join(
                    str(item.get("text", ""))
                    for item in content
                    if isinstance(item, dict)
                )
            )
            serialized_messages.append(
                {
                    "role": "tool",
                    "tool_call_id": message.tool_call_id,
                    "content": text,
                }
            )
            continue
        content = _serialize_gemini_content_parts(message.content_parts)
        serialized_messages.append(
            {
                "role": message.role,
                "content": "" if len(content) == 0 else content,
            }
        )
    return serialized_messages


def _serialize_anthropic_compat_messages(
    messages: Sequence[AdapterChatMessage],
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Serialize chat history for Anthropic: extract system blocks, pass rest as OpenAI format.

    native LLM translates OpenAI-format messages to Anthropic wire format internally.
    This function only handles what native LLM does NOT do reliably: extracting system
    messages into the top-level ``system`` param so they never appear inline mid-turn.
    Tool messages stay as ``role=tool`` (OpenAI format); native LLM groups them correctly.
    """
    system_blocks: list[dict[str, Any]] = []
    serialized_messages: list[dict[str, Any]] = []
    for message in messages:
        if message.role == "system":
            system_blocks.extend(
                _serialize_anthropic_content_parts(message.content_parts)
            )
            continue
        serialized_messages.append(_to_llm_message(message))
    extra_kwargs: dict[str, Any] = {}
    if system_blocks:
        extra_kwargs["system"] = system_blocks
    return serialized_messages, extra_kwargs


def _serialize_openai_content_parts(
    parts: Sequence[ChatContentPart],
) -> list[dict[str, Any]]:
    """Serialize structured parts into OpenAI native text content blocks."""
    blocks: list[dict[str, Any]] = []
    run: list[ChatContentPart] = []

    def flush() -> None:
        if len(run) == 0:
            return
        text = _render_content_parts(tuple(run))
        run.clear()
        if text != "":
            blocks.append({"type": "text", "text": text})

    for part in parts:
        if isinstance(part, CachePointContentPart):
            flush()
            continue
        run.append(part)
    flush()
    return blocks


def _serialize_gemini_content_parts(
    parts: Sequence[ChatContentPart],
) -> list[dict[str, Any]]:
    """Serialize structured parts into Gemini-friendly text content blocks."""
    blocks: list[dict[str, Any]] = []
    run: list[ChatContentPart] = []

    def flush() -> None:
        if len(run) == 0:
            return
        text = _render_content_parts(tuple(run))
        run.clear()
        if text != "":
            blocks.append({"type": "text", "text": text})

    for part in parts:
        if isinstance(part, CachePointContentPart):
            flush()
            continue
        run.append(part)
    flush()
    return blocks


def _serialize_anthropic_content_parts(
    parts: Sequence[ChatContentPart],
    *,
    ttl: str | None = None,
) -> list[dict[str, Any]]:
    """Serialize structured parts into Anthropic text blocks with cache markers."""
    blocks: list[dict[str, Any]] = []
    run: list[ChatContentPart] = []

    def flush(*, cache_breakpoint: bool) -> None:
        if run:
            text = _render_content_parts(tuple(run))
            run.clear()
            if text != "":
                block: dict[str, Any] = {"type": "text", "text": text}
                if cache_breakpoint:
                    block["cache_control"] = _anthropic_cache_control(ttl=ttl)
                blocks.append(block)
                return
        if cache_breakpoint and blocks:
            blocks[-1]["cache_control"] = _anthropic_cache_control(ttl=ttl)

    for part in parts:
        if isinstance(part, CachePointContentPart):
            flush(cache_breakpoint=True)
            continue
        run.append(part)
    flush(cache_breakpoint=False)
    return blocks


def _to_anthropic_tool(value: AdapterChatToolDefinition) -> dict[str, Any]:
    """Convert one normalized tool definition into Anthropic Messages API shape."""
    payload: dict[str, Any] = {
        "name": value.name,
        "input_schema": value.parameters_json_schema,
    }
    if value.description is not None:
        payload["description"] = value.description
    return payload


def _to_anthropic_tool_result(value: InferenceToolResult) -> dict[str, Any]:
    """Convert one canonical tool result into Anthropic `tool_result` content."""
    payload: dict[str, Any] = {
        "type": "tool_result",
        "tool_use_id": value.call_id,
        "content": _anthropic_tool_result_content(value),
    }
    if value.status == "error" or value.is_error:
        payload["is_error"] = True
    return payload


def _anthropic_tool_result_content(value: InferenceToolResult) -> str:
    """Render one canonical tool result into Anthropic tool-result text."""
    if value.result.text is not None:
        return value.result.text
    if value.result.data is not None:
        return _json_dumps_or_str(value.result.data)
    return ""


def _anthropic_cache_control(*, ttl: str | None) -> dict[str, Any]:
    """Return one Anthropic cache-control payload."""
    payload: dict[str, Any] = {"type": "ephemeral"}
    if ttl is not None and ttl != "":
        payload["ttl"] = ttl
    return payload


def _anthropic_cache_breaker_block(*, ttl: str | None) -> dict[str, Any]:
    """Return one minimal cacheable text block to anchor a cache boundary."""
    return {
        "type": "text",
        "text": " ",
        "cache_control": _anthropic_cache_control(ttl=ttl),
    }


def _to_anthropic_tool_use(value: AdapterChatToolCall) -> dict[str, Any]:
    """Convert one normalized tool call into Anthropic `tool_use` content."""
    return {
        "type": "tool_use",
        "id": value.tool_call_id,
        "name": value.tool_name,
        "input": _decode_tool_input_json(value.args_json),
    }


def _decode_tool_input_json(value: str) -> object:
    """Decode one tool args JSON string into structured Anthropic tool input."""
    try:
        payload = json.loads(value)
    except ValueError:
        return {"raw_args_json": value}
    return payload


def _to_anthropic_tool_choice(
    *,
    tool_choice: str | dict[str, object] | None,
    parallel_tool_calls: bool | None,
) -> dict[str, object] | None:
    """Convert generic tool-choice settings into Anthropic Messages API shape."""
    if tool_choice is None and parallel_tool_calls is None:
        return None
    if tool_choice is None:
        result: dict[str, object] = {"type": "auto"}
    elif isinstance(tool_choice, str):
        result = {"type": _map_anthropic_tool_choice_type(tool_choice)}
    else:
        result = _normalize_anthropic_tool_choice_dict(tool_choice)
    if parallel_tool_calls is False and result.get("type") in {"auto", "any", "tool"}:
        result["disable_parallel_tool_use"] = True
    return result


def _map_anthropic_tool_choice_type(value: str) -> str:
    """Map one generic string tool-choice selector into Anthropic form."""
    lowered = value.strip().lower()
    if lowered == "required":
        return "any"
    if lowered in {"auto", "any", "tool", "none"}:
        return lowered
    raise ValueError(f"unsupported anthropic tool_choice string: {value!r}")


def _normalize_anthropic_tool_choice_dict(
    value: dict[str, object],
) -> dict[str, object]:
    """Normalize one generic dict tool_choice into Anthropic shape."""
    raw_type = value.get("type")
    if raw_type == "function":
        function = value.get("function")
        if isinstance(function, dict) and function.get("name"):
            return {"type": "tool", "name": str(function["name"])}
        raise ValueError("anthropic function tool_choice requires function.name")
    if raw_type in {"auto", "any", "tool", "none"}:
        result = dict(value)
        if raw_type == "tool" and "name" not in result:
            function = value.get("function")
            if isinstance(function, dict) and function.get("name"):
                result["name"] = str(function["name"])
        return result
    raise ValueError(f"unsupported anthropic tool_choice payload: {value!r}")


def _render_content_parts(parts: Sequence[ChatContentPart]) -> str:
    """Render structured content parts into one stable fallback text payload."""
    rendered: list[str] = []
    text_parts: list[str] = []
    dialogue_turns: list[DialogueTurnContentPart] = []
    reference_snippets: list[ReferenceSnippetContentPart] = []

    def flush_text() -> None:
        if len(text_parts) == 0:
            return
        rendered.append("\n".join(text_parts))
        text_parts.clear()

    def flush_dialogue() -> None:
        if len(dialogue_turns) == 0:
            return
        body = "\n".join(f"- {item.role}: {item.text}" for item in dialogue_turns)
        rendered.append(_render_prompt_template(_DIALOGUE_TEMPLATE, turns=body))
        dialogue_turns.clear()

    def flush_reference_snippets() -> None:
        if len(reference_snippets) == 0:
            return
        body = "\n".join(f"- {item.text}" for item in reference_snippets)
        rendered.append(
            _render_prompt_template(_REFERENCE_CONTEXT_TEMPLATE, snippets=body)
        )
        reference_snippets.clear()

    def render_environment_context(part: EnvironmentContextContentPart) -> str:
        capability_blocks = "\n".join(
            "\n".join(
                (
                    f"<{item.tag_name}>",
                    json.dumps(item.output, sort_keys=True, separators=(",", ":")),
                    f"</{item.tag_name}>",
                )
            )
            for item in part.items
        )
        if capability_blocks == "":
            return ""
        return _render_prompt_template(
            _ENVIRONMENT_CONTEXT_TEMPLATE,
            capability_blocks=capability_blocks,
        )

    for part in parts:
        if isinstance(part, CachePointContentPart):
            continue
        if isinstance(part, DialogueTurnContentPart):
            flush_text()
            dialogue_turns.append(part)
            continue
        if isinstance(part, ReferenceSnippetContentPart):
            flush_text()
            reference_snippets.append(part)
            continue
        flush_text()
        flush_dialogue()
        flush_reference_snippets()
        if isinstance(part, TextContentPart):
            text_parts.append(part.text)
        elif isinstance(part, FocusContentPart):
            rendered.append(_render_prompt_template(_FOCUS_TEMPLATE, text=part.text))
        elif isinstance(part, ConversationSummaryContentPart):
            rendered.append(
                _render_prompt_template(_CONVERSATION_SUMMARY_TEMPLATE, text=part.text)
            )
        elif isinstance(part, MetadataFieldContentPart):
            rendered.append(
                _render_prompt_template(
                    _METADATA_FIELD_TEMPLATE,
                    name=part.name,
                    value=part.value,
                )
            )
        elif isinstance(part, EnvironmentContextContentPart):
            rendered.append(render_environment_context(part))
        elif isinstance(part, OperatorMessageContentPart):
            rendered.append(_render_operator_message(part))
        else:
            raise TypeError(f"unsupported chat content part: {type(part)!r}")

    flush_text()
    flush_dialogue()
    flush_reference_snippets()
    return "".join(rendered)


def _render_operator_message(part: OperatorMessageContentPart) -> str:
    """Render one operator instruction part into the stable fallback block."""
    fields = [
        ("channel", part.channel),
        ("sender", part.sender_e164),
        ("approval_intent", _optional_text(part.approval_intent)),
        ("reaction_emoji", _optional_text(part.reaction_emoji)),
        (
            "quote_target_timestamp_ms",
            _optional_int(part.quote_target_timestamp_ms),
        ),
        (
            "reaction_target_timestamp_ms",
            _optional_int(part.reaction_target_timestamp_ms),
        ),
        (
            "reply_to_proposal_token",
            _optional_text(part.reply_to_proposal_token),
        ),
        (
            "reaction_to_proposal_token",
            _optional_text(part.reaction_to_proposal_token),
        ),
    ]
    metadata = "\n".join(
        _render_prompt_template(_METADATA_FIELD_TEMPLATE, name=name, value=value)
        for name, value in fields
    )
    return _render_prompt_template(
        _OPERATOR_MESSAGE_TEMPLATE,
        metadata=metadata,
        message_text=part.message_text,
    )


def _optional_text(value: str | None) -> str:
    """Render one optional text field for fallback serialization."""
    return "" if value is None else value


def _optional_int(value: int | None) -> str:
    """Render one optional integer field for fallback serialization."""
    return "" if value is None else str(value)
