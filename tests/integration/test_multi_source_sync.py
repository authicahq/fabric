"""Integration tests for multi-source synchronization."""

from __future__ import annotations

import time
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from fabric.core.models import (
    AppConfig,
    BackendConfig,
    LlamaCppConfig,
    LocalAIConfig,
    SyncConfig,
    SyncMode,
)
from fabric.core.multi_sync import MultiSourceSyncEngine
from fabric.core.sync import SyncEngine


@pytest.fixture
def temp_backend_dirs(tmp_path):
    """Create temporary backend directories."""
    return {
        "llama_cpp": tmp_path / "llama_cpp",
        "localai": tmp_path / "localai",
        "ollama": tmp_path / "ollama",
    }


@pytest.fixture
def mock_backends(temp_backend_dirs):
    """Create mock backends with temporary directories."""
    backends = []
    for name, dir_path in temp_backend_dirs.items():
        dir_path.mkdir()
        backend = MagicMock()
        backend.name = name
        backend.backend_id = name
        backend.output_dir = dir_path
        backend.config = BackendConfig(output_dir=dir_path)
        backends.append(backend)
    return backends


@pytest.fixture
def multi_source_config(temp_backend_dirs):
    """Create a multi-source configuration."""
    return AppConfig(
        source_dir=temp_backend_dirs["llama_cpp"],
        backends={
            "llama_cpp": LlamaCppConfig(
                enabled=True,
                output_dir=temp_backend_dirs["llama_cpp"],
            ),
            "localai": LocalAIConfig(
                enabled=True,
                output_dir=temp_backend_dirs["localai"],
            ),
        },
        sync=SyncConfig(
            mode=SyncMode.MULTI_SOURCE,
            add_only=True,
            metadata_dir=temp_backend_dirs["llama_cpp"].parent / ".fabric",
            cooldown_seconds=0.05,  # Short cooldown for tests
        ),
    )


