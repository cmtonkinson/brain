# Brain Agent
The Brain Agent is the long-lived L2 actor process that:
- long-polls Switchboard for inbound operator instructions
- uses MAS to assemble per-turn context
- uses the Brain SDK as its only access path into Core
- executes Capabilities as model tools
- records finalized responses back into MAS

------------------------------------------------------------------------
## Turn Execution Model
For each inbound operator instruction, the Agent uses two separate layers of
context.

### 1. Cross-turn memory from MAS
The Agent sends the new inbound message to `memory/assemble_context`.

MAS appends that inbound turn to the session and returns the authoritative
session context block:
- profile
- focus
- prior dialogue
- any compaction summaries
- reference snippets

This is the durable cross-turn conversational state.

### 2. Turn-local orchestration state
The Agent formats the MAS context plus the new inbound message into the current
turn prompt for inference.

Within that single turn, the model may:
- request one or more tool calls
- receive tool results
- request additional tool calls
- eventually return a final response

That back-and-forth is temporary. It exists only for the duration of the
current turn and is not the same thing as the long-lived conversation history
stored by MAS.

In other words:
- MAS owns durable cross-turn memory
- the Agent runtime owns only the ephemeral intra-turn tool loop

### Turn Finalization
After the model returns a final answer, the Agent sends that outbound response
to `memory/record_response` so the turn is persisted into MAS session history.


------------------------------------------------------------------------
## Intra-Turn Token Budget Management
Within a single turn the Agent may make several sequential LLM calls to Sonnet
as it works through tool calls. Each call re-sends the full accumulated context
from scratch — there is no implicit continuity between intra-turn requests.
Left unmanaged, this causes two problems:

1. **Token amplification.** A large tool result (e.g. a vault search returning
   tens of thousands of characters) gets re-sent verbatim on every subsequent
   intra-turn call, multiplying its cost by the number of hops.
2. **Rate limit exhaustion.** Anthropic enforces a per-model TPM limit. A single
   turn with a few large tool results and several hops can exhaust the 30k TPM
   Sonnet allowance on its own.

### Context window structure per call
Every intra-turn Sonnet request contains these components, in order:

```
[tools array]  ← top-level, before messages; ~1,400-7,000 tok depending on active set
[system-prompt]  ← ~70 tok, static
[user-prompt]    ← MAS context + operator instruction; ~1,400 tok, stable per turn
[tool-call / tool-return pairs]  ← grows with each hop; returns can be very large
```

The operator's actual instruction is typically under 100 tokens. The dominant
costs are MAS context (~1,400 tok, fixed), tool definitions (~350-1,750 tok,
fixed once stabilized), and accumulated tool results (unbounded, the main risk).

### Prompt caching
Anthropic prompt caching is applied via `CachePoint` markers in the message
history. The cache key is a hash of the exact byte sequence from position 0 up
to the breakpoint — any change to content before a breakpoint invalidates
everything after it.

Two-tier strategy:

**Tier 1 — static, set once per turn.**
Placed after the first `ModelRequest` (system prompt + MAS context + user
prompt). This prefix is byte-stable across all intra-turn hops as long as the
tool array does not change. Cost: one cache write (125% of base) on the first
hop, then cache reads (10% of base) on all subsequent hops.

**Tier 2 — dynamic, placed when a turn runs deep.**
Placed after accumulated tool exchanges once hop count or token usage crosses a
threshold. Advances forward each hop: prior content is read from cache at 10%,
only the new delta is written at 125%.

**Tool array stability is a prerequisite for Tier 1 caching.** If the active
tool set changes between hops — e.g. due to dynamic capability discovery — the
tools array hash changes and the Tier 1 cache is invalidated. The tool list
should be frozen after the first intra-turn call.

### Tool result compression
The primary mechanism for controlling token amplification is compression of
large tool results before they enter the message history. This is implemented
at the tool boundary, not inside the LLM loop.

When a tool returns a result exceeding a size threshold, a secondary Haiku call
compresses it before the result is returned to Sonnet as a `ToolReturnPart`.
Sonnet's context window sees only the summary; the raw result is never
accumulated across hops.

Haiku compression calls are stateless by default — each receives only the raw
tool result and enough intent context to guide summarization. They do not share
Sonnet's context window and cannot bust Sonnet's cache.

**Call mode tagging.** Tool definitions include an optional `call_mode`
parameter (`"decide"` or `"explore"`) that Sonnet populates at call time:
- `decide` — Sonnet knows what it is looking for; Haiku can compress
  aggressively against the stated intent.
- `explore` — Sonnet is orienting; full result is passed through (or truncated
  only) since downstream relevance is not yet known.

An optional `response_detail` parameter lets Sonnet state its specific intent,
giving Haiku precise guidance on what to preserve during compression.

Tools known to produce large results safely compressible regardless of mode
(e.g. `vault-list-files`, capability discovery) may be flagged as always
eligible for compression in their capability definition.

### History processor
Both caching and compression concerns are applied in a PydanticAI
`history_processors` function registered on the `Agent` at construction time.
This function runs before every intra-turn LLM request and is responsible for:
- placing `CachePoint` markers (Tier 1 and Tier 2)
- enforcing a hard char ceiling on `ToolReturnPart` content (truncation
  fallback when Haiku compression is not applicable)
- evicting or summarizing stale tool exchanges when context grows too large


------------------------------------------------------------------------
_End of Brain Agent README_
