Instructions for working in this repo:
- Read `README.md`.
- Read `docs/manifesto.md`.
- Read `docs/architecture-doctrine.md`.
- Never modify `docs/manifesto.md`; if you think you need to, raise it as a question/suggestion for user modification.
- Ask clarifying questions when needed to resolve ambiguity or conflict.
- `'work-*/` directories:
  - Read-only inspection is allowed; writes are restricted.
  - These are transient agent/task management workspaces, not permanent project directories.
  - No work output should be stored in these directories.
  - Do not modify the contents (with the exception of `index.md`) unless instructed.
- Non-obvious architecture/design tradeoffs should be documented in an ADR.
- Do not generate documentation files (`.md`, etc.) unless instructed.

When modifying code:
- Adhere to SOLID principles when they improve clarity or testability.
- Bias toward cohesion and locality.
- Prefer domain-aligned code and prioritize clarity of intent.
- Optimize for clarity first; refactor to DRY once repetition is stable.
- Avoid clever tricks and elegant patterns when it sacrifices legibility or testability.
- Respect existing patterns and conventions, fall back to idiomatic standards.
- Every file/class/unit should have a complete and meaningful docblock/docstring.
- Prefer smaller composable units over larger monolithic ones.
- When designing or implementing functionality, consider how 3rd party dependencies (open source packages via gems, npm,
  pip, mods, etc) may reduce effort and save time.
- Prefer explicit errors and observable failure modes over silent recovery.
- Before adding new units, search existing code for logic that may be reused/refactored.
- When modifying existing units, write/modify tests as appropriate.
- When creating new units, design them to be tested, and write appropriate tests.
- Run relevant linting, type checking, tests, etc. after making changes to validate behavior.
- When tests fail, do not blindly modify the tests to make them pass. First, suspect that the SUT is flawed and assess
  the root cause of the failure.
- Remember: The goal is not that the tests pass, the goal is correct code which implements the provided scope, which
  _also_ has passing tests that exercise it to ensure resiliency in the face of future changes.
 
Whenever changes impact config files (`.env`, `config/*.{yml,json}`, etc.):
- Always modify `.sample` files in the course of your other work.
- Once your changes are complete, always request approval to modify the live/.gitignored files.
- When modifying the live/.gitignored files, always migrate the existing data to the new format.
- Never replace existing live/.gitignored config values with sample data.
- Never modify the live/.gitignored files without approval.
- Always report what changes were made to live/.gitignored files.

Test suites can be run using the helper `test.sh` script:
- including integration tests: `BRAIN_RUN_INTEGRATION=1 test.sh`
- generating a coverage report: `BRAIN_RUN_COVERAGE=1 test.sh`
- or both at the same time

