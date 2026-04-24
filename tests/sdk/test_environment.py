"""Tests for SDK environment context assembly."""

from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace

import pytest

from lib.sdk.environment import (
    EnvironmentContextResolutionError,
    assemble_environment_context,
)
from lib.sdk.errors import BrainDependencyError


class _FakeClient:
    def __init__(self) -> None:
        self.calls: list[dict[str, object]] = []

    def invoke_capability(self, **kwargs: object) -> object:
        self.calls.append(kwargs)
        if kwargs["capability_id"] == "broken-capability":
            raise BrainDependencyError(
                message="dependency down",
                operation="capabilities.invoke",
            )
        return SimpleNamespace(output={"value": kwargs["input_payload"]})


def test_assemble_environment_context_invokes_configured_capabilities() -> None:
    """Environment context assembly should preserve ordered capability outputs."""
    client = _FakeClient()

    context, diagnostics = assemble_environment_context(
        client=client,
        entries=(
            {
                "capability_id": "demo-context",
                "input_payload": {"scope": "today"},
            },
        ),
        actor="operator",
        channel="signal",
    )

    assert diagnostics == ()
    assert len(context.items) == 1
    assert context.items[0].capability_id == "demo-context"
    assert context.items[0].tag_name == "demo-context"
    assert context.items[0].output == {"value": {"scope": "today"}}
    assert client.calls[0]["actor"] == "operator"
    assert client.calls[0]["channel"] == "signal"


def test_assemble_environment_context_omits_failed_capabilities() -> None:
    """Failed environment capabilities should be omitted with diagnostics."""
    context, diagnostics = assemble_environment_context(
        client=_FakeClient(),
        entries=("broken-capability", "current-datetime"),
        actor="operator",
        channel="signal",
    )

    assert [item.capability_id for item in context.items] == ["current-datetime"]
    assert len(diagnostics) == 1
    assert diagnostics[0].capability_id == "broken-capability"
    assert diagnostics[0].error_type == "BrainDependencyError"


def test_assemble_environment_context_resolves_local_datetime_boundaries() -> None:
    """Dynamic local boundary resolvers should render concrete ISO 8601 values."""
    client = _FakeClient()

    context, diagnostics = assemble_environment_context(
        client=client,
        entries=(
            {
                "capability_id": "eventkit--list-calendar-events",
                "input_payload": {
                    "start_date": {
                        "resolve": "local_datetime_boundary",
                        "boundary": "start_of_day",
                        "day_offset": 0,
                    },
                    "end_date": {
                        "resolve": "local_datetime_boundary",
                        "boundary": "end_of_day",
                        "day_offset": 1,
                    },
                },
            },
        ),
        actor="operator",
        channel="signal",
        preferred_timezone="America/New_York",
        reference_now=datetime(2026, 4, 23, 15, 30, tzinfo=UTC),
    )

    assert diagnostics == ()
    assert context.items[0].output == {
        "value": {
            "start_date": "2026-04-23T00:00:00-04:00",
            "end_date": "2026-04-24T23:59:59-04:00",
        }
    }


def test_assemble_environment_context_reports_invalid_dynamic_value_specs() -> None:
    """Dynamic resolver failures should omit the entry and emit diagnostics."""
    context, diagnostics = assemble_environment_context(
        client=_FakeClient(),
        entries=(
            {
                "capability_id": "eventkit--list-calendar-events",
                "input_payload": {
                    "start_date": {
                        "resolve": "unknown",
                    }
                },
            },
        ),
        actor="operator",
        channel="signal",
        preferred_timezone="America/New_York",
        reference_now=datetime(2026, 4, 23, 15, 30, tzinfo=UTC),
    )

    assert context.items == ()
    assert len(diagnostics) == 1
    assert diagnostics[0].capability_id == "eventkit--list-calendar-events"
    assert diagnostics[0].error_type == "EnvironmentContextResolutionError"


