# SeaweedFS Substrate
State *Substrate* *Resource* that persists digest-addressed object blobs in
SeaweedFS for the Object Service.

------------------------------------------------------------------------
## What This Component Is
`resources/substrates/seaweedfs/` provides Tier 1 blob persistence primitives:
* `component.py`: `ResourceManifest` registration (`substrate_seaweedfs`)
* `config.py`: strict substrate settings and config resolver
* `substrate.py`: transport-agnostic blob substrate protocol
* `seaweedfs_substrate.py`: SeaweedFS S3-compatible implementation

------------------------------------------------------------------------
## Boundary and Ownership
This *Resource* is owned by `service_object` via `owner_service_id` in
`resources/substrates/seaweedfs/component.py`.

This substrate owns provider key derivation and byte IO against the SeaweedFS
S3-compatible API. It does not own object-key semantics, metadata authority,
validation policy, or envelope errors.

------------------------------------------------------------------------
## Interactions
Primary interactions:
* Object resolves substrate config via `resolve_seaweedfs_substrate_settings(...)`.
* Object composes `SeaweedFSBlobSubstrate(...)` in its service implementation.
* Object calls `write_blob`, `read_blob`, `stat_blob`, and `delete_blob` for blob
  lifecycle operations.

------------------------------------------------------------------------
## Failure Modes and Error Semantics
* Invalid digest/extension inputs raise explicit `ValueError`.
* Missing objects raise `FileNotFoundError`.
* HTTP provider failures raise `httpx.HTTPStatusError` or transport errors.
* Existing target objects short-circuit writes and are treated as idempotent
  success.

------------------------------------------------------------------------
## Configuration Surface
Settings are sourced from `components.substrate.seaweedfs`:
* `endpoint_url`
* `bucket`
* `region`
* `access_key_id`
* `secret_access_key`
* `key_prefix`
* `request_timeout_seconds`
* `default_extension`

------------------------------------------------------------------------
## Testing and Validation
Component tests:
* `resources/substrates/seaweedfs/tests/test_seaweedfs_substrate.py`
* `resources/substrates/seaweedfs/tests/test_seaweedfs_config.py`

Project-wide validation command:
```bash
make test
```


------------------------------------------------------------------------
_End of SeaweedFS Substrate README_
