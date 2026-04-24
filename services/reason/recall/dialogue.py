"""Dialogue module for Recall Service."""

from __future__ import annotations

from lib.shared.envelope import EnvelopeMeta
from services.effect.language.service import LanguageService
from services.reason.recall.config import RecallSettings
from services.reason.recall.data.repository import MemoryRepository
from services.reason.recall.domain import (
    DialogueTurn,
    FocusRecord,
    InboundInstructionRecord,
    SessionRecord,
    TurnDirection,
    TurnRecord,
    estimate_token_count,
)


class DialogueModule:
    """Store turns and assemble dialogue context with a rolling summary frontier."""

    def __init__(
        self,
        *,
        repository: MemoryRepository,
        language_model: LanguageService,
        settings: RecallSettings,
    ) -> None:
        self._repository = repository
        self._language_model = language_model
        self._min_turns_to_keep = settings.min_turns_to_keep
        self._max_turns_to_keep = settings.max_turns_to_keep

    def append_inbound(
        self,
        *,
        session_id: str,
        content: str,
        trace_id: str,
        conversation_episode_id: str,
        principal: str,
        instruction: InboundInstructionRecord | None = None,
    ) -> TurnRecord:
        """Append one inbound user turn."""
        return self._repository.insert_turn(
            session_id=session_id,
            direction=TurnDirection.INBOUND,
            content=content,
            role="user",
            model=None,
            provider=None,
            token_count=estimate_token_count(content),
            reasoning_level=None,
            trace_id=trace_id,
            conversation_episode_id=conversation_episode_id,
            principal=principal,
            source=None if instruction is None else instruction.source,
            instruction=instruction,
        )

    def append_outbound(
        self,
        *,
        session_id: str,
        content: str,
        model: str,
        provider: str,
        token_count: int,
        reasoning_level: str,
        trace_id: str,
        conversation_episode_id: str,
        principal: str,
    ) -> TurnRecord:
        """Append one outbound assistant turn."""
        return self._repository.insert_turn(
            session_id=session_id,
            direction=TurnDirection.OUTBOUND,
            content=content,
            role="assistant",
            model=model,
            provider=provider,
            token_count=token_count,
            reasoning_level=reasoning_level,
            trace_id=trace_id,
            conversation_episode_id=conversation_episode_id,
            principal=principal,
        )

    def assemble(
        self,
        *,
        meta: EnvelopeMeta,
        session_id: str,
        focus: FocusRecord | None,
        exclude_turn_id: str | None = None,
    ) -> tuple[str, list[DialogueTurn]]:
        """Assemble rolling summary + recent dialogue, optionally excluding one live turn."""
        turns = self._repository.list_turns(session_id=session_id)
        if not turns:
            return "", []

        session = self._repository.get_session(session_id=session_id)
        pointer = None if session is None else session.dialogue_start_turn_id
        visible_turns = self._turns_after_pointer(turns=turns, pointer_turn_id=pointer)
        if exclude_turn_id is not None:
            visible_turns = [
                turn for turn in visible_turns if turn.id != exclude_turn_id
            ]
        summary_text = (
            ""
            if session is None or session.dialogue_summary is None
            else session.dialogue_summary
        )
        if not visible_turns:
            return summary_text, []

        turns_to_render = visible_turns
        if len(visible_turns) > self._max_turns_to_keep:
            turns_to_absorb = len(visible_turns) - self._min_turns_to_keep
            absorbable = visible_turns[:turns_to_absorb]
            # TODO(cmtonkinson): Move rolling summary compaction to an async job
            # once the scheduler/jobs service exists; assembly should then read
            # precomputed summary state instead of blocking on Language work inline.
            updated_summary = self._roll_summary(
                meta=meta,
                existing_summary=summary_text,
                focus=focus,
                run=absorbable,
            )
            if updated_summary is not None and session is not None:
                updated_session = self._repository.update_dialogue_summary(
                    session_id=session_id,
                    dialogue_summary=updated_summary,
                    dialogue_summary_token_count=estimate_token_count(updated_summary),
                    dialogue_start_turn_id=absorbable[-1].id,
                )
                if updated_session is not None:
                    summary_text = updated_summary
                    turns_to_render = visible_turns[turns_to_absorb:]

        recent_dialogue = [
            DialogueTurn(
                role=turn.role,
                content=turn.content,
                is_summary=False,
                timestamp_ms=turn.timestamp_ms,
            )
            for turn in turns_to_render
        ]
        return summary_text, recent_dialogue

    def compact(
        self,
        *,
        meta: EnvelopeMeta,
        session_id: str,
        focus: FocusRecord | None,
    ) -> SessionRecord | None:
        """Force-absorb all visible turns into the rolling summary.

        Advances ``dialogue_start_turn_id`` to the latest visible turn so that
        the next context assembly returns zero recent verbatim turns — only
        focus and summary remain.
        """
        session = self._repository.get_session(session_id=session_id)
        if session is None:
            return None

        turns = self._repository.list_turns(session_id=session_id)
        visible_turns = self._turns_after_pointer(
            turns=turns, pointer_turn_id=session.dialogue_start_turn_id
        )
        if not visible_turns:
            return session

        existing_summary = (
            "" if session.dialogue_summary is None else session.dialogue_summary
        )
        updated_summary = self._roll_summary(
            meta=meta,
            existing_summary=existing_summary,
            focus=focus,
            run=visible_turns,
        )
        if updated_summary is None:
            return session

        updated_session = self._repository.update_dialogue_summary(
            session_id=session_id,
            dialogue_summary=updated_summary,
            dialogue_summary_token_count=estimate_token_count(updated_summary),
            dialogue_start_turn_id=visible_turns[-1].id,
        )
        return updated_session if updated_session is not None else session

    def _roll_summary(
        self,
        *,
        meta: EnvelopeMeta,
        existing_summary: str,
        focus: FocusRecord | None,
        run: list[TurnRecord],
    ) -> str | None:
        """Rewrite the rolling summary by folding in newly-absorbed turns."""
        if not run:
            return None

        transcript = "\n".join(f"{turn.role}: {turn.content}" for turn in run)
        focus_text = (
            "" if focus is None or focus.content is None else focus.content.strip()
        )
        focus_section = (
            "Current focus:\n(none)\n\n"
            if focus_text == ""
            else f"Current focus:\n{focus_text}\n\n"
        )
        existing_summary_section = (
            "Existing summary:\n(none)\n\n"
            if existing_summary.strip() == ""
            else f"Existing summary:\n{existing_summary.strip()}\n\n"
        )
        prompt = (
            "Update the rolling conversation summary for context recall. "
            "Preserve active goals, decisions, commitments, and unresolved threads. "
            "Bias toward what matters for current focus. "
            "Output only the rewritten summary.\n\n"
            f"{existing_summary_section}"
            f"{focus_section}"
            f"New dialogue to absorb:\n{transcript}"
        )
        result = self._language_model.chat(
            meta=meta,
            prompt=prompt,
            profile="quick",
        )
        if not result.ok or result.payload is None:
            return None

        payload = result.payload.value
        summary_raw = getattr(payload, "text", None)
        if not isinstance(summary_raw, str):
            return None
        summary_text = summary_raw.strip()
        if summary_text == "":
            return None
        return summary_text

    def _turns_after_pointer(
        self,
        *,
        turns: list[TurnRecord],
        pointer_turn_id: str | None,
    ) -> list[TurnRecord]:
        """Return turns strictly after session dialogue pointer turn id."""
        if pointer_turn_id is None:
            return turns

        pointer_index = None
        for idx, turn in enumerate(turns):
            if turn.id == pointer_turn_id:
                pointer_index = idx
                break

        if pointer_index is None:
            return turns
        return turns[pointer_index + 1 :]
