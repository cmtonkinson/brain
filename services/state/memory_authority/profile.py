"""Profile context module for Memory Authority Service."""

from __future__ import annotations

from packages.brain_shared.config.models import ProfileSettings
from services.state.memory_authority.domain import BrainVerbosity, ProfileContext


class ProfileModule:
    """Read-only profile projection loaded from top-level profile configuration."""

    def __init__(self, profile: ProfileSettings) -> None:
        self._profile = ProfileContext(
            operator_name=profile.operator_name,
            brain_name=profile.brain_name,
            brain_verbosity=BrainVerbosity(profile.brain_verbosity),
        )

    def read(self) -> ProfileContext:
        """Return immutable profile context for assembly operations."""
        return self._profile
