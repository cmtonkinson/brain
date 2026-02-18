<!--
File: docs/policy-runtime.md
Purpose: Policy evaluator contract, precedence, storage/reload, metadata, audit/explainability/observability.
-->
# Policy Runtime

## Evaluator Contract

Inputs:
- actor
- channel
- entry (skill/op runtime entry)
- allowed_capabilities
- max_autonomy
- confirmed
- dry_run

Outputs (PolicyDecision):
- allowed (bool)
- reasons (list of reason codes)
- metadata (normalized policy metadata)

Dry-run returns the same decision object without side effects.

## Precedence and Conflict Resolution

- Base registries load first.
- Overlays apply in canonical order; later overrides replace earlier values.
- Deny overrides allow.
- If allow list exists and context not included, deny.
- If multiple constraints conflict, choose the most restrictive outcome.

Versioning:
- registry_version and overlay_version are required (semver).
- Unsupported versions fail closed.

## Storage and Reload

Base registries:
- config/skill-registry.json
- config/op-registry.json
- config/capabilities.json

Overlays:
- config/skill-registry.local.yml
- ~/.config/brain/skill-registry.local.yml
- config/op-registry.local.yml
- ~/.config/brain/op-registry.local.yml

Validation:
- schema validation (registry + overlay)
- capability IDs must exist in config/capabilities.json
- side_effects must be subset of capabilities

Reload:
- reload on file mtime change
- invalid data fails closed and keeps last known-good view

## Policy Metadata Normalization

Normalized fields:
- policy.context.actor
- policy.context.channel
- policy.context.max_autonomy
- policy.context.confirmed
- policy.context.dry_run
- policy.entry.autonomy
- policy.entry.tags
- policy.channels.allow
- policy.channels.deny
- policy.actors.allow
- policy.actors.deny
- policy.rate_limit.max_per_minute

## Audit Logging

Required fields:
- trace_id
- invocation_id
- entry_name, entry_version
- actor, channel
- capabilities, side_effects
- entry_autonomy, requested_autonomy
- decision, reason_codes
- policy_metadata
- duration_ms

Redaction:
- apply registry redaction rules to inputs/outputs
- never log secrets or credentials

## Explainability

Human-readable explanations must include:
- decision
- summary
- ordered reasons
- entry name/version
- actor/channel
- autonomy (entry and context ceiling)
- trace_id

Reason codes map to clear, concise messages and avoid payload leakage.

## Observability

Structured logs must be queryable by:
- action type
- actor
- policy metadata
- outcome

Correlation uses trace_id across evaluation, approval, and execution.
