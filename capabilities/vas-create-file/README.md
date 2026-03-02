# vas-create-file

Create one markdown file; fails when it already exists.

## Parameters

| Name | Type | Required | Default | Description |
|------|------|----------|---------|-------------|
| `file_path` | `str` | yes | — | Vault-relative path for the new file. |
| `content` | `str` | yes | — | Markdown content for the file. |

## Returns

`VaultFileRecord` — metadata and content of the created file.
