# Skill Registry Schema

This document defines the canonical schema for the Brain OS skill registry. The registry
is the authoritative inventory of skills, their contracts, and required capabilities.

## Format

The base registry is Tier 0 data, versioned in the repo at `config/skill-registry.json`.
It is required for runtime startup, even when no overlays are present.

The registry is stored as JSON (canonical) and validated by the Pydantic schema in
`src/skills/registry_schema.py`.

Top-level fields:
- `registry_version` (string, semver)
- `skills` (array of skill definitions)

## Skill Definition

Required fields:
- `name` (string, snake_case)
- `version` (string, semver)
- `status` (`enabled` | `disabled` | `deprecated`)
- `description` (string)
- `inputs_schema` (JSON Schema object)
- `outputs_schema` (JSON Schema object)
- `capabilities` (array of capability IDs)
- `autonomy` (string, `L0` | `L1` | `L2` | `L3`)
- `entrypoint` (runtime descriptor)
- `failure_modes` (array of failure mode objects)

Optional fields:
- `side_effects` (array of capability IDs; must be subset of `capabilities`)
- `policy_tags` (array of strings used by policy evaluation)
- `owners` (array of strings)
- `rate_limit` (object with `max_per_minute`)
- `redaction` (object with `inputs` and `outputs` lists)
- `deprecation` (metadata object, required when `status` is `deprecated`)

### Entrypoint

Entrypoints are runtime-agnostic pointers to the skill implementation:
- `runtime`: `python` | `mcp` | `http` | `script`
- `module` + `handler` for `python`
- `tool` for `mcp`
- `url` for `http`
- `command` for `script`

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

## Capability Source of Truth

Capability IDs must exist in `config/capabilities.json` and follow the
`domain.verb` naming convention.
