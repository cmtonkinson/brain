"""Summarize and rank batched signals before delivery."""

from __future__ import annotations

import logging
from dataclasses import dataclass

from sqlalchemy.orm import Session

from models import AttentionBatch, AttentionBatchItem, AttentionBatchSummary, BatchedSignal

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class RankedItem:
    """Ranked batch item linked to the original signal."""

    signal_reference: str
    rank: int


@dataclass(frozen=True)
class BatchSummaryResult:
    """Summary result for a batch."""

    decision: str
    batch_id: int
    summary: str | None
    ranked_items: list[RankedItem]
    delivery_channel: str | None
    error: str | None = None


def summarize_batch(session: Session, batch_id: int) -> BatchSummaryResult:
    """Summarize and rank batched signals for the given batch."""
    try:
        batch = session.get(AttentionBatch, batch_id)
        if batch is None:
            raise ValueError(f"Batch not found: {batch_id}")
        signals = (
            session.query(BatchedSignal)
            .filter(BatchedSignal.batch_id == batch_id)
            .order_by(BatchedSignal.created_at.desc())
            .all()
        )
        summary_text = _build_summary(batch, signals)
        ranked_items = _store_ranked_items(session, batch_id, signals)
        summary = AttentionBatchSummary(batch_id=batch_id, summary=summary_text)
        session.add(summary)
        session.flush()
        return BatchSummaryResult(
            decision="DELIVER",
            batch_id=batch_id,
            summary=summary_text,
            ranked_items=ranked_items,
            delivery_channel="digest",
        )
    except Exception as exc:
        logger.exception("Batch summarization failed for batch_id=%s", batch_id)
        return BatchSummaryResult(
            decision="DEFER",
            batch_id=batch_id,
            summary=None,
            ranked_items=[],
            delivery_channel=None,
            error=str(exc),
        )


def _build_summary(batch: AttentionBatch, signals: list[BatchedSignal]) -> str:
    """Construct a simple summary for a batch."""
    count = len(signals)
    topic_label = f" ({batch.topic}/{batch.category})" if batch.topic else ""
    return f"Batch {batch.id}{topic_label}: {count} items."


def _store_ranked_items(
    session: Session, batch_id: int, signals: list[BatchedSignal]
) -> list[RankedItem]:
    """Persist ranked items linked to their original signals."""
    ranked: list[RankedItem] = []
    for idx, signal in enumerate(signals, start=1):
        item = AttentionBatchItem(
            batch_id=batch_id,
            signal_reference=signal.signal_reference,
            rank=idx,
        )
        session.add(item)
        ranked.append(RankedItem(signal_reference=signal.signal_reference, rank=idx))
    session.flush()
    return ranked
