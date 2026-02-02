"""Tests for extraction sandbox boundary."""

from __future__ import annotations

from ingestion.sandbox import SandboxConfig, SandboxExecutor


def test_sandbox_executor_success() -> None:
    """Test that sandbox wrapper executes successfully."""
    executor = SandboxExecutor(config=SandboxConfig(enabled=False))

    def sample_func(x: int, y: int) -> int:
        return x + y

    result = executor.execute(sample_func, 2, 3)

    assert result.success is True
    assert result.result == 5
    assert result.error is None


def test_sandbox_executor_catches_failure() -> None:
    """Test that sandbox wrapper catches and records failures."""
    executor = SandboxExecutor(config=SandboxConfig(enabled=False))

    def failing_func() -> int:
        raise ValueError("test error")

    result = executor.execute(failing_func)

    assert result.success is False
    assert result.result is None
    assert result.error is not None
    assert "ValueError: test error" in result.error


def test_sandbox_executor_with_kwargs() -> None:
    """Test sandbox executor with keyword arguments."""
    executor = SandboxExecutor(config=SandboxConfig(enabled=False))

    def sample_func(a: int, b: int, c: int = 10) -> int:
        return a + b + c

    result = executor.execute(sample_func, 1, 2, c=3)

    assert result.success is True
    assert result.result == 6
    assert result.error is None


def test_sandbox_config_defaults() -> None:
    """Test that sandbox config has reasonable defaults."""
    config = SandboxConfig()

    assert config.timeout_seconds == 300
    assert config.max_memory_mb is None
    assert config.enabled is True


def test_sandboxed_extraction_failure_records_error() -> None:
    """Test that sandboxed extraction failures are recorded as stage errors."""
    # This is a conceptual test demonstrating the intent.
    # The actual integration is tested in Stage 2 extraction runner tests.

    executor = SandboxExecutor(config=SandboxConfig(enabled=False))

    def extraction_that_crashes() -> list:
        raise RuntimeError("extractor crashed")

    result = executor.execute(extraction_that_crashes)

    # Verify failure is caught and recorded, not propagated
    assert result.success is False
    assert result.error is not None
    assert "RuntimeError: extractor crashed" in result.error
