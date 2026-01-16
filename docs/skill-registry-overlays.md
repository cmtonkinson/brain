# Skill and Op Registry Overlays

This document defines how environment-specific overlays are applied to the skill
and op registries. Overlays are optional and only adjust operational controls;
they never change contracts.

## Canonical Paths

Base registries (required, Tier 0):
- `config/skill-registry.json`
- `config/op-registry.json`

Optional overlays (loaded in order, later wins):
1. `config/skill-registry.local.yml` (repo-local overrides for development)
2. `~/.config/brain/skill-registry.local.yml` (host-specific overrides)
3. `config/op-registry.local.yml` (repo-local op overrides)
4. `~/.config/brain/op-registry.local.yml` (host-specific op overrides)

The base registries must always load, even when no overlays are present.

## Overlay Scope

Overlays may only change the following fields per skill:
- `status` (`enabled` | `disabled`)
- `autonomy` (`L0` | `L1` | `L2` | `L3`)
- `rate_limit` (`max_per_minute`)
- `channels.allow` (list of channel IDs allowed to invoke the skill)
- `channels.deny` (list of channel IDs denied from invoking the skill)
- `actors.allow` (list of actor IDs allowed to invoke the skill)
- `actors.deny` (list of actor IDs denied from invoking the skill)

Overlays MUST NOT change:
- contracts (inputs/outputs)
- capabilities
- entrypoints or runtimes
- descriptions or names
- ownership

The same rules apply to op overlays, targeting ops by name and optional version.

## Merge Rules

- Load the base registry first.
- Apply overlays in the canonical order above.
- Each overlay entry targets a skill by `name` and optional `version`.
- If `version` is omitted, the override applies to all versions of that skill.
- Later overlays replace earlier values for the same field.
- Lists are replaced, not merged.

## Overlay Format (Skills)

```yaml
overlay_version: "1.0.0"
overrides:
  - name: search_notes
    version: "1.0.0"
    status: disabled
    autonomy: L0
    rate_limit:
      max_per_minute: 2
    channels:
      allow: ["signal"]
      deny: ["email"]
    actors:
      allow: ["user", "brain"]
      deny: ["celery"]
```

## Overlay Format (Ops)

```yaml
overlay_version: "1.0.0"
overrides:
  - name: obsidian_search
    version: "1.0.0"
    status: enabled
    autonomy: L1
    rate_limit:
      max_per_minute: 10
```

## Notes

- Channel IDs are implementation-defined (e.g., `signal`, `cli`, `scheduler`).
- Actor IDs are implementation-defined (e.g., `user`, `brain`, `celery`).
- Policy can further restrict execution even when overlays allow it.

## Migration Guidance

If you previously used a single `skill-registry.local.yml`, split overrides into:
- `config/skill-registry.local.yml` for skill overrides
- `config/op-registry.local.yml` for op overrides

Copy existing overrides into the matching file based on whether the entry targets
a skill or an op. Keep overlay versions unchanged unless the schema changes.
