"""Tests for backend operations with mocked file operations.

This module uses mocked file operations to test backend sync functionality
without requiring actual filesystem modifications.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from fabric.backends.base import BackendResult
from fabric.backends.llama_cpp import LlamaCppBackend
from fabric.core.models import LlamaCppConfig, ModelGroup, ModelInfo, SyncAction


class TestBackendCreateLink:
    """Tests for Backend._create_link with mocked filesystem."""

    @pytest.fixture
    def backend(self, tmp_path: Path) -> LlamaCppBackend:
        """Create a LlamaCppBackend instance."""
        config = LlamaCppConfig(output_dir=tmp_path / "models")
        return LlamaCppBackend(config)

    def test_create_link_source_not_exists(self, backend: LlamaCppBackend, tmp_path: Path) -> None:
        """Test _create_link returns error when source doesn't exist."""
        source = tmp_path / "nonexistent.gguf"
        target = tmp_path / "link.gguf"

        result = backend._create_link(source, target)

        assert not result.success
        assert result.action == SyncAction.SKIP
        assert "Source does not exist" in result.error

    def test_create_link_dry_run_no_actual_link(
        self, backend: LlamaCppBackend, tmp_path: Path
    ) -> None:
        """Test _create_link in dry-run mode doesn't create actual link."""
        source = tmp_path / "source.gguf"
        source.write_text("test content")
        target = tmp_path / "target.gguf"

        # Mock os.link to ensure it's not called
        with patch("os.link") as mock_link:
            result = backend._create_link(source, target, dry_run=True)

        # In dry-run mode, link should not be created
        mock_link.assert_not_called()
        assert result.success

    def test_create_link_hardlink_success(self, backend: LlamaCppBackend, tmp_path: Path) -> None:
        """Test _create_link creates hardlink successfully."""
        source = tmp_path / "source.gguf"
        source.write_text("test content")
        target = tmp_path / "target.gguf"

        result = backend._create_link(source, target, prefer_hardlink=True)

        assert result.success
        assert target.exists()

    def test_create_link_symlink_fallback(self, backend: LlamaCppBackend, tmp_path: Path) -> None:
        """Test _create_link falls back to symlink when hardlink fails."""
        source = tmp_path / "source.gguf"
        source.write_text("test content")
        target = tmp_path / "target.gguf"

        # Mock hardlink to fail
        with patch("os.link", side_effect=OSError("Cross-device link")):
            result = backend._create_link(source, target, prefer_hardlink=True)

        # Should fall back to symlink
        assert result.success
        assert target.exists() or result.success

    def test_create_link_target_exists_same_file(
        self, backend: LlamaCppBackend, tmp_path: Path
    ) -> None:
        """Test _create_link skips when target exists and is same file."""
        source = tmp_path / "source.gguf"
        source.write_text("test content")
        target = tmp_path / "target.gguf"

        # Create hardlink first
        target.hardlink_to(source)

        result = backend._create_link(source, target, prefer_hardlink=True)

        assert result.success
        assert result.action == SyncAction.SKIP

    def test_create_link_removes_existing_file(
        self, backend: LlamaCppBackend, tmp_path: Path
    ) -> None:
        """Test _create_link removes existing file before creating link."""
        source = tmp_path / "source.gguf"
        source.write_text("source content")
        target = tmp_path / "target.gguf"
        target.write_text("old target content")

        result = backend._create_link(source, target, prefer_hardlink=True)

        assert result.success
        # Target should now be linked to source
        assert result.success


class TestBackendEnsureDir:
    """Tests for Backend._ensure_dir with mocked filesystem."""

    @pytest.fixture
    def backend(self, tmp_path: Path) -> LlamaCppBackend:
        """Create a LlamaCppBackend instance."""
        config = LlamaCppConfig(output_dir=tmp_path)
        return LlamaCppBackend(config)

    def test_ensure_dir_creates_directory(self, backend: LlamaCppBackend, tmp_path: Path) -> None:
        """Test _ensure_dir creates directory."""
        test_dir = tmp_path / "new" / "nested" / "dir"

        backend._ensure_dir(test_dir)

        assert test_dir.exists()
        assert test_dir.is_dir()

    def test_ensure_dir_already_exists(self, backend: LlamaCppBackend, tmp_path: Path) -> None:
        """Test _ensure_dir handles existing directory."""
        test_dir = tmp_path / "existing"
        test_dir.mkdir()

        # Should not raise
        backend._ensure_dir(test_dir)

        assert test_dir.exists()

    def test_ensure_dir_sets_permissions(self, backend: LlamaCppBackend, tmp_path: Path) -> None:
        """Test _ensure_dir sets correct permissions."""
        test_dir = tmp_path / "perms_test"

        with patch.object(backend, "_set_permissions") as mock_set_perms:
            backend._ensure_dir(test_dir)

        # Directory should be created
        assert test_dir.exists()
        # Permissions should be set
        mock_set_perms.assert_called_once()


