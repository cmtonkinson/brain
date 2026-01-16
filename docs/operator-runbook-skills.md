# Operator Runbook: Skill Registry

This runbook covers managing the skill registry, overlays, and validation tooling.

## Updating the Registry

1. Edit `config/skill-registry.json` to add or update skills.
2. Keep capability IDs aligned with `config/capabilities.json`.
3. Validate changes:
   - `scripts/validate_skill_registry.py`
4. Commit registry updates as Tier 0 data (versioned in the repo).

## Overlays

Overlays are optional and only adjust operational controls:
- `config/skill-registry.local.yml`
- `~/.config/brain/skill-registry.local.yml`

Overlays can change `status`, `autonomy`, `rate_limit`, `channels`, and `actors` only.
They must not change contracts or capabilities.

## Policy and Approvals

- Write skills require explicit approval and `allow_capabilities` grants.
- Deprecations must include replacement notes in the registry.

## Validation and Troubleshooting

- `scripts/validate_skill_registry.py` validates registry + overlays.
- Use the unit tests under `test/skills/` for mocked skill runs.
