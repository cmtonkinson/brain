"""
LiteLLM observability callback for token and cost tracking.

Integrates with the Brain observability stack to capture:
- Token counts (input/output/total)
- Cost estimates using LiteLLM's pricing database
- Model usage and latency metrics
- Error tracking

See docs/observability.md for full documentation.
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import TYPE_CHECKING, Any

import litellm
from litellm.integrations.custom_logger import CustomLogger
from opentelemetry import trace

if TYPE_CHECKING:
    from src.observability import BrainMetrics

logger = logging.getLogger(__name__)


class BrainLiteLLMCallback(CustomLogger):
    """Custom LiteLLM callback for observability integration.

    Captures:
    - Token counts (input/output/total)
    - Cost estimates using LiteLLM's built-in pricing
    - Model usage patterns
    - Latency metrics
    - Error tracking
    """

    def __init__(self, brain_metrics: BrainMetrics) -> None:
        """Initialize the callback with Brain metrics instance.

        Args:
            brain_metrics: BrainMetrics instance from observability module
        """
        self.metrics = brain_metrics
        self.tracer = trace.get_tracer(__name__)

    def log_pre_api_call(
        self,
        model: str,
        messages: list[dict[str, Any]],
        kwargs: dict[str, Any],
    ) -> None:
        """Called before LLM API request.

        Adds model info to current span.
        """
        span = trace.get_current_span()
        if span and span.is_recording():
            span.set_attribute("llm.model", model)
            span.set_attribute("llm.messages_count", len(messages))

            # Estimate input tokens (rough)
            total_chars = sum(len(str(m.get("content", ""))) for m in messages)
            span.set_attribute("llm.estimated_input_chars", total_chars)

    def log_success_event(
        self,
        kwargs: dict[str, Any],
        response_obj: Any,
        start_time: datetime,
        end_time: datetime,
    ) -> None:
        """Called after successful LLM API response.

        Records token usage, cost, and latency metrics.
        """
        try:
            model = kwargs.get("model", "unknown")
            # Normalize model name for consistent labeling
            model_label = self._normalize_model_name(model)

            # Extract usage from response
            usage = getattr(response_obj, "usage", None)
            if usage:
                input_tokens = getattr(usage, "prompt_tokens", 0)
                output_tokens = getattr(usage, "completion_tokens", 0)
                total_tokens = getattr(usage, "total_tokens", 0)

                # Record token metrics
                self.metrics.llm_tokens_input.add(
                    input_tokens,
                    {"model": model_label},
                )
                self.metrics.llm_tokens_output.add(
                    output_tokens,
                    {"model": model_label},
                )

                # Calculate cost using LiteLLM's cost calculator
                cost = self._calculate_cost(model, input_tokens, output_tokens)

                if cost is not None and cost > 0:
                    self.metrics.llm_cost.add(
                        cost,
                        {"model": model_label},
                    )

                # Add to span
                span = trace.get_current_span()
                if span and span.is_recording():
                    span.set_attribute("llm.tokens.input", input_tokens)
                    span.set_attribute("llm.tokens.output", output_tokens)
                    span.set_attribute("llm.tokens.total", total_tokens)
                    if cost is not None:
                        span.set_attribute("llm.cost_usd", cost)

                logger.debug(
                    f"LLM call: model={model_label} "
                    f"tokens={total_tokens} cost=${cost:.6f if cost else 0}"
                )

            # Record latency
            latency_ms = (end_time - start_time).total_seconds() * 1000
            self.metrics.llm_latency.record(latency_ms, {"model": model_label})
            self.metrics.llm_requests.add(1, {"model": model_label, "status": "success"})

        except Exception as e:
            logger.error(f"Error in LiteLLM success callback: {e}")

    def log_failure_event(
        self,
        kwargs: dict[str, Any],
        response_obj: Any,
        start_time: datetime,
        end_time: datetime,
    ) -> None:
        """Called after failed LLM API request.

        Records error metrics and span attributes.
        """
        model = kwargs.get("model", "unknown")
        model_label = self._normalize_model_name(model)
        error_type = type(response_obj).__name__ if response_obj else "unknown"

        self.metrics.llm_requests.add(
            1,
            {"model": model_label, "status": "error", "error_type": error_type},
        )

        span = trace.get_current_span()
        if span and span.is_recording():
            span.set_attribute("llm.error", True)
            span.set_attribute("llm.error_type", error_type)

        logger.warning(f"LLM call failed: model={model_label} error={error_type}")

    def _normalize_model_name(self, model: str) -> str:
        """Normalize model name for consistent labeling.

        Strips provider prefixes and normalizes common model names.
        """
        # Remove common prefixes
        prefixes = ["anthropic/", "openai/", "azure/", "bedrock/"]
        for prefix in prefixes:
            if model.startswith(prefix):
                model = model[len(prefix) :]
                break

        # Truncate long model names with dates
        # e.g., "claude-sonnet-4-20250514" -> "claude-sonnet-4"
        parts = model.split("-")
        if len(parts) > 3 and parts[-1].isdigit() and len(parts[-1]) == 8:
            model = "-".join(parts[:-1])

        return model

    def _calculate_cost(
        self,
        model: str,
        input_tokens: int,
        output_tokens: int,
    ) -> float | None:
        """Calculate cost using LiteLLM's pricing database.

        Returns None if cost cannot be calculated.
        """
        try:
            cost = litellm.completion_cost(
                model=model,
                prompt_tokens=input_tokens,
                completion_tokens=output_tokens,
            )
            return float(cost) if cost else None
        except Exception as e:
            logger.debug(f"Could not calculate cost for {model}: {e}")
            return None


def setup_litellm_observability(brain_metrics: BrainMetrics) -> BrainLiteLLMCallback:
    """Configure LiteLLM with observability callbacks.

    Args:
        brain_metrics: BrainMetrics instance from observability module

    Returns:
        The configured callback instance
    """
    callback = BrainLiteLLMCallback(brain_metrics)

    # Set up LiteLLM callbacks
    # Note: litellm.callbacks is a list that can hold multiple callbacks
    if not hasattr(litellm, "callbacks") or litellm.callbacks is None:
        litellm.callbacks = []

    # Add our callback if not already present
    if callback not in litellm.callbacks:
        litellm.callbacks.append(callback)

    # Also set success/failure callbacks for redundancy
    litellm.success_callback = [callback.log_success_event]
    litellm.failure_callback = [callback.log_failure_event]

    logger.info("LiteLLM observability configured")

    return callback
