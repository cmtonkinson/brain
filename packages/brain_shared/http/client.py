"""Minimal shared HTTP client wrappers over httpx."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

import httpx

from .errors import HttpJsonDecodeError, HttpRequestError, HttpStatusError


def _response_text(response: httpx.Response) -> str:
    """Return response text without raising secondary decode errors."""
    try:
        return response.text
    except Exception:
        return ""


def _status_error(response: httpx.Response) -> HttpStatusError:
    """Build a typed status error from one HTTP response."""
    status_code = response.status_code
    retryable = status_code >= 500 or status_code == 429
    return HttpStatusError(
        message=f"HTTP {status_code} for {response.request.method} {response.request.url}",
        method=response.request.method,
        url=str(response.request.url),
        retryable=retryable,
        status_code=status_code,
        response_body=_response_text(response),
        response_headers=dict(response.headers.items()),
    )


class HttpClient:
    """Thin synchronous wrapper over ``httpx.Client``."""

    def __init__(
        self,
        *,
        base_url: str = "",
        timeout_seconds: float = 10.0,
        headers: Mapping[str, str] | None = None,
        follow_redirects: bool = False,
        transport: httpx.BaseTransport | None = None,
        client: httpx.Client | None = None,
    ) -> None:
        """Create a new shared HTTP client wrapper."""
        self._owns_client = client is None
        self._client = client or httpx.Client(
            base_url=base_url,
            timeout=timeout_seconds,
            headers=dict(headers or {}),
            follow_redirects=follow_redirects,
            transport=transport,
        )

    def close(self) -> None:
        """Close underlying transport resources when owned."""
        if self._owns_client:
            self._client.close()

    def __enter__(self) -> HttpClient:
        """Enter context manager scope."""
        return self

    def __exit__(self, *_: object) -> None:
        """Exit context manager scope and close client."""
        self.close()

    def request(
        self,
        method: str,
        url: str,
        *,
        raise_for_status: bool = True,
        **kwargs: Any,
    ) -> httpx.Response:
        """Issue one request and map transport/status failures to typed errors."""
        try:
            response = self._client.request(method=method, url=url, **kwargs)
        except httpx.RequestError as exc:
            request = exc.request
            request_url = str(request.url) if request is not None else url
            request_method = request.method if request is not None else method.upper()
            raise HttpRequestError(
                message=f"HTTP request failed for {request_method} {request_url}",
                method=request_method,
                url=request_url,
                retryable=True,
                cause=exc,
            ) from exc

        if raise_for_status and response.is_error:
            raise _status_error(response)
        return response

    def get(self, url: str, **kwargs: Any) -> httpx.Response:
        """Issue one GET request."""
        return self.request("GET", url, **kwargs)

    def post(self, url: str, **kwargs: Any) -> httpx.Response:
        """Issue one POST request."""
        return self.request("POST", url, **kwargs)

    def put(self, url: str, **kwargs: Any) -> httpx.Response:
        """Issue one PUT request."""
        return self.request("PUT", url, **kwargs)

    def patch(self, url: str, **kwargs: Any) -> httpx.Response:
        """Issue one PATCH request."""
        return self.request("PATCH", url, **kwargs)

    def delete(self, url: str, **kwargs: Any) -> httpx.Response:
        """Issue one DELETE request."""
        return self.request("DELETE", url, **kwargs)

    def request_json(self, method: str, url: str, **kwargs: Any) -> Any:
        """Issue one request and decode JSON from a successful response."""
        response = self.request(method, url, **kwargs)
        try:
            return response.json()
        except ValueError as exc:
            raise HttpJsonDecodeError(
                message=f"Invalid JSON response for {response.request.method} {response.request.url}",
                method=response.request.method,
                url=str(response.request.url),
                retryable=False,
                status_code=response.status_code,
                response_body=_response_text(response),
                cause=exc,
            ) from exc

    def get_json(self, url: str, **kwargs: Any) -> Any:
        """Issue one GET request and decode JSON."""
        return self.request_json("GET", url, **kwargs)

    def post_json(self, url: str, *, json: Any, **kwargs: Any) -> Any:
        """Issue one POST request with a JSON body and decode JSON response."""
        return self.request_json("POST", url, json=json, **kwargs)


class AsyncHttpClient:
    """Thin asynchronous wrapper over ``httpx.AsyncClient``."""

    def __init__(
        self,
        *,
        base_url: str = "",
        timeout_seconds: float = 10.0,
        headers: Mapping[str, str] | None = None,
        follow_redirects: bool = False,
        transport: httpx.AsyncBaseTransport | None = None,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        """Create a new shared asynchronous HTTP client wrapper."""
        self._owns_client = client is None
        self._client = client or httpx.AsyncClient(
            base_url=base_url,
            timeout=timeout_seconds,
            headers=dict(headers or {}),
            follow_redirects=follow_redirects,
            transport=transport,
        )

    async def aclose(self) -> None:
        """Close underlying transport resources when owned."""
        if self._owns_client:
            await self._client.aclose()

    async def __aenter__(self) -> AsyncHttpClient:
        """Enter async context manager scope."""
        return self

    async def __aexit__(self, *_: object) -> None:
        """Exit async context manager scope and close client."""
        await self.aclose()

    async def request(
        self,
        method: str,
        url: str,
        *,
        raise_for_status: bool = True,
        **kwargs: Any,
    ) -> httpx.Response:
        """Issue one request and map transport/status failures to typed errors."""
        try:
            response = await self._client.request(method=method, url=url, **kwargs)
        except httpx.RequestError as exc:
            request = exc.request
            request_url = str(request.url) if request is not None else url
            request_method = request.method if request is not None else method.upper()
            raise HttpRequestError(
                message=f"HTTP request failed for {request_method} {request_url}",
                method=request_method,
                url=request_url,
                retryable=True,
                cause=exc,
            ) from exc

        if raise_for_status and response.is_error:
            raise _status_error(response)
        return response

    async def get(self, url: str, **kwargs: Any) -> httpx.Response:
        """Issue one GET request."""
        return await self.request("GET", url, **kwargs)

    async def post(self, url: str, **kwargs: Any) -> httpx.Response:
        """Issue one POST request."""
        return await self.request("POST", url, **kwargs)

    async def put(self, url: str, **kwargs: Any) -> httpx.Response:
        """Issue one PUT request."""
        return await self.request("PUT", url, **kwargs)

    async def patch(self, url: str, **kwargs: Any) -> httpx.Response:
        """Issue one PATCH request."""
        return await self.request("PATCH", url, **kwargs)

    async def delete(self, url: str, **kwargs: Any) -> httpx.Response:
        """Issue one DELETE request."""
        return await self.request("DELETE", url, **kwargs)

    async def request_json(self, method: str, url: str, **kwargs: Any) -> Any:
        """Issue one request and decode JSON from a successful response."""
        response = await self.request(method, url, **kwargs)
        try:
            return response.json()
        except ValueError as exc:
            raise HttpJsonDecodeError(
                message=f"Invalid JSON response for {response.request.method} {response.request.url}",
                method=response.request.method,
                url=str(response.request.url),
                retryable=False,
                status_code=response.status_code,
                response_body=_response_text(response),
                cause=exc,
            ) from exc

    async def get_json(self, url: str, **kwargs: Any) -> Any:
        """Issue one GET request and decode JSON."""
        return await self.request_json("GET", url, **kwargs)

    async def post_json(self, url: str, *, json: Any, **kwargs: Any) -> Any:
        """Issue one POST request with a JSON body and decode JSON response."""
        return await self.request_json("POST", url, json=json, **kwargs)
