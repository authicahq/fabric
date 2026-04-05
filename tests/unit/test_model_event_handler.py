"""Tests for ModelEventHandler."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

import pytest

from fabric.core.watcher import DownloadDetector, ModelEventHandler


class TestModelEventHandler:
    """Tests for ModelEventHandler class."""

    @pytest.fixture
    def handler(self) -> ModelEventHandler:
        """Create a ModelEventHandler instance."""
        callback = MagicMock()
        detector = DownloadDetector()
        return ModelEventHandler(
            callback=callback,
            source_dirs=[Path("/models")],
            download_detector=detector,
        )

    def test_handler_init(self, handler: ModelEventHandler) -> None:
        """Test ModelEventHandler initialization."""
        assert handler.callback is not None
        assert handler.source_dirs == [Path("/models")]
        assert handler.download_detector is not None

    def test_on_created_with_directory(self, handler: ModelEventHandler) -> None:
        """Test on_created with directory event."""
        mock_event = MagicMock()
        mock_event.is_directory = True
        mock_event.src_path = "/models/newdir"

        handler.on_created(mock_event)
        # Callback should not be called for directories
        handler.callback.assert_not_called()

    def test_on_created_with_non_gguf(self, handler: ModelEventHandler) -> None:
        """Test on_created with non-GGUF file."""
        mock_event = MagicMock()
        mock_event.is_directory = False
        mock_event.src_path = "/models/readme.txt"

        handler.on_created(mock_event)
        # Callback should not be called for non-GGUF files
        handler.callback.assert_not_called()

    def test_on_modified_with_directory(self, handler: ModelEventHandler) -> None:
        """Test on_modified with directory event."""
        mock_event = MagicMock()
        mock_event.is_directory = True
        mock_event.src_path = "/models"

        handler.on_modified(mock_event)
        handler.callback.assert_not_called()

    def test_on_deleted_with_directory(self, handler: ModelEventHandler) -> None:
        """Test on_deleted with directory event."""
        mock_event = MagicMock()
        mock_event.is_directory = True
        mock_event.src_path = "/models"

        handler.on_deleted(mock_event)
        handler.callback.assert_not_called()

    def test_on_deleted_with_non_gguf(self, handler: ModelEventHandler) -> None:
        """Test on_deleted with non-GGUF file."""
        mock_event = MagicMock()
        mock_event.is_directory = False
        mock_event.src_path = "/models/readme.txt"

        handler.on_deleted(mock_event)
        handler.callback.assert_not_called()

    def test_on_moved_with_directory(self, handler: ModelEventHandler) -> None:
        """Test on_moved with directory event."""
        mock_event = MagicMock()
        mock_event.is_directory = True
        mock_event.src_path = "/models/olddir"
        mock_event.dest_path = "/models/newdir"

        handler.on_moved(mock_event)
        handler.callback.assert_not_called()


class TestModelEventHandlerGetSourceDir:
    """Tests for ModelEventHandler._get_source_dir method."""

    @pytest.fixture
    def handler(self) -> ModelEventHandler:
        """Create a ModelEventHandler instance."""
        callback = MagicMock()
        detector = DownloadDetector()
        return ModelEventHandler(
            callback=callback,
            source_dirs=[Path("/models"), Path("/data/models")],
            download_detector=detector,
        )

    def test_get_source_dir_exact_match(self, handler: ModelEventHandler) -> None:
        """Test _get_source_dir with exact path match."""
        result = handler._get_source_dir(Path("/models"))
        assert result == Path("/models")

    def test_get_source_dir_subpath(self, handler: ModelEventHandler) -> None:
        """Test _get_source_dir with subpath."""
        result = handler._get_source_dir(Path("/models/llama/test.gguf"))
        assert result == Path("/models")

    def test_get_source_dir_no_match(self, handler: ModelEventHandler) -> None:
        """Test _get_source_dir with no matching source dir."""
        result = handler._get_source_dir(Path("/other/path"))
        assert result is None

    def test_get_source_dir_second_source(self, handler: ModelEventHandler) -> None:
        """Test _get_source_dir matches second source dir."""
        result = handler._get_source_dir(Path("/data/models/test.gguf"))
        assert result == Path("/data/models")
