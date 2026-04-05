"""Unit tests for multi-source synchronization."""

from __future__ import annotations

import time
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from fabric.core.conflict_resolver import (
    ConflictDatabase,
    ConflictPreservationHandler,
)
from fabric.core.cooldown import SyncCooldownManager
from fabric.core.models import normalize_model_id
from fabric.core.origin_tracker import OriginTracker
from fabric.core.unified_index import ModelInstance, UnifiedIndex, UnifiedModelEntry


class TestModelInstance:
    """Tests for ModelInstance."""

    def test_model_id_extraction(self, tmp_path):
        """Test that model_id is correctly extracted from filename."""
        path = tmp_path / "model-name-Q4_K_M.gguf"
        instance = ModelInstance(
            path=path,
            backend_id="test_backend",
            inode=123,
            device=1,
            mtime=time.time(),
            size=1000,
        )
        assert instance.model_id == "model-name-q4-k-m"

    def test_same_content_same_inode(self):
        """Test same_content returns True for same inode/device."""
        instance1 = ModelInstance(
            path=Path("/a/model.gguf"),
            backend_id="backend_a",
            inode=123,
            device=1,
            mtime=100.0,
            size=1000,
        )
        instance2 = ModelInstance(
            path=Path("/b/model.gguf"),
            backend_id="backend_b",
            inode=123,
            device=1,
            mtime=200.0,
            size=2000,
        )
        assert instance1.same_content(instance2)
        assert instance2.same_content(instance1)

    def test_same_content_different_size(self):
        """Test same_content returns False for different size."""
        instance1 = ModelInstance(
            path=Path("/a/model.gguf"),
            backend_id="backend_a",
            inode=123,
            device=1,
            mtime=100.0,
            size=1000,
        )
        instance2 = ModelInstance(
            path=Path("/b/model.gguf"),
            backend_id="backend_b",
            inode=456,
            device=1,
            mtime=100.0,
            size=2000,
        )
        assert not instance1.same_content(instance2)

    def test_same_content_different_mtime(self):
        """Test same_content returns False for different mtime."""
        instance1 = ModelInstance(
            path=Path("/a/model.gguf"),
            backend_id="backend_a",
            inode=123,
            device=1,
            mtime=100.0,
            size=1000,
        )
        instance2 = ModelInstance(
            path=Path("/b/model.gguf"),
            backend_id="backend_b",
            inode=456,
            device=1,
            mtime=200.0,
            size=1000,
        )
        assert not instance1.same_content(instance2)


class TestUnifiedModelEntry:
    """Tests for UnifiedModelEntry."""

    def test_no_conflicts_single_instance(self):
        """Test no conflicts with single instance."""
        entry = UnifiedModelEntry(model_id="test-model")
        instance = ModelInstance(
            path=Path("/a/model.gguf"),
            backend_id="backend_a",
            inode=123,
            device=1,
            mtime=100.0,
            size=1000,
        )
        entry.add_instance(instance)
        assert not entry.has_conflicts
        assert entry.unique_content_count == 1

    def test_no_conflicts_same_content(self):
        """Test no conflicts with hardlinked instances."""
        entry = UnifiedModelEntry(model_id="test-model")
        instance1 = ModelInstance(
            path=Path("/a/model.gguf"),
            backend_id="backend_a",
            inode=123,
            device=1,
            mtime=100.0,
            size=1000,
        )
        instance2 = ModelInstance(
            path=Path("/b/model.gguf"),
            backend_id="backend_b",
            inode=123,
            device=1,
            mtime=100.0,
            size=1000,
        )
        entry.add_instance(instance1)
        entry.add_instance(instance2)
        assert not entry.has_conflicts
        assert entry.unique_content_count == 1

    def test_has_conflicts_different_content(self):
        """Test conflict detection with different content."""
        entry = UnifiedModelEntry(model_id="test-model")
        instance1 = ModelInstance(
            path=Path("/a/model.gguf"),
            backend_id="backend_a",
            inode=123,
            device=1,
            mtime=100.0,
            size=1000,
        )
        instance2 = ModelInstance(
            path=Path("/b/model.gguf"),
            backend_id="backend_b",
            inode=456,
            device=1,
            mtime=100.0,
            size=2000,
        )
        entry.add_instance(instance1)
        entry.add_instance(instance2)
        assert entry.has_conflicts
        assert entry.unique_content_count == 2

    def test_newest_instance(self):
        """Test newest_instance property."""
        entry = UnifiedModelEntry(model_id="test-model")
        instance1 = ModelInstance(
            path=Path("/a/model.gguf"),
            backend_id="backend_a",
            inode=123,
            device=1,
            mtime=100.0,
            size=1000,
        )
        instance2 = ModelInstance(
            path=Path("/b/model.gguf"),
            backend_id="backend_b",
            inode=456,
            device=1,
            mtime=200.0,
            size=1000,
        )
        entry.add_instance(instance1)
        entry.add_instance(instance2)
        assert entry.newest_instance == instance2

    def test_largest_instance(self):
        """Test largest_instance property."""
        entry = UnifiedModelEntry(model_id="test-model")
        instance1 = ModelInstance(
            path=Path("/a/model.gguf"),
            backend_id="backend_a",
            inode=123,
            device=1,
            mtime=100.0,
            size=1000,
        )
        instance2 = ModelInstance(
            path=Path("/b/model.gguf"),
            backend_id="backend_b",
            inode=456,
            device=1,
            mtime=100.0,
            size=2000,
        )
        entry.add_instance(instance1)
        entry.add_instance(instance2)
        assert entry.largest_instance == instance2

    def test_get_instance_for_backend(self):
        """Test get_instance_for_backend method."""
        entry = UnifiedModelEntry(model_id="test-model")
        instance = ModelInstance(
            path=Path("/a/model.gguf"),
            backend_id="backend_a",
            inode=123,
            device=1,
            mtime=100.0,
            size=1000,
        )
        entry.add_instance(instance)
        assert entry.get_instance_for_backend("backend_a") == instance
        assert entry.get_instance_for_backend("backend_b") is None


