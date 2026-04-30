Follow the instructions in @~/.config/agents/agents.md now.

Additional instructions for working in this specific project:
* @README.md
* @docs/*.md
* `python -m pytest ...` for targeted verification
* `ruff [format]` for linting / style enforcement
* `gmake test` for comprehensive basic checks - docs, lint, unit (takes ~12)
* `gmake test integration` for unit+integration tests (~40s)
* `gmake test-all` for full suite, incl. e2e smoke tests (~2m)
* This is a new, unpublished, unsupported project. The author is the only
  contributor, and isn't even a user yet. As such, when making changes:
    * Never keep old naming, docs, functionality, specs, or expectations as
  "legacy".
    * Never assume migrations or backwards compatibility are desired unless
      asked.
    * If an identifier changes, propagate that change throughout the project.
    * If code would be dead as a result, prune it; don't leave old paths "for
      compatibility."
    * Don't leave notes about what what things "used to" be called.
* Configuration parameters > module-level constants > magic scalars
* Configuration parameters should:
  * have a sane default
  * be shown in the appropriate `.yaml.sample` file
  * be shown in `docs/configuration.md`
* Do not hardcode prompts or prompt templates; all context assembly and
  manipulation must be done through InferenceRequest and its related objects.
  Only the LLM Adapter may flatten and serialize data for LLM API calls.

