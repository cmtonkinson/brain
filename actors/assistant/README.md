# Brain Assistant
The Brain Assistant is the long-lived T3 actor process that:
* long-polls Relay inbound for inbound operator instructions
* uses Recall to assemble per-turn context
* uses the Brain SDK as its only access path into Core
* executes Ops as model tools
* records finalized responses back into Recall

------------------------------------------------------------------------
## Turn Execution Model
For each inbound operator instruction, the Agent uses two separate layers of
context.

### 1. Cross-turn memory from Recall
The Agent sends the new inbound message to `memory/assemble_context`.

Recall appends that inbound turn to the session and returns the authoritative
session context block:
* focus
* recent conversation summary
* recent dialogue turns
* reference snippets

This is the durable cross-turn conversational state.

### 2. Turn-local orchestration state
The Agent assembles the canonical inference request for Language. That request is
provider-agnostic and contains:
* system blocks (assistant persona, operator profile, instructions)
* Recall-owned `memory_context`
* current operator message
* available tools
* ordered intra-turn live events (assistant text, tool calls, tool results)
* controls and cache hints

Within that single turn, the model may:
* request one or more tool calls
* receive tool results
* request additional tool calls
* eventually return a final response

That back-and-forth is temporary. It exists only for the duration of the
current turn and is not the same thing as the long-lived conversation history
stored by Recall.

In other words:
* Recall owns durable cross-turn memory
* the Agent runtime owns the full inference request assembly and the ephemeral
  intra-turn tool loop

### Turn Finalization
After the model returns a final answer, the Agent sends that outbound response
to `memory/record_response` so the turn is persisted into Recall session history.


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
Every intra-turn Sonnet request is lowered from one canonical inference request.
At Anthropic wire level the dominant sections are:

```
[tools array]  ← top-level, before messages; ~1,400-7,000 tok depending on active set
[system blocks]  ← assistant persona + operator profile + instructions
[memory/current-turn context]  ← Recall context + operator instruction; stable per turn
[live events]  ← assistant text + tool-call / tool-result exchanges; grows with each hop
```

The operator's actual instruction is typically under 100 tokens. The dominant
costs are Recall context (~1,400 tok, fixed), tool definitions (~350-1,750 tok,
fixed once stabilized), and accumulated tool results (unbounded, the main risk).

### Prompt caching
#### Anthropic
Anthropic prompt caching is applied via `CachePoint` markers in the message
history. The cache key is a hash of the exact byte sequence from position 0 up
to the breakpoint — any change to content before a breakpoint invalidates
everything after it.

Caching is priced at a 1.25x write premium and a 0.10x read rate relative to
normal input cost. Anthropic also permits at most four `cache_control`
breakpoints in one request, so the runtime must treat them as a scarce resource
and never emit more than four.

We express `CachePoint` breakpoints here as `CP0` through `CP3`.

**CP0** is the static prefix cachepoint. It covers the stable prompt prefix:
system blocks, the initial Recall snapshot framing, and any other byte-stable
context shared across intra-turn hops. This prefix is worth caching
unconditionally as long as the tool array remains stable.

**CP1-CP3** are optional rolling cachepoints for deep intra-turn loops. They
should be chosen by marginal value, not by a fixed "every N hops" rule. If
$\Delta T(i)$ is the uncached token growth since the prior retained cachepoint
and $E[R(i)]$ is the expected number of future cache reuses for that extended
prefix, then the decision rule is:

$$
\mathrm{Score}(i) = \Delta T(i) \times (0.90 E[R(i)] - 0.25)
$$

This comes directly from Anthropic's 5-minute pricing: each candidate
cachepoint pays a `0.25x` write premium up front and saves `0.90x` of base
input cost on each future reuse. In practice this means:
* keep `CP0` always
* only place `CP1`-`CP3` when the uncached delta is large enough and another
  identical follow-up hop is likely
* when the request would exceed Anthropic's 4-point limit, retain `CP0` and the
  highest-value recent rolling points, dropping older lower-value ones first

**Tool array stability is a prerequisite for `CP0`.** If the active tool set
changes between hops — for example due to dynamic op discovery — the
cached prefix no longer matches and the value of that prefix cache is reset. The
tool list should therefore be frozen after the first intra-turn call.

#### OpenAI
OpenAI applies prompt caching automatically for exact matched prefixes once the
prompt reaches 1,024 tokens, with cache hits growing in 128-token increments.
Caches are typically retained for 5-10 minutes of inactivity and are always
removed within one hour of the last use.

OpenAI cached-input pricing is model-specific rather than a single global
multiplier. For example, the GPT-4o family is priced at a 50% cached-input
discount, while GPT-4.1 cached input is priced at 25% of normal input cost. The
same prompt-structuring rule applies: place static prefix material first and
volatile per-turn content last.

### Tool result compression
The primary mechanism for controlling token amplification is normalization of
tool results before they enter the message history. This is implemented at the
tool boundary, not inside the LLM loop, and applies to every `ToolReturnPart`
before that result can be sent back to the primary model.

The normalization boundary has exactly three outcomes:
* `pass_through` — the raw tool result is already small enough to keep
* `compress` — a secondary Haiku call rewrites the raw result to the minimum
  display-safe content needed for the stated intent
* `truncate` — the raw result is clipped to a hard ceiling when compression is
  not applicable

This means the primary model never sees an unbounded raw tool payload once the
normalization boundary has run. Sonnet's context window receives only the
normalized display content; the full raw result is not allowed to accumulate
across intra-turn hops.

Haiku compression calls are stateless by default. Each receives only:
* tool name
* call mode
* response detail / intent
* raw tool output

They do not share Sonnet's context window, cannot call tools themselves, and
cannot invalidate Sonnet's prompt-cache prefix with unrelated conversational
state.

**Call mode tagging.** Tool definitions include an optional `call_mode`
parameter (`"decide"` or `"explore"`) that Sonnet populates at call time:
* `decide` — Sonnet knows what it is looking for; Haiku can compress
  aggressively against the stated intent.
* `explore` — Sonnet is orienting; large results truncate to the hard ceiling
  without LLM compression since downstream relevance is not yet known.

An optional `response_detail` parameter lets Sonnet state its specific intent,
giving Haiku precise guidance on what to preserve during compression.

The runtime, not the model, decides which normalization path applies. The
decision is based on:
* tool name
* raw result size
* `call_mode`
* `response_detail`
* the configured compression and truncation thresholds

### History processor
Both caching and compression concerns are applied in a PydanticAI
`history_processors` function registered on the `Agent` at construction time.
This function runs before every intra-turn LLM request and is responsible for:
* placing `CachePoint` markers (`CP0` through `CP3`)
* normalizing every `ToolReturnPart` through the mandatory
  `pass_through` / `compress` / `truncate` boundary
* ensuring only normalized display content is returned to the primary model

### Tool return audit logging
Every normalized tool result produces one structured agent log record. The
record includes:
* `tool_name`
* `tool_call_id`
* `tool_input`
* `raw_output`
* `display_output`
* `normalization_kind`
* `raw_char_count`
* `final_char_count`
* `compressed_by_model`
* `compressed_by_provider`

This makes the full tool-return path inspectable after the fact:
* what the primary model asked for
* what the tool actually returned
* how the runtime transformed that result before reuse
* which secondary model performed compression when compression occurred


------------------------------------------------------------------------
_End of Brain Assistant README_
