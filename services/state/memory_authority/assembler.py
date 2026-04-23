"""Context assembly module for Memory Authority Service."""

from __future__ import annotations

from lib.shared.envelope import EnvelopeMeta
from services.state.memory_authority.dialogue import DialogueModule
from services.state.memory_authority.domain import ContextBlock
from services.state.memory_authority.focus import FocusModule


class ContextAssembler:
    """Compose Focus and Dialogue into one context block."""

    def __init__(
        self,
        *,
        focus: FocusModule,
        dialogue: DialogueModule,
    ) -> None:
        self._focus = focus
        self._dialogue = dialogue

    def assemble(
        self,
        *,
        meta: EnvelopeMeta,
        session_id: str,
        exclude_turn_id: str | None = None,
    ) -> ContextBlock:
        """Assemble one historical context block for a session."""
        focus = self._focus.read(session_id=session_id)
        recent_conversation_summary, recent_turns = self._dialogue.assemble(
            meta=meta,
            session_id=session_id,
            focus=focus,
            exclude_turn_id=exclude_turn_id,
        )

        return ContextBlock(
            current_focus=None if focus is None else focus.content,
            recent_conversation_summary=recent_conversation_summary,
            recent_turns=recent_turns,
            # TODO(cmtonkinson): Inject relevant Reference snippets via EAS/VAS.
            reference_snippets=[],
        )
