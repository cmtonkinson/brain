<!--
File: docs/policy-core.md
Purpose: Core policy vocabulary and defaults (autonomy, actions, capabilities, actors, channels, context).
-->
# Policy Core

## Purpose
Define the canonical vocabulary for autonomy, actions, capabilities, actors,
channels, and contextual conditions used by policy evaluation.

## Autonomy Levels (L0-L4)

### L0 -- Suggest Only
- Execution: propose/draft only; no side effects.
- Approval: explicit human initiation required.
- Reversibility: not applicable (no execution).
- Audit: log proposal intent.
- Examples: propose memory, suggest tasks, draft content.

### L1 -- Draft + Approval
- Execution: prepare draft or plan; block until approved.
- Approval: required before any side effect.
- Reversibility: required where feasible; otherwise remain L1 with strict review.
- Audit: log draft, approval decision, execution.
- Examples: send message, create calendar event, promote memory.

### L2 -- Bounded Automatic
- Execution: automatic within tight bounds.
- Approval: not required per execution.
- Reversibility: fully reversible and low risk.
- Audit: log action, scope, rollback details.
- Examples: tag notes, update metadata, mark tasks complete.

### L3 -- Automatic with Guardrails
- Execution: automatic with guardrails and monitoring.
- Approval: not required per action, but bounded by policy.
- Reversibility: preferred; otherwise include compensating controls.
- Audit: continuous logging and periodic review.
- Examples: recurring summaries, daily brief generation, watcher polling.

### L4 -- Restricted Autonomy (Future)
- Execution: high-trust autonomous actions in strict opt-in boundaries.
- Approval: explicit opt-in and policy enablement required.
- Reversibility: strong rollback and containment required.
- Audit: elevated, continuous audit.

## Action Taxonomy (Defaults)

| Action Class | Default Autonomy | Minimum Autonomy | Risk Notes |
| --- | --- | --- | --- |
| propose | L0 | L0 | Suggest-only; no execution. |
| memory.promote | L1 | L1 | Durable memory writes. |
| messaging.send | L1 | L1 | External side effects and attention impact. |
| scheduling.write | L1 | L1 | Creates future automation. |
| data.modify.reversible | L2 | L2 | Low risk if scoped and reversible. |
| data.delete.or.irreversible | L1 | L1 | Destructive; approval required. |
| external.read | L2 | L2 | Crosses trust boundary. |
| external.write | L1 | L1 | External mutation; approval required. |
| filesystem.write | L1 | L1 | Potentially destructive. |
| policy.modify | L1 | L1 | Highest trust changes. |

## Action to Capability Mapping

| Action Class | Required Capabilities | Notes |
| --- | --- | --- |
| propose | memory.propose | Suggest-only actions have no side effects. |
| memory.promote | memory.promote, obsidian.write | Durable memory writes. |
| messaging.send | messaging.send, attention.notify | Explicitly visible. |
| scheduling.write | scheduler.write, calendar.write, reminders.write | Scheduling writes. |
| data.modify.reversible | obsidian.write, filesystem.write (scoped) | Only when reversible. |
| data.delete.or.irreversible | filesystem.write, obsidian.write | Destructive operations. |
| external.read | web.fetch, github.read, blob.read | Untrusted inputs. |
| external.write | github.write, messaging.send | External mutation. |
| filesystem.write | filesystem.write | Local mutation. |
| policy.modify | policy.write | Authority changes. |

## Actor Categories and Ceilings

| Actor | Max Autonomy | Notes |
| --- | --- | --- |
| user | L3 | Human-initiated flows. |
| skill | L2 | Bounded, reversible by default. |
| scheduler | L2 | Low trust automation. |
| watcher | L2 | External triggers. |
| system | L2 | Maintenance actions remain bounded. |

Recommended capability scopes (defaults):
- user: allow most; policy.write requires explicit review.
- skill: only declared capabilities; deny policy.write, memory.promote unless approved.
- scheduler: allow scheduler.read/write, telemetry.emit, obsidian.read, vault.search, memory.propose;
  deny messaging.send, memory.promote, policy.write, filesystem.write.
- watcher: allow web.fetch, github.read, blob.read, ingest.normalize, obsidian.read, vault.search, memory.propose;
  deny messaging.send, memory.promote, policy.write, filesystem.write.
- system: allow telemetry.emit, scheduler.read/write, policy.read; deny policy.write unless approved.

## Channels

Canonical channels:
- signal
- cli
- webui
- scheduler
- api

Default actor channel rules:
- user: allow cli, webui, signal; deny scheduler unless approved.
- skill: inherit caller channel.
- scheduler: allow scheduler; deny signal and webui.
- watcher: allow api, scheduler; deny signal and webui.
- system: allow cli, scheduler; deny signal unless approved.

## Context Conditions (Current)

Supported conditions:
- channel
- actor
- rate_limit
- policy_tags
- autonomy_ceiling

Supported operators:
- equals
- in
- not_in
- lte / gte

Evaluation order:
1) channel allow/deny
2) actor allow/deny
3) capability allow/deny
4) autonomy ceiling
5) policy tags
6) rate limits

Missing context defaults to conservative behavior.

## Planned Conditions (Future)

- time window / quiet hours (Attention Router config)
- confidence thresholds (model metadata)
- failure rate (audit logs)
- environment mode (runtime config)
- historical trust signals (audit logs)
