# vas-move-path

Move one file or directory path.

## Parameters

| Name | Type | Required | Default | Description |
|------|------|----------|---------|-------------|
| `source_path` | `str` | yes | — | Vault-relative source path. |
| `target_path` | `str` | yes | — | Vault-relative destination path. |
| `if_revision` | `str` | no | `""` | Optimistic concurrency revision guard. |
| `force` | `bool` | no | `false` | Skip revision check. |

## Returns

`VaultEntry` — metadata for the moved entry at its new path.
