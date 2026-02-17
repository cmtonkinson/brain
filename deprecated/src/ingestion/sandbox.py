"""Sandbox execution boundary for extraction tool isolation."""

from __future__ import annotations

import logging
import subprocess
import sys
from dataclasses import dataclass
from typing import Any, Callable

LOGGER = logging.getLogger(__name__)


@dataclass(frozen=True)
class SandboxConfig:
    """Configuration for sandbox execution limits."""

    timeout_seconds: int = 300  # 5 minutes default
    max_memory_mb: int | None = None  # No limit by default
    enabled: bool = True


@dataclass(frozen=True)
class SandboxResult:
    """Result of a sandboxed execution attempt."""

    success: bool
    result: Any | None
    error: str | None


class SandboxExecutor:
    """Executor that runs extraction operations with isolation boundaries."""

    def __init__(self, config: SandboxConfig | None = None) -> None:
        """
        Initialize the sandbox executor with optional configuration.

        Args:
            config: Sandbox configuration. If None, uses defaults.
        """
        self._config = config or SandboxConfig()

    def execute(self, func: Callable[..., Any], *args: Any, **kwargs: Any) -> SandboxResult:
        """
        Execute a function with sandbox isolation.

        If sandboxing is disabled, runs the function directly. Otherwise, runs it
        with resource limits and timeout protection.

        Args:
            func: The function to execute.
            *args: Positional arguments to pass to the function.
            **kwargs: Keyword arguments to pass to the function.

        Returns:
            SandboxResult containing the outcome of the execution.
        """
        if not self._config.enabled:
            # Sandbox disabled, run directly
            try:
                result = func(*args, **kwargs)
                return SandboxResult(success=True, result=result, error=None)
            except Exception as exc:
                error_text = f"{type(exc).__name__}: {exc}"
                LOGGER.exception("Direct execution failed: %s", error_text)
                return SandboxResult(success=False, result=None, error=error_text)

        # Run with isolation and timeout
        try:
            result = self._execute_with_timeout(func, *args, **kwargs)
            return SandboxResult(success=True, result=result, error=None)
        except subprocess.TimeoutExpired:
            error_text = f"Execution timeout after {self._config.timeout_seconds}s"
            LOGGER.warning("Sandboxed execution timeout: %s", error_text)
            return SandboxResult(success=False, result=None, error=error_text)
        except Exception as exc:
            error_text = f"{type(exc).__name__}: {exc}"
            LOGGER.exception("Sandboxed execution failed: %s", error_text)
            return SandboxResult(success=False, result=None, error=error_text)

    def _execute_with_timeout(self, func: Callable[..., Any], *args: Any, **kwargs: Any) -> Any:
        """
        Execute function with timeout protection.

        This is a simplified implementation that runs the function with a timeout.
        In a production system, this would use subprocess isolation or containers.

        Args:
            func: The function to execute.
            *args: Positional arguments.
            **kwargs: Keyword arguments.

        Returns:
            The function result.

        Raises:
            TimeoutError: If execution exceeds the configured timeout.
            Any exception raised by the function.
        """
        # For now, we run the function directly with a Python-level timeout
        # In production, this would be subprocess-based or use Docker/firejail
        import signal
        from contextlib import contextmanager

        @contextmanager
        def timeout_context(seconds: int):
            """Context manager for timeout using signals."""

            def timeout_handler(signum, frame):
                raise TimeoutError(f"Execution exceeded {seconds}s timeout")

            # Set the signal handler and alarm
            old_handler = signal.signal(signal.SIGALRM, timeout_handler)
            signal.alarm(seconds)
            try:
                yield
            finally:
                # Restore old handler and cancel alarm
                signal.alarm(0)
                signal.signal(signal.SIGALRM, old_handler)

        # Execute with timeout
        if sys.platform == "win32":
            # Windows doesn't support SIGALRM, run without timeout
            LOGGER.warning("Sandbox timeout not supported on Windows, running without timeout")
            return func(*args, **kwargs)
        else:
            with timeout_context(self._config.timeout_seconds):
                return func(*args, **kwargs)


def sandboxed_extraction(func: Callable[..., Any]) -> Callable[..., SandboxResult]:
    """
    Decorator to wrap extraction functions with sandbox isolation.

    Usage:
        @sandboxed_extraction
        def my_extractor(context):
            # extraction logic
            return result

    Args:
        func: The extraction function to wrap.

    Returns:
        A wrapped function that returns a SandboxResult.
    """
    executor = SandboxExecutor()

    def wrapper(*args: Any, **kwargs: Any) -> SandboxResult:
        return executor.execute(func, *args, **kwargs)

    wrapper.__name__ = func.__name__
    wrapper.__doc__ = func.__doc__
    return wrapper
