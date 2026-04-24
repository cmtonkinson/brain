# cache-set-value

Set one component-scoped cache value.

## Parameters

| Name | Type | Required | Default | Description |
|------|------|----------|---------|-------------|
| `component_id` | `str` | yes | — | Canonical component id namespace for the cache key. |
| `key` | `str` | yes | — | Cache key within the component namespace. |
| `value` | `object` | yes | — | JSON-serializable value to persist. |
| `ttl_seconds` | `int \| null` | no | `null` | Optional TTL override in seconds. |

## Returns

`CacheEntry` — the authoritative cache record after the write.
