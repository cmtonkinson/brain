# vas-append-file

Append content to one markdown file.

## Parameters

| Name | Type | Required | Default | Description |
|------|------|----------|---------|-------------|
| `file_path` | `str` | yes | — | Vault-relative file path. |
| `content` | `str` | yes | — | Content to append. |
| `if_revision` | `str` | no | `""` | Optimistic concurrency revision guard. |
| `force` | `bool` | no | `false` | Skip revision check. |

## Returns

`VaultFileRecord` — metadata and content of the updated file.
