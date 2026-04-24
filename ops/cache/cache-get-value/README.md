# cache-get-value

Get one component-scoped cache value by key.

## Parameters

| Name | Type | Required | Default | Description |
|------|------|----------|---------|-------------|
| `component_id` | `str` | yes | — | Canonical component id namespace for the cache key. |
| `key` | `str` | yes | — | Cache key within the component namespace. |

## Returns

`CacheEntry | null` — the cache record when present, otherwise `null`.
