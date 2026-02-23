"""Concrete Vault Authority Service implementation."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any, Sequence

from pydantic import BaseModel, ValidationError

from packages.brain_shared.config import BrainSettings
from packages.brain_shared.envelope import (
    Envelope,
    EnvelopeMeta,
    failure,
    success,
    validate_meta,
)
from packages.brain_shared.errors import (
    ErrorDetail,
    codes,
    conflict_error,
    dependency_error,
    internal_error,
    not_found_error,
    validation_error,
)
from packages.brain_shared.logging import get_logger, public_api_instrumented
from resources.adapters.obsidian import (
    FileEditOperation,
    ObsidianAdapter,
    ObsidianAdapterAlreadyExistsError,
    ObsidianAdapterConflictError,
    ObsidianAdapterDependencyError,
    ObsidianAdapterInternalError,
    ObsidianAdapterNotFoundError,
    ObsidianEntry,
    ObsidianEntryType,
    ObsidianFileRecord,
    ObsidianLocalRestAdapter,
    ObsidianSearchMatch,
    resolve_obsidian_adapter_settings,
)
from services.state.vault_authority.component import SERVICE_COMPONENT_ID
from services.state.vault_authority.config import (
    VaultAuthoritySettings,
    resolve_vault_authority_settings,
)
from services.state.vault_authority.domain import (
    FileEdit,
    SearchFileMatch,
    VaultEntry,
    VaultEntryType,
    VaultFileRecord,
)
from services.state.vault_authority.service import VaultAuthorityService
from services.state.vault_authority.validation import (
    AppendFileRequest,
    CreateDirectoryRequest,
    CreateFileRequest,
    DeleteDirectoryRequest,
    DeleteFileRequest,
    EditFileRequest,
    GetFileRequest,
    ListDirectoryRequest,
    MovePathRequest,
    SearchFilesRequest,
    UpdateFileRequest,
)

_LOGGER = get_logger(__name__)


class DefaultVaultAuthorityService(VaultAuthorityService):
    """Default VAS implementation backed by Obsidian Local REST API adapter."""

    def __init__(
        self,
        *,
        settings: VaultAuthoritySettings,
        adapter: ObsidianAdapter,
    ) -> None:
        self._settings = settings
        self._adapter = adapter

    @classmethod
    def from_settings(cls, settings: BrainSettings) -> "DefaultVaultAuthorityService":
        """Build VAS and owned Obsidian adapter from typed root settings."""
        service_settings = resolve_vault_authority_settings(settings)
        adapter_settings = resolve_obsidian_adapter_settings(settings)
        return cls(
            settings=service_settings,
            adapter=ObsidianLocalRestAdapter(settings=adapter_settings),
        )

    @public_api_instrumented(logger=_LOGGER, component_id=str(SERVICE_COMPONENT_ID))
    def list_directory(
        self,
        *,
        meta: EnvelopeMeta,
        directory_path: str,
    ) -> Envelope[list[VaultEntry]]:
        """List file and directory entries under one vault-relative path."""
        request, errors = self._validate_request(
            meta=meta,
            model=ListDirectoryRequest,
            payload={"directory_path": directory_path},
        )
        if errors:
            return failure(meta=meta, errors=errors)
        assert request is not None

        try:
            entries = self._adapter.list_directory(
                directory_path=request.directory_path
            )
        except Exception as exc:  # noqa: BLE001
            return self._adapter_failure(meta=meta, operation="list_directory", exc=exc)

        return success(
            meta=meta,
            payload=[
                _to_entry(item) for item in entries[: self._settings.max_list_limit]
            ],
        )

    @public_api_instrumented(logger=_LOGGER, component_id=str(SERVICE_COMPONENT_ID))
    def create_directory(
        self,
        *,
        meta: EnvelopeMeta,
        directory_path: str,
        recursive: bool = False,
    ) -> Envelope[VaultEntry]:
        """Create one directory."""
        request, errors = self._validate_request(
            meta=meta,
            model=CreateDirectoryRequest,
            payload={"directory_path": directory_path, "recursive": recursive},
        )
        if errors:
            return failure(meta=meta, errors=errors)
        assert request is not None

        try:
            entry = self._adapter.create_directory(
                directory_path=request.directory_path,
                recursive=request.recursive,
            )
        except Exception as exc:  # noqa: BLE001
            return self._adapter_failure(
                meta=meta, operation="create_directory", exc=exc
            )

        return success(meta=meta, payload=_to_entry(entry))

    @public_api_instrumented(logger=_LOGGER, component_id=str(SERVICE_COMPONENT_ID))
    def delete_directory(
        self,
        *,
        meta: EnvelopeMeta,
        directory_path: str,
        recursive: bool = False,
        missing_ok: bool = False,
        use_trash: bool = True,
    ) -> Envelope[bool]:
        """Delete one directory, optionally recursively and missing-ok."""
        request, errors = self._validate_request(
            meta=meta,
            model=DeleteDirectoryRequest,
            payload={
                "directory_path": directory_path,
                "recursive": recursive,
                "missing_ok": missing_ok,
                "use_trash": use_trash,
            },
        )
        if errors:
            return failure(meta=meta, errors=errors)
        assert request is not None

        try:
            deleted = self._adapter.delete_directory(
                directory_path=request.directory_path,
                recursive=request.recursive,
                missing_ok=request.missing_ok,
                use_trash=request.use_trash,
            )
        except Exception as exc:  # noqa: BLE001
            return self._adapter_failure(
                meta=meta, operation="delete_directory", exc=exc
            )

        return success(meta=meta, payload=deleted)

    @public_api_instrumented(
        logger=_LOGGER,
        component_id=str(SERVICE_COMPONENT_ID),
        id_fields=("file_path",),
    )
    def create_file(
        self,
        *,
        meta: EnvelopeMeta,
        file_path: str,
        content: str,
    ) -> Envelope[VaultFileRecord]:
        """Create one markdown file and fail when it already exists."""
        request, errors = self._validate_request(
            meta=meta,
            model=CreateFileRequest,
            payload={"file_path": file_path, "content": content},
        )
        if errors:
            return failure(meta=meta, errors=errors)
        assert request is not None

        try:
            record = self._adapter.create_file(
                file_path=request.file_path,
                content=request.content,
            )
        except Exception as exc:  # noqa: BLE001
            return self._adapter_failure(meta=meta, operation="create_file", exc=exc)

        return success(meta=meta, payload=_to_file(record))

    @public_api_instrumented(
        logger=_LOGGER,
        component_id=str(SERVICE_COMPONENT_ID),
        id_fields=("file_path",),
    )
    def get_file(
        self,
        *,
        meta: EnvelopeMeta,
        file_path: str,
    ) -> Envelope[VaultFileRecord]:
        """Read one markdown file by path."""
        request, errors = self._validate_request(
            meta=meta,
            model=GetFileRequest,
            payload={"file_path": file_path},
        )
        if errors:
            return failure(meta=meta, errors=errors)
        assert request is not None

        try:
            record = self._adapter.get_file(file_path=request.file_path)
        except Exception as exc:  # noqa: BLE001
            return self._adapter_failure(meta=meta, operation="get_file", exc=exc)

        return success(meta=meta, payload=_to_file(record))

    @public_api_instrumented(
        logger=_LOGGER,
        component_id=str(SERVICE_COMPONENT_ID),
        id_fields=("file_path",),
    )
    def update_file(
        self,
        *,
        meta: EnvelopeMeta,
        file_path: str,
        content: str,
        if_revision: str = "",
        force: bool = False,
    ) -> Envelope[VaultFileRecord]:
        """Replace markdown file content with optional optimistic precondition."""
        request, errors = self._validate_request(
            meta=meta,
            model=UpdateFileRequest,
            payload={
                "file_path": file_path,
                "content": content,
                "if_revision": if_revision,
                "force": force,
            },
        )
        if errors:
            return failure(meta=meta, errors=errors)
        assert request is not None

        precondition_error = self._enforce_file_precondition(
            meta=meta,
            file_path=request.file_path,
            if_revision=request.if_revision,
            force=request.force,
            operation="update_file",
        )
        if precondition_error is not None:
            return precondition_error

        try:
            record = self._adapter.update_file(
                file_path=request.file_path,
                content=request.content,
                if_revision=request.if_revision,
                force=request.force,
            )
        except Exception as exc:  # noqa: BLE001
            return self._adapter_failure(meta=meta, operation="update_file", exc=exc)

        return success(meta=meta, payload=_to_file(record))

    @public_api_instrumented(
        logger=_LOGGER,
        component_id=str(SERVICE_COMPONENT_ID),
        id_fields=("file_path",),
    )
    def append_file(
        self,
        *,
        meta: EnvelopeMeta,
        file_path: str,
        content: str,
        if_revision: str = "",
        force: bool = False,
    ) -> Envelope[VaultFileRecord]:
        """Append content to one markdown file."""
        request, errors = self._validate_request(
            meta=meta,
            model=AppendFileRequest,
            payload={
                "file_path": file_path,
                "content": content,
                "if_revision": if_revision,
                "force": force,
            },
        )
        if errors:
            return failure(meta=meta, errors=errors)
        assert request is not None

        precondition_error = self._enforce_file_precondition(
            meta=meta,
            file_path=request.file_path,
            if_revision=request.if_revision,
            force=request.force,
            operation="append_file",
        )
        if precondition_error is not None:
            return precondition_error

        try:
            record = self._adapter.append_file(
                file_path=request.file_path,
                content=request.content,
                if_revision=request.if_revision,
                force=request.force,
            )
        except Exception as exc:  # noqa: BLE001
            return self._adapter_failure(meta=meta, operation="append_file", exc=exc)

        return success(meta=meta, payload=_to_file(record))

    @public_api_instrumented(
        logger=_LOGGER,
        component_id=str(SERVICE_COMPONENT_ID),
        id_fields=("file_path",),
    )
    def edit_file(
        self,
        *,
        meta: EnvelopeMeta,
        file_path: str,
        edits: Sequence[FileEdit],
        if_revision: str = "",
        force: bool = False,
    ) -> Envelope[VaultFileRecord]:
        """Apply one or more line-range edits to a markdown file."""
        request, errors = self._validate_request(
            meta=meta,
            model=EditFileRequest,
            payload={
                "file_path": file_path,
                "edits": [item.model_dump(mode="python") for item in edits],
                "if_revision": if_revision,
                "force": force,
            },
        )
        if errors:
            return failure(meta=meta, errors=errors)
        assert request is not None

        adapter_edits = [
            FileEditOperation(
                start_line=item.start_line,
                end_line=item.end_line,
                content=item.content,
            )
            for item in request.edits
        ]

        precondition_error = self._enforce_file_precondition(
            meta=meta,
            file_path=request.file_path,
            if_revision=request.if_revision,
            force=request.force,
            operation="edit_file",
        )
        if precondition_error is not None:
            return precondition_error

        try:
            record = self._adapter.edit_file(
                file_path=request.file_path,
                edits=adapter_edits,
                if_revision=request.if_revision,
                force=request.force,
            )
        except Exception as exc:  # noqa: BLE001
            return self._adapter_failure(meta=meta, operation="edit_file", exc=exc)

        return success(meta=meta, payload=_to_file(record))

    @public_api_instrumented(logger=_LOGGER, component_id=str(SERVICE_COMPONENT_ID))
    def move_path(
        self,
        *,
        meta: EnvelopeMeta,
        source_path: str,
        target_path: str,
        if_revision: str = "",
        force: bool = False,
    ) -> Envelope[VaultEntry]:
        """Move one file or directory path."""
        request, errors = self._validate_request(
            meta=meta,
            model=MovePathRequest,
            payload={
                "source_path": source_path,
                "target_path": target_path,
                "if_revision": if_revision,
                "force": force,
            },
        )
        if errors:
            return failure(meta=meta, errors=errors)
        assert request is not None

        source_is_file = request.source_path.lower().endswith(".md")
        target_is_file = request.target_path.lower().endswith(".md")
        if source_is_file != target_is_file:
            return failure(
                meta=meta,
                errors=[
                    validation_error(
                        "move_path requires source_path and target_path to both be files or both be directories",
                        code=codes.INVALID_ARGUMENT,
                    )
                ],
            )
        if source_is_file:
            precondition_error = self._enforce_file_precondition(
                meta=meta,
                file_path=request.source_path,
                if_revision=request.if_revision,
                force=request.force,
                operation="move_path",
            )
            if precondition_error is not None:
                return precondition_error

        try:
            entry = self._adapter.move_path(
                source_path=request.source_path,
                target_path=request.target_path,
                if_revision=request.if_revision,
                force=request.force,
            )
        except Exception as exc:  # noqa: BLE001
            return self._adapter_failure(meta=meta, operation="move_path", exc=exc)

        return success(meta=meta, payload=_to_entry(entry))

    @public_api_instrumented(
        logger=_LOGGER,
        component_id=str(SERVICE_COMPONENT_ID),
        id_fields=("file_path",),
    )
    def delete_file(
        self,
        *,
        meta: EnvelopeMeta,
        file_path: str,
        missing_ok: bool = False,
        use_trash: bool = True,
        if_revision: str = "",
        force: bool = False,
    ) -> Envelope[bool]:
        """Delete one markdown file."""
        request, errors = self._validate_request(
            meta=meta,
            model=DeleteFileRequest,
            payload={
                "file_path": file_path,
                "missing_ok": missing_ok,
                "use_trash": use_trash,
                "if_revision": if_revision,
                "force": force,
            },
        )
        if errors:
            return failure(meta=meta, errors=errors)
        assert request is not None

        precondition_error = self._enforce_file_precondition(
            meta=meta,
            file_path=request.file_path,
            if_revision=request.if_revision,
            force=request.force,
            operation="delete_file",
        )
        if precondition_error is not None:
            return precondition_error

        try:
            deleted = self._adapter.delete_file(
                file_path=request.file_path,
                missing_ok=request.missing_ok,
                use_trash=request.use_trash,
                if_revision=request.if_revision,
                force=request.force,
            )
        except Exception as exc:  # noqa: BLE001
            return self._adapter_failure(meta=meta, operation="delete_file", exc=exc)

        return success(meta=meta, payload=deleted)

    @public_api_instrumented(logger=_LOGGER, component_id=str(SERVICE_COMPONENT_ID))
    def search_files(
        self,
        *,
        meta: EnvelopeMeta,
        query: str,
        directory_scope: str = "",
        limit: int = 20,
    ) -> Envelope[list[SearchFileMatch]]:
        """Search markdown files lexically through Obsidian Local REST API."""
        request, errors = self._validate_request(
            meta=meta,
            model=SearchFilesRequest,
            payload={
                "query": query,
                "directory_scope": directory_scope,
                "limit": limit,
            },
        )
        if errors:
            return failure(meta=meta, errors=errors)
        assert request is not None

        resolved_limit = min(request.limit, self._settings.max_search_limit)
        try:
            matches = self._adapter.search_files(
                query=request.query,
                directory_scope=request.directory_scope,
                limit=resolved_limit,
            )
        except Exception as exc:  # noqa: BLE001
            return self._adapter_failure(meta=meta, operation="search_files", exc=exc)

        return success(meta=meta, payload=[_to_search_match(item) for item in matches])

    def _validate_request(
        self,
        *,
        meta: EnvelopeMeta,
        model: type[BaseModel],
        payload: dict[str, object],
    ) -> tuple[BaseModel | None, list[ErrorDetail]]:
        """Validate envelope metadata and request payload for one operation."""
        try:
            validate_meta(meta)
            request = model.model_validate(payload)
        except ValidationError as exc:
            first_error = exc.errors()[0]
            location = ".".join(str(item) for item in first_error.get("loc", ()))
            message = str(first_error.get("msg", "invalid request"))
            return None, [
                validation_error(
                    f"{location}: {message}",
                    code=codes.INVALID_ARGUMENT,
                    metadata={"service": str(SERVICE_COMPONENT_ID)},
                )
            ]
        except ValueError as exc:
            return None, [
                validation_error(
                    str(exc),
                    code=codes.INVALID_ARGUMENT,
                    metadata={"service": str(SERVICE_COMPONENT_ID)},
                )
            ]

        return request, []

    def _adapter_failure(
        self,
        *,
        meta: EnvelopeMeta,
        operation: str,
        exc: Exception,
    ) -> Envelope[Any]:
        """Map adapter exceptions into explicit service-level error contracts."""
        metadata = {"service": str(SERVICE_COMPONENT_ID), "operation": operation}
        if isinstance(exc, ObsidianAdapterNotFoundError):
            return failure(
                meta=meta,
                errors=[
                    not_found_error(
                        str(exc) or "vault path not found",
                        code=codes.RESOURCE_NOT_FOUND,
                        metadata=metadata,
                    )
                ],
            )
        if isinstance(exc, ObsidianAdapterAlreadyExistsError):
            return failure(
                meta=meta,
                errors=[
                    conflict_error(
                        str(exc) or "vault path already exists",
                        code=codes.ALREADY_EXISTS,
                        metadata=metadata,
                    )
                ],
            )
        if isinstance(exc, ObsidianAdapterConflictError):
            return failure(
                meta=meta,
                errors=[
                    conflict_error(
                        str(exc) or "vault operation conflict",
                        code=codes.CONFLICT,
                        metadata=metadata,
                    )
                ],
            )
        if isinstance(exc, ObsidianAdapterDependencyError):
            return failure(
                meta=meta,
                errors=[
                    dependency_error(
                        str(exc) or "obsidian adapter dependency failure",
                        code=codes.DEPENDENCY_UNAVAILABLE,
                        metadata=metadata,
                    )
                ],
            )
        if isinstance(exc, ObsidianAdapterInternalError):
            return failure(
                meta=meta,
                errors=[
                    internal_error(
                        str(exc) or "obsidian adapter internal failure",
                        code=codes.INTERNAL_ERROR,
                        metadata=metadata,
                    )
                ],
            )

        return failure(
            meta=meta,
            errors=[
                internal_error(
                    str(exc) or "unexpected vault authority failure",
                    code=codes.UNEXPECTED_EXCEPTION,
                    metadata=metadata,
                )
            ],
        )

    def _enforce_file_precondition(
        self,
        *,
        meta: EnvelopeMeta,
        file_path: str,
        if_revision: str,
        force: bool,
        operation: str,
    ) -> Envelope[Any] | None:
        """Enforce optimistic concurrency token when one is provided."""
        expected = if_revision.strip()
        if expected == "" or force:
            return None

        current = self.get_file(meta=meta, file_path=file_path)
        if not current.ok:
            return failure(meta=meta, errors=current.errors)
        if current.payload is None:
            return failure(
                meta=meta,
                errors=[
                    not_found_error(
                        "vault file not found",
                        code=codes.RESOURCE_NOT_FOUND,
                        metadata={
                            "service": str(SERVICE_COMPONENT_ID),
                            "operation": operation,
                            "file_path": file_path,
                        },
                    )
                ],
            )

        actual = current.payload.value.revision.strip()
        if actual != expected:
            return failure(
                meta=meta,
                errors=[
                    conflict_error(
                        "revision precondition failed",
                        code=codes.CONFLICT,
                        metadata={
                            "service": str(SERVICE_COMPONENT_ID),
                            "operation": operation,
                            "file_path": file_path,
                            "expected_revision": expected,
                            "actual_revision": actual,
                        },
                    )
                ],
            )
        return None


def _to_entry(item: ObsidianEntry) -> VaultEntry:
    """Map adapter directory-entry DTO into service domain contract."""
    entry_type = (
        VaultEntryType.DIRECTORY
        if item.entry_type == ObsidianEntryType.DIRECTORY
        else VaultEntryType.FILE
    )
    return VaultEntry(
        path=item.path,
        name=item.name,
        entry_type=entry_type,
        size_bytes=item.size_bytes,
        created_at=_parse_timestamp(item.created_at),
        updated_at=_parse_timestamp(item.updated_at),
        revision=item.revision,
    )


def _to_file(item: ObsidianFileRecord) -> VaultFileRecord:
    """Map adapter file DTO into service domain contract."""
    return VaultFileRecord(
        path=item.path,
        content=item.content,
        size_bytes=item.size_bytes,
        created_at=_parse_timestamp(item.created_at),
        updated_at=_parse_timestamp(item.updated_at),
        revision=item.revision,
    )


def _to_search_match(item: ObsidianSearchMatch) -> SearchFileMatch:
    """Map adapter search DTO into service domain contract."""
    return SearchFileMatch(
        path=item.path,
        score=item.score,
        snippets=item.snippets,
        updated_at=_parse_timestamp(item.updated_at),
        revision=item.revision,
    )


def _parse_timestamp(value: str) -> datetime | None:
    """Parse ISO-like timestamp text into UTC datetime when present."""
    text = value.strip()
    if text == "":
        return None
    normalized = text.replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(normalized)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)
