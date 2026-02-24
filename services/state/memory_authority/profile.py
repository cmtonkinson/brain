"""Profile context module for Memory Authority Service."""

from __future__ import annotations

from services.state.memory_authority.config import MemoryAuthoritySettings
from services.state.memory_authority.domain import ProfileContext


class ProfileModule:
    """Read-only profile projection loaded from MAS configuration."""

    def __init__(self, settings: MemoryAuthoritySettings) -> None:
        profile = settings.profile
        self._profile = ProfileContext(
            operator_name=profile.operator_name,
            brain_name=profile.brain_name,
            brain_verbosity=profile.brain_verbosity,
        )

    def read(self) -> ProfileContext:
        """Return immutable profile context for assembly operations."""
        return self._profile
