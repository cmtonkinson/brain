# Skill Registry Overlays

This document defines how environment-specific overlays are applied to the skill registry.
Overlays are optional and only adjust operational controls; they never change contracts.

## Canonical Paths

Base registry (required, Tier 0):
- `config/skill-registry.json`

Optional overlays (loaded in order, later wins):
1. `config/skill-registry.local.yml` (repo-local overrides for development)
2. `~/.config/brain/skill-registry.local.yml` (host-specific overrides)

The base registry must always load, even when no overlays are present.

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
- entrypoints
- descriptions or names
- ownership

## Merge Rules

- Load the base registry first.
- Apply overlays in the canonical order above.
- Each overlay entry targets a skill by `name` and optional `version`.
- If `version` is omitted, the override applies to all versions of that skill.
- Later overlays replace earlier values for the same field.
- Lists are replaced, not merged.

## Overlay Format

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

## Notes

- Channel IDs are implementation-defined (e.g., `signal`, `cli`, `scheduler`).
- Actor IDs are implementation-defined (e.g., `user`, `brain`, `celery`).
- Policy can further restrict execution even when overlays allow it.
