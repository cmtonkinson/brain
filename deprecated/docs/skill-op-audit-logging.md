# Skill & Op Audit Logging

This document defines the required audit fields and redaction behavior for
Skill and Op executions. It also documents the intentional differences between
Skill and Op audit payloads.

## Required Fields

Both Skill and Op audit events must include:
- trace_id
- span_id
- status
- duration_ms
- actor
- channel
- invocation_id
- parent_invocation_id
- capabilities
- side_effects
- inputs
- outputs
- error
- policy_reasons
- policy_metadata

## Skill Audit Payload

Skill audit records include:
- skill (skill name)
- version (skill version)

Skill audit events are emitted with the log message `skill_audit`.

## Op Audit Payload

Op audit records include:
- op (op name)
- version (op version)

Op audit events are emitted with the log message `op_audit`.

## Redaction

Both Skill and Op audit events must apply redaction before logging.
Redaction fields are defined in the registry `redaction` section for the
corresponding Skill or Op and applied independently to inputs and outputs.

## Intentional Differences

- Skill audit records use the `skill` field; Op audit records use the `op` field.
- Skill and Op events may use different redaction settings, reflecting
  their own input/output schemas.
