"""Tests for logging module."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

import structlog


class TestSetupLogging:
    """Tests for setup_logging function."""

    def test_setup_logging_default(self) -> None:
        """Test default logging setup."""
        from fabric.core.logging import setup_logging

        setup_logging()
        logger = structlog.get_logger("test")
        assert logger is not None

    def test_setup_logging_verbose(self) -> None:
        """Test verbose logging setup."""
        from fabric.core.logging import setup_logging

        setup_logging(verbose=True)
        logger = structlog.get_logger("test-verbose")
        assert logger is not None

    def test_setup_logging_json(self) -> None:
        """Test JSON logging setup."""
        from fabric.core.logging import setup_logging

        setup_logging(json_format=True)
        logger = structlog.get_logger("test-json")
        assert logger is not None

    def test_setup_logging_with_file(self) -> None:
        """Test logging with file output (currently a no-op)."""
        from fabric.core.logging import setup_logging

        setup_logging(log_file=Path("/tmp/test.log"))
        logger = structlog.get_logger("test-file")
        assert logger is not None


class TestGetLogger:
    """Tests for get_logger function."""

    def test_get_logger_with_name(self) -> None:
        """Test getting logger with explicit name."""
        from fabric.core.logging import get_logger

        logger = get_logger("test.logger")
        assert logger is not None

    def test_get_logger_without_name(self) -> None:
        """Test getting logger without name (uses caller module)."""
        from fabric.core.logging import get_logger

        logger = get_logger()
        assert logger is not None


class TestLogAction:
    """Tests for log_action function."""

    def test_log_action_dry_run(self) -> None:
        """Test log_action with dry run enabled."""
        from fabric.core.logging import log_action

        logger = MagicMock()
        log_action(logger, "link", "test model", dry_run=True)
        logger.info.assert_called_once()
        call_args = logger.info.call_args
        assert call_args[1]["dry_run"] is True

    def test_log_action_no_dry_run(self) -> None:
        """Test log_action without dry run."""
        from fabric.core.logging import log_action

        logger = MagicMock()
        log_action(logger, "link", "test model", dry_run=False)
        logger.info.assert_called_once()
        call_args = logger.info.call_args
        assert "dry_run" not in call_args[1]

    def test_log_action_with_extra_kwargs(self) -> None:
        """Test log_action with extra keyword arguments."""
        from fabric.core.logging import log_action

        logger = MagicMock()
        log_action(logger, "link", "test model", source="/models", dest="/output")
        logger.info.assert_called_once()
        call_kwargs = logger.info.call_args[1]
        assert call_kwargs["source"] == "/models"
        assert call_kwargs["dest"] == "/output"
