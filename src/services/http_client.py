"""HTTP client wrapper with configurable error handling and retry logic.

This module provides lightweight HTTP client wrappers that eliminate boilerplate
for service-to-service communication. Key features:

- Centralized timeout configuration
- Pluggable error handling strategies
- Optional retry logic with exponential backoff
- Improved testability through dependency injection

Usage Examples:

    # Simple async GET with default error handling (raises on errors)
    client = AsyncHttpClient()
    response = await client.get("https://api.example.com/data")

    # Sync POST with custom error handling (log and return None)
    client = HttpClient(
        timeout=60,
        error_config=ErrorConfig(strategy=ErrorStrategy.LOG_AND_RETURN_NONE)
    )
    response = client.post("https://api.example.com/endpoint", json={...})
    if response is None:
        return []  # Service handles gracefully

    # With retries for transient failures
    client = AsyncHttpClient(
        retry_config=RetryConfig(
            max_attempts=3,
            retry_status_codes={500, 502, 503, 504},
            backoff_factor=2.0
        )
    )
    response = await client.get("https://flaky-api.example.com/data")

Design Decisions:

- **Separate async/sync classes**: Brain uses both patterns extensively, keeping
  them separate improves clarity and type safety.
- **Context manager per call**: Matches existing pattern (fresh client per operation),
  simplifies error handling and resource cleanup.
- **Error strategies match existing patterns**: Signal/Obsidian log and return None,
  vector search raises, Letta has custom fallback logic (kept in service).
- **Retries opt-in**: Default is no retries for backward compatibility, enable
  per-service as needed for idempotent operations.
"""

from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass, field
from enum import Enum

import httpx

from config import settings

logger = logging.getLogger(__name__)


class ErrorStrategy(Enum):
    """Strategy for handling HTTP errors.

    - RAISE: Re-raise exceptions (default, for strict error handling)
    - LOG_AND_RETURN_NONE: Log error and return None (for graceful degradation)
    - LOG_AND_SUPPRESS: Log error and suppress exception (for fire-and-forget)
    """

    RAISE = "raise"
    LOG_AND_RETURN_NONE = "log_and_return_none"
    LOG_AND_SUPPRESS = "log_and_suppress"


@dataclass
class ErrorConfig:
    """Configuration for error handling behavior.

    Args:
        strategy: How to handle HTTP errors
        log_level: Logging level for errors (default: ERROR)
        include_response_body: Whether to log response body on errors
    """

    strategy: ErrorStrategy = ErrorStrategy.RAISE
    log_level: int = logging.ERROR
    include_response_body: bool = False


@dataclass
class RetryConfig:
    """Configuration for retry logic with exponential backoff.

    Args:
        max_attempts: Maximum number of attempts (including initial attempt)
        retry_status_codes: HTTP status codes that should trigger a retry
        backoff_factor: Multiplier for exponential backoff (delay = backoff_factor * 2^attempt)
        max_backoff: Maximum backoff delay in seconds
        retry_exceptions: Exception types that should trigger a retry
    """

    max_attempts: int = 3
    retry_status_codes: set[int] = field(default_factory=lambda: {500, 502, 503, 504})
    backoff_factor: float = 2.0
    max_backoff: float = 60.0
    retry_exceptions: tuple[type[Exception], ...] = (
        httpx.ConnectError,
        httpx.ReadTimeout,
        httpx.PoolTimeout,
    )