class TestMultiSourceSyncEngine:
    """Integration tests for MultiSourceSyncEngine."""

    def test_setup_verifies_filesystem(self, multi_source_config, mock_backends, tmp_path):
        """Test that setup verifies all backends are on same filesystem."""
        engine = MultiSourceSyncEngine(multi_source_config, mock_backends)
        engine.setup()  # Should not raise

    def test_full_sync_empty_backends(self, multi_source_config, mock_backends):
        """Test full sync with empty backends."""
        engine = MultiSourceSyncEngine(multi_source_config, mock_backends)
        engine.setup()
        
        result = engine.full_sync()
        
        assert result.success
        assert result.linked == 0
        assert result.conflicts == 0

    def test_full_sync_distributes_models(self, multi_source_config, mock_backends, tmp_path):
        """Test that full sync distributes models to all backends."""
        # Create a model in one backend
        model_file = mock_backends[0].output_dir / "test-model.gguf"
        model_file.write_text("test content")
        
        engine = MultiSourceSyncEngine(multi_source_config, mock_backends)
        engine.setup()
        
        result = engine.full_sync()
        
        assert result.success
        # Should create hardlinks in other backends
        assert result.linked > 0
        
        # Verify hardlink was created
        other_backend = mock_backends[1]
        hardlink_file = other_backend.output_dir / "test-model.gguf"
        assert hardlink_file.exists()
        
        # Verify they have same inode
        assert model_file.stat().st_ino == hardlink_file.stat().st_ino

    def test_full_sync_detects_conflicts(self, multi_source_config, mock_backends):
        """Test that full sync detects existing conflicts."""
        # Create conflicting models
        model_a = mock_backends[0].output_dir / "test-model.gguf"
        model_a.write_text("content A")
        
        model_b = mock_backends[1].output_dir / "test-model.gguf"
        model_b.write_text("content B")  # Different content
        
        engine = MultiSourceSyncEngine(multi_source_config, mock_backends)
        engine.setup()
        
        result = engine.full_sync()
        
        # Should detect the conflict
        assert result.conflicts == 1
        
        # Verify conflict is recorded
        conflicts = engine.conflict_handler.get_unresolved_conflicts()
        assert len(conflicts) == 1
        assert conflicts[0].model_id == "test-model"

    def test_handle_event_new_model(self, multi_source_config, mock_backends):
        """Test handling a new model event."""
        from fabric.core.models import SyncEvent, SyncEventType
        
        engine = MultiSourceSyncEngine(multi_source_config, mock_backends)
        engine.setup()
        
        # Create a model file
        model_file = mock_backends[0].output_dir / "new-model.gguf"
        model_file.write_text("new content")
        
        # Create event
        event = SyncEvent(
            event_type=SyncEventType.FILE_CREATED,
            path=model_file,
            source_dir=mock_backends[0].output_dir,
        )
        
        result = engine.handle_event(event)
        
        # Wait for cooldown
        time.sleep(0.1)
        
        assert result.success
        assert result.linked > 0
        
        # Verify hardlink in other backend
        other_backend = mock_backends[1]
        hardlink_file = other_backend.output_dir / "new-model.gguf"
        assert hardlink_file.exists()

    def test_handle_event_conflict(self, multi_source_config, mock_backends):
        """Test handling an event that creates a conflict."""
        from fabric.core.models import SyncEvent, SyncEventType
        import time
        
        engine = MultiSourceSyncEngine(multi_source_config, mock_backends)
        engine.setup()
        
        # Create initial model in backend A
        model_a = mock_backends[0].output_dir / "conflict-model.gguf"
        model_a.write_text("content A")
        
        engine.full_sync()
        
        # Wait for cooldown to expire
        time.sleep(0.1)
        
        # Delete the hardlinked file in backend B and create different content
        model_b = mock_backends[1].output_dir / "conflict-model.gguf"
        if model_b.exists():
            model_b.unlink()
        model_b.write_text("content B")
        
        event = SyncEvent(
            event_type=SyncEventType.FILE_CREATED,
            path=model_b,
            source_dir=mock_backends[1].output_dir,
        )
        
        result = engine.handle_event(event)
        
        # Should detect conflict
        assert result.conflicts == 1
        
        # Original file should remain (NOT renamed to avoid disrupting backends)
        assert model_b.exists()
        assert model_b.name == "conflict-model.gguf"
        
        # Conflict should be recorded in database
        conflicts = engine.conflict_handler.get_unresolved_conflicts()
        assert len(conflicts) == 1
        assert conflicts[0].model_id == "conflict-model"

    def test_cooldown_prevents_circular_sync(self, multi_source_config, mock_backends):
        """Test that cooldown prevents circular sync loops."""
        from fabric.core.models import SyncEvent, SyncEventType
        
        engine = MultiSourceSyncEngine(multi_source_config, mock_backends)
        engine.setup()
        
        # Create a model
        model_file = mock_backends[0].output_dir / "cooldown-test.gguf"
        model_file.write_text("test content")
        
        # First event should be processed
        event1 = SyncEvent(
            event_type=SyncEventType.FILE_CREATED,
            path=model_file,
            source_dir=mock_backends[0].output_dir,
        )
        engine.handle_event(event1)
        
        # Immediately send another event for the hardlinked file
        hardlink_file = mock_backends[1].output_dir / "cooldown-test.gguf"
        if hardlink_file.exists():
            event2 = SyncEvent(
                event_type=SyncEventType.FILE_CREATED,
                path=hardlink_file,
                source_dir=mock_backends[1].output_dir,
            )
            result = engine.handle_event(event2)
            
            # Should be ignored due to cooldown
            assert result.linked == 0

    def test_origin_tracking(self, multi_source_config, mock_backends):
        """Test that model origins are correctly tracked."""
        from fabric.core.models import SyncEvent, SyncEventType
        
        engine = MultiSourceSyncEngine(multi_source_config, mock_backends)
        engine.setup()
        
        model_file = mock_backends[0].output_dir / "origin-test.gguf"
        model_file.write_text("test content")
        
        event = SyncEvent(
            event_type=SyncEventType.FILE_CREATED,
            path=model_file,
            source_dir=mock_backends[0].output_dir,
        )
        
        engine.handle_event(event)
        
        # Verify origin was recorded
        origin = engine.origin_tracker.get_origin("origin-test")
        assert origin is not None
        assert origin.backend_id == mock_backends[0].backend_id

    def test_is_multi_source_config(self, multi_source_config):
        """Test that multi-source config is correctly identified."""
        assert multi_source_config.is_multi_source is True

    def test_effective_source_dirs(self, multi_source_config, mock_backends):
        """Test that effective source dirs include all backend dirs."""
        source_dirs = multi_source_config.effective_source_dirs
        
        # Should include both enabled backend directories
        assert len(source_dirs) == 2
        assert mock_backends[0].output_dir in source_dirs
        assert mock_backends[1].output_dir in source_dirs


