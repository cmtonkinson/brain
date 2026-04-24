# embedding-upsert-document-batch

Persist a batch of embedding vectors for chunk and spec pairs.

## Parameters

| Name | Type | Required | Default | Description |
|------|------|----------|---------|-------------|
| `items` | `list[UpsertEmbeddingVectorInput]` | yes | — | Batch of chunk/spec/vector inputs to persist. |

## Returns

`list[EmbeddingRecord]` — persisted embedding materialization records.