class AsyncHttpClient:
    """Async HTTP client with configurable error handling and retries.

    This client wraps httpx.AsyncClient to provide:
    - Default timeout from settings.http.timeout
    - Pluggable error handling strategies
    - Optional retry logic with exponential backoff
    - Clean resource management via context managers

    Args:
        timeout: Request timeout in seconds (default: settings.http.timeout)
        connect_timeout: Connection timeout in seconds (default: settings.http.connect_timeout)
        error_config: Error handling configuration
        retry_config: Retry configuration (None = no retries)

    Example:
        # Default behavior (raises on errors, no retries)
        client = AsyncHttpClient()
        response = await client.get("https://api.example.com/data")

        # With custom error handling
        client = AsyncHttpClient(
            error_config=ErrorConfig(strategy=ErrorStrategy.LOG_AND_RETURN_NONE)
        )
        response = await client.get("https://api.example.com/data")
        if response is None:
            # Handle gracefully
            return default_value
    """

    def __init__(
        self,
        timeout: int | None = None,
        connect_timeout: int | None = None,
        error_config: ErrorConfig | None = None,
        retry_config: RetryConfig | None = None,
    ):
        """Initialize the async HTTP client."""
        self.timeout = timeout if timeout is not None else settings.http.timeout
        self.connect_timeout = (
            connect_timeout if connect_timeout is not None else settings.http.connect_timeout
        )
        self.error_config = error_config or ErrorConfig()
        self.retry_config = retry_config

    async def get(self, url: str, **kwargs) -> httpx.Response | None:
        """Perform an async GET request.

        Args:
            url: Target URL
            **kwargs: Additional arguments passed to httpx (headers, params, etc.)

        Returns:
            Response object, or None if error_strategy is LOG_AND_RETURN_NONE

        Raises:
            httpx.HTTPError: If error_strategy is RAISE and request fails
        """
        return await self._request("GET", url, **kwargs)

    async def post(self, url: str, **kwargs) -> httpx.Response | None:
        """Perform an async POST request.

        Args:
            url: Target URL
            **kwargs: Additional arguments passed to httpx (json, data, headers, etc.)

        Returns:
            Response object, or None if error_strategy is LOG_AND_RETURN_NONE

        Raises:
            httpx.HTTPError: If error_strategy is RAISE and request fails
        """
        return await self._request("POST", url, **kwargs)

    async def put(self, url: str, **kwargs) -> httpx.Response | None:
        """Perform an async PUT request.

        Args:
            url: Target URL
            **kwargs: Additional arguments passed to httpx (json, data, headers, etc.)

        Returns:
            Response object, or None if error_strategy is LOG_AND_RETURN_NONE

        Raises:
            httpx.HTTPError: If error_strategy is RAISE and request fails
        """
        return await self._request("PUT", url, **kwargs)

    async def patch(self, url: str, **kwargs) -> httpx.Response | None:
        """Perform an async PATCH request.

        Args:
            url: Target URL
            **kwargs: Additional arguments passed to httpx (json, data, headers, etc.)

        Returns:
            Response object, or None if error_strategy is LOG_AND_RETURN_NONE

        Raises:
            httpx.HTTPError: If error_strategy is RAISE and request fails
        """
        return await self._request("PATCH", url, **kwargs)

    async def delete(self, url: str, **kwargs) -> httpx.Response | None:
        """Perform an async DELETE request.

        Args:
            url: Target URL
            **kwargs: Additional arguments passed to httpx (headers, params, etc.)

        Returns:
            Response object, or None if error_strategy is LOG_AND_RETURN_NONE

        Raises:
            httpx.HTTPError: If error_strategy is RAISE and request fails
        """
        return await self._request("DELETE", url, **kwargs)

    async def _request(self, method: str, url: str, **kwargs) -> httpx.Response | None:
        """Execute an HTTP request with error handling and optional retries."""
        if self.retry_config is None:
            return await self._execute_once(method, url, **kwargs)
        return await self._execute_with_retry(method, url, **kwargs)

    async def _execute_once(self, method: str, url: str, **kwargs) -> httpx.Response | None:
        """Execute a single HTTP request with error handling."""
        try:
            async with httpx.AsyncClient(
                timeout=httpx.Timeout(self.timeout, connect=self.connect_timeout)
            ) as client:
                response = await client.request(method, url, **kwargs)
                response.raise_for_status()
                return response
        except (httpx.HTTPStatusError, httpx.RequestError) as e:
            return self._handle_error(e, method, url)

    async def _execute_with_retry(self, method: str, url: str, **kwargs) -> httpx.Response | None:
        """Execute an HTTP request with retry logic and exponential backoff."""
        assert self.retry_config is not None
        last_exception = None

        for attempt in range(self.retry_config.max_attempts):
            try:
                async with httpx.AsyncClient(
                    timeout=httpx.Timeout(self.timeout, connect=self.connect_timeout)
                ) as client:
                    response = await client.request(method, url, **kwargs)
                    response.raise_for_status()
                    return response
            except httpx.HTTPStatusError as e:
                last_exception = e
                # Only retry on specific status codes
                if e.response.status_code not in self.retry_config.retry_status_codes:
                    return self._handle_error(e, method, url)
                # Don't retry on last attempt
                if attempt + 1 >= self.retry_config.max_attempts:
                    break
                # Exponential backoff
                delay = min(
                    self.retry_config.backoff_factor * (2**attempt),
                    self.retry_config.max_backoff,
                )
                logger.warning(
                    f"HTTP {method} {url} failed with status {e.response.status_code}, "
                    f"retrying in {delay:.1f}s (attempt {attempt + 1}/{self.retry_config.max_attempts})"
                )
                await asyncio.sleep(delay)
            except self.retry_config.retry_exceptions as e:
                last_exception = e
                # Don't retry on last attempt
                if attempt + 1 >= self.retry_config.max_attempts:
                    break
                # Exponential backoff
                delay = min(
                    self.retry_config.backoff_factor * (2**attempt),
                    self.retry_config.max_backoff,
                )
                logger.warning(
                    f"HTTP {method} {url} failed with {type(e).__name__}, "
                    f"retrying in {delay:.1f}s (attempt {attempt + 1}/{self.retry_config.max_attempts})"
                )
                await asyncio.sleep(delay)
            except httpx.RequestError as e:
                # Non-retryable request error
                last_exception = e
                break

        # All retries exhausted or non-retryable error
        return self._handle_error(last_exception, method, url)

    def _handle_error(self, error: Exception, method: str, url: str) -> httpx.Response | None:
        """Handle HTTP errors according to configured strategy."""
        if self.error_config.strategy == ErrorStrategy.RAISE:
            raise error

        # Log the error
        error_msg = f"HTTP {method} {url} failed: {error}"
        if isinstance(error, httpx.HTTPStatusError) and self.error_config.include_response_body:
            error_msg += f"\nResponse body: {error.response.text}"
        logger.log(self.error_config.log_level, error_msg)

        if self.error_config.strategy == ErrorStrategy.LOG_AND_RETURN_NONE:
            return None
        # LOG_AND_SUPPRESS
        return None


