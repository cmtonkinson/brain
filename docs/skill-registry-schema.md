# Skill Registry Schema (v2)

This document defines the canonical schema for the Brain OS skill registry. The registry
is the authoritative inventory of skills, their contracts, and required capabilities.
Ops are tracked in a separate registry, documented below.

## Skill Registry Format

The skill registry is Tier 0 data, versioned in the repo at
`config/skill-registry.json`. It is required for runtime startup, even when no
overlays are present.

The registry is stored as JSON (canonical) and validated by the Pydantic schema in
`src/skills/registry_schema.py`.

Top-level fields:
- `registry_version` (string, semver)
- `skills` (array of skill definitions)

## Skill Definition (Logic or Pipeline)

Required fields:
- `name` (string, snake_case)
- `version` (string, semver)
- `status` (`enabled` | `disabled` | `deprecated`)
- `description` (string)
- `kind` (`logic` | `pipeline`)
- `inputs_schema` (JSON Schema object)
- `outputs_schema` (JSON Schema object)
- `capabilities` (array of capability IDs)
- `autonomy` (string, `L0` | `L1` | `L2` | `L3`)
- `failure_modes` (array of failure mode objects)

Optional fields:
- `side_effects` (array of capability IDs; must be subset of `capabilities`)
- `policy_tags` (array of strings used by policy evaluation)
- `owners` (array of strings)
- `rate_limit` (object with `max_per_minute`)
- `redaction` (object with `inputs` and `outputs` lists)
- `deprecation` (metadata object, required when `status` is `deprecated`)

### Logic Skills

Logic Skills execute code and must declare explicit call targets.

Additional required fields:
- `entrypoint` (runtime descriptor)
- `call_targets` (array of skill/op references)

Entrypoints are runtime-agnostic pointers to the skill implementation:
- `runtime`: `python` | `http` | `script`
- `module` + `handler` for `python`
- `url` for `http`
- `command` for `script`

Call targets reference Skills and Ops by name and optional version.

### Pipeline Skills

Pipeline Skills are declarative call graphs with ordered steps. They do not use
an entrypoint.

Additional required fields:
- `steps` (ordered list of pipeline steps)

Pipeline capabilities are computed from dependency closures at load time. If a
capabilities list is provided, it must match the computed union.

Pipeline steps include:
- `id` (string, unique step identifier)
- `target` (skill/op reference)
- `inputs` (mapping of target input fields to pipeline inputs or prior step outputs)
- `outputs` (mapping of target output fields to named pipeline outputs)

### Deprecation Metadata

When a skill is deprecated, include:
- `deprecated`: true
- `replaced_by`: replacement skill name (optional)
- `removal_version`: semver release where removal is expected (optional)

### Failure Modes

Failure modes enumerate expected error codes for a skill:
- `code` (string, snake_case)
- `description` (string)
- `retryable` (boolean, default `false`)

## Versioning Rules

- Skill versions are semver. Breaking changes require a new major version.
- `registry_version` is semver and reflects schema revisions.
- Deprecations must be explicit and include migration notes.

## Example Registry (Valid)

```json
{
  "registry_version": "1.0.0",
  "skills": [
    {
      "name": "search_notes",
      "version": "1.0.0",
      "status": "enabled",
      "description": "Search notes in the Obsidian vault.",
      "kind": "logic",
      "inputs_schema": {
        "type": "object",
        "required": ["query"],
        "properties": {
          "query": {"type": "string"}
        }
      },
      "outputs_schema": {
        "type": "object",
        "required": ["results"],
        "properties": {
          "results": {"type": "array", "items": {"type": "string"}}
        }
      },
      "capabilities": ["obsidian.read", "vault.search"],
      "side_effects": [],
      "autonomy": "L1",
      "policy_tags": ["requires_review"],
      "owners": ["core"],
      "rate_limit": {"max_per_minute": 10},
      "entrypoint": {
        "runtime": "python",
        "module": "skills.search_notes",
        "handler": "run"
      },
      "call_targets": [
        {"kind": "op", "name": "obsidian_search", "version": "1.0.0"}
      ],
      "redaction": {
        "inputs": ["query"],
        "outputs": []
      },
      "failure_modes": [
        {
          "code": "search_failed",
          "description": "Search backend error.",
          "retryable": true
        }
      }
    }
  ]
}
```

