"""gRPC adapter entrypoints for Vault Authority Service (VAS)."""

from __future__ import annotations

from datetime import timezone
from typing import Sequence

import grpc
from brain.shared.v1 import envelope_pb2
from brain.state.v1 import vault_pb2, vault_pb2_grpc
from packages.brain_shared.envelope import Envelope, EnvelopeKind, EnvelopeMeta
from packages.brain_shared.errors import (
    ErrorCategory,
    ErrorDetail,
    codes,
    validation_error,
)
from services.state.vault_authority.domain import (
    FileEdit,
    SearchFileMatch,
    VaultEntry,
    VaultEntryType,
    VaultFileRecord,
)
from services.state.vault_authority.service import VaultAuthorityService


class GrpcVaultAuthorityService(vault_pb2_grpc.VaultAuthorityServiceServicer):
    """gRPC servicer mapping transport requests into native VAS API calls."""

    def __init__(self, service: VaultAuthorityService) -> None:
        self._service = service

    def ListDirectory(
        self, request: vault_pb2.ListDirectoryRequest, context: grpc.ServicerContext
    ) -> vault_pb2.ListDirectoryResponse:
        result = self._service.list_directory(
            meta=_meta_from_proto(request.metadata),
            directory_path=request.payload.directory_path,
        )
        _abort_for_transport_errors(context=context, result=result)
        payload = (
            []
            if result.payload is None
            else [_entry_to_proto(item) for item in result.payload.value]
        )
        return vault_pb2.ListDirectoryResponse(
            metadata=_meta_to_proto(result.metadata),
            payload=payload,
            errors=[_error_to_proto(item) for item in result.errors],
        )

    def CreateDirectory(
        self, request: vault_pb2.CreateDirectoryRequest, context: grpc.ServicerContext
    ) -> vault_pb2.CreateDirectoryResponse:
        result = self._service.create_directory(
            meta=_meta_from_proto(request.metadata),
            directory_path=request.payload.directory_path,
            recursive=request.payload.recursive,
        )
        _abort_for_transport_errors(context=context, result=result)
        return vault_pb2.CreateDirectoryResponse(
            metadata=_meta_to_proto(result.metadata),
            payload=_entry_to_proto(
                None if result.payload is None else result.payload.value
            ),
            errors=[_error_to_proto(item) for item in result.errors],
        )

    def DeleteDirectory(
        self, request: vault_pb2.DeleteDirectoryRequest, context: grpc.ServicerContext
    ) -> vault_pb2.DeleteDirectoryResponse:
        result = self._service.delete_directory(
            meta=_meta_from_proto(request.metadata),
            directory_path=request.payload.directory_path,
            recursive=request.payload.recursive,
            missing_ok=request.payload.missing_ok,
            use_trash=request.payload.use_trash,
        )
        _abort_for_transport_errors(context=context, result=result)
        return vault_pb2.DeleteDirectoryResponse(
            metadata=_meta_to_proto(result.metadata),
            payload=False if result.payload is None else bool(result.payload.value),
            errors=[_error_to_proto(item) for item in result.errors],
        )

    def CreateFile(
        self, request: vault_pb2.CreateFileRequest, context: grpc.ServicerContext
    ) -> vault_pb2.CreateFileResponse:
        result = self._service.create_file(
            meta=_meta_from_proto(request.metadata),
            file_path=request.payload.file_path,
            content=request.payload.content,
        )
        _abort_for_transport_errors(context=context, result=result)
        return vault_pb2.CreateFileResponse(
            metadata=_meta_to_proto(result.metadata),
            payload=_file_to_proto(
                None if result.payload is None else result.payload.value
            ),
            errors=[_error_to_proto(item) for item in result.errors],
        )

    def GetFile(
        self, request: vault_pb2.GetFileRequest, context: grpc.ServicerContext
    ) -> vault_pb2.GetFileResponse:
        result = self._service.get_file(
            meta=_meta_from_proto(request.metadata),
            file_path=request.payload.file_path,
        )
        _abort_for_transport_errors(context=context, result=result)
        return vault_pb2.GetFileResponse(
            metadata=_meta_to_proto(result.metadata),
            payload=_file_to_proto(
                None if result.payload is None else result.payload.value
            ),
            errors=[_error_to_proto(item) for item in result.errors],
        )

    def UpdateFile(
        self, request: vault_pb2.UpdateFileRequest, context: grpc.ServicerContext
    ) -> vault_pb2.UpdateFileResponse:
        result = self._service.update_file(
            meta=_meta_from_proto(request.metadata),
            file_path=request.payload.file_path,
            content=request.payload.content,
            if_revision=request.payload.if_revision,
            force=request.payload.force,
        )
        _abort_for_transport_errors(context=context, result=result)
        return vault_pb2.UpdateFileResponse(
            metadata=_meta_to_proto(result.metadata),
            payload=_file_to_proto(
                None if result.payload is None else result.payload.value
            ),
            errors=[_error_to_proto(item) for item in result.errors],
        )

    def AppendFile(
        self, request: vault_pb2.AppendFileRequest, context: grpc.ServicerContext
    ) -> vault_pb2.AppendFileResponse:
        result = self._service.append_file(
            meta=_meta_from_proto(request.metadata),
            file_path=request.payload.file_path,
            content=request.payload.content,
            if_revision=request.payload.if_revision,
            force=request.payload.force,
        )
        _abort_for_transport_errors(context=context, result=result)
        return vault_pb2.AppendFileResponse(
            metadata=_meta_to_proto(result.metadata),
            payload=_file_to_proto(
                None if result.payload is None else result.payload.value
            ),
            errors=[_error_to_proto(item) for item in result.errors],
        )

    def EditFile(
        self, request: vault_pb2.EditFileRequest, context: grpc.ServicerContext
    ) -> vault_pb2.EditFileResponse:
        edits, edit_errors = _coerce_file_edits(request.payload.edits)
        if len(edit_errors) > 0:
            meta = _meta_from_proto(request.metadata)
            return vault_pb2.EditFileResponse(
                metadata=_meta_to_proto(meta),
                payload=vault_pb2.VaultFileRecord(),
                errors=[_error_to_proto(item) for item in edit_errors],
            )
        result = self._service.edit_file(
            meta=_meta_from_proto(request.metadata),
            file_path=request.payload.file_path,
            edits=edits,
            if_revision=request.payload.if_revision,
            force=request.payload.force,
        )
        _abort_for_transport_errors(context=context, result=result)
        return vault_pb2.EditFileResponse(
            metadata=_meta_to_proto(result.metadata),
            payload=_file_to_proto(
                None if result.payload is None else result.payload.value
            ),
            errors=[_error_to_proto(item) for item in result.errors],
        )

    def MovePath(
        self, request: vault_pb2.MovePathRequest, context: grpc.ServicerContext
    ) -> vault_pb2.MovePathResponse:
        result = self._service.move_path(
            meta=_meta_from_proto(request.metadata),
            source_path=request.payload.source_path,
            target_path=request.payload.target_path,
            if_revision=request.payload.if_revision,
            force=request.payload.force,
        )
        _abort_for_transport_errors(context=context, result=result)
        return vault_pb2.MovePathResponse(
            metadata=_meta_to_proto(result.metadata),
            payload=_entry_to_proto(
                None if result.payload is None else result.payload.value
            ),
            errors=[_error_to_proto(item) for item in result.errors],
        )

    def DeleteFile(
        self, request: vault_pb2.DeleteFileRequest, context: grpc.ServicerContext
    ) -> vault_pb2.DeleteFileResponse:
        result = self._service.delete_file(
            meta=_meta_from_proto(request.metadata),
            file_path=request.payload.file_path,
            missing_ok=request.payload.missing_ok,
            use_trash=request.payload.use_trash,
            if_revision=request.payload.if_revision,
            force=request.payload.force,
        )
        _abort_for_transport_errors(context=context, result=result)
        return vault_pb2.DeleteFileResponse(
            metadata=_meta_to_proto(result.metadata),
            payload=False if result.payload is None else bool(result.payload.value),
            errors=[_error_to_proto(item) for item in result.errors],
        )

    def SearchFiles(
        self, request: vault_pb2.SearchFilesRequest, context: grpc.ServicerContext
    ) -> vault_pb2.SearchFilesResponse:
        result = self._service.search_files(
            meta=_meta_from_proto(request.metadata),
            query=request.payload.query,
            directory_scope=request.payload.directory_scope,
            limit=request.payload.limit,
        )
        _abort_for_transport_errors(context=context, result=result)
        payload = (
            []
            if result.payload is None
            else [_search_match_to_proto(item) for item in result.payload.value]
        )
        return vault_pb2.SearchFilesResponse(
            metadata=_meta_to_proto(result.metadata),
            payload=payload,
            errors=[_error_to_proto(item) for item in result.errors],
        )


