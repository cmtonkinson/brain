"""Smoke tests for the PydanticAI-backed headless loop driver."""

from __future__ import annotations

from lib.agent import LoopResult, run


def test_run_signature_exposes_keyword_only_contract() -> None:
    """``lib.agent.run`` is the canonical entry point for headless callers."""
    import inspect

    signature = inspect.signature(run)
    parameters = signature.parameters
    expected_kwargs = {
        "client",
        "system_blocks",
        "prompt",
        "principal",
        "source",
        "channel",
        "session_id",
        "parent_invocation_id",
        "tool_allowlist",
        "max_turns",
        "cancel_check",
        "record_turn",
        "timeout_seconds",
        "context_text",
        "context_environment_items",
    }
    missing = expected_kwargs - set(parameters)
    assert not missing, f"missing keyword-only parameters on lib.agent.run: {missing}"
    assert signature.return_annotation in (LoopResult, "LoopResult")


def test_loop_result_shape_is_stable() -> None:
    """``LoopResult`` exposes the three fields the headless driver promises."""
    result = LoopResult(final_response="ok", turn_count=1, exhausted=False)
    assert result.final_response == "ok"
    assert result.turn_count == 1
    assert result.exhausted is False
