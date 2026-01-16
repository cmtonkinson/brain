# Skill Discovery and Invocation

The agent discovers skills through the registry loader (`SkillRegistryLoader`), which reads
`config/skill-registry.json` and applies overlays. Ops are loaded from
`config/op-registry.json` and are only invoked through skills. The agent exposes:

- `list_skills` to list skills by status and capability.
- `run_skill` to execute a skill by name/version via the runtime wrapper.

Version selection rules:
- If a version is specified, the runtime resolves that exact version.
- If no version is provided and multiple versions exist, the runtime rejects the call and
  the agent must choose explicitly.

All invocations go through policy checks, schema validation, and the runtime adapter
appropriate to the skill entrypoint or op runtime.