## Pipeline Skill Example (Valid)

```json
{
  "registry_version": "2.0.0",
  "skills": [
    {
      "name": "summarize_note",
      "version": "1.0.0",
      "status": "enabled",
      "description": "Read a note and summarize it.",
      "kind": "pipeline",
      "inputs_schema": {
        "type": "object",
        "required": ["path"],
        "properties": {"path": {"type": "string"}}
      },
      "outputs_schema": {
        "type": "object",
        "required": ["summary"],
        "properties": {"summary": {"type": "string"}}
      },
      "capabilities": [],
      "autonomy": "L1",
      "steps": [
        {
          "id": "read",
          "target": {"kind": "skill", "name": "read_note", "version": "1.0.0"},
          "inputs": {"path": "$inputs.path"},
          "outputs": {"content": "$step.read.content"}
        },
        {
          "id": "summarize",
          "target": {"kind": "skill", "name": "summarize_text", "version": "1.0.0"},
          "inputs": {"text": "$step.read.content"},
          "outputs": {"summary": "$outputs.summary"}
        }
      ],
      "failure_modes": [
        {
          "code": "pipeline_failed",
          "description": "Pipeline execution failed.",
          "retryable": false
        }
      ]
    }
  ]
}
```

## Op Registry Format

Ops are stored in a separate Tier 0 registry at `config/op-registry.json`.

Top-level fields:
- `registry_version` (string, semver)
- `ops` (array of op definitions)

## Op Definition

Required fields:
- `name` (string, snake_case)
- `version` (string, semver)
- `status` (`enabled` | `disabled` | `deprecated`)
- `description` (string)
- `inputs_schema` (JSON Schema object)
- `outputs_schema` (JSON Schema object)
- `capabilities` (array of capability IDs)
- `autonomy` (string, `L0` | `L1` | `L2` | `L3`)
- `runtime` (`native` | `mcp` | `http` | `script`)
- `failure_modes` (array of failure mode objects)

Optional fields:
- `side_effects` (array of capability IDs; must be subset of `capabilities`)
- `policy_tags` (array of strings used by policy evaluation)
- `owners` (array of strings)
- `rate_limit` (object with `max_per_minute`)
- `redaction` (object with `inputs` and `outputs` lists)
- `deprecation` (metadata object, required when `status` is `deprecated`)

Runtime-specific metadata:
- `module` + `handler` for `native`
- `tool` for `mcp`
- `url` for `http`
- `command` for `script`

## Op Registry Example (Valid)

```json
{
  "registry_version": "1.0.0",
  "ops": [
    {
      "name": "obsidian_search",
      "version": "1.0.0",
      "status": "enabled",
      "description": "Search the Obsidian vault.",
      "inputs_schema": {
        "type": "object",
        "required": ["query"],
        "properties": {"query": {"type": "string"}}
      },
      "outputs_schema": {
        "type": "object",
        "required": ["results"],
        "properties": {"results": {"type": "array", "items": {"type": "string"}}}
      },
      "capabilities": ["obsidian.read", "vault.search"],
      "side_effects": [],
      "autonomy": "L1",
      "runtime": "native",
      "module": "skills.ops.obsidian",
      "handler": "search",
      "failure_modes": [
        {
          "code": "op_failed",
          "description": "Op execution failed.",
          "retryable": false
        }
      ]
    }
  ]
}
```

## Capability Source of Truth

Capability IDs must exist in `config/capabilities.json` and follow the
`domain.verb` naming convention.
