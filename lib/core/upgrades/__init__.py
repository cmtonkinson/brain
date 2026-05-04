"""Forward-only host-side state-mutation runner (Upgrades subsystem).

See ``docs/upgrades.md`` for operator and author documentation.
"""

from __future__ import annotations

from lib.core.upgrades.api import UpgradeContext, load_sibling

__all__ = ["UpgradeContext", "load_sibling"]
