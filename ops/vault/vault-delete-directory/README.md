# vault-delete-directory

Delete one directory, optionally recursively.

## Parameters

| Name | Type | Required | Default | Description |
|------|------|----------|---------|-------------|
| `directory_path` | `str` | yes | — | Vault-relative path of the directory to delete. |
| `recursive` | `bool` | no | `false` | Delete contents recursively. |
| `missing_ok` | `bool` | no | `false` | Succeed silently if the directory does not exist. |
| `use_trash` | `bool` | no | `true` | Move to trash instead of permanent deletion. |

## Returns

`bool` — `true` on success.