def register_grpc(*, server: grpc.Server, service: VaultAuthorityService) -> None:
    """Register Vault Authority gRPC service implementation on one server."""
    vault_pb2_grpc.add_VaultAuthorityServiceServicer_to_server(
        GrpcVaultAuthorityService(service),
        server,
    )


def _meta_from_proto(meta: envelope_pb2.EnvelopeMeta) -> EnvelopeMeta:
    """Map protobuf envelope metadata into native shared metadata model."""
    return EnvelopeMeta(
        envelope_id=meta.envelope_id,
        trace_id=meta.trace_id,
        parent_id=meta.parent_id,
        timestamp=meta.timestamp.ToDatetime(tzinfo=timezone.utc),
        kind=_kind_from_proto(meta.kind),
        source=meta.source,
        principal=meta.principal,
    )


def _meta_to_proto(meta: EnvelopeMeta) -> envelope_pb2.EnvelopeMeta:
    """Map native shared metadata into protobuf envelope metadata."""
    message = envelope_pb2.EnvelopeMeta(
        envelope_id=meta.envelope_id,
        trace_id=meta.trace_id,
        parent_id=meta.parent_id,
        kind=_kind_to_proto(meta.kind),
        source=meta.source,
        principal=meta.principal,
    )
    message.timestamp.FromDatetime(meta.timestamp.astimezone(timezone.utc))
    return message