def test_assemble_environment_context_resolves_nested_payload_values() -> None:
    """Dynamic resolvers should work recursively inside dict and list payloads."""
    client = _FakeClient()

    context, diagnostics = assemble_environment_context(
        client=client,
        entries=(
            {
                "capability_id": "eventkit--list-calendar-events",
                "input_payload": {
                    "window": {
                        "start": {
                            "resolve": "local_datetime_boundary",
                            "boundary": "start_of_day",
                            "day_offset": -1,
                        },
                        "end": {
                            "resolve": "local_datetime_boundary",
                            "boundary": "end_of_day",
                            "day_offset": 0,
                            "format": "iso8601",
                        },
                    },
                    "checkpoints": [
                        {"label": "open"},
                        {
                            "at": {
                                "resolve": "local_datetime_boundary",
                                "boundary": "start_of_day",
                                "day_offset": 2,
                            }
                        },
                    ],
                },
            },
        ),
        actor="operator",
        channel="signal",
        preferred_timezone="America/New_York",
        reference_now=datetime(2026, 4, 23, 15, 30, tzinfo=UTC),
    )

    assert diagnostics == ()
    assert client.calls[0]["input_payload"] == {
        "window": {
            "start": "2026-04-22T00:00:00-04:00",
            "end": "2026-04-23T23:59:59-04:00",
        },
        "checkpoints": [
            {"label": "open"},
            {"at": "2026-04-25T00:00:00-04:00"},
        ],
    }
    assert context.items[0].output == {"value": client.calls[0]["input_payload"]}


def test_assemble_environment_context_omits_only_bad_resolver_entry() -> None:
    """One resolver failure should not prevent later entries from being invoked."""
    client = _FakeClient()

    context, diagnostics = assemble_environment_context(
        client=client,
        entries=(
            {
                "capability_id": "bad-context",
                "input_payload": {
                    "start_date": {
                        "resolve": "local_datetime_boundary",
                        "boundary": "not-a-boundary",
                    }
                },
            },
            {
                "capability_id": "good-context",
                "input_payload": {"static": "ok"},
            },
        ),
        actor="operator",
        channel="signal",
        preferred_timezone="America/New_York",
        reference_now=datetime(2026, 4, 23, 15, 30, tzinfo=UTC),
    )

    assert [item.capability_id for item in context.items] == ["good-context"]
    assert [call["capability_id"] for call in client.calls] == ["good-context"]
    assert len(diagnostics) == 1
    assert diagnostics[0].capability_id == "bad-context"
    assert diagnostics[0].error_type == "EnvironmentContextResolutionError"


def test_assemble_environment_context_rejects_naive_reference_now() -> None:
    """Naive reference times should fail fast as an invalid top-level precondition."""
    with pytest.raises(
        EnvironmentContextResolutionError,
        match="reference_now must be timezone-aware",
    ):
        assemble_environment_context(
            client=_FakeClient(),
            entries=(
                {
                    "capability_id": "eventkit--list-calendar-events",
                    "input_payload": {
                        "start_date": {
                            "resolve": "local_datetime_boundary",
                            "boundary": "start_of_day",
                        }
                    },
                },
            ),
            actor="operator",
            channel="signal",
            preferred_timezone="America/New_York",
            reference_now=datetime(2026, 4, 23, 15, 30),
        )


@pytest.mark.parametrize(
    ("reference_now", "expected_start", "expected_end"),
    [
        (
            datetime(2026, 1, 10, 15, 30, tzinfo=UTC),
            "2026-01-10T00:00:00-05:00",
            "2026-01-11T23:59:59-05:00",
        ),
        (
            datetime(2026, 7, 10, 15, 30, tzinfo=UTC),
            "2026-07-10T00:00:00-04:00",
            "2026-07-11T23:59:59-04:00",
        ),
    ],
)
def test_assemble_environment_context_uses_timezone_offset_for_target_day(
    reference_now: datetime,
    expected_start: str,
    expected_end: str,
) -> None:
    """Resolved day-boundary datetimes should reflect the local DST offset."""
    client = _FakeClient()

    assemble_environment_context(
        client=client,
        entries=(
            {
                "capability_id": "eventkit--list-calendar-events",
                "input_payload": {
                    "start_date": {
                        "resolve": "local_datetime_boundary",
                        "boundary": "start_of_day",
                    },
                    "end_date": {
                        "resolve": "local_datetime_boundary",
                        "boundary": "end_of_day",
                        "day_offset": 1,
                    },
                },
            },
        ),
        actor="operator",
        channel="signal",
        preferred_timezone="America/New_York",
        reference_now=reference_now,
    )

    assert client.calls[0]["input_payload"] == {
        "start_date": expected_start,
        "end_date": expected_end,
    }
