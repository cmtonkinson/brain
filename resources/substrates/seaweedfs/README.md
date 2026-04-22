# SeaweedFS Substrate
State _Substrate_ _Resource_ that persists digest-addressed object blobs in
SeaweedFS for the Object Authority Service.

------------------------------------------------------------------------
## What This Component Is
`resources/substrates/seaweedfs/` provides Layer 0 blob persistence primitives:
- `component.py`: `ResourceManifest` registration (`substrate_seaweedfs`)
- `config.py`: strict substrate settings and config resolver
- `substrate.py`: transport-agnostic blob substrate protocol
- `seaweedfs_substrate.py`: SeaweedFS S3-compatible implementation

------------------------------------------------------------------------
## Boundary and Ownership
This _Resource_ is owned by `service_object_authority` via `owner_service_id` in
`resources/substrates/seaweedfs/component.py`.

This substrate owns provider key derivation and byte IO against the SeaweedFS
S3-compatible API. It does not own object-key semantics, metadata authority,
validation policy, or envelope errors.

------------------------------------------------------------------------
## Interactions
Primary interactions:
- OAS resolves substrate config via `resolve_seaweedfs_substrate_settings(...)`.
- OAS composes `SeaweedFSBlobSubstrate(...)` in its service implementation.
- OAS calls `write_blob`, `read_blob`, `stat_blob`, and `delete_blob` for blob
  lifecycle operations.

------------------------------------------------------------------------
## Failure Modes and Error Semantics
- Invalid digest/extension inputs raise explicit `ValueError`.
- Missing objects raise `FileNotFoundError`.
- HTTP provider failures raise `httpx.HTTPStatusError` or transport errors.
- Existing target objects short-circuit writes and are treated as idempotent
  success.

------------------------------------------------------------------------
## Configuration Surface
Settings are sourced from `components.substrate.seaweedfs`:
- `endpoint_url`
- `bucket`
- `region`
- `access_key_id`
- `secret_access_key`
- `key_prefix`
- `request_timeout_seconds`
- `default_extension`

------------------------------------------------------------------------
## Testing and Validation
Component tests:
- `resources/substrates/seaweedfs/tests/test_seaweedfs_substrate.py`
- `resources/substrates/seaweedfs/tests/test_seaweedfs_config.py`

Project-wide validation command:
```bash
make test
```


------------------------------------------------------------------------
_End of SeaweedFS Substrate README_
