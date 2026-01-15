# MCP Servers

This system uses UTCP/Code-Mode to access MCP servers in a token-efficient way. Instead of embedding large tool schemas in prompts, the agent issues compact tool queries (via UTCP) and executes only the selected MCP tool calls. This reduces prompt size and keeps tool usage dynamic without bloating the conversation.

## Routing and Tool Selection

We use a keyword-based, namespace-locking router for Code-Mode tool search:

- Route intent to a namespace (`filesystem`, `eventkit`, `github`) using simple keyword rules.
- Search only within that namespace and rank matches by name/description.
- Fallback to Code-Mode’s global search when routing yields no namespace matches.
- Log routing and search behavior for debugging.

This avoids cross-server collisions while preserving dynamic discovery within each MCP server.

## Supported MCP Servers

### filesystem (MCP filesystem server)

**Capabilities**
- Read/list/search: `filesystem.list_directory`, `filesystem.list_directory_with_sizes`, `filesystem.directory_tree`, `filesystem.search_files`
- File access: `filesystem.read_file`, `filesystem.read_text_file`, `filesystem.read_multiple_files`, `filesystem.read_media_file`
- Metadata: `filesystem.get_file_info`, `filesystem.list_allowed_directories`
- Write/modify: `filesystem.write_file`, `filesystem.edit_file`, `filesystem.create_directory`, `filesystem.move_file`

**Configuration**
- UTCP config: `~/.config/brain/utcp.json` (mounted into container at `/config/utcp.json`)
- Example (from `utcp.json.sample`):
  - `command: npx`
  - `args: ["-y", "@modelcontextprotocol/server-filesystem", "/Users/yourname"]`
- Effective root must be an allowed directory; relative paths resolve inside the container and are rejected if outside allowed roots.

**Notes/Errata**
- The MCP filesystem server enforces allowed directories. Use an allowed root (e.g., `/Users/chris`) for deterministic behavior.
- The self-test now uses `filesystem.list_allowed_directories` and then lists the first allowed root directly.

### eventkit (EventKit MCP server)

**Capabilities**
- Reminders: list, create, update, delete, search, toggle flag
  - Examples: `eventkit.list_reminders`, `eventkit.create_reminder`, `eventkit.search_reminders`
- Calendars/events: list calendars/events, create/update/delete events
  - Examples: `eventkit.list_calendars`, `eventkit.list_calendar_events`, `eventkit.create_calendar_event`
- Tags: `eventkit.list_tags`

**Configuration**
- UTCP config: `~/.config/brain/utcp.json` (mounted into container at `/config/utcp.json`)
- Example (from `utcp.json.sample`):
  - `url: "http://host.docker.internal:7411/eventkit/rpc"`
  - `headers.Authorization: "Bearer REPLACE_ME"`

**Notes/Errata**
- EventKit returns both reminders and calendars under the same server, so namespace locking prevents cross-server collisions but does not disambiguate reminders vs. calendar intent. We plan to refine intent mapping for that within the namespace.

### github (GitHub MCP server)

**Capabilities**
- Repository, branch, and file operations
  - Examples: `github.get_file_contents`, `github.list_branches`, `github.create_or_update_file`
- Issues and PRs
  - Examples: `github.issue_read`, `github.issue_write`, `github.list_pull_requests`, `github.create_pull_request`
- Search and metadata
  - Examples: `github.search_repositories`, `github.search_issues`, `github.get_latest_release`

**Configuration**
- UTCP config: `~/.config/brain/utcp.json` (mounted into container at `/config/utcp.json`)
- Example (from `utcp.json.sample`):
  - `command: "/usr/local/bin/github-mcp-server"`
  - `args: ["stdio"]`
  - `env.GITHUB_PERSONAL_ACCESS_TOKEN: "set-me"`

**Notes/Errata**
- GitHub MCP tool schemas may include `outputSchema=null` for some tools; the container image patches UTCP MCP handling to accept null outputs.
