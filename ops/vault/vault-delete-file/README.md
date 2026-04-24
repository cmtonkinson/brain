# vault-delete-file

Delete one markdown file.

## Parameters

| Name | Type | Required | Default | Description |
|------|------|----------|---------|-------------|
| `file_path` | `str` | yes | — | Vault-relative file path. |
| `missing_ok` | `bool` | no | `false` | Succeed silently if the file does not exist. |
| `use_trash` | `bool` | no | `true` | Move to trash instead of permanent deletion. |
| `if_revision` | `str` | no | `""` | Optimistic concurrency revision guard. |
| `force` | `bool` | no | `false` | Skip revision check. |

## Returns

`bool` — `true` on success.
