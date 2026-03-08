"""In-process LiteLLM adapter implementation."""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from datetime import UTC, datetime
from http import HTTPStatus
from time import perf_counter
from typing import Any, Mapping, Sequence

import litellm

from packages.brain_shared.logging import get_logger, public_api_instrumented
from resources.adapters.litellm.adapter import (
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
        response, raw_call = self._call_completion(
            provider=provider,
            model=model,
            messages=[{"role": "user", "content": prompt}],
        )
        content = _extract_chat_content(response)
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
        messages: Sequence[AdapterChatMessage],
        tools: Sequence[AdapterChatToolDefinition],
        tool_choice: str | dict[str, object] | None = None,
        parallel_tool_calls: bool | None = None,
    ) -> AdapterToolChatResult:
        """Generate one tool-capable completion using the LiteLLM Python API."""
        response, raw_call = self._call_completion(
            provider=provider,
            model=model,
            messages=[_to_litellm_message(item) for item in messages],
            tools=[_to_litellm_tool(item) for item in tools],
            tool_choice=tool_choice,
            parallel_tool_calls=parallel_tool_calls,
        )
        return AdapterToolChatResult(
            text=_extract_optional_chat_content(response),
            tool_calls=tuple(_extract_tool_calls(response)),
            provider=provider,
            model=model,
            finish_reason=_extract_finish_reason(response),
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
        response, raw_call = self._call_embedding(
            provider=provider,
            model=model,
            inputs=list(texts),
        )
        vectors = _extract_embedding_vectors(response)
        return [
            AdapterEmbeddingResult(
                values=item,
                provider=provider,
                model=model,
                raw_call=raw_call,
            )
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
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
        tool_choice: str | dict[str, object] | None = None,
        parallel_tool_calls: bool | None = None,
    ) -> tuple[object, AdapterProviderCallAudit | None]:
        """Invoke `litellm.completion` with resolved provider settings."""
        litellm = _load_litellm_module()
        _enable_raw_request_capture(litellm)
        resolved = self._resolve_provider_settings(provider=provider)
        raw_call = _RawCallCapture()
        kwargs = self._request_kwargs(provider=provider, model=model, resolved=resolved)
        kwargs["messages"] = messages
        kwargs["logger_fn"] = _provider_raw_json_logger(
            logger=_LOGGER,
            provider=provider,
            model=model,
            operation="completion",
            capture=raw_call,
        )
        if tools is not None:
            kwargs["tools"] = tools
        if tool_choice is not None:
            kwargs["tool_choice"] = tool_choice
        if parallel_tool_calls is not None:
            kwargs["parallel_tool_calls"] = parallel_tool_calls
        started_at = perf_counter()
        _LOGGER.debug(
            "LiteLLM provider request starting",
            extra={
                "provider": provider,
                "model": model,
                "operation": "completion",
                "api_base": resolved.api_base,
            },
        )
        try:
            response = litellm.completion(**kwargs)
        except Exception as exc:
            self._raise_mapped_exception(
                exc,
                raw_call=_finalize_exception_raw_call(
                    exc,
                    capture=raw_call,
                    fallback_request=_fallback_request_audit(kwargs=kwargs),
                ),
            )
        _LOGGER.debug(
            "LiteLLM provider request completed",
            extra={
                "provider": provider,
                "model": model,
                "operation": "completion",
                "duration_ms": round((perf_counter() - started_at) * 1000, 3),
            },
        )
        return response, raw_call.to_model()

    def _call_embedding(
        self,
        *,
        provider: str,
        model: str,
        inputs: list[str],
    ) -> tuple[object, AdapterProviderCallAudit | None]:
        """Invoke `litellm.embedding` with resolved provider settings."""
        litellm = _load_litellm_module()
        _enable_raw_request_capture(litellm)
        resolved = self._resolve_provider_settings(provider=provider)
        raw_call = _RawCallCapture()
        kwargs = self._request_kwargs(provider=provider, model=model, resolved=resolved)
        kwargs["input"] = inputs
        kwargs["logger_fn"] = _provider_raw_json_logger(
            logger=_LOGGER,
            provider=provider,
            model=model,
            operation="embedding",
            capture=raw_call,
        )
        started_at = perf_counter()
        _LOGGER.debug(
            "LiteLLM provider request starting",
            extra={
                "provider": provider,
                "model": model,
                "operation": "embedding",
                "api_base": resolved.api_base,
                "input_count": len(inputs),
            },
        )
        try:
            response = litellm.embedding(**kwargs)
        except Exception as exc:
            self._raise_mapped_exception(
                exc,
                raw_call=_finalize_exception_raw_call(
                    exc,
                    capture=raw_call,
                    fallback_request=_fallback_request_audit(kwargs=kwargs),
                ),
            )
        _LOGGER.debug(
            "LiteLLM provider request completed",
            extra={
                "provider": provider,
                "model": model,
                "operation": "embedding",
                "input_count": len(inputs),
                "duration_ms": round((perf_counter() - started_at) * 1000, 3),
            },
        )
        return response, raw_call.to_model()

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

    def _raise_mapped_exception(
        self, exc: Exception, *, raw_call: AdapterProviderCallAudit | None = None
    ) -> None:
        """Map third-party exceptions into adapter dependency/internal classes."""
        if _is_dependency_exception(exc):
            raise AdapterDependencyError(
                str(exc) or "litellm dependency failure",
                raw_call=raw_call,
            ) from None
        raise AdapterInternalError(
            str(exc) or "litellm adapter internal failure",
            raw_call=raw_call,
        ) from None


def _load_litellm_module() -> Any:
    """Return the imported `litellm` module."""
    return litellm


def _enable_raw_request_capture(litellm_module: Any) -> None:
    """Enable LiteLLM's internal raw request capture path for this process."""
    setattr(litellm_module, "log_raw_request_response", True)


def _provider_raw_json_logger(
    *,
    logger: Any,
    provider: str,
    model: str,
    operation: str,
    capture: "_RawCallCapture",
):
    """Return one LiteLLM logger_fn that emits raw upstream request/response JSON."""

    def _log(model_call_details: dict[str, Any]) -> None:
        if not isinstance(model_call_details, dict):
            return
        event_type = str(model_call_details.get("log_event_type", "")).strip()
        if event_type == "pre_api_call":
            raw_request = model_call_details.get("raw_request_typed_dict", {})
            capture.request_api_base = str(
                _json_safe_value(_mapping_get(raw_request, "raw_request_api_base", ""))
            )
            capture.request_headers = _coerce_json_object(
                _json_safe_value(_mapping_get(raw_request, "raw_request_headers", {}))
            )
            capture.request_body = _json_safe_value(
                _mapping_get(raw_request, "raw_request_body", {})
            )
            payload = {
                "provider": provider,
                "model": model,
                "operation": operation,
                "event": "provider_raw_request",
                "api_base": _json_safe_value(
                    _mapping_get(raw_request, "raw_request_api_base", "")
                ),
                "headers": _json_safe_value(
                    _mapping_get(raw_request, "raw_request_headers", {})
                ),
                "body": _json_safe_value(
                    _mapping_get(raw_request, "raw_request_body", {})
                ),
                "logged_at": datetime.now(UTC).isoformat(),
            }
            logger.verbose(
                "LiteLLM provider raw json %s", json.dumps(payload, default=str)
            )
            return
        if event_type == "post_api_call":
            capture.response_body = _json_safe_value(
                model_call_details.get("original_response")
            )
            payload = {
                "provider": provider,
                "model": model,
                "operation": operation,
                "event": "provider_raw_response",
                "response": capture.response_body,
                "logged_at": datetime.now(UTC).isoformat(),
            }
            logger.verbose(
                "LiteLLM provider raw json %s", json.dumps(payload, default=str)
            )

    return _log


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


def _response_body_from_exception(exc: Exception) -> object | None:
    """Extract one JSON-safe upstream error payload from a LiteLLM exception."""
    body = _json_safe_value(getattr(exc, "body", None))
    if body is not None:
        return body
    response = getattr(exc, "response", None)
    payload = _response_payload_from_httpx(response)
    if payload is not None:
        return payload
    debug_info = getattr(exc, "litellm_debug_info", None)
    if isinstance(debug_info, str) and debug_info.strip() != "":
        return {"litellm_debug_info": debug_info}
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


@dataclass
class _RawCallCapture:
    """Mutable per-call raw provider payload capture populated by LiteLLM hooks."""

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


def _qualified_model(*, provider: str, model: str) -> str:
    """Compose LiteLLM provider/model selector value."""
    return f"{provider}/{model}"


def _extract_chat_content(response: object) -> str:
    """Extract first chat message content from LiteLLM completion response."""
    content = _extract_optional_chat_content(response)
    if not isinstance(content, str):
        raise AdapterInternalError("chat response content is invalid")
    return content


def _extract_optional_chat_content(response: object) -> str | None:
    """Extract optional assistant text from a LiteLLM completion response."""
    choice = _first_item(
        _response_field(response=response, field="choices"), field="choices"
    )
    message = _response_field(response=choice, field="message")
    content = _response_value(response=message, field="content")
    if content is None:
        return None
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        text_parts: list[str] = []
        for item in content:
            if isinstance(item, Mapping) and item.get("type") == "text":
                text = item.get("text")
                if isinstance(text, str):
                    text_parts.append(text)
        return "".join(text_parts)
    raise AdapterInternalError("chat response content is invalid")


def _extract_tool_calls(response: object) -> list[AdapterChatToolCall]:
    """Extract normalized tool calls from a LiteLLM completion response."""
    choice = _first_item(
        _response_field(response=response, field="choices"), field="choices"
    )
    message = _response_field(response=choice, field="message")
    payload = _response_value(response=message, field="tool_calls")
    if payload is None:
        return []
    if not isinstance(payload, list):
        raise AdapterInternalError("tool call payload is invalid")
    result: list[AdapterChatToolCall] = []
    for item in payload:
        function = _response_field(response=item, field="function")
        tool_name = _response_field(response=function, field="name")
        args_json = _response_field(response=function, field="arguments")
        tool_call_id = _response_field(response=item, field="id")
        if not all(
            isinstance(value, str) for value in (tool_name, args_json, tool_call_id)
        ):
            raise AdapterInternalError("tool call payload is invalid")
        result.append(
            AdapterChatToolCall(
                tool_name=tool_name,
                args_json=args_json,
                tool_call_id=tool_call_id,
            )
        )
    return result


def _extract_finish_reason(response: object) -> str:
    """Extract the normalized finish reason from a LiteLLM completion response."""
    choice = _first_item(
        _response_field(response=response, field="choices"), field="choices"
    )
    value = _response_value(response=choice, field="finish_reason")
    if value == "tool_calls":
        return "tool_call"
    if isinstance(value, str) and value != "":
        return value
    return "stop"


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


def _to_litellm_tool(value: AdapterChatToolDefinition) -> dict[str, Any]:
    """Convert one normalized tool definition into LiteLLM/OpenAI tool shape."""
    function: dict[str, Any] = {
        "name": value.name,
        "parameters": value.parameters_json_schema,
    }
    if value.description is not None:
        function["description"] = value.description
    if value.strict is not None:
        function["strict"] = value.strict
    return {"type": "function", "function": function}


def _to_litellm_message(value: AdapterChatMessage) -> dict[str, Any]:
    """Convert one normalized chat message into LiteLLM/OpenAI message shape."""
    if value.role == "assistant":
        payload: dict[str, Any] = {"role": "assistant"}
        payload["content"] = None if value.content == "" else value.content
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
            "content": value.content,
        }
    return {"role": value.role, "content": value.content}