class TestUnifiedIndex:
    """Tests for UnifiedIndex."""

    @pytest.fixture
    def mock_backends(self, tmp_path):
        """Create mock backends with temporary directories."""
        backend_a = MagicMock()
        backend_a.output_dir = tmp_path / "backend_a"
        backend_a.output_dir.mkdir()

        backend_b = MagicMock()
        backend_b.output_dir = tmp_path / "backend_b"
        backend_b.output_dir.mkdir()

        return {"backend_a": backend_a, "backend_b": backend_b}

    def test_build_index_empty(self, mock_backends):
        """Test building index with empty backends."""
        index = UnifiedIndex(mock_backends)
        index.build()
        assert len(index.entries) == 0

    def test_build_index_with_files(self, mock_backends, tmp_path):
        """Test building index with model files."""
        # Create model files
        (mock_backends["backend_a"].output_dir / "model1.gguf").write_text("content1")
        (mock_backends["backend_b"].output_dir / "model1.gguf").write_text("content1")
        (mock_backends["backend_a"].output_dir / "model2.gguf").write_text("content2")

        index = UnifiedIndex(mock_backends)
        index.build()

        assert len(index.entries) == 2
        assert "model1" in index.entries
        assert "model2" in index.entries
        assert len(index.entries["model1"].instances) == 2
        assert len(index.entries["model2"].instances) == 1

    def test_get_conflicts(self, mock_backends, tmp_path):
        """Test conflict detection."""
        # Create conflicting files (same name, different content)
        (mock_backends["backend_a"].output_dir / "model.gguf").write_text("content_a")
        (mock_backends["backend_b"].output_dir / "model.gguf").write_text("content_b")

        index = UnifiedIndex(mock_backends)
        index.build()

        conflicts = index.get_conflicts()
        assert len(conflicts) == 1
        assert conflicts[0].model_id == "model"

    def test_extract_model_id_conflict_file(self):
        """Test extraction of model_id from conflict filename."""
        index = UnifiedIndex({})
        model_id = index._extract_model_id("model-name.conflict.backend.gguf")
        assert model_id == "model-name"

    def test_add_and_remove_instance(self):
        """Test adding and removing instances."""
        index = UnifiedIndex({})

        instance = ModelInstance(
            path=Path("/a/model.gguf"),
            backend_id="backend_a",
            inode=123,
            device=1,
            mtime=100.0,
            size=1000,
        )

        index.add_instance("test-model", instance)
        assert "test-model" in index.entries
        assert len(index.entries["test-model"].instances) == 1

        index.remove_instance("test-model", "backend_a")
        assert "test-model" not in index.entries


