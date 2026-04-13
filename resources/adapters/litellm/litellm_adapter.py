"""In-process LiteLLM adapter implementation."""

from __future__ import annotations

import json
import os
import re
from random import random
from dataclasses import dataclass
from datetime import UTC, datetime
from http import HTTPStatus
from pathlib import Path
from time import perf_counter, sleep
from typing import Any, Mapping, Sequence

import httpx
import litellm

from packages.brain_shared.language_model import (
    CachePointContentPart,
    ChatContentPart,
    ConversationSummaryContentPart,
    DialogueTurnContentPart,
    FocusContentPart,
    InferenceAssistantTextEvent,
    InferenceCache,
    InferenceCurrentTurn,
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
    timeout_retry_backoff_schedule_seconds,
)

_LOGGER = get_logger(__name__)
_RESOURCE_DIR = Path(__file__).resolve().parent
_PROMPTS_DIR = _RESOURCE_DIR / "prompts"
_FOCUS_TEMPLATE_PATH = _PROMPTS_DIR / "focus-template.txt"
_CONVERSATION_SUMMARY_TEMPLATE_PATH = _PROMPTS_DIR / "conversation-summary-template.txt"
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
    """Provider-ready LiteLLM completion kwargs derived from one inference request."""

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
        system_prompt: str = "",
        prompt: str,
    ) -> AdapterChatResult:
        """Generate one chat completion using the LiteLLM Python API."""
        messages, extra_kwargs = _serialize_simple_prompt_for_provider(
            provider=provider,
            system_prompt=system_prompt,
            prompt=prompt,
        )
        response, raw_call = self._call_completion(
            provider=provider,
            model=model,
            messages=messages,
            extra_kwargs=extra_kwargs,
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
        inference_request: InferenceRequest,
    ) -> AdapterToolChatResult:
        """Generate one tool-capable completion using the LiteLLM Python API."""
        lowered = _lower_inference_request_for_provider(
            provider=provider,
            inference_request=inference_request,
        )
        response, raw_call = self._call_completion(
            provider=provider,
            model=model,
            messages=lowered.messages,
            tools=lowered.tools,
            tool_choice=lowered.tool_choice,
            parallel_tool_calls=lowered.parallel_tool_calls,
            extra_kwargs=lowered.extra_kwargs,
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
        extra_kwargs: dict[str, Any] | None = None,
    ) -> tuple[object, AdapterProviderCallAudit | None]:
        """Invoke `litellm.completion` with resolved provider settings."""
        litellm = _load_litellm_module()
        _enable_raw_request_capture(litellm)
        resolved = self._resolve_provider_settings(provider=provider)
        raw_call = _RawCallCapture()
        kwargs = self._request_kwargs(provider=provider, model=model, resolved=resolved)
        kwargs["messages"] = messages
        if extra_kwargs is not None:
            kwargs.update(extra_kwargs)
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
                "messages": _json_safe_value(messages),
            },
        )
        response = self._call_completion_with_timeout_retry(
            litellm=litellm,
            provider=provider,
            model=model,
            kwargs=kwargs,
            raw_call=raw_call,
        )
        audit = _finalize_success_raw_call(
            response=response,
            capture=raw_call,
            fallback_request=_fallback_request_audit(kwargs=kwargs),
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
        return response, audit

    def _call_completion_with_timeout_retry(
        self,
        *,
        litellm: Any,
        provider: str,
        model: str,
        kwargs: dict[str, Any],
        raw_call: "_RawCallCapture",
    ) -> object:
        """Invoke completion with bounded retry/backoff on timeout-like failures."""
        backoff_schedule = timeout_retry_backoff_schedule_seconds(self._settings)
        max_attempts = 1 + len(backoff_schedule)
        for attempt_index in range(max_attempts):
            try:
                return litellm.completion(**kwargs)
            except Exception as exc:
                if attempt_index >= len(backoff_schedule) or not _is_timeout_exception(
                    exc
                ):
                    self._raise_mapped_exception(
                        exc,
                        raw_call=_finalize_exception_raw_call(
                            exc,
                            capture=raw_call,
                            fallback_request=_fallback_request_audit(kwargs=kwargs),
                        ),
                    )
                delay = _jittered_delay(
                    base_delay=backoff_schedule[attempt_index],
                    jitter_ratio=self._settings.timeout_retry_jitter_ratio,
                )
                _LOGGER.warning(
                    "LiteLLM provider timeout; retrying completion",
                    extra={
                        "provider": provider,
                        "model": model,
                        "attempt": attempt_index + 1,
                        "max_attempts": max_attempts,
                        "delay_seconds": round(delay, 3),
                    },
                )
                if delay > 0:
                    sleep(delay)
        raise AssertionError("unreachable completion retry state")

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
        audit = _finalize_success_raw_call(
            response=response,
            capture=raw_call,
            fallback_request=_fallback_request_audit(kwargs=kwargs),
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
        return response, audit

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


def _jittered_delay(*, base_delay: float, jitter_ratio: float) -> float:
    """Return one bounded delay with optional symmetric jitter."""
    if base_delay <= 0 or jitter_ratio <= 0:
        return max(0.0, base_delay)
    jitter = base_delay * jitter_ratio * (random() * 2 - 1)
    return max(0.0, base_delay + jitter)


def _is_timeout_exception(exc: Exception) -> bool:
    """Return True when one provider exception represents a timeout."""
    litellm_timeout = getattr(litellm, "Timeout", None)
    timeout_types = (
        (TimeoutError,)
        if litellm_timeout is None
        else (
            TimeoutError,
            litellm_timeout,
        )
    )
    if isinstance(exc, timeout_types):
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
    """Lower one canonical inference request into provider-ready LiteLLM kwargs."""
    if provider == "anthropic":
        adapter_messages = _inference_request_to_adapter_messages(inference_request)
        adapter_tools = _inference_tools_to_adapter_tools(inference_request.tools)
        serialized_messages, extra_kwargs = _serialize_messages_for_provider(
            provider=provider,
            messages=adapter_messages,
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
            tools=[_to_anthropic_tool(item) for item in adapter_tools],
            tool_choice=_to_anthropic_tool_choice(
                tool_choice=serialized_tool_choice,
                parallel_tool_calls=serialized_parallel_tool_calls,
            ),
            parallel_tool_calls=None,
            extra_kwargs=extra_kwargs,
        )

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
    return ([_to_litellm_message(item) for item in messages], {})


def _serialize_tools_for_provider(
    *,
    provider: str,
    tools: Sequence[AdapterChatToolDefinition],
) -> list[dict[str, Any]]:
    """Serialize one tool set into provider-specific tool definitions."""
    return [_to_litellm_tool(item) for item in tools]


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
    current_turn: InferenceCurrentTurn,
    cache: InferenceCache,
) -> list[dict[str, Any]]:
    """Serialize the canonical memory + current-turn context for Anthropic."""
    return _serialize_anthropic_content_parts(
        _context_to_content_parts(
            memory_context=memory_context,
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

    LiteLLM translates OpenAI-format messages to Anthropic wire format internally.
    This function only handles what LiteLLM does NOT do reliably: extracting system
    messages into the top-level ``system`` param so they never appear inline mid-turn.
    Tool messages stay as ``role=tool`` (OpenAI format); LiteLLM groups them correctly.
    """
    system_blocks: list[dict[str, Any]] = []
    serialized_messages: list[dict[str, Any]] = []
    for message in messages:
        if message.role == "system":
            system_blocks.extend(
                _serialize_anthropic_content_parts(message.content_parts)
            )
            continue
        serialized_messages.append(_to_litellm_message(message))
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
