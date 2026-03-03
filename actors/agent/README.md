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
_End of Brain Agent README_
