# vault-search-files

Search markdown files lexically through Obsidian Local REST API.

## Parameters

| Name | Type | Required | Default | Description |
|------|------|----------|---------|-------------|
| `query` | `str` | yes | — | Search query string. |
| `directory_scope` | `str` | no | `""` | Limit search to this vault-relative directory. |
| `limit` | `int` | no | `20` | Maximum number of results to return. |

## Returns

`list[SearchFileMatch]` — list of matching file results with scores and snippets.
