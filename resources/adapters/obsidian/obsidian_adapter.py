"""In-process Obsidian adapter implementation over Local REST API."""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any
from uuid import uuid4
from urllib import error as urllib_error
from urllib import parse as urllib_parse
from urllib import request as urllib_request

from packages.brain_shared.logging import get_logger, public_api_instrumented
from packages.brain_shared.vault_paths import (
    normalize_vault_directory_path,
    normalize_vault_file_path,
    normalize_vault_relative_path,
)
from resources.adapters.obsidian.adapter import (
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
    ObsidianSearchMatch,
)
from resources.adapters.obsidian.component import RESOURCE_COMPONENT_ID
from resources.adapters.obsidian.config import ObsidianAdapterSettings

_LOGGER = get_logger(__name__)


@dataclass(frozen=True)
class _HttpResult:
    """Normalized HTTP response envelope."""

    status_code: int
    payload: Any


class ObsidianLocalRestAdapter(ObsidianAdapter):
    """Obsidian adapter backed by HTTP calls to Local REST API."""

    _ACCEPT_NOTE_JSON = "application/vnd.olrapi.note+json"

    def __init__(self, *, settings: ObsidianAdapterSettings) -> None:
        self._settings = settings
        self._base_url = settings.base_url.rstrip("/")

    @public_api_instrumented(logger=_LOGGER, component_id=str(RESOURCE_COMPONENT_ID))
    def list_directory(self, *, directory_path: str) -> list[ObsidianEntry]:
        """List file and directory entries directly under one path."""
        normalized = _normalize_directory_path(directory_path)
        endpoint = _vault_directory_endpoint(normalized)
        result = self._request_json(method="GET", endpoint=endpoint)

        if not isinstance(result.payload, Mapping):
            raise ObsidianAdapterInternalError(
                "obsidian list response must be an object"
            )
        files = result.payload.get("files")
        if not isinstance(files, list):
            raise ObsidianAdapterInternalError(
                "obsidian list response missing files array"
            )

        entries: list[ObsidianEntry] = []
        for item in files:
            if not isinstance(item, str):
                raise ObsidianAdapterInternalError(
                    "obsidian list response contains non-string path"
                )
            is_directory = item.endswith("/")
            basename = item[:-1] if is_directory else item
            path = basename if normalized == "" else f"{normalized}/{basename}"
            entries.append(
                ObsidianEntry(
                    path=path,
                    name=basename,
                    entry_type=(
                        ObsidianEntryType.DIRECTORY
                        if is_directory
                        else ObsidianEntryType.FILE
                    ),
                )
            )
        return entries

    @public_api_instrumented(logger=_LOGGER, component_id=str(RESOURCE_COMPONENT_ID))
    def create_directory(
        self, *, directory_path: str, recursive: bool
    ) -> ObsidianEntry:
        """Create one directory and return resulting metadata."""
        normalized = _normalize_directory_path(directory_path)
        if normalized == "":
            raise ObsidianAdapterConflictError("cannot create vault root directory")

        try:
            self.list_directory(directory_path=normalized)
        except ObsidianAdapterNotFoundError:
            pass
        else:
            raise ObsidianAdapterAlreadyExistsError("directory already exists")

        if not recursive and "/" in normalized:
            parent = normalized.rsplit("/", maxsplit=1)[0]
            try:
                self.list_directory(directory_path=parent)
            except ObsidianAdapterNotFoundError:
                raise ObsidianAdapterConflictError(
                    "parent directory does not exist"
                ) from None

        sentinel = f"{normalized}/.brain_directory_{uuid4().hex}.md"
        self._request_raw(
            method="PUT",
            endpoint=_vault_file_endpoint(sentinel),
            body=b"",
            content_type="text/markdown",
            accept="application/json",
        )
        # Best-effort cleanup: tolerate races/retries where sentinel is already gone.
        self._delete_file(file_path=sentinel, missing_ok=True)
        return ObsidianEntry(
            path=normalized,
            name=normalized.rsplit("/", maxsplit=1)[-1],
            entry_type=ObsidianEntryType.DIRECTORY,
        )

    @public_api_instrumented(logger=_LOGGER, component_id=str(RESOURCE_COMPONENT_ID))
    def delete_directory(
        self,
        *,
        directory_path: str,
        recursive: bool,
        missing_ok: bool,
        use_trash: bool,
    ) -> bool:
        """Delete one directory, optionally recursively."""
        del use_trash  # Not supported by Local REST API.
        normalized = _normalize_directory_path(directory_path)

        try:
            entries = self.list_directory(directory_path=normalized)
        except ObsidianAdapterNotFoundError:
            if missing_ok:
                return False
            raise

        if not recursive and len(entries) > 0:
            raise ObsidianAdapterConflictError(
                "directory delete requires recursive=true for non-empty directories"
            )

        if recursive:
            for file_path in self._iter_files_under_directory(normalized):
                self._delete_file(file_path=file_path, missing_ok=True)
        try:
            self._request_raw(
                method="DELETE",
                endpoint=_vault_directory_endpoint(normalized),
                accept="application/json",
            )
        except ObsidianAdapterNotFoundError:
            if missing_ok:
                return False
            raise
        return True

    @public_api_instrumented(logger=_LOGGER, component_id=str(RESOURCE_COMPONENT_ID))
    def create_file(self, *, file_path: str, content: str) -> ObsidianFileRecord:
        """Create one file and fail when it already exists."""
        normalized = _normalize_file_path(file_path)
        try:
            self.get_file(file_path=normalized)
        except ObsidianAdapterNotFoundError:
            pass
        else:
            raise ObsidianAdapterAlreadyExistsError("file already exists")

        self._request_raw(
            method="PUT",
            endpoint=_vault_file_endpoint(normalized),
            body=content.encode("utf-8"),
            content_type="text/markdown",
            accept="application/json",
        )
        return self.get_file(file_path=normalized)

    @public_api_instrumented(
        logger=_LOGGER,
        component_id=str(RESOURCE_COMPONENT_ID),
        id_fields=("file_path",),
    )
    def get_file(self, *, file_path: str) -> ObsidianFileRecord:
        """Read one file by path."""
        normalized = _normalize_file_path(file_path)
        result = self._request_json(
            method="GET",
            endpoint=_vault_file_endpoint(normalized),
            accept=self._ACCEPT_NOTE_JSON,
        )
        if not isinstance(result.payload, Mapping):
            raise ObsidianAdapterInternalError(
                "obsidian note response must be an object"
            )

        stat = result.payload.get("stat")
        stat_data = stat if isinstance(stat, Mapping) else {}
        revision = str(stat_data.get("mtime", ""))
        return ObsidianFileRecord(
            path=str(result.payload.get("path", normalized)),
            content=str(result.payload.get("content", "")),
            size_bytes=int(stat_data.get("size", 0) or 0),
            created_at=_to_iso_from_epoch_ms(stat_data.get("ctime")),
            updated_at=_to_iso_from_epoch_ms(stat_data.get("mtime")),
            revision=revision,
        )

    @public_api_instrumented(
        logger=_LOGGER,
        component_id=str(RESOURCE_COMPONENT_ID),
        id_fields=("file_path",),
    )
    def update_file(
        self,
        *,
        file_path: str,
        content: str,
        if_revision: str,
        force: bool,
    ) -> ObsidianFileRecord:
        """Replace one file content, optionally guarded by revision token."""
        del if_revision, force  # Concurrency is enforced in service layer.
        normalized = _normalize_file_path(file_path)
        self._request_raw(
            method="PUT",
            endpoint=_vault_file_endpoint(normalized),
            body=content.encode("utf-8"),
            content_type="text/markdown",
            accept="application/json",
        )
        return self.get_file(file_path=normalized)

    @public_api_instrumented(
        logger=_LOGGER,
        component_id=str(RESOURCE_COMPONENT_ID),
        id_fields=("file_path",),
    )
    def append_file(
        self,
        *,
        file_path: str,
        content: str,
        if_revision: str,
        force: bool,
    ) -> ObsidianFileRecord:
        """Append one content fragment to a file."""
        del if_revision, force  # Concurrency is enforced in service layer.
        normalized = _normalize_file_path(file_path)
        self._request_raw(
            method="POST",
            endpoint=_vault_file_endpoint(normalized),
            body=content.encode("utf-8"),
            content_type="text/markdown",
            accept="application/json",
            retryable=False,
        )
        return self.get_file(file_path=normalized)

    @public_api_instrumented(
        logger=_LOGGER,
        component_id=str(RESOURCE_COMPONENT_ID),
        id_fields=("file_path",),
    )
    def edit_file(
        self,
        *,
        file_path: str,
        edits: Sequence[FileEditOperation],
        if_revision: str,
        force: bool,
    ) -> ObsidianFileRecord:
        """Apply line-based edits to a file."""
        del if_revision, force  # Concurrency is enforced in service layer.
        normalized = _normalize_file_path(file_path)
        record = self.get_file(file_path=normalized)
        patched = _apply_line_edits(content=record.content, edits=edits)
        self._request_raw(
            method="PUT",
            endpoint=_vault_file_endpoint(normalized),
            body=patched.encode("utf-8"),
            content_type="text/markdown",
            accept="application/json",
        )
        return self.get_file(file_path=normalized)

    @public_api_instrumented(logger=_LOGGER, component_id=str(RESOURCE_COMPONENT_ID))
    def move_path(
        self,
        *,
        source_path: str,
        target_path: str,
        if_revision: str,
        force: bool,
    ) -> ObsidianEntry:
        """Move or rename one file or directory path."""
        del if_revision, force  # Concurrency is enforced in service layer.
        source = _normalize_relative_path(source_path)
        target = _normalize_relative_path(target_path)
        if source == target:
            raise ObsidianAdapterConflictError(
                "source_path and target_path must differ"
            )

        try:
            file = self.get_file(file_path=source)
        except ObsidianAdapterNotFoundError:
            file = None

        if file is not None:
            self._assert_file_missing(target)
            self._request_raw(
                method="PUT",
                endpoint=_vault_file_endpoint(target),
                body=file.content.encode("utf-8"),
                content_type="text/markdown",
                accept="application/json",
            )
            self._delete_file(file_path=source, missing_ok=False)
            return ObsidianEntry(
                path=target,
                name=target.rsplit("/", maxsplit=1)[-1],
                entry_type=ObsidianEntryType.FILE,
            )

        files = list(self._iter_files_under_directory(source))
        if len(files) == 0:
            raise ObsidianAdapterNotFoundError("source path does not exist")
        try:
            self.list_directory(directory_path=target)
        except ObsidianAdapterNotFoundError:
            pass
        else:
            raise ObsidianAdapterAlreadyExistsError("target directory already exists")

        source_prefix = f"{source}/"
        for file_path in files:
            relative = file_path[len(source_prefix) :]
            destination = f"{target}/{relative}"
            self._assert_file_missing(destination)
            content = self.get_file(file_path=file_path).content
            self._request_raw(
                method="PUT",
                endpoint=_vault_file_endpoint(destination),
                body=content.encode("utf-8"),
                content_type="text/markdown",
                accept="application/json",
            )
            self._delete_file(file_path=file_path, missing_ok=True)

        return ObsidianEntry(
            path=target,
            name=target.rsplit("/", maxsplit=1)[-1],
            entry_type=ObsidianEntryType.DIRECTORY,
        )

    @public_api_instrumented(
        logger=_LOGGER,
        component_id=str(RESOURCE_COMPONENT_ID),
        id_fields=("file_path",),
    )
    def delete_file(
        self,
        *,
        file_path: str,
        missing_ok: bool,
        use_trash: bool,
        if_revision: str,
        force: bool,
    ) -> bool:
        """Delete one file, optionally by moving to Obsidian trash."""
        del use_trash, if_revision, force  # Not supported by Local REST API.
        return self._delete_file(file_path=file_path, missing_ok=missing_ok)

    @public_api_instrumented(logger=_LOGGER, component_id=str(RESOURCE_COMPONENT_ID))
    def search_files(
        self,
        *,
        query: str,
        directory_scope: str,
        limit: int,
    ) -> list[ObsidianSearchMatch]:
        """Run lexical file search through Obsidian Local REST API."""
        result = self._request_json(
            method="POST",
            endpoint="/search/simple/",
            query={"query": query, "contextLength": "120"},
        )
        rows = _ensure_list_of_mappings(result.payload, field="payload")

        scope = _normalize_directory_path(directory_scope)
        scope_prefix = "" if scope == "" else f"{scope}/"
        matches: list[ObsidianSearchMatch] = []
        for row in rows:
            path = str(row.get("filename", ""))
            if path == "":
                continue
            if scope_prefix and not path.startswith(scope_prefix):
                continue
            snippets = _extract_search_context_snippets(row)
            matches.append(
                ObsidianSearchMatch(
                    path=path,
                    score=float(row.get("score", 0.0) or 0.0),
                    snippets=snippets,
                )
            )
            if len(matches) >= limit:
                break

        return matches

    def _iter_files_under_directory(self, directory_path: str) -> Sequence[str]:
        """Yield markdown file paths recursively below one directory path."""
        files: list[str] = []
        for entry in self.list_directory(directory_path=directory_path):
            if entry.entry_type == ObsidianEntryType.FILE:
                files.append(entry.path)
            else:
                files.extend(self._iter_files_under_directory(entry.path))
        return files

    def _delete_file(self, *, file_path: str, missing_ok: bool) -> bool:
        """Issue a file delete request with optional missing-ok semantics."""
        normalized = _normalize_file_path(file_path)
        try:
            self._request_raw(
                method="DELETE",
                endpoint=_vault_file_endpoint(normalized),
                accept="application/json",
            )
        except ObsidianAdapterNotFoundError:
            if missing_ok:
                return False
            raise
        return True

    def _assert_file_missing(self, file_path: str) -> None:
        """Raise already-exists error when a file path currently resolves."""
        try:
            self.get_file(file_path=file_path)
        except ObsidianAdapterNotFoundError:
            return
        raise ObsidianAdapterAlreadyExistsError("target file already exists")

    def _request_json(
        self,
        *,
        method: str,
        endpoint: str,
        query: Mapping[str, str] | None = None,
        body: bytes | None = None,
        content_type: str | None = None,
        accept: str = "application/json",
        retryable: bool = True,
    ) -> _HttpResult:
        """Issue one HTTP request and decode JSON response payload."""
        result = self._request_raw(
            method=method,
            endpoint=endpoint,
            query=query,
            body=body,
            content_type=content_type,
            accept=accept,
            retryable=retryable,
        )

        if isinstance(result.payload, bytes):
            raw = result.payload
            if len(raw) == 0:
                return _HttpResult(status_code=result.status_code, payload={})
            try:
                payload = json.loads(raw.decode("utf-8"))
            except ValueError:
                raise ObsidianAdapterInternalError(
                    "obsidian adapter returned non-JSON response"
                ) from None
            return _HttpResult(status_code=result.status_code, payload=payload)

        return result

    def _request_raw(
        self,
        *,
        method: str,
        endpoint: str,
        query: Mapping[str, str] | None = None,
        body: bytes | None = None,
        content_type: str | None = None,
        accept: str = "application/json",
        retryable: bool = True,
    ) -> _HttpResult:
        """Issue one request and return raw payload bytes with retry semantics."""
        attempts = self._settings.max_retries + 1 if retryable else 1
        last_error: Exception | None = None
        for _ in range(attempts):
            try:
                return self._request_raw_once(
                    method=method,
                    endpoint=endpoint,
                    query=query,
                    body=body,
                    content_type=content_type,
                    accept=accept,
                )
            except ObsidianAdapterDependencyError as exc:
                last_error = exc
                continue
        assert last_error is not None
        raise last_error

    def _request_raw_once(
        self,
        *,
        method: str,
        endpoint: str,
        query: Mapping[str, str] | None,
        body: bytes | None,
        content_type: str | None,
        accept: str,
    ) -> _HttpResult:
        """Issue one raw HTTP request and map status/error classes."""
        headers: dict[str, str] = {"Accept": accept}
        api_key = self._settings.api_key.strip()
        if api_key != "":
            headers["Authorization"] = f"Bearer {api_key}"
        if content_type is not None:
            headers["Content-Type"] = content_type

        encoded_query = ""
        if query:
            items = [(key, value) for key, value in query.items() if value != ""]
            encoded_query = urllib_parse.urlencode(items)

        url = f"{self._base_url}{endpoint}"
        if encoded_query:
            url = f"{url}?{encoded_query}"

        request = urllib_request.Request(
            url=url,
            data=body,
            method=method,
            headers=headers,
        )

        try:
            with urllib_request.urlopen(  # noqa: S310
                request,
                timeout=self._settings.timeout_seconds,
            ) as response:
                status_code = int(getattr(response, "status", 200))
                raw = response.read()
                return _HttpResult(status_code=status_code, payload=raw)
        except urllib_error.HTTPError as exc:
            self._raise_http_error(exc)
        except urllib_error.URLError as exc:
            raise ObsidianAdapterDependencyError(
                f"obsidian adapter request failed: {exc.reason}"
            ) from None
        except TimeoutError as exc:
            raise ObsidianAdapterDependencyError(
                str(exc) or "obsidian request timed out"
            ) from None

        raise ObsidianAdapterInternalError(
            "obsidian adapter request failed unexpectedly"
        )

    def _raise_http_error(self, exc: urllib_error.HTTPError) -> None:
        """Map HTTP status codes into adapter-specific exceptions."""
        status = int(exc.code)
        message = _http_error_message(exc)
        if status in {500, 502, 503, 504, 429, 408}:
            raise ObsidianAdapterDependencyError(message) from None
        if status == 404:
            raise ObsidianAdapterNotFoundError(message) from None
        if status == 409:
            raise ObsidianAdapterAlreadyExistsError(message) from None
        if status == 412:
            raise ObsidianAdapterConflictError(message) from None
        if status in {400, 405}:
            raise ObsidianAdapterInternalError(message) from None
        raise ObsidianAdapterInternalError(message) from None


