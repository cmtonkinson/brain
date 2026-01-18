<!--
File: docs/policy-workflows.md
Purpose: Approval workflow, proposals, tokens, routing, tools, migration, trust signals.
-->
# Policy Workflows

## Approval Workflow (Phase Plan)

Phase 1: confirmed flag gating
- L1 or requires_review actions denied unless confirmed.
- Denials include reason codes.

Phase 2: proposals and routing
- Generate proposal artifacts.
- Route via Attention Router.
- Record approvals/rejections/expirations.
- Apply approval tokens scoped to action instance.

## Proposal Artifacts

Required fields:
- proposal_version
- proposal_id (deterministic hash)
- action entry name/version, action class, autonomy
- required capabilities
- reason_for_review
- context (actor/channel/trace_id/invocation_id)
- redactions
- timestamps (created_at, expires_at)

Redaction strategies: mask, hash, omit.

## Approval Tokens

- Scoped to action_id and actor.
- TTL required; expired or mismatched tokens deny execution.
- Prior-authorization tokens allowed only with explicit scope and audit.

## Routing and Outcomes

- Proposals routed through Attention Router (quiet hours, escalation).
- Approval records include approver_id, decision, timestamp, reason.
- Outcomes linked via trace_id.

## Tooling

### Documentation generator
- Command: poetry run python scripts/policy_doc_gen.py --output docs/policy.generated.md
- Fails closed on invalid registry/overlay data.

### Simulation tool
- Command: poetry run python scripts/policy_simulate.py --kind skill --name read_note
- Uses same evaluator; returns decision, reasons, metadata, precedence order.

### Conflict reporting
- Command: poetry run python scripts/policy_conflicts.py
- Reports overlaps (allow/deny) and conflicting overrides.

## Migration Plan (Standalone Policy File)

- Translate registry + overlays into policy file.
- Dual-read and compare decisions.
- Cut over only when parity achieved.
- Roll back by disabling policy file evaluation.

## Historical Trust Signals

- Derived from structured audit logs (approvals, outcomes, failures).
- Only suggest durable approvals; never auto-grant.
