"""Dialogue module for Memory Authority Service.

MAS uses lazy summarization: summaries are generated only when an older dialogue
slice is requested during context assembly and coverage is missing. This avoids
paying summarization cost for turns that may never be included in context.
"""

from __future__ import annotations

from dataclasses import dataclass

from packages.brain_shared.envelope import EnvelopeMeta
from services.action.language_model.service import LanguageModelService
from services.state.memory_authority.config import MemoryAuthoritySettings
from services.state.memory_authority.data.repository import MemoryRepository
from services.state.memory_authority.domain import (
    DialogueTurn,
    TurnDirection,
    TurnRecord,
    estimate_token_count,
)


@dataclass(frozen=True)
class _SummarySegment:
    """Inclusive index range for one summary-covered dialogue segment."""

    start_index: int
    end_index: int
    content: str


class DialogueModule:
    """Store turns and assemble dialogue context with lazy summary coverage."""

    def __init__(
        self,
        *,
        repository: MemoryRepository,
        language_model: LanguageModelService,
        settings: MemoryAuthoritySettings,
    ) -> None:
        self._repository = repository
        self._language_model = language_model
        self._recent_turns = settings.dialogue_recent_turns
        self._older_turns = settings.dialogue_older_turns

    def append_inbound(
        self,
        *,
        session_id: str,
        content: str,
        trace_id: str,
        principal: str,
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
            principal=principal,
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
            principal=principal,
        )

    def assemble(self, *, meta: EnvelopeMeta, session_id: str) -> list[DialogueTurn]:
        """Assemble dialogue as recent verbatim turns plus capped older summaries."""
        turns = self._repository.list_turns(session_id=session_id)
        if not turns:
            return []

        session = self._repository.get_session(session_id=session_id)
        pointer = None if session is None else session.dialogue_start_turn_id
        visible_turns = self._turns_after_pointer(turns=turns, pointer_turn_id=pointer)
        if not visible_turns:
            return []

        if len(visible_turns) <= self._recent_turns:
            return [
                DialogueTurn(role=turn.role, content=turn.content, is_summary=False)
                for turn in visible_turns
            ]

        older_turns = visible_turns[: -self._recent_turns]
        recent_turns = visible_turns[-self._recent_turns :]
        if self._older_turns == 0:
            older_selected: list[TurnRecord] = []
        elif len(older_turns) > self._older_turns:
            older_selected = older_turns[-self._older_turns :]
        else:
            older_selected = older_turns

        older_dialogue = self._assemble_older_dialogue(
            meta=meta,
            session_id=session_id,
            turns=older_selected,
        )
        recent_dialogue = [
            DialogueTurn(role=turn.role, content=turn.content, is_summary=False)
            for turn in recent_turns
        ]
        return [*older_dialogue, *recent_dialogue]

    def _assemble_older_dialogue(
        self,
        *,
        meta: EnvelopeMeta,
        session_id: str,
        turns: list[TurnRecord],
    ) -> list[DialogueTurn]:
        """Build the older dialogue block using persisted or newly-created summaries."""
        if not turns:
            return []

        summaries = self._repository.list_turn_summaries(session_id=session_id)
        turn_index = {turn.id: idx for idx, turn in enumerate(turns)}

        covered: dict[int, _SummarySegment] = {}
        for summary in summaries:
            start = turn_index.get(summary.start_turn_id)
            end = turn_index.get(summary.end_turn_id)
            if start is None or end is None or end < start:
                continue
            segment = _SummarySegment(
                start_index=start,
                end_index=end,
                content=summary.content,
            )
            covered[start] = segment

        items: list[DialogueTurn] = []
        index = 0
        while index < len(turns):
            segment = covered.get(index)
            if segment is not None:
                items.append(
                    DialogueTurn(
                        role="system", content=segment.content, is_summary=True
                    )
                )
                index = segment.end_index + 1
                continue

            next_segment_start = min(
                (pos for pos in covered.keys() if pos > index),
                default=len(turns),
            )
            run = turns[index:next_segment_start]
            summary = self._summarize_run(meta=meta, session_id=session_id, run=run)
            if summary is not None:
                items.append(
                    DialogueTurn(role="system", content=summary, is_summary=True)
                )
            else:
                for turn in run:
                    items.append(
                        DialogueTurn(
                            role=turn.role, content=turn.content, is_summary=False
                        )
                    )
            index = next_segment_start

        return items

    def _summarize_run(
        self,
        *,
        meta: EnvelopeMeta,
        session_id: str,
        run: list[TurnRecord],
    ) -> str | None:
        """Summarize one older run and persist its range summary record."""
        if not run:
            return None

        existing = self._repository.get_turn_summary_by_range(
            session_id=session_id,
            start_turn_id=run[0].id,
            end_turn_id=run[-1].id,
        )
        if existing is not None:
            return existing.content

        transcript = "\n".join(f"{turn.role}: {turn.content}" for turn in run)
        prompt = (
            "Summarize this dialogue segment for context recall. "
            "Preserve active goals, decisions, and commitments. "
            "Keep it concise and factual.\n\n"
            f"Dialogue:\n{transcript}"
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

        persisted = self._repository.create_turn_summary(
            session_id=session_id,
            start_turn_id=run[0].id,
            end_turn_id=run[-1].id,
            content=summary_text,
            token_count=estimate_token_count(summary_text),
        )
        return persisted.content

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
