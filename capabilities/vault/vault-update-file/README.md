# vault-update-file

Replace markdown file content with optional optimistic precondition.

## Parameters

| Name | Type | Required | Default | Description |
|------|------|----------|---------|-------------|
| `file_path` | `str` | yes | — | Vault-relative file path. |
| `content` | `str` | yes | — | New content to replace existing file content. |
| `if_revision` | `str` | no | `""` | Optimistic concurrency revision guard. |
| `force` | `bool` | no | `false` | Skip revision check. |

## Returns

`VaultFileRecord` — metadata and content of the updated file.
