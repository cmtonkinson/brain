# language-model-embed-chunks

Generate embedding vectors for a batch of text chunks.

## Parameters

| Name | Type | Required | Default | Description |
|------|------|----------|---------|-------------|
| `texts` | `list[str]` | yes | — | The text chunks to embed. |
| `profile` | `EmbeddingProfile` | no | `document_embedding` | Embedding profile override (`document_embedding` or `capability_embedding`). |

## Returns

`list[EmbeddingVector]` — one embedding vector result per input text chunk.