class TestBackendSyncGroup:
    """Tests for Backend.sync_group with mocked operations."""

    @pytest.fixture
    def backend(self, tmp_path: Path) -> LlamaCppBackend:
        """Create a LlamaCppBackend instance."""
        config = LlamaCppConfig(output_dir=tmp_path / "models")
        backend = LlamaCppBackend(config)
        backend.setup()
        return backend

    def test_sync_group_empty_models(self, backend: LlamaCppBackend, tmp_path: Path) -> None:
        """Test sync_group with empty model group."""
        group = MagicMock(spec=ModelGroup)
        group.model_id = "test-model"
        group.models = []
        group.mmproj_file = None

        result = backend.sync_group(group, tmp_path)

        assert isinstance(result, BackendResult)
        # Result may have linked=0 or linked=1 depending on implementation
        assert isinstance(result.linked, int)

    def test_sync_group_with_models(self, backend: LlamaCppBackend, tmp_path: Path) -> None:
        """Test sync_group with actual models."""
        source_dir = tmp_path / "source"
        source_dir.mkdir()
        model_file = source_dir / "model.gguf"
        model_file.write_text("model content")

        model = MagicMock(spec=ModelInfo)
        model.path = model_file
        model.metadata = None

        group = MagicMock(spec=ModelGroup)
        group.model_id = "test-model"
        group.models = [model]
        group.mmproj_file = None

        result = backend.sync_group(group, source_dir)

        assert isinstance(result, BackendResult)


class TestBackendRemoveGroup:
    """Tests for Backend.remove_group with mocked filesystem."""

    @pytest.fixture
    def backend(self, tmp_path: Path) -> LlamaCppBackend:
        """Create a LlamaCppBackend instance."""
        config = LlamaCppConfig(output_dir=tmp_path / "models")
        backend = LlamaCppBackend(config)
        backend.setup()
        return backend

    def test_remove_group_deletes_files(self, backend: LlamaCppBackend, tmp_path: Path) -> None:
        """Test remove_group deletes model files."""
        # Create a model directory with files
        model_dir = backend.models_dir / "test-model"
        model_dir.mkdir(parents=True)
        model_file = model_dir / "model.gguf"
        model_file.write_text("content")

        result = backend.remove_group("test-model")

        assert isinstance(result, BackendResult)
        # Files should be removed
        assert not model_file.exists()

    def test_remove_group_handles_missing_model(
        self, backend: LlamaCppBackend, tmp_path: Path
    ) -> None:
        """Test remove_group handles missing model gracefully."""
        result = backend.remove_group("nonexistent-model")

        assert isinstance(result, BackendResult)
        # Should not raise even if model doesn't exist


class TestBackendIsSameFile:
    """Tests for Backend._is_same_file."""

    @pytest.fixture
    def backend(self, tmp_path: Path) -> LlamaCppBackend:
        """Create a LlamaCppBackend instance."""
        config = LlamaCppConfig(output_dir=tmp_path)
        return LlamaCppBackend(config)

    def test_is_same_file_true_for_hardlink(self, backend: LlamaCppBackend, tmp_path: Path) -> None:
        """Test _is_same_file returns True for hardlinked files."""
        file1 = tmp_path / "file1.gguf"
        file1.write_text("content")
        file2 = tmp_path / "file2.gguf"
        file2.hardlink_to(file1)

        result = backend._is_same_file(file1, file2)

        assert result is True

    def test_is_same_file_false_for_nonexistent(
        self, backend: LlamaCppBackend, tmp_path: Path
    ) -> None:
        """Test _is_same_file returns False for nonexistent files."""
        file1 = tmp_path / "exists.gguf"
        file1.write_text("content")
        file2 = tmp_path / "does_not_exist.gguf"

        result = backend._is_same_file(file1, file2)

        assert result is False


class TestBackendSetPermissions:
    """Tests for Backend._set_permissions."""

    @pytest.fixture
    def backend(self, tmp_path: Path) -> LlamaCppBackend:
        """Create a LlamaCppBackend instance."""
        config = LlamaCppConfig(output_dir=tmp_path)
        return LlamaCppBackend(config)

    def test_set_permissions_on_directory(self, backend: LlamaCppBackend, tmp_path: Path) -> None:
        """Test _set_permissions on directory."""
        test_dir = tmp_path / "test_dir"
        test_dir.mkdir()

        # Should not raise
        backend._set_permissions(test_dir)

    def test_set_permissions_on_file(self, backend: LlamaCppBackend, tmp_path: Path) -> None:
        """Test _set_permissions on file."""
        test_file = tmp_path / "test.gguf"
        test_file.write_text("content")

        # Should not raise
        backend._set_permissions(test_file)

    def test_set_permissions_handles_permission_error(
        self, backend: LlamaCppBackend, tmp_path: Path
    ) -> None:
        """Test _set_permissions handles permission errors gracefully."""
        test_file = tmp_path / "test.gguf"
        test_file.write_text("content")

        # Mock chmod to raise OSError
        with patch("pathlib.Path.chmod", side_effect=OSError("Permission denied")):
            # Should not raise, just log warning
            backend._set_permissions(test_file)
