# language-model-embed-chunks

Generate embedding vectors for a batch of text chunks.

## Parameters

| Name | Type | Required | Default | Description |
|------|------|----------|---------|-------------|
| `texts` | `list[str]` | yes | — | The text chunks to embed. |
| `profile` | `EmbeddingProfile` | no | `embedding` | Embedding profile override. |

## Returns

`list[EmbeddingVector]` — one embedding vector result per input text chunk.
