# Filesystem Adapter
State _Adapter_ _Resource_ that persists digest-addressed object blobs on local disk for the Object Authority Service.
------------------------------------------------------------------------
## What This Component Is
`resources/adapters/filesystem/` provides Layer 0 filesystem persistence primitives:
- `component.py`: `ResourceManifest` registration (`adapter_filesystem`)
- `config.py`: strict adapter settings and config resolver
- `substrate.py`: transport-agnostic adapter protocol
- `adapter.py`: local-disk implementation with atomic safe-write behavior
------------------------------------------------------------------------
## Boundary and Ownership
This _Resource_ is owned by `service_object_authority` via `owner_service_id` in `resources/adapters/filesystem/component.py`.

This adapter owns only file IO behavior and path derivation from digest + extension. It does not own object key semantics, metadata authority, validation policy, or envelope errors.
------------------------------------------------------------------------
## Interactions
Primary interactions:
- OAS resolves adapter config via `resolve_filesystem_adapter_settings(...)`.
- OAS composes `LocalFilesystemBlobAdapter(...)` in its service implementation.
- OAS calls `write_blob`, `read_blob`, `stat_blob`, and `delete_blob` for blob lifecycle operations.
------------------------------------------------------------------------
## Failure Modes and Error Semantics
- Invalid digest/extension inputs raise explicit `ValueError`.
- Invalid root path (non-directory) raises `OSError`.
- Write failures clean temporary files in all paths.
- Existing target blobs short-circuit writes and are treated as idempotent success.
------------------------------------------------------------------------
## Configuration Surface
Settings are sourced from `components.adapter_filesystem`:
- `root_dir`
- `temp_prefix`
- `fsync_writes`
- `default_extension`
------------------------------------------------------------------------
## Testing and Validation
Component tests:
- `resources/adapters/filesystem/tests/test_filesystem_adapter.py`
- `resources/adapters/filesystem/tests/test_filesystem_config.py`

Project-wide validation command:
```bash
make test
```
------------------------------------------------------------------------
_End of Filesystem Adapter README_
