# Skill Test Harness

The harness allows running skills with mocks, without the agent or external services.

## Usage

- Instantiate `SkillTestHarness` with registry and capabilities paths.
- Provide adapters (e.g., `PythonSkillAdapter`) or mocks.
- Use `dry_run=True` to skip execution for side-effecting skills.

## Dry-Run Contract

Dry-run returns a `DryRunResult`:

```
{
  "dry_run": true,
  "skill": "create_note",
  "version": "1.0.0",
  "inputs": { ... },
  "side_effects": ["obsidian.write"]
}
```

No external calls are executed in dry-run mode.

## Mocks

Mocks live in `test/skills/mocks/` and include:
- `MockObsidianClient`
- `MockCodeModeManager`
- `MockSignalClient`

Use these to simulate external systems deterministically.
