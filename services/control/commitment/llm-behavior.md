# Deferred LLM Behavior
This note captures the LLM-backed commitment behavior intentionally deferred from the lifecycle-first migration so the product intent is preserved while the native service core stabilizes.

------------------------------------------------------------------------
## Deferred Behaviors
- LMS-backed dedupe proposals for candidate or direct creation flows
- LMS-backed extraction of commitment candidates from ingestion outputs
- LMS-backed review-summary generation for weekly review delivery

------------------------------------------------------------------------
## Required Boundaries
- All model access must route through `LanguageModelService`.
- Core lifecycle, repository, and transition logic must remain independent of LMS availability.
- Ingestion-derived extraction must enter Commitment Service through the explicit candidate-intake boundary, not hooks or hidden callbacks.
- Review delivery formatting may consume LMS-generated summaries later, but review run/item persistence must remain deterministic and independent of that summary.

------------------------------------------------------------------------
## Expected Future Integration Points
- `ingest_commitment_candidate(...)`: optional pre-step that calls LMS to score or structure extracted candidate commitments before proposal persistence.
- `create_commitment(...)`: optional dedupe stage that calls LMS and converts a high-confidence duplicate signal into a persisted proposal.
- `deliver_review(...)`: optional summary-generation step that produces concise operator-facing prose from already-persisted review runs and items.

------------------------------------------------------------------------
## What To Preserve
- Dedupe should remain proposal-based, not automatic merge or silent suppression.
- Extraction should remain probabilistic and confidence-aware.
- Review summarization should remain additive presentation logic over persisted authoritative review data.

------------------------------------------------------------------------
_End of Deferred LLM Behavior_