class HttpClient:
    """Synchronous HTTP client with configurable error handling and retries.

    This client wraps httpx.Client to provide:
    - Default timeout from settings.http.timeout
    - Pluggable error handling strategies
    - Optional retry logic with exponential backoff
    - Clean resource management via context managers

    Args:
        timeout: Request timeout in seconds (default: settings.http.timeout)
        connect_timeout: Connection timeout in seconds (default: settings.http.connect_timeout)
        error_config: Error handling configuration
        retry_config: Retry configuration (None = no retries)

    Example:
        # Default behavior (raises on errors, no retries)
        client = HttpClient()
        response = client.get("https://api.example.com/data")

        # With custom error handling
        client = HttpClient(
            error_config=ErrorConfig(strategy=ErrorStrategy.LOG_AND_RETURN_NONE)
        )
        response = client.get("https://api.example.com/data")
        if response is None:
            # Handle gracefully
            return default_value
    """

    def __init__(
        self,
        timeout: int | None = None,
        connect_timeout: int | None = None,
        error_config: ErrorConfig | None = None,
        retry_config: RetryConfig | None = None,
    ):
        """Initialize the synchronous HTTP client."""
        self.timeout = timeout if timeout is not None else settings.http.timeout
        self.connect_timeout = (
            connect_timeout if connect_timeout is not None else settings.http.connect_timeout
        )
        self.error_config = error_config or ErrorConfig()
        self.retry_config = retry_config

    def get(self, url: str, **kwargs) -> httpx.Response | None:
        """Perform a synchronous GET request.

        Args:
            url: Target URL
            **kwargs: Additional arguments passed to httpx (headers, params, etc.)

        Returns:
            Response object, or None if error_strategy is LOG_AND_RETURN_NONE

        Raises:
            httpx.HTTPError: If error_strategy is RAISE and request fails
        """
        return self._request("GET", url, **kwargs)

    def post(self, url: str, **kwargs) -> httpx.Response | None:
        """Perform a synchronous POST request.

        Args:
            url: Target URL
            **kwargs: Additional arguments passed to httpx (json, data, headers, etc.)

        Returns:
            Response object, or None if error_strategy is LOG_AND_RETURN_NONE

        Raises:
            httpx.HTTPError: If error_strategy is RAISE and request fails
        """
        return self._request("POST", url, **kwargs)

    def put(self, url: str, **kwargs) -> httpx.Response | None:
        """Perform a synchronous PUT request.

        Args:
            url: Target URL
            **kwargs: Additional arguments passed to httpx (json, data, headers, etc.)

        Returns:
            Response object, or None if error_strategy is LOG_AND_RETURN_NONE

        Raises:
            httpx.HTTPError: If error_strategy is RAISE and request fails
        """
        return self._request("PUT", url, **kwargs)

    def patch(self, url: str, **kwargs) -> httpx.Response | None:
        """Perform a synchronous PATCH request.

        Args:
            url: Target URL
            **kwargs: Additional arguments passed to httpx (json, data, headers, etc.)

        Returns:
            Response object, or None if error_strategy is LOG_AND_RETURN_NONE

        Raises:
            httpx.HTTPError: If error_strategy is RAISE and request fails
        """
        return self._request("PATCH", url, **kwargs)

    def delete(self, url: str, **kwargs) -> httpx.Response | None:
        """Perform a synchronous DELETE request.

        Args:
            url: Target URL
            **kwargs: Additional arguments passed to httpx (headers, params, etc.)

        Returns:
            Response object, or None if error_strategy is LOG_AND_RETURN_NONE

        Raises:
            httpx.HTTPError: If error_strategy is RAISE and request fails
        """
        return self._request("DELETE", url, **kwargs)

    def _request(self, method: str, url: str, **kwargs) -> httpx.Response | None:
        """Execute an HTTP request with error handling and optional retries."""
        if self.retry_config is None:
            return self._execute_once(method, url, **kwargs)
        return self._execute_with_retry(method, url, **kwargs)

    def _execute_once(self, method: str, url: str, **kwargs) -> httpx.Response | None:
        """Execute a single HTTP request with error handling."""
        try:
            with httpx.Client(
                timeout=httpx.Timeout(self.timeout, connect=self.connect_timeout)
            ) as client:
                response = client.request(method, url, **kwargs)
                response.raise_for_status()
                return response
        except (httpx.HTTPStatusError, httpx.RequestError) as e:
            return self._handle_error(e, method, url)

    def _execute_with_retry(self, method: str, url: str, **kwargs) -> httpx.Response | None:
        """Execute an HTTP request with retry logic and exponential backoff."""
        assert self.retry_config is not None
        last_exception = None

        for attempt in range(self.retry_config.max_attempts):
            try:
                with httpx.Client(
                    timeout=httpx.Timeout(self.timeout, connect=self.connect_timeout)
                ) as client:
                    response = client.request(method, url, **kwargs)
                    response.raise_for_status()
                    return response
            except httpx.HTTPStatusError as e:
                last_exception = e
                # Only retry on specific status codes
                if e.response.status_code not in self.retry_config.retry_status_codes:
                    return self._handle_error(e, method, url)
                # Don't retry on last attempt
                if attempt + 1 >= self.retry_config.max_attempts:
                    break
                # Exponential backoff
                delay = min(
                    self.retry_config.backoff_factor * (2**attempt),
                    self.retry_config.max_backoff,
                )
                logger.warning(
                    f"HTTP {method} {url} failed with status {e.response.status_code}, "
                    f"retrying in {delay:.1f}s (attempt {attempt + 1}/{self.retry_config.max_attempts})"
                )
                time.sleep(delay)
            except self.retry_config.retry_exceptions as e:
                last_exception = e
                # Don't retry on last attempt
                if attempt + 1 >= self.retry_config.max_attempts:
                    break
                # Exponential backoff
                delay = min(
                    self.retry_config.backoff_factor * (2**attempt),
                    self.retry_config.max_backoff,
                )
                logger.warning(
                    f"HTTP {method} {url} failed with {type(e).__name__}, "
                    f"retrying in {delay:.1f}s (attempt {attempt + 1}/{self.retry_config.max_attempts})"
                )
                time.sleep(delay)
            except httpx.RequestError as e:
                # Non-retryable request error
                last_exception = e
                break

        # All retries exhausted or non-retryable error
        return self._handle_error(last_exception, method, url)

    def _handle_error(self, error: Exception, method: str, url: str) -> httpx.Response | None:
        """Handle HTTP errors according to configured strategy."""
        if self.error_config.strategy == ErrorStrategy.RAISE:
            raise error

        # Log the error
        error_msg = f"HTTP {method} {url} failed: {error}"
        if isinstance(error, httpx.HTTPStatusError) and self.error_config.include_response_body:
            error_msg += f"\nResponse body: {error.response.text}"
        logger.log(self.error_config.log_level, error_msg)

        if self.error_config.strategy == ErrorStrategy.LOG_AND_RETURN_NONE:
            return None
        # LOG_AND_SUPPRESS
        return None
