"""Canonical op effect/approval taxonomy shared across services and SDK.

Owning these as a single shared module avoids the literal sets drifting between
the Execution Service (which writes them onto manifests and dynamic-op rows),
the Policy Service (which evaluates them), the SDK (which exposes them to op
authors), and the SDK consumers (which classify dynamic ops).
"""

from __future__ import annotations

from typing import Literal, get_args

OpEffect = Literal["read", "write", "execute", "external"]
OpApproval = Literal["always", "never"]

OP_EFFECTS: tuple[str, ...] = tuple(get_args(OpEffect))
OP_APPROVALS: tuple[str, ...] = tuple(get_args(OpApproval))

__all__ = [
    "OP_APPROVALS",
    "OP_EFFECTS",
    "OpApproval",
    "OpEffect",
]