def _normalize_relative_path(value: str) -> str:
    """Normalize and validate one vault-relative path."""
    try:
        return normalize_vault_relative_path(value, allow_root=False)
    except ValueError as exc:
        raise ObsidianAdapterInternalError(str(exc)) from None


def _normalize_directory_path(value: str) -> str:
    """Normalize an optional directory path where empty means vault root."""
    try:
        return normalize_vault_directory_path(value, allow_root=True)
    except ValueError as exc:
        raise ObsidianAdapterInternalError(str(exc)) from None


def _normalize_file_path(value: str) -> str:
    """Normalize one markdown file path."""
    try:
        return normalize_vault_file_path(value, suffix=".md")
    except ValueError as exc:
        raise ObsidianAdapterInternalError(str(exc)) from None


def _vault_file_endpoint(file_path: str) -> str:
    """Build encoded vault-file endpoint path."""
    return f"/vault/{urllib_parse.quote(file_path, safe='/')}"


def _vault_directory_endpoint(directory_path: str) -> str:
    """Build encoded vault-directory endpoint path."""
    if directory_path == "":
        return "/vault/"
    encoded = urllib_parse.quote(f"{directory_path}/", safe="/")
    return f"/vault/{encoded}"


def _http_error_message(exc: urllib_error.HTTPError) -> str:
    """Extract best-effort error message from an HTTP error response."""
    body = ""
    try:
        raw = exc.read()
    except Exception:  # noqa: BLE001
        raw = b""
    if raw:
        try:
            payload = json.loads(raw.decode("utf-8"))
            if isinstance(payload, Mapping):
                value = payload.get("message") or payload.get("error")
                if isinstance(value, str) and value.strip() != "":
                    body = value.strip()
        except Exception:  # noqa: BLE001
            body = ""
    if body != "":
        return body
    return str(exc.reason) or f"http {exc.code}"


