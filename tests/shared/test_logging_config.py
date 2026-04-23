"""Tests for shared logging configuration and custom levels."""

from __future__ import annotations

import json
import logging
from pathlib import Path

from lib.shared.logging.config import (
    JsonFormatter,
    VERBOSE,
    configure_logging,
    get_logger,
)


def test_verbose_level_is_registered() -> None:
    """Shared logging config should register a custom VERBOSE level."""
    logger = get_logger("tests.shared.logging")

    assert logging.getLevelName(VERBOSE) == "VERBOSE"
    assert getattr(logging, "VERBOSE", None) == VERBOSE
    assert hasattr(logger, "verbose")


def test_verbose_level_emits_below_debug(caplog) -> None:
    """Logger.verbose should emit records at a level below DEBUG."""
    logger = get_logger("tests.shared.logging.verbose")

    with caplog.at_level(VERBOSE, logger="tests.shared.logging.verbose"):
        logger.verbose("low-level detail")  # type: ignore[attr-defined]

    assert len(caplog.records) == 1
    assert caplog.records[0].levelno == VERBOSE
    assert caplog.records[0].levelname == "VERBOSE"
    assert caplog.records[0].getMessage() == "low-level detail"


def test_json_formatter_outputs_verbose_level_name() -> None:
    """JSON formatter should preserve the custom level name in output."""
    formatter = JsonFormatter()
    record = logging.LogRecord(
        name="tests.shared.logging.json",
        level=VERBOSE,
        pathname=__file__,
        lineno=1,
        msg="payload",
        args=(),
        exc_info=None,
    )

    rendered = formatter.format(record)
    payload = json.loads(rendered)

    assert payload["level"] == "VERBOSE"
    assert payload["message"] == "payload"


def test_json_formatter_includes_extra_fields() -> None:
    """JSON formatter should preserve custom ``extra=...`` metadata."""
    formatter = JsonFormatter()
    record = logging.LogRecord(
        name="tests.shared.logging.json.extra",
        level=logging.INFO,
        pathname=__file__,
        lineno=1,
        msg="request complete",
        args=(),
        exc_info=None,
    )
    record.service = "switchboard"
    record.operation = "switchboard.poll_operator_instruction"
    record.endpoint = "/switchboard/poll_operator_instruction"
    record.status_code = 200

    rendered = formatter.format(record)
    payload = json.loads(rendered)

    assert payload["service"] == "switchboard"
    assert payload["operation"] == "switchboard.poll_operator_instruction"
    assert payload["endpoint"] == "/switchboard/poll_operator_instruction"
    assert payload["status_code"] == 200


def test_configure_logging_supports_split_stdout_and_file_levels(
    capsys,
    tmp_path: Path,
) -> None:
    """Stdout and file capture should honor independent thresholds."""
    configure_logging(
        level="WARNING",
        file_capture_enabled=True,
        file_capture_level="VERBOSE",
        file_capture_directory=str(tmp_path / "logs"),
        json_output=False,
        process_name="core",
    )
    logger = get_logger("tests.shared.logging.split")

    logger.verbose("verbose detail")  # type: ignore[attr-defined]
    logger.warning("warning detail")

    stdout = capsys.readouterr().out
    assert "warning detail" in stdout
    assert "verbose detail" not in stdout

    log_file = tmp_path / "logs" / "core.log"
    assert log_file.exists()
    contents = log_file.read_text(encoding="utf-8")
    assert "verbose detail" in contents
    assert "warning detail" in contents


def test_configure_logging_uses_process_name_for_file_capture(tmp_path: Path) -> None:
    """File capture should isolate per-process sinks by configured process name."""
    configure_logging(
        level="INFO",
        file_capture_enabled=True,
        file_capture_level="INFO",
        file_capture_directory=str(tmp_path / "logs"),
        json_output=False,
        process_name="agent",
    )

    logger = get_logger("tests.shared.logging.process_name")
    logger.info("agent detail")

    agent_log_file = tmp_path / "logs" / "agent.log"
    assert agent_log_file.exists()
    assert "agent detail" in agent_log_file.read_text(encoding="utf-8")
