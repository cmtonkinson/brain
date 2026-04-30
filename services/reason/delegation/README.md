# Delegation Service
Reason-system T2 service that owns the lifecycle of subagent invocations.
------------------------------------------------------------------------
## Responsibilities
* Persist and query the `delegation.invocation` row family.
* Atomically claim the oldest queued invocation for a Subagent Actor (uses
  `SELECT ... FOR UPDATE SKIP LOCKED`).
* Track per-turn token deltas and turn counts; enforce per-invocation budget
  ceilings (`max_turns`, `budget_tokens`).
* Reap wallclock-exceeded running invocations via a daemon sweeper.
* Cascade cancel from a parent invocation to all transitive children.
* Block in-process callers via `invoke_and_wait` / `wait` until terminal state.
------------------------------------------------------------------------
## Public API
| Method | Purpose |
|---|---|
| `invoke` | Queue one invocation; return its identifier. |
| `invoke_and_wait` | Queue and block until terminal state. |
| `wait` | Block on an existing invocation until terminal state. |
| `get_status` | Read current status projection (status, counters, timestamps). |
| `cancel` | Mark queued/running invocation `canceling`; cascade to descendants. |
| `claim_next_invocation` | Subagent Actor claim API. |
| `record_turn` | Per-turn checkpoint; increments counters, returns budget decision. |
| `finalize_invocation` | Apply terminal status; unblock waiters. |
------------------------------------------------------------------------
## Schema
One table: `delegation.invocation`. Columns capture the full invocation
contract: prompt, context refs, personality, tool allowlist, budget ceilings,
counters, claim metadata, and terminal fields.

`status` enum (string): `queued`, `running`, `succeeded`, `failed`,
`canceling`, `canceled`. `cancel_reason` enum (string): `manual`,
`budget_tokens`, `budget_turns`, `budget_wallclock`, `parent_canceled`,
`actor_lost`.
------------------------------------------------------------------------
## Cancellation
Cooperative checkpoints in the Subagent Actor loop:

1. Turn-start: actor calls `delegation.status` and aborts if `canceling`.
2. Post-Language: actor calls `delegation.record_turn` with token deltas. The
   service evaluates ceilings inline and returns `should_stop` plus a
   `cancel_reason` if breached.

Manual cancels and wallclock sweeps both flip the row to `canceling`; the
actor sees the change at its next checkpoint and finalizes the row as
`canceled` with the appropriate reason.
------------------------------------------------------------------------
## Public Ops
The `subagent-*` op family (under `ops/delegation/`) wraps these methods:

| Op | Service method |
|---|---|
| `subagent-sync` | `invoke_and_wait` |
| `subagent-async` | `invoke` |
| `subagent-wait` | `wait` |
| `subagent-status` | `get_status` |
| `subagent-cancel` | `cancel` |

Tool calls inside the loop run under the `subagent` channel and `subagent`
principal — distinct from the caller's identity, allowing narrower allowlists
at the policy layer.


------------------------------------------------------------------------
_End of Delegation Service README_
