"""SeaweedFS-backed blob substrate over its S3-compatible HTTP surface."""

from __future__ import annotations

from collections.abc import Mapping
from datetime import UTC, datetime
import functools
import hashlib
import hmac
from urllib.parse import quote, urlsplit

import httpx

from lib.shared.blob_validation import normalize_extension
from resources.substrates.seaweedfs.config import SeaweedFSSubstrateSettings
from resources.substrates.seaweedfs.substrate import (
    BlobHealthStatus,
    BlobStat,
    BlobSubstrate,
)

_HEX = frozenset("0123456789abcdef")
_DIGEST_HEX_LENGTH = 64
_FANOUT_CHARS = 2
_DEFAULT_CONTENT_TYPE = "application/octet-stream"


class SeaweedFSBlobSubstrate(BlobSubstrate):
    """Persist and retrieve Object blobs in a SeaweedFS S3 bucket."""

    def __init__(
        self,
        *,
        settings: SeaweedFSSubstrateSettings,
        client: httpx.Client | None = None,
    ) -> None:
        self._settings = settings
        self._client = client or httpx.Client(timeout=settings.request_timeout_seconds)

    def health(self) -> BlobHealthStatus:
        """Return SeaweedFS S3 bucket readiness."""
        try:
            url = self._bucket_url()
            response = self._client.head(url, headers=self._headers("HEAD", url))
        except Exception as exc:  # noqa: BLE001
            return BlobHealthStatus(
                ready=False,
                detail=f"seaweedfs probe failed: {type(exc).__name__}",
            )
        if response.status_code in {httpx.codes.OK, httpx.codes.NO_CONTENT}:
            return BlobHealthStatus(ready=True, detail="ok")
        return BlobHealthStatus(
            ready=False,
            detail=f"seaweedfs bucket probe returned {response.status_code}",
        )

    def resolve_key(self, *, digest_hex: str, extension: str) -> str:
        """Resolve the deterministic SeaweedFS object key for digest and extension."""
        digest = _normalize_digest_hex(digest_hex)
        ext = normalize_extension(value=extension)
        filename = f"{digest}.{ext}"
        suffix = (
            f"{digest[:_FANOUT_CHARS]}/"
            f"{digest[_FANOUT_CHARS : _FANOUT_CHARS * 2]}/"
            f"{filename}"
        )
        if self._settings.key_prefix == "":
            return suffix
        return f"{self._settings.key_prefix}/{suffix}"

    def write_blob(self, *, digest_hex: str, extension: str, content: bytes) -> str:
        """Write one blob to SeaweedFS and return its object key."""
        key = self.resolve_key(digest_hex=digest_hex, extension=extension)
        if self._object_exists(key=key):
            return key

        url = self._object_url(key=key)
        response = self._client.put(
            url,
            content=content,
            headers=self._headers(
                "PUT",
                url,
                body=content,
                extra={
                    "Content-Type": _DEFAULT_CONTENT_TYPE,
                    "Content-Length": str(len(content)),
                },
            ),
        )
        if response.status_code in {
            httpx.codes.OK,
            httpx.codes.CREATED,
            httpx.codes.NO_CONTENT,
        }:
            return key
        if response.status_code == httpx.codes.CONFLICT and self._object_exists(
            key=key
        ):
            return key
        response.raise_for_status()
        return key

    def read_blob(self, *, digest_hex: str, extension: str) -> bytes:
        """Read one blob from SeaweedFS by digest and extension."""
        key = self.resolve_key(digest_hex=digest_hex, extension=extension)
        url = self._object_url(key=key)
        response = self._client.get(url, headers=self._headers("GET", url))
        if response.status_code == httpx.codes.NOT_FOUND:
            raise FileNotFoundError(key)
        response.raise_for_status()
        return response.content

    def stat_blob(self, *, digest_hex: str, extension: str) -> BlobStat:
        """Return metadata for one stored SeaweedFS object."""
        key = self.resolve_key(digest_hex=digest_hex, extension=extension)
        url = self._object_url(key=key)
        response = self._client.head(url, headers=self._headers("HEAD", url))
        if response.status_code == httpx.codes.NOT_FOUND:
            raise FileNotFoundError(key)
        response.raise_for_status()
        return BlobStat(
            key=key,
            size_bytes=_int_header(response.headers, "content-length"),
            etag=response.headers.get("etag", "").strip('"'),
            content_type=response.headers.get("content-type", ""),
        )

    def delete_blob(self, *, digest_hex: str, extension: str) -> bool:
        """Delete one SeaweedFS object and return whether it existed."""
        key = self.resolve_key(digest_hex=digest_hex, extension=extension)
        if not self._object_exists(key=key):
            return False
        url = self._object_url(key=key)
        response = self._client.delete(url, headers=self._headers("DELETE", url))
        if response.status_code == httpx.codes.NOT_FOUND:
            return True
        response.raise_for_status()
        return True

    def _object_exists(self, *, key: str) -> bool:
        """Return whether one object currently exists in the configured bucket."""
        url = self._object_url(key=key)
        response = self._client.head(url, headers=self._headers("HEAD", url))
        if response.status_code == httpx.codes.NOT_FOUND:
            return False
        response.raise_for_status()
        return True

    def _bucket_url(self) -> str:
        """Return the path-style URL for the configured bucket."""
        return f"{self._settings.endpoint_url}/{self._settings.bucket}"

    def _object_url(self, *, key: str) -> str:
        """Return the path-style URL for one object key."""
        return f"{self._bucket_url()}/{key}"

    def _headers(
        self,
        method: str,
        url: str,
        *,
        body: bytes = b"",
        extra: Mapping[str, str] | None = None,
    ) -> dict[str, str]:
        """Return AWS Signature V4 headers for SeaweedFS S3 requests."""
        now = datetime.now(tz=UTC)
        amz_date = now.strftime("%Y%m%dT%H%M%SZ")
        datestamp = now.strftime("%Y%m%d")
        payload_hash = hashlib.sha256(body).hexdigest()
        headers = {
            "Host": _host_header(url),
            "X-Amz-Content-Sha256": payload_hash,
            "X-Amz-Date": amz_date,
        }
        # extra headers (e.g. Content-Type, Content-Length) intentionally unsigned
        if extra is not None:
            headers.update(extra)

        signed_headers = "host;x-amz-content-sha256;x-amz-date"
        canonical_headers = (
            f"host:{headers['Host']}\n"
            f"x-amz-content-sha256:{headers['X-Amz-Content-Sha256']}\n"
            f"x-amz-date:{headers['X-Amz-Date']}\n"
        )
        credential_scope = f"{datestamp}/{self._settings.region}/s3/aws4_request"
        canonical_request = "\n".join(
            [
                method,
                _canonical_uri(url),
                "",
                canonical_headers,
                signed_headers,
                payload_hash,
            ]
        )
        string_to_sign = "\n".join(
            [
                "AWS4-HMAC-SHA256",
                amz_date,
                credential_scope,
                hashlib.sha256(canonical_request.encode("utf-8")).hexdigest(),
            ]
        )
        signing_key = _signing_key(
            secret_access_key=self._settings.secret_access_key,
            datestamp=datestamp,
            region=self._settings.region,
        )
        signature = hmac.new(
            signing_key,
            string_to_sign.encode("utf-8"),
            hashlib.sha256,
        ).hexdigest()
        headers["Authorization"] = (
            "AWS4-HMAC-SHA256 "
            f"Credential={self._settings.access_key_id}/{credential_scope}, "
            f"SignedHeaders={signed_headers}, Signature={signature}"
        )
        return headers


