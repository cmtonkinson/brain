Instructions for working in this repo:
- Read `README.md`.
- Read `docs/manifesto.md`.
- Read `docs/architecture-doctrine.md`.
- Never modify `docs/manifesto.md`; if you think you need to, raise it as a question/suggestion for user modification.

Whenever changes impact config files (`.env`, `config/*.{yml,json}`, etc.):
- Always modify `.sample` files in the course of your other work.
- Once your changes are complete, always request approval to modify the live/.gitignored files.
- When modifying the live/.gitignored files, always migrate the existing data to the new format.
- Never replace existing live/.gitignored config values with sample data.
- Never modify the live/.gitignored files without approval.
- Always report what changes were made to live/.gitignored files.

Test suites can be run using the helper `test.sh -a` script:
- core suite (lint, checks, unit/contract/smoke/go): `./test.sh`
- include integration tests: `./test.sh --integration`
- enable coverage reporting: `./test.sh --coverage`
- include both integration and coverage: `./test.sh --all`
