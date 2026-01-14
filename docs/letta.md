## Letta (MemGPT) integration

### What it does
- Runs as a separate service (`letta/letta:latest`) on port `8283`.
- Uses Ollama for both LLM and embeddings (configured via env).
- Uses Qdrant via tool calls to search the vault embeddings.
- Lets Letta manage memory on its side while the agent can still do direct semantic search.

### Required env vars
Set these in `.env`:
- `LETTA_BASE_URL` (for in-network containers: `http://letta:8283`)
- `LETTA_SERVER_PASSWORD` (required when `SECURE=true`)
- `LETTA_AGENT_NAME` (default `brain`)
- `LETTA_MODEL` (example: `ollama/llama3.1:8b`)
- `LETTA_EMBED_MODEL` (example: `ollama/mxbai-embed-large:latest`)
- `LETTA_BOOTSTRAP_ON_START` (optional, `true` to auto-bootstrap on agent start)

### Bootstrapping
Bootstrapping registers custom tools and creates a Letta agent if missing.

Run once:
```bash
docker-compose exec agent python src/letta_bootstrap.py
```

What it does:
- Creates the `search_vault` tool (semantic search in Qdrant)
- Creates the `read_note` tool (read full note via Obsidian Local REST)
- Creates a Letta agent named `LETTA_AGENT_NAME` with the tools attached

When you need it:
- First time you bring Letta up
- After changing tool code in `src/letta_tools/*`
- After changing `LETTA_AGENT_NAME`, `LETTA_MODEL`, or `LETTA_EMBED_MODEL`

When you do **not** need it:
- On every restart (unless you changed any of the above)

### Maintenance notes
- Letta persists its own state in `./data/letta` (its internal Postgres).
- Qdrant storage remains in `./data/qdrant`.
- Indexing still runs via the existing indexer and updates Qdrant.
- The agent still has a direct `search_vault_embeddings` tool; Letta uses its own tool.
- When Letta is configured (`LETTA_BASE_URL` + `LETTA_SERVER_PASSWORD`), the agent routes responses through Letta by default.

### Troubleshooting
- If Letta refuses requests: verify `LETTA_SERVER_PASSWORD` and `SECURE=true`.
- If tools are missing: re-run bootstrap.
- If embeddings mismatch: verify `OLLAMA_URL` and `OLLAMA_EMBED_MODEL` for both agent and Letta.
