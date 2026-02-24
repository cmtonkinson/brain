"""Context assembly module for Memory Authority Service."""

from __future__ import annotations

from packages.brain_shared.envelope import EnvelopeMeta
from services.state.memory_authority.dialogue import DialogueModule
from services.state.memory_authority.domain import ContextBlock
from services.state.memory_authority.focus import FocusModule
from services.state.memory_authority.profile import ProfileModule


class ContextAssembler:
    """Compose Profile, Focus, and Dialogue into one context block."""

    def __init__(
        self,
        *,
        profile: ProfileModule,
        focus: FocusModule,
        dialogue: DialogueModule,
    ) -> None:
        self._profile = profile
        self._focus = focus
        self._dialogue = dialogue

    def assemble(self, *, meta: EnvelopeMeta, session_id: str) -> ContextBlock:
        """Assemble full context block for one session."""
        focus = self._focus.read(session_id=session_id)
        dialogue = self._dialogue.assemble(meta=meta, session_id=session_id)

        return ContextBlock(
            profile=self._profile.read(),
            focus=None if focus is None else focus.content,
            dialogue=dialogue,
            # TODO(cmtonkinson): Inject relevant Reference snippets via EAS/VAS.
            reference_snippets=[],
        )
