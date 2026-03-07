"""Tests for shared logging configuration and custom levels."""

from __future__ import annotations

import json
import logging

from packages.brain_shared.logging.config import JsonFormatter, VERBOSE, get_logger


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
