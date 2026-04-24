"""Capability-backed environment context assembly for Agent inference."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime, time, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from lib.sdk.errors import BrainSdkError
from lib.sdk.meta import MetaOverrides
from lib.shared.language_model import (
    InferenceEnvironmentContext,
    InferenceEnvironmentItem,
)


@dataclass(frozen=True, slots=True)
class EnvironmentContextEntry:
    """One configured environment-context capability invocation."""

    capability_id: str
    input_payload: dict[str, object]


@dataclass(frozen=True, slots=True)
class EnvironmentContextDiagnostic:
    """One omitted environment-context capability invocation."""

    capability_id: str
    error_type: str
    message: str


class EnvironmentContextResolutionError(ValueError):
    """Raised when one dynamic environment-context value cannot be resolved."""


_LOCAL_BOUNDARY_RESOLVER = "local_datetime_boundary"
_ISO8601_FORMAT = "iso8601"


def assemble_environment_context(
    *,
    client: object,
    entries: Iterable[object],
    actor: str,
    channel: str,
    preferred_timezone: str = "UTC",
    reference_now: datetime | None = None,
    meta: MetaOverrides | None = None,
) -> tuple[InferenceEnvironmentContext, tuple[EnvironmentContextDiagnostic, ...]]:
    """Invoke configured capabilities and assemble transient environment context."""
    items: list[InferenceEnvironmentItem] = []
    diagnostics: list[EnvironmentContextDiagnostic] = []
    resolved_now = (
        datetime.now(UTC)
        if reference_now is None
        else _normalize_reference_now(reference_now)
    )
    for raw_entry in entries:
        try:
            entry = _normalize_entry(
                raw_entry,
                preferred_timezone=preferred_timezone,
                reference_now=resolved_now,
            )
        except EnvironmentContextResolutionError as exc:
            capability_id = _extract_capability_id(raw_entry)
            diagnostics.append(
                EnvironmentContextDiagnostic(
                    capability_id=capability_id,
                    error_type=type(exc).__name__,
                    message=str(exc),
                )
            )
            continue
        if entry.capability_id == "":
            continue
        try:
            result = client.invoke_capability(  # type: ignore[attr-defined]
                capability_id=entry.capability_id,
                input_payload=entry.input_payload,
                actor=actor,
                channel=channel,
                meta=meta,
            )
        except BrainSdkError as exc:
            diagnostics.append(
                EnvironmentContextDiagnostic(
                    capability_id=entry.capability_id,
                    error_type=type(exc).__name__,
                    message=str(exc),
                )
            )
            continue
        output = getattr(result, "output", None)
        if output is None:
            continue
        items.append(
            InferenceEnvironmentItem(
                capability_id=entry.capability_id,
                tag_name=_capability_id_to_tag_name(entry.capability_id),
                output=output,
            )
        )
    return InferenceEnvironmentContext(items=tuple(items)), tuple(diagnostics)


def _normalize_entry(
    value: object,
    *,
    preferred_timezone: str,
    reference_now: datetime,
) -> EnvironmentContextEntry:
    """Normalize one entry and resolve any dynamic input payload values."""
    raw_entry = _normalize_entry_static(value)
    return EnvironmentContextEntry(
        capability_id=raw_entry.capability_id,
        input_payload=_resolve_payload(
            raw_entry.input_payload,
            preferred_timezone=preferred_timezone,
            reference_now=reference_now,
        ),
    )


def _normalize_entry_static(value: object) -> EnvironmentContextEntry:
    """Normalize pydantic/dataclass/dict/string config entries without resolution."""
    if isinstance(value, str):
        return EnvironmentContextEntry(
            capability_id=value.strip(),
            input_payload={},
        )
    if isinstance(value, Mapping):
        capability_id = str(value.get("capability_id", "")).strip()
        raw_payload = value.get("input_payload", {})
        payload = raw_payload if isinstance(raw_payload, dict) else {}
        return EnvironmentContextEntry(
            capability_id=capability_id,
            input_payload={str(key): item for key, item in payload.items()},
        )
    capability_id = str(getattr(value, "capability_id", "")).strip()
    raw_payload: Any = getattr(value, "input_payload", {})
    payload = raw_payload if isinstance(raw_payload, dict) else {}
    return EnvironmentContextEntry(
        capability_id=capability_id,
        input_payload={str(key): item for key, item in payload.items()},
    )


def _resolve_payload(
    payload: Mapping[str, object],
    *,
    preferred_timezone: str,
    reference_now: datetime,
) -> dict[str, object]:
    """Resolve one input payload tree into concrete JSON-serializable values."""
    return {
        str(key): _resolve_value(
            item,
            preferred_timezone=preferred_timezone,
            reference_now=reference_now,
        )
        for key, item in payload.items()
    }


def _resolve_value(
    value: object,
    *,
    preferred_timezone: str,
    reference_now: datetime,
) -> object:
    """Resolve one recursive environment-context input value."""
    if isinstance(value, Mapping):
        if "resolve" in value:
            return _resolve_dynamic_value(
                value,
                preferred_timezone=preferred_timezone,
                reference_now=reference_now,
            )
        return {
            str(key): _resolve_value(
                item,
                preferred_timezone=preferred_timezone,
                reference_now=reference_now,
            )
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [
            _resolve_value(
                item,
                preferred_timezone=preferred_timezone,
                reference_now=reference_now,
            )
            for item in value
        ]
    return value


def _resolve_dynamic_value(
    value: Mapping[str, object],
    *,
    preferred_timezone: str,
    reference_now: datetime,
) -> object:
    """Resolve one dynamic value spec into a concrete value."""
    resolver_name = str(value.get("resolve", "")).strip()
    if resolver_name != _LOCAL_BOUNDARY_RESOLVER:
        raise EnvironmentContextResolutionError(
            f"unsupported environment-context resolver: {resolver_name or '<empty>'}"
        )
    boundary = str(value.get("boundary", "")).strip()
    if boundary not in {"start_of_day", "end_of_day"}:
        raise EnvironmentContextResolutionError(
            f"invalid local_datetime_boundary boundary: {boundary or '<empty>'}"
        )
    raw_day_offset = value.get("day_offset", 0)
    if not isinstance(raw_day_offset, int):
        raise EnvironmentContextResolutionError(
            "local_datetime_boundary day_offset must be an integer"
        )
    rendered_format = str(value.get("format", _ISO8601_FORMAT)).strip()
    if rendered_format != _ISO8601_FORMAT:
        raise EnvironmentContextResolutionError(
            f"unsupported local_datetime_boundary format: {rendered_format or '<empty>'}"
        )
    return _resolve_local_datetime_boundary(
        preferred_timezone=preferred_timezone,
        reference_now=reference_now,
        boundary=boundary,
        day_offset=raw_day_offset,
    )


def _resolve_local_datetime_boundary(
    *,
    preferred_timezone: str,
    reference_now: datetime,
    boundary: str,
    day_offset: int,
) -> str:
    """Resolve one local day boundary as an ISO 8601 datetime string."""
    local_tz = ZoneInfo(preferred_timezone)
    local_now = reference_now.astimezone(local_tz)
    target_date = local_now.date() + timedelta(days=day_offset)
    target_time = (
        time(hour=0, minute=0, second=0)
        if boundary == "start_of_day"
        else time(hour=23, minute=59, second=59)
    )
    return datetime.combine(target_date, target_time, tzinfo=local_tz).isoformat()


def _normalize_reference_now(reference_now: datetime) -> datetime:
    """Return one timezone-aware UTC reference time."""
    if reference_now.tzinfo is None:
        raise EnvironmentContextResolutionError("reference_now must be timezone-aware")
    return reference_now.astimezone(UTC)


def _extract_capability_id(value: object) -> str:
    """Best-effort capability id extraction for diagnostics."""
    if isinstance(value, str):
        return value.strip()
    if isinstance(value, Mapping):
        return str(value.get("capability_id", "")).strip()
    return str(getattr(value, "capability_id", "")).strip()


def _capability_id_to_tag_name(capability_id: str) -> str:
    """Derive an SGML-safe tag name from one capability id."""
    return capability_id.strip().replace("_", "-")