class TestOriginTracker:
    """Tests for OriginTracker."""

    @pytest.fixture
    def tracker(self, tmp_path):
        """Create an OriginTracker with temporary directory."""
        return OriginTracker(tmp_path / ".fabric")

    def test_record_origin(self, tracker):
        """Test recording model origin."""
        result = tracker.record_origin(
            model_id="test-model",
            backend_id="backend_a",
            original_path=Path("/a/model.gguf"),
        )
        assert result is True

        origin = tracker.get_origin("test-model")
        assert origin is not None
        assert origin.backend_id == "backend_a"

    def test_record_origin_idempotent(self, tracker):
        """Test that recording origin is idempotent."""
        tracker.record_origin(
            model_id="test-model",
            backend_id="backend_a",
            original_path=Path("/a/model.gguf"),
        )

        # Second call should return False (not a new origin)
        result = tracker.record_origin(
            model_id="test-model",
            backend_id="backend_b",
            original_path=Path("/b/model.gguf"),
        )
        assert result is False

        # Origin should still be backend_a
        origin = tracker.get_origin("test-model")
        assert origin.backend_id == "backend_a"

    def test_is_origin(self, tracker):
        """Test is_origin method."""
        tracker.record_origin(
            model_id="test-model",
            backend_id="backend_a",
            original_path=Path("/a/model.gguf"),
        )

        assert tracker.is_origin("test-model", "backend_a")
        assert not tracker.is_origin("test-model", "backend_b")
        assert not tracker.is_origin("unknown-model", "backend_a")

    def test_update_origin_backend(self, tracker):
        """Test updating origin backend."""
        tracker.record_origin(
            model_id="test-model",
            backend_id="backend_a",
            original_path=Path("/a/model.gguf"),
        )

        result = tracker.update_origin_backend("test-model", "backend_b")
        assert result is True

        origin = tracker.get_origin("test-model")
        assert origin.backend_id == "backend_b"

    def test_remove_origin(self, tracker):
        """Test removing origin tracking."""
        tracker.record_origin(
            model_id="test-model",
            backend_id="backend_a",
            original_path=Path("/a/model.gguf"),
        )

        result = tracker.remove_origin("test-model")
        assert result is True
        assert tracker.get_origin("test-model") is None

    def test_persistence(self, tmp_path):
        """Test that origins are persisted to disk."""
        tracker1 = OriginTracker(tmp_path / ".fabric")
        tracker1.record_origin(
            model_id="test-model",
            backend_id="backend_a",
            original_path=Path("/a/model.gguf"),
        )

        # Create new tracker instance (simulates restart)
        tracker2 = OriginTracker(tmp_path / ".fabric")
        origin = tracker2.get_origin("test-model")

        assert origin is not None
        assert origin.backend_id == "backend_a"


class TestConflictPreservationHandler:
    """Tests for ConflictPreservationHandler."""

    @pytest.fixture
    def handler(self, tmp_path):
        """Create a ConflictPreservationHandler with temporary directory."""
        return ConflictPreservationHandler(tmp_path / ".fabric")

    @pytest.fixture
    def mock_entry(self):
        """Create a mock UnifiedModelEntry."""
        entry = MagicMock()
        entry.model_id = "test-model"
        entry.instances = [
            ModelInstance(
                path=Path("/a/model.gguf"),
                backend_id="backend_a",
                inode=123,
                device=1,
                mtime=100.0,
                size=1000,
            )
        ]
        return entry

    def test_handle_conflict(self, handler, mock_entry, tmp_path):
        """Test conflict recording (files are NOT renamed)."""
        # Create the new instance file
        new_file = tmp_path / "backend_b" / "test-model.gguf"
        new_file.parent.mkdir()
        new_file.write_text("different content")

        instance = ModelInstance(
            path=new_file,
            backend_id="backend_b",
            inode=456,
            device=1,
            mtime=200.0,
            size=2000,
        )

        success = handler.handle_conflict(instance, mock_entry)

        assert success is True
        # File should NOT be renamed - left in place for safety
        assert new_file.exists()
        assert new_file.name == "test-model.gguf"

        # But conflict should be recorded in database
        conflicts = handler.get_unresolved_conflicts()
        assert len(conflicts) == 1
        assert conflicts[0].model_id == "test-model"


