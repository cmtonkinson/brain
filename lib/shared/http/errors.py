"""Typed errors for shared HTTP client and server helpers."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Mapping


@dataclass
class HttpError(Exception):
    """Base error type for shared HTTP helper failures."""

    message: str

    def __str__(self) -> str:
        """Return the human-readable error message."""
        return self.message


@dataclass
class HttpClientError(HttpError):
    """Base error for outbound HTTP client call failures."""

    method: str
    url: str
    retryable: bool = False


@dataclass
class HttpRequestError(HttpClientError):
    """HTTP client transport-level failure."""

    cause: Exception | None = None


@dataclass
class HttpStatusError(HttpClientError):
    """HTTP client non-success status code failure."""

    status_code: int = 0
    response_body: str = ""
    response_headers: Mapping[str, str] = field(default_factory=dict)


@dataclass
class HttpJsonDecodeError(HttpClientError):
    """HTTP client JSON decode failure for a successful response."""

    status_code: int = 0
    response_body: str = ""
    cause: Exception | None = None


@dataclass
class HttpServerError(HttpError):
    """Base error type for inbound HTTP parsing/validation helpers."""


@dataclass
class MissingHeaderError(HttpServerError):
    """Required inbound HTTP header is missing or blank."""

    header_name: str


@dataclass
class InvalidBodyError(HttpServerError):
    """Inbound HTTP body is invalid for the expected shape."""


@dataclass
class InvalidJsonBodyError(InvalidBodyError):
    """Inbound HTTP body is not valid JSON."""
