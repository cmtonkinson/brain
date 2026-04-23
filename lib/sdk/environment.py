"""Capability-backed environment context assembly for Agent inference."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from typing import Any

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


def assemble_environment_context(
    *,
    client: object,
    entries: Iterable[object],
    actor: str,
    channel: str,
    meta: MetaOverrides | None = None,
) -> tuple[InferenceEnvironmentContext, tuple[EnvironmentContextDiagnostic, ...]]:
    """Invoke configured capabilities and assemble transient environment context."""
    items: list[InferenceEnvironmentItem] = []
    diagnostics: list[EnvironmentContextDiagnostic] = []
    for raw_entry in entries:
        entry = _normalize_entry(raw_entry)
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


def _normalize_entry(value: object) -> EnvironmentContextEntry:
    """Normalize pydantic/dataclass/dict/string config entries."""
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


def _capability_id_to_tag_name(capability_id: str) -> str:
    """Derive an SGML-safe tag name from one capability id."""
    return capability_id.strip().replace("_", "-")
