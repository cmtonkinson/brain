Instructions for working in this repo:
- Read `README.md`.
- Read `docs/manifesto.md`.
- Read `docs/architecture-doctrine.md`.
- Read `docs/security-trust-boundary-model.md`.
- Never modify `docs/manifesto.md`; if you think you need to, raise it as a question/suggestion for user modification.
- Ask clarifying questions when needed.
- Never create JSONB fields, or string/text fields meant to hold JSON data, in the database without:
  - A very good rationale.
  - Clearly and explicitly explaining why you believe it is justfied.
  - Explicit user approval.

When modifying code:
- Write code that is concise, readable, maintainable, and idiomatic.
- Every file/class/unit should have a complete docblock/docstring.
- Prefer smaller composable units over larger monolithic ones.
- When designing or implementing functionality, consider how 3rd party dependencies (open source packages via gems, npm, pip, etc) may reduce effort and save time.
- Code defensively; assume failure; assume invalid input.
- Before adding new units, search existing code for logic that may be reused/refactored.
- When modifying existing untis, write/modify tests as appropriate.
- When creating new units, design them to be tested, and write appropriate tests.
- Run all tests after making changes to validate behavior (e.g. using `./test.sh`).
- When tests fail, don't just modify the tests to make them pass. First, suspect that the SUT is flawed.

Whenever changes impact config files (`.env`, `config/*.{yml,json}`, etc.):
- Always modify `.sample` files in the course of your other work.
- Once your changes are complete, always request approval to modify the live/.gitignored files.
- When modifying the live/.gitignored files, always migrate the existing data to the new format.
- Never replace existing live/.gitignored config values with sample data.
- Never modify the live/.gitignored files without approval.
- Always report what changes were made to live/.gitignored files.
