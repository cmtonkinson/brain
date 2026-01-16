# Operator Runbook: Skill Registry

This runbook covers managing the skill and op registries, overlays, and validation tooling.

## Updating the Registry

1. Edit `config/skill-registry.json` to add or update skills.
2. Edit `config/op-registry.json` to add or update ops.
3. Keep capability IDs aligned with `config/capabilities.json`.
4. Validate changes:
   - `scripts/validate_skill_registry.py`
5. Commit registry updates as Tier 0 data (versioned in the repo).

## Overlays

Overlays are optional and only adjust operational controls:
- `config/skill-registry.local.yml`
- `~/.config/brain/skill-registry.local.yml`
- `config/op-registry.local.yml`
- `~/.config/brain/op-registry.local.yml`

Overlays can change `status`, `autonomy`, `rate_limit`, `channels`, and `actors` only.
They must not change contracts or capabilities.

## Policy and Approvals

- Write skills require explicit approval and `allow_capabilities` grants.
- Ops are only invoked through skills (no direct agent access).
- Deprecations must include replacement notes in the registry.

## Validation and Troubleshooting

- `scripts/validate_skill_registry.py` validates skill + op registries and overlays.
- Use the unit tests under `test/skills/` for mocked skill runs.