def _kind_from_proto(kind: int) -> EnvelopeKind:
    """Map protobuf envelope kind enum to canonical kind."""
    if kind == envelope_pb2.ENVELOPE_KIND_COMMAND:
        return EnvelopeKind.COMMAND
    if kind == envelope_pb2.ENVELOPE_KIND_EVENT:
        return EnvelopeKind.EVENT
    if kind == envelope_pb2.ENVELOPE_KIND_RESULT:
        return EnvelopeKind.RESULT
    if kind == envelope_pb2.ENVELOPE_KIND_STREAM:
        return EnvelopeKind.STREAM
    return EnvelopeKind.UNSPECIFIED


def _kind_to_proto(kind: EnvelopeKind) -> int:
    """Map canonical envelope kind to protobuf enum value."""
    if kind == EnvelopeKind.COMMAND:
        return envelope_pb2.ENVELOPE_KIND_COMMAND
    if kind == EnvelopeKind.EVENT:
        return envelope_pb2.ENVELOPE_KIND_EVENT
    if kind == EnvelopeKind.RESULT:
        return envelope_pb2.ENVELOPE_KIND_RESULT
    if kind == EnvelopeKind.STREAM:
        return envelope_pb2.ENVELOPE_KIND_STREAM
    return envelope_pb2.ENVELOPE_KIND_UNSPECIFIED


def _entry_to_proto(entry: VaultEntry | None) -> vault_pb2.VaultEntry:
    """Map one domain vault entry to protobuf payload representation."""
    if entry is None:
        return vault_pb2.VaultEntry()
    message = vault_pb2.VaultEntry(
        path=entry.path,
        name=entry.name,
        entry_type=_entry_type_to_proto(entry.entry_type),
        size_bytes=entry.size_bytes,
        revision=entry.revision,
    )
    if entry.created_at is not None:
        message.created_at.FromDatetime(entry.created_at.astimezone(timezone.utc))
    if entry.updated_at is not None:
        message.updated_at.FromDatetime(entry.updated_at.astimezone(timezone.utc))
    return message