def _ensure_list_of_mappings(
    payload: object, *, field: str
) -> list[Mapping[str, object]]:
    """Validate payload is a list of object mappings."""
    if not isinstance(payload, list):
        raise ObsidianAdapterInternalError(f"obsidian response {field} must be a list")
    items: list[Mapping[str, object]] = []
    for item in payload:
        if not isinstance(item, Mapping):
            raise ObsidianAdapterInternalError(
                f"obsidian response {field} contains invalid item"
            )
        items.append(item)
    return items


def _extract_search_context_snippets(row: Mapping[str, object]) -> tuple[str, ...]:
    """Extract context snippets from search/simple response row."""
    matches = row.get("matches")
    if not isinstance(matches, list):
        return ()
    snippets: list[str] = []
    for item in matches:
        if not isinstance(item, Mapping):
            continue
        context = item.get("context")
        if isinstance(context, str) and context.strip() != "":
            snippets.append(context)
    return tuple(snippets)


def _to_iso_from_epoch_ms(value: object) -> str:
    """Convert epoch-milliseconds value into an ISO-8601 UTC string."""
    if value is None:
        return ""
    try:
        epoch_ms = float(value)
    except (TypeError, ValueError):
        return ""
    from datetime import UTC, datetime

    return datetime.fromtimestamp(epoch_ms / 1000.0, tz=UTC).isoformat()


def _apply_line_edits(content: str, edits: Sequence[FileEditOperation]) -> str:
    """Apply line-range replacement edits against markdown text."""
    lines = content.split("\n")
    for edit in edits:
        start_idx = int(edit.start_line) - 1
        end_idx = int(edit.end_line)
        if start_idx < 0 or end_idx < start_idx or start_idx > len(lines):
            raise ObsidianAdapterInternalError("edit operation line range is invalid")
        replacement = str(edit.content).split("\n")
        lines[start_idx:end_idx] = replacement
    return "\n".join(lines)
