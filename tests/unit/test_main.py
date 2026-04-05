"""Tests for CLI main module."""

from __future__ import annotations

from pathlib import Path

import pytest
import typer

from fabric.main import get_backends, version_callback


class TestVersionCallback:
    """Tests for version callback."""

    def test_version_callback_raises_exit(self) -> None:
        """Test that version callback raises Exit."""
        with pytest.raises(typer.Exit):
            version_callback(True)

    def test_version_callback_no_exit(self) -> None:
        """Test that version callback without value does not exit."""
        # Should not raise
        version_callback(False)


class TestGetBackends:
    """Tests for get_backends function."""

    @pytest.fixture
    def mock_backends(self) -> dict:
        """Create mock backend configs."""
        from fabric.core.models import (
            LlamaCppConfig,
            LocalAIConfig,
            OllamaConfig,
        )

        return {
            "llama_cpp": LlamaCppConfig(output_dir=Path("/tmp/llama")),
            "localai": LocalAIConfig(output_dir=Path("/tmp/localai")),
            "ollama": OllamaConfig(output_dir=Path("/tmp/ollama")),
        }

    def test_get_backends_returns_list(self, mock_backends: dict) -> None:
        """Test that get_backends returns a list."""
        from fabric.core.models import AppConfig

        config = AppConfig(
            source_dir=Path("/tmp/models"),
            backends=mock_backends,
        )
        result = get_backends(config)
        assert isinstance(result, list)
        assert len(result) == 3

    def test_get_backends_skips_disabled(self, mock_backends: dict) -> None:
        """Test that disabled backends are skipped."""
        from fabric.core.models import AppConfig, OllamaConfig

        mock_backends["ollama"] = OllamaConfig(
            output_dir=Path("/tmp/ollama"),
            enabled=False,
        )
        config = AppConfig(
            source_dir=Path("/tmp/models"),
            backends=mock_backends,
        )
        result = get_backends(config)
        assert len(result) == 2

    def test_get_backends_handles_unknown_type(self) -> None:
        """Test that unknown backend types are skipped gracefully."""
        from fabric.core.models import AppConfig, LlamaCppConfig

        config = AppConfig(
            source_dir=Path("/tmp/models"),
            backends={"llama_cpp": LlamaCppConfig(output_dir=Path("/tmp/llama"))},
        )

        class UnknownBackendConfig:
            enabled = True
            output_dir = Path("/tmp/unknown")

        config.backends = {
            "llama_cpp": LlamaCppConfig(output_dir=Path("/tmp/llama")),
            "unknown": UnknownBackendConfig(),
        }

        result = get_backends(config)
        assert len(result) == 1

    def test_get_backends_all_types(self) -> None:
        """Test get_backends with all backend types."""
        from fabric.core.models import (
            AppConfig,
            GPT4AllConfig,
            JanConfig,
            KoboldCppConfig,
            LlamaCppConfig,
            LlamaCppPythonConfig,
            LMStudioConfig,
            LocalAIConfig,
            OllamaConfig,
            TextGenConfig,
            vLLMConfig,
        )

        backends = {
            "llama_cpp": LlamaCppConfig(output_dir=Path("/tmp/llama")),
            "localai": LocalAIConfig(output_dir=Path("/tmp/localai")),
            "lmstudio": LMStudioConfig(output_dir=Path("/tmp/lmstudio")),
            "ollama": OllamaConfig(output_dir=Path("/tmp/ollama")),
            "textgen": TextGenConfig(output_dir=Path("/tmp/textgen")),
            "gpt4all": GPT4AllConfig(output_dir=Path("/tmp/gpt4all")),
            "koboldcpp": KoboldCppConfig(output_dir=Path("/tmp/koboldcpp")),
            "vllm": vLLMConfig(output_dir=Path("/tmp/vllm")),
            "jan": JanConfig(output_dir=Path("/tmp/jan")),
            "llama_cpp_python": LlamaCppPythonConfig(output_dir=Path("/tmp/llama-cpp-python")),
        }
        config = AppConfig(
            source_dir=Path("/tmp/models"),
            backends=backends,
        )
        result = get_backends(config)
        assert len(result) == 10


class TestAppConfig:
    """Tests for AppConfig default values."""

    def test_default_source_dir(self) -> None:
        """Test default source directory."""
        from fabric.core.models import AppConfig

        config = AppConfig()
        assert config.source_dir == Path("/models")

    def test_default_backends_empty(self) -> None:
        """Test default backends are empty."""
        from fabric.core.models import AppConfig

        config = AppConfig()
        assert config.backends == {}

    def test_default_watch_config(self) -> None:
        """Test default watch configuration."""
        from fabric.core.models import AppConfig, WatchConfig

        config = AppConfig()
        assert isinstance(config.watch, WatchConfig)
        assert config.watch.enabled is False

    def test_default_logging_config(self) -> None:
        """Test default logging configuration."""
        from fabric.core.models import AppConfig, LoggingConfig

        config = AppConfig()
        assert isinstance(config.logging, LoggingConfig)
        assert config.logging.level == "INFO"

    def test_default_sync_config(self) -> None:
        """Test default sync configuration."""
        from fabric.core.models import AppConfig, SyncConfig

        config = AppConfig()
        assert isinstance(config.sync, SyncConfig)
        assert config.sync.prefer_hardlinks is True


class TestCLICommands:
    """Tests for CLI commands - simple function tests."""

    pass


class TestMainModuleAttributes:
    """Tests for main module attributes."""

    def test_app_object_exists(self) -> None:
        """Test that the app object exists."""
        from fabric.main import app

        assert app is not None

    def test_console_object_exists(self) -> None:
        """Test that the console object exists."""
        from fabric.main import console

        assert console is not None