class TestConflictDatabase:
    """Tests for ConflictDatabase."""

    @pytest.fixture
    def db(self, tmp_path):
        """Create a ConflictDatabase with temporary directory."""
        return ConflictDatabase(tmp_path / ".fabric")

    def test_add_conflict(self, db):
        """Test adding a conflict."""
        from fabric.core.unified_index import ModelInstance

        new_instance = ModelInstance(
            path=Path("/b/model.gguf"),
            backend_id="backend_b",
            inode=456,
            device=1,
            mtime=200.0,
            size=2000,
        )
        existing_instances = [
            ModelInstance(
                path=Path("/a/model.gguf"),
                backend_id="backend_a",
                inode=123,
                device=1,
                mtime=100.0,
                size=1000,
            )
        ]

        db.add_conflict("test-model", new_instance, existing_instances)

        unresolved = db.get_unresolved()
        assert len(unresolved) == 1
        assert unresolved[0].model_id == "test-model"
        assert len(unresolved[0].instances) == 2

    def test_resolve_conflict(self, db):
        """Test resolving a conflict."""
        from fabric.core.unified_index import ModelInstance

        db.add_conflict(
            "test-model",
            ModelInstance(
                path=Path("/b/model.gguf"),
                backend_id="backend_b",
                inode=456,
                device=1,
                mtime=200.0,
                size=2000,
            ),
            [
                ModelInstance(
                    path=Path("/a/model.gguf"),
                    backend_id="backend_a",
                    inode=123,
                    device=1,
                    mtime=100.0,
                    size=1000,
                )
            ],
        )

        result = db.resolve_conflict("test-model", "keep_newest", "backend_a")
        assert result is True

        unresolved = db.get_unresolved()
        assert len(unresolved) == 0

        record = db.get_record("test-model")
        assert record.status == "resolved"
        assert record.resolution == "keep_newest"

    def test_persistence(self, tmp_path):
        """Test that conflicts are persisted to disk."""
        from fabric.core.unified_index import ModelInstance

        db1 = ConflictDatabase(tmp_path / ".fabric")
        db1.add_conflict(
            "test-model",
            ModelInstance(
                path=Path("/b/model.gguf"),
                backend_id="backend_b",
                inode=456,
                device=1,
                mtime=200.0,
                size=2000,
            ),
            [
                ModelInstance(
                    path=Path("/a/model.gguf"),
                    backend_id="backend_a",
                    inode=123,
                    device=1,
                    mtime=100.0,
                    size=1000,
                )
            ],
        )

        # Create new database instance (simulates restart)
        db2 = ConflictDatabase(tmp_path / ".fabric")
        unresolved = db2.get_unresolved()

        assert len(unresolved) == 1
        assert unresolved[0].model_id == "test-model"


class TestSyncCooldownManager:
    """Tests for SyncCooldownManager."""

    def test_enter_and_check_cooldown(self, tmp_path):
        """Test entering and checking cooldown."""
        manager = SyncCooldownManager(cooldown_seconds=0.1)

        test_file = tmp_path / "test.gguf"
        test_file.write_text("test")

        # Should not be in cooldown initially
        assert not manager.is_in_cooldown(test_file)

        # Enter cooldown
        manager.enter_cooldown(test_file, "test_backend")

        # Should be in cooldown now
        assert manager.is_in_cooldown(test_file)

        # Wait for cooldown to expire
        time.sleep(0.15)

        # Should not be in cooldown anymore
        assert not manager.is_in_cooldown(test_file)

    def test_different_files_independent(self, tmp_path):
        """Test that different files have independent cooldowns."""
        manager = SyncCooldownManager(cooldown_seconds=0.1)

        file1 = tmp_path / "file1.gguf"
        file2 = tmp_path / "file2.gguf"
        file1.write_text("content1")
        file2.write_text("content2")

        manager.enter_cooldown(file1, "backend_a")

        # file1 should be in cooldown
        assert manager.is_in_cooldown(file1)
        # file2 should not be in cooldown
        assert not manager.is_in_cooldown(file2)

    def test_clear(self, tmp_path):
        """Test clearing all cooldowns."""
        manager = SyncCooldownManager(cooldown_seconds=10.0)

        test_file = tmp_path / "test.gguf"
        test_file.write_text("test")

        manager.enter_cooldown(test_file, "test_backend")
        assert manager.is_in_cooldown(test_file)

        manager.clear()
        assert not manager.is_in_cooldown(test_file)

    def test_get_active_count(self, tmp_path):
        """Test getting active cooldown count."""
        manager = SyncCooldownManager(cooldown_seconds=10.0)

        assert manager.get_active_count() == 0

        file1 = tmp_path / "file1.gguf"
        file2 = tmp_path / "file2.gguf"
        file1.write_text("content1")
        file2.write_text("content2")

        manager.enter_cooldown(file1, "backend_a")
        assert manager.get_active_count() == 1

        manager.enter_cooldown(file2, "backend_b")
        assert manager.get_active_count() == 2


class TestNormalizeModelId:
    """Tests for normalize_model_id function."""

    def test_basic_normalization(self):
        """Test basic model ID normalization."""
        assert normalize_model_id("Model-Name") == "model-name"
        assert normalize_model_id("MODEL_NAME") == "model-name"
        assert normalize_model_id("model.name") == "model-name"

    def test_multiple_special_chars(self):
        """Test normalization with multiple special characters."""
        assert normalize_model_id("model--name") == "model-name"
        assert normalize_model_id("model__name") == "model-name"
        assert normalize_model_id("model..name") == "model-name"

    def test_leading_trailing_special_chars(self):
        """Test normalization of leading/trailing special characters."""
        assert normalize_model_id("-model-") == "model"
        assert normalize_model_id("_model_") == "model"

    def test_quantization_suffix(self):
        """Test normalization with quantization suffix."""
        assert normalize_model_id("llama-3-8b-Q4_K_M") == "llama-3-8b-q4-k-m"
        assert normalize_model_id("mistral-7b-q5") == "mistral-7b-q5"
