"""Unit tests for routing envelope schema validation."""

from __future__ import annotations

from attention.envelope_schema import EnvelopeDecision, validate_routing_envelope_payload


def test_routing_envelope_accepts_valid_payload() -> None:
    """Ensure routing envelopes validate with required fields."""
    payload = {
        "version": "1.0.0",
        "signal_type": "skill.invocation",
        "signal_reference": "skill:example:123",
        "actor": "tester",
        "owner": "tester",
        "channel_hint": "signal",
        "urgency": 0.2,
        "channel_cost": 0.8,
        "content_type": "internal",
        "notification": {
            "version": "1.0.0",
            "source_component": "skill_runtime",
            "origin_signal": "skill:example:123",
            "confidence": 0.7,
            "provenance": [
                {
                    "input_type": "invocation",
                    "reference": "invocation-123",
                    "description": "example",
                }
            ],
        },
    }
    result = validate_routing_envelope_payload(payload)

    assert result.decision == EnvelopeDecision.ACCEPT
    assert result.envelope is not None


def test_routing_envelope_missing_notification_logs_only() -> None:
    """Ensure routing envelopes without notification data are rejected."""
    payload = {
        "version": "1.0.0",
        "signal_type": "skill.invocation",
        "signal_reference": "skill:example:123",
        "actor": "tester",
        "owner": "tester",
        "urgency": 0.2,
        "channel_cost": 0.8,
        "content_type": "internal",
    }
    result = validate_routing_envelope_payload(payload)

    assert result.decision == EnvelopeDecision.LOG_ONLY
    assert result.envelope is None
