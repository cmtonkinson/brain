# vault-edit-file

Apply one or more line-range edits to a markdown file.

## Parameters

| Name | Type | Required | Default | Description |
|------|------|----------|---------|-------------|
| `file_path` | `str` | yes | — | Vault-relative file path. |
| `edits` | `Sequence[FileEdit]` | yes | — | List of line-range edit operations. |
| `if_revision` | `str` | no | `""` | Optimistic concurrency revision guard. |
| `force` | `bool` | no | `false` | Skip revision check. |

## Returns

`VaultFileRecord` — metadata and content of the edited file.