def _file_to_proto(record: VaultFileRecord | None) -> vault_pb2.VaultFileRecord:
    """Map one domain vault file record to protobuf payload representation."""
    if record is None:
        return vault_pb2.VaultFileRecord()
    message = vault_pb2.VaultFileRecord(
        path=record.path,
        content=record.content,
        size_bytes=record.size_bytes,
        revision=record.revision,
    )
    if record.created_at is not None:
        message.created_at.FromDatetime(record.created_at.astimezone(timezone.utc))
    if record.updated_at is not None:
        message.updated_at.FromDatetime(record.updated_at.astimezone(timezone.utc))
    return message


def _search_match_to_proto(match: SearchFileMatch | None) -> vault_pb2.SearchFileMatch:
    """Map one domain search match to protobuf payload representation."""
    if match is None:
        return vault_pb2.SearchFileMatch()
    message = vault_pb2.SearchFileMatch(
        path=match.path,
        score=match.score,
        snippets=list(match.snippets),
        revision=match.revision,
    )
    if match.updated_at is not None:
        message.updated_at.FromDatetime(match.updated_at.astimezone(timezone.utc))
    return message


def _entry_type_to_proto(value: VaultEntryType) -> vault_pb2.VaultEntryType:
    """Map one domain enum value into protobuf enum value."""
    mapping = {
        VaultEntryType.DIRECTORY: vault_pb2.VAULT_ENTRY_TYPE_DIRECTORY,
        VaultEntryType.FILE: vault_pb2.VAULT_ENTRY_TYPE_FILE,
    }
    return mapping[value]


def _error_to_proto(error: ErrorDetail) -> envelope_pb2.ErrorDetail:
    """Map one shared error detail into protobuf error detail."""
    return envelope_pb2.ErrorDetail(
        code=error.code,
        message=error.message,
        category=_error_category_to_proto(error.category),
        retryable=error.retryable,
        metadata=dict(error.metadata),
    )


def _error_category_to_proto(category: ErrorCategory) -> int:
    """Map shared-domain error category enum into protobuf enum value."""
    mapping = {
        ErrorCategory.VALIDATION: envelope_pb2.ERROR_CATEGORY_VALIDATION,
        ErrorCategory.CONFLICT: envelope_pb2.ERROR_CATEGORY_CONFLICT,
        ErrorCategory.NOT_FOUND: envelope_pb2.ERROR_CATEGORY_NOT_FOUND,
        ErrorCategory.POLICY: envelope_pb2.ERROR_CATEGORY_POLICY,
        ErrorCategory.DEPENDENCY: envelope_pb2.ERROR_CATEGORY_DEPENDENCY,
        ErrorCategory.INTERNAL: envelope_pb2.ERROR_CATEGORY_INTERNAL,
    }
    return mapping.get(category, envelope_pb2.ERROR_CATEGORY_UNSPECIFIED)


def _transport_status_for_error(error: ErrorDetail) -> grpc.StatusCode | None:
    """Map one service error to optional transport-level gRPC status."""
    if error.category == ErrorCategory.DEPENDENCY:
        return grpc.StatusCode.UNAVAILABLE
    if error.category == ErrorCategory.INTERNAL:
        return grpc.StatusCode.INTERNAL
    return None


def _abort_for_transport_errors(
    *,
    context: grpc.ServicerContext,
    result: Envelope[object],
) -> None:
    """Abort transport for dependency/internal errors; preserve domain errors in payload."""
    for error in result.errors:
        status = _transport_status_for_error(error)
        if status is None:
            continue
        context.abort(status, error.message)


def _coerce_file_edits(
    edits: Sequence[vault_pb2.FileEditOperation],
) -> tuple[list[FileEdit], list[ErrorDetail]]:
    """Coerce protobuf edit payloads into domain edit DTOs with validation errors."""
    payload: list[FileEdit] = []
    for item in edits:
        if item.start_line <= 0 or item.end_line <= 0:
            return [], [
                validation_error(
                    "edit operation line numbers must be >= 1",
                    code=codes.INVALID_ARGUMENT,
                )
            ]
        if item.end_line < item.start_line:
            return [], [
                validation_error(
                    "edit operation end_line must be >= start_line",
                    code=codes.INVALID_ARGUMENT,
                )
            ]
        payload.append(
            FileEdit(
                start_line=int(item.start_line),
                end_line=int(item.end_line),
                content=item.content,
            )
        )
    return payload, []
