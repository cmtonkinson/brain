# AGENTS.md
Instructions for agents working in this repo:
- Run tests (`./test.sh`) after making changes to validate behavior.
- Suggest new tests when approptiate.

Whenever changes are required that would impact config files such as `config/brain.yml`,
`config/utcp.json`, `config/secrets.yml`, `.env`, etc.:
- Always modify `.sample` files in the course of your other work.
- Once your changes are complete, always request approval to modify the live/.gitignored files.
- When modifying the live/.gitignored files, always migrate the existing data to the new format.
- Never replace existing live/.gitignored config values with sample data.
- Never modify the live/.gitignored files without approval.
