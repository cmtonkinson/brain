"""Global service registry for skill execution."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass
class SkillServices:
    """Service bundle exposed to skill implementations."""

    obsidian: Any | None = None
    code_mode: Any | None = None
    signal: Any | None = None


_services: SkillServices | None = None


def set_services(services: SkillServices) -> None:
    """Register the current skill services bundle."""
    global _services
    _services = services


def get_services() -> SkillServices:
    """Return the current skill services bundle."""
    if _services is None:
        raise RuntimeError("Skill services not initialized")
    return _services
