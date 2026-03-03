# cache-delete-value

Delete one component-scoped cache value.

## Parameters

| Name | Type | Required | Default | Description |
|------|------|----------|---------|-------------|
| `component_id` | `str` | yes | — | Canonical component id namespace for the cache key. |
| `key` | `str` | yes | — | Cache key within the component namespace. |

## Returns

`bool` — `true` when the delete operation completes.
