"""Service bundle descriptor for skill execution."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class SkillServices:
    """Service bundle exposed to skill implementations."""

    obsidian: Any | None = None
    code_mode: Any | None = None
    signal: Any | None = None
    object_store: Any | None = None
