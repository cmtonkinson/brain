"""Focus module for Memory Authority Service."""

from __future__ import annotations

from dataclasses import dataclass

from packages.brain_shared.envelope import EnvelopeMeta
from services.action.language_model.service import LanguageModelService
from services.state.memory_authority.config import MemoryAuthoritySettings
from services.state.memory_authority.data.repository import MemoryRepository
from services.state.memory_authority.domain import FocusRecord, estimate_token_count


class FocusCompactionError(RuntimeError):
    """Raised when focus compaction cannot produce an in-budget result."""


@dataclass(frozen=True)
class _CompactionResult:
    """Container for compacted focus payload and estimated token count."""

    content: str
    token_count: int


class FocusModule:
    """Read and mutate session focus with budget-aware compaction."""

    def __init__(
        self,
        *,
        repository: MemoryRepository,
        language_model: LanguageModelService,
        settings: MemoryAuthoritySettings,
    ) -> None:
        self._repository = repository
        self._language_model = language_model
        self._token_budget = settings.focus_token_budget

    def read(self, *, session_id: str) -> FocusRecord | None:
        """Read current session focus snapshot."""
        session = self._repository.get_session(session_id=session_id)
        if session is None:
            return None
        return FocusRecord(
            session_id=session.id,
            content=session.focus,
            token_count=session.focus_token_count,
            updated_at=session.updated_at,
        )

    def update(
        self, *, meta: EnvelopeMeta, session_id: str, content: str
    ) -> FocusRecord:
        """Update focus content and compact if budget is exceeded."""
        token_count = estimate_token_count(content)
        focus_text = content

        if token_count > self._token_budget:
            compacted = self._compact_focus(meta=meta, content=content)
            focus_text = compacted.content
            token_count = compacted.token_count

        session = self._repository.update_focus(
            session_id=session_id,
            focus=focus_text,
            focus_token_count=token_count,
        )
        if session is None:
            raise KeyError("session not found")

        return FocusRecord(
            session_id=session.id,
            content=session.focus,
            token_count=session.focus_token_count,
            updated_at=session.updated_at,
        )

    def _compact_focus(self, *, meta: EnvelopeMeta, content: str) -> _CompactionResult:
        """Rewrite focus with at most one retry when initial compaction is oversized."""
        first = self._request_compaction(meta=meta, content=content, retry=False)
        if first.token_count <= self._token_budget:
            return first

        second = self._request_compaction(meta=meta, content=first.content, retry=True)
        if second.token_count <= self._token_budget:
            return second

        raise FocusCompactionError("focus compaction exceeded token budget after retry")

    def _request_compaction(
        self,
        *,
        meta: EnvelopeMeta,
        content: str,
        retry: bool,
    ) -> _CompactionResult:
        """Call LMS quick profile to compact focus content."""
        retry_instruction = ""
        if retry:
            retry_instruction = (
                "Prior compaction was too long. Be stricter and shorter this time. "
            )

        prompt = (
            "Rewrite the Focus block to fit the required budget while preserving "
            "the most important active threads, decisions, and commitments-in-flight. "
            f"Target maximum token estimate: {self._token_budget}. "
            f"{retry_instruction}"
            "Output only rewritten focus text.\n\n"
            f"Current Focus:\n{content}"
        )
        result = self._language_model.chat(
            meta=meta,
            prompt=prompt,
            profile="quick",
        )
        if not result.ok or result.payload is None:
            raise FocusCompactionError("focus compaction request failed")

        payload = result.payload.value
        compacted_raw = getattr(payload, "text", None)
        if not isinstance(compacted_raw, str):
            raise FocusCompactionError("focus compaction returned invalid payload")

        compacted_text = compacted_raw.strip()
        if compacted_text == "":
            raise FocusCompactionError("focus compaction returned empty text")

        return _CompactionResult(
            content=compacted_text,
            token_count=estimate_token_count(compacted_text),
        )
