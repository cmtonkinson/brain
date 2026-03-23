If ~/.config/agents/agents.md exists, read it and follow its instructions now.

Additional instructions for working in this specific project:
- Read `README.md`.
- Read `docs/*.md`.
- Use `make test integration` to validate when making any code/config changes
  (tests not required for e.g. planning, documentation, etc).
- This is a new, unpublished, unsupported project. The author is the only
  contributor, and isn't even a user yet. As such, when making changes:
    - Never keep old naming, docs, functionality, specs, or expectations as
  "legacy".
    - Never assume migrations or backwards compatibility are desired unless
      asked.
    - If an identifier changes, propagate that change throughout the project.
    - If code would be dead as a result, prune it; don't leave old paths "for
      compatibility."
    - Don't leave notes about what what things "used to" be called.