class TestMultiSourceWithConflicts:
    """Tests for conflict handling in multi-source mode."""

    def test_conflict_preservation_records_only(self, multi_source_config, mock_backends):
        """Test that conflicts are recorded but files are NOT renamed."""
        from fabric.core.unified_index import ModelInstance, UnifiedModelEntry
        
        engine = MultiSourceSyncEngine(multi_source_config, mock_backends)
        engine.setup()
        
        # Create existing model
        existing_file = mock_backends[0].output_dir / "test-model.gguf"
        existing_file.write_text("existing content")
        
        existing_entry = UnifiedModelEntry(model_id="test-model")
        existing_entry.add_instance(ModelInstance(
            path=existing_file,
            backend_id=mock_backends[0].backend_id,
            inode=existing_file.stat().st_ino,
            device=existing_file.stat().st_dev,
            mtime=existing_file.stat().st_mtime,
            size=existing_file.stat().st_size,
        ))
        
        # Create conflicting new model
        new_file = mock_backends[1].output_dir / "test-model.gguf"
        new_file.write_text("new content")
        
        new_instance = ModelInstance(
            path=new_file,
            backend_id=mock_backends[1].backend_id,
            inode=new_file.stat().st_ino,
            device=new_file.stat().st_dev,
            mtime=new_file.stat().st_mtime,
            size=new_file.stat().st_size,
        )
        
        # Handle conflict
        success = engine.conflict_handler.handle_conflict(
            new_instance, existing_entry
        )
        
        assert success is True
        # File should NOT be renamed - left in place
        assert new_file.exists()
        assert new_file.name == "test-model.gguf"
        
        # But conflict should be recorded
        conflicts = engine.conflict_handler.get_unresolved_conflicts()
        assert len(conflicts) == 1
        assert conflicts[0].model_id == "test-model"

    def test_conflict_database_records_all_instances(self, multi_source_config, mock_backends):
        """Test that conflict database records all instances."""
        from fabric.core.unified_index import ModelInstance, UnifiedModelEntry
        
        engine = MultiSourceSyncEngine(multi_source_config, mock_backends)
        engine.setup()
        
        # Create entry with multiple instances
        entry = UnifiedModelEntry(model_id="multi-conflict")
        
        for i, backend in enumerate(mock_backends):
            file_path = backend.output_dir / f"multi-conflict-v{i}.gguf"
            file_path.write_text(f"content {i}")
            entry.add_instance(ModelInstance(
                path=file_path,
                backend_id=backend.backend_id,
                inode=file_path.stat().st_ino,
                device=file_path.stat().st_dev,
                mtime=file_path.stat().st_mtime,
                size=file_path.stat().st_size,
            ))
        
        # Add conflict
        new_file = mock_backends[0].output_dir / "multi-conflict.conflict.test.gguf"
        new_file.write_text("conflict content")
        new_instance = ModelInstance(
            path=new_file,
            backend_id="test_backend",
            inode=new_file.stat().st_ino,
            device=new_file.stat().st_dev,
            mtime=new_file.stat().st_mtime,
            size=new_file.stat().st_size,
        )
        
        engine.conflict_handler.handle_conflict(new_instance, entry)
        
        # Verify database
        conflicts = engine.conflict_handler.get_unresolved_conflicts()
        assert len(conflicts) == 1
        assert len(conflicts[0].instances) == len(mock_backends) + 1


class TestMultiSourceFilesystemVerification:
    """Tests for filesystem verification."""

    def test_cross_filesystem_detection(self, tmp_path):
        """Test that cross-filesystem setups are detected."""
        # This test would need actual different filesystems to test properly
        # For now, we just verify the method exists and runs
        config = MagicMock()
        config.sync.metadata_dir = tmp_path / ".fabric"
        config.sync.cooldown_seconds = 0.1
        
        backend = MagicMock()
        backend.output_dir = tmp_path / "backend"
        backend.output_dir.mkdir()
        backend.backend_id = "test"
        
        engine = MultiSourceSyncEngine(config, [backend])
        
        # Should not raise for same filesystem
        engine._verify_filesystem()
