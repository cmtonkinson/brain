"""Classify one dynamic op by mapping operator-supplied words to effect/approval."""

from __future__ import annotations

from lib.sdk import OP_APPROVALS, OP_EFFECTS
from lib.sdk.client import BrainSdkClient


def execute(input_payload: dict[str, object] | None = None) -> str:
    """Persist effect and/or approval for one dynamic op based on free-form words."""
    payload = {} if input_payload is None else input_payload
    op_id = str(payload.get("op_id", "")).strip()
    if op_id == "":
        raise ValueError("op_id is required")

    raw_words = payload.get("words")
    if not isinstance(raw_words, (list, tuple)):
        raise ValueError("words must be an array of strings")
    words = [str(item).strip().lower() for item in raw_words if str(item).strip() != ""]
    if not words:
        raise ValueError("words must contain at least one classification term")

    effect: str | None = None
    approval: str | None = None
    for word in words:
        if word in OP_EFFECTS:
            if effect is not None and effect != word:
                raise ValueError(f"conflicting effect words: {effect!r} and {word!r}")
            effect = word
            continue
        if word in OP_APPROVALS:
            if approval is not None and approval != word:
                raise ValueError(
                    f"conflicting approval words: {approval!r} and {word!r}"
                )
            approval = word
            continue
        raise ValueError(
            f"unknown classification word: {word!r}. "
            f"Effects: {'|'.join(OP_EFFECTS)}. "
            f"Approvals: {'|'.join(OP_APPROVALS)}."
        )

    if effect is None and approval is None:
        raise ValueError("at least one effect or approval word is required")

    with BrainSdkClient(source="op-classify", principal="operator") as client:
        row = client.classify_dynamic_op(
            op_id=op_id,
            effect=effect,
            approval=approval,
        )

    parts = []
    if effect is not None:
        parts.append(f"effect={effect}")
    if approval is not None:
        parts.append(f"approval={approval}")
    set_summary = ", ".join(parts)

    final_effect = row.effect or "<unset>"
    final_approval = row.approval or "<unset>"
    if row.effect is not None and row.approval is not None:
        ready_note = "op is now active and invokable."
    else:
        ready_note = "op remains inactive until both effect and approval are set."

    return (
        f"Classified {op_id}: set {set_summary}. "
        f"Persisted: effect={final_effect}, approval={final_approval}. "
        f"{ready_note}"
    )
