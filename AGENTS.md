When working in this repo:
- Read `README.md`.
- Read `docs/manifesto.md`.
- Read `docs/architecture-doctrine.md`.
- Never modify `docs/manifesto.md`; if you think you need to, raise it as a question/suggestion for user modification.
- Ask clarifying questions when needed.
- Never create JSONB fields, or string/text fields meant to hold JSON data, in the database without:
  - A very good rationale.
  - Clearly and explicitly explaining why you believe it is justfied.
  - Explicit user approval.
- `'work-*/` directories:
  - These are transient agent/task management workspaces.
  - These are not permanent project directories.
  - No work output should be stored in these directories.
  - Do not modify the contents of these directories (with the exception of `index.md`) unless explicitly instructed to
    do so.

When modifying code:
- Prefer DRY designs and adhere to SOLID principles when reasonable.
- Prefer domain-aligned code and prioritize clarity of intent.
- Avoid clever tricks and elegant patterns when it sacrifices legibility or testability.
- Bias toward cohesion and locality.
- Respect existing patterns and conventions, fall back to idiomatic standards.
- Every file/class/unit should have a complete docblock/docstring.
- Prefer smaller composable units over larger monolithic ones.
- When designing or implementing functionality, consider how 3rd party dependencies (open source packages via gems, npm,
  pip, mods, etc) may reduce effort and save time.
- Code defensively; assume failure; assume invalid input.
- Before adding new units, search existing code for logic that may be reused/refactored.
- When modifying existing untis, write/modify tests as appropriate.
- When creating new units, design them to be tested, and write appropriate tests.
- Run all tests after making changes to validate behavior (e.g. using `./test.sh`).
- When tests fail, do not blindly modify the tests to make them pass. First, suspect that the SUT is flawed and assess
  the root cause of the failure.

Whenever changes impact config files (`.env`, `config/*.{yml,json}`, etc.):
- Always modify `.sample` files in the course of your other work.
- Once your changes are complete, always request approval to modify the live/.gitignored files.
- When modifying the live/.gitignored files, always migrate the existing data to the new format.
- Never replace existing live/.gitignored config values with sample data.
- Never modify the live/.gitignored files without approval.
- Always report what changes were made to live/.gitignored files.
