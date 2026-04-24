# ingestion-advance

Advance one ingestion from a named stage through the remainder of the pipeline.

## Parameters

- `ingestion_id`: ingestion identifier to advance
- `from_stage`: first stage to consider
- `force_target`: re-run the target stage even if it already succeeded

## Returns

The updated ingestion record after orchestration stops or reaches completion.