def _normalize_digest_hex(value: str) -> str:
    """Validate and normalize one 64-character sha256 digest hex string."""
    normalized = value.strip().lower()
    if len(normalized) != _DIGEST_HEX_LENGTH:
        raise ValueError("digest_hex must contain exactly 64 hex characters")
    if any(ch not in _HEX for ch in normalized):
        raise ValueError("digest_hex must be hexadecimal")
    return normalized


def _int_header(headers: httpx.Headers, name: str) -> int | None:
    """Parse one integer response header, returning None when absent."""
    raw = headers.get(name)
    if raw is None or raw.strip() == "":
        return None
    return int(raw)


def _host_header(url: str) -> str:
    """Return the canonical HTTP Host header value for a URL."""
    parsed = urlsplit(url)
    if parsed.port is None:
        return parsed.hostname or ""
    return f"{parsed.hostname}:{parsed.port}"


def _canonical_uri(url: str) -> str:
    """Return the AWS SigV4 canonical URI for a URL."""
    path = urlsplit(url).path or "/"
    return quote(path, safe="/~")


@functools.lru_cache(maxsize=8)
def _signing_key(
    *,
    secret_access_key: str,
    datestamp: str,
    region: str,
) -> bytes:
    """Return one AWS Signature V4 signing key, cached per calendar day."""
    date_key = _sign(f"AWS4{secret_access_key}".encode("utf-8"), datestamp)
    region_key = _sign(date_key, region)
    service_key = _sign(region_key, "s3")
    return _sign(service_key, "aws4_request")


def _sign(key: bytes, message: str) -> bytes:
    """Return one HMAC-SHA256 digest."""
    return hmac.new(key, message.encode("utf-8"), hashlib.sha256).digest()
