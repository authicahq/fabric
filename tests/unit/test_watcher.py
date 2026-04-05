"""Tests for file watcher."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

from fabric.core.watcher import DownloadDetector, FileSystemWatcher, PendingDownload


class TestPendingDownload:
    """Tests for PendingDownload."""

    def test_pending_download_creation(self) -> None:
        """Test creating a PendingDownload."""
        download = PendingDownload(path=Path("/models/test.gguf"))
        assert download.path == Path("/models/test.gguf")
        assert download.stable_count == 0
        assert download.is_partial is False

    def test_pending_download_with_real_name(self) -> None:
        """Test PendingDownload with real name."""
        download = PendingDownload(
            path=Path("/models/test.part"),
            real_name="test.gguf",
            is_partial=True,
        )
        assert download.real_name == "test.gguf"
        assert download.is_partial is True


class TestDownloadDetector:
    """Tests for DownloadDetector."""

    def test_download_detector_init(self) -> None:
        """Test DownloadDetector initialization."""
        detector = DownloadDetector()
        assert detector._pending == {}
        assert detector.pending_count == 0

    def test_download_detector_with_params(self) -> None:
        """Test DownloadDetector initialization with custom params."""
        detector = DownloadDetector(check_interval=1.0, stable_count=5, max_wait=60)
        assert detector.check_interval == 1.0
        assert detector.stable_count_required == 5
        assert detector.max_wait == 60

    def test_is_partial(self) -> None:
        """Test is_partial detection."""
        detector = DownloadDetector()
        assert detector.is_partial(Path("model.gguf.part")) is True
        assert detector.is_partial(Path("model.gguf.tmp")) is True
        assert detector.is_partial(Path("model.gguf")) is False
        assert detector.is_partial(Path("model.bin")) is False

    def test_get_real_name(self) -> None:
        """Test get_real_name."""
        detector = DownloadDetector()
        assert detector.get_real_name(Path("model.gguf.part")) == "model.gguf"
        assert detector.get_real_name(Path("model.gguf.tmp")) == "model.gguf"
        assert detector.get_real_name(Path("model.gguf")) == "model.gguf"

    def test_add_pending(self) -> None:
        """Test adding a pending download."""
        detector = DownloadDetector()
        path = Path("/models/test.gguf.part")

        pending = detector.add_pending(path)
        assert path in detector._pending
        assert pending.path == path
        assert pending.is_partial is True

    def test_remove_pending(self) -> None:
        """Test removing a pending download."""
        detector = DownloadDetector()
        path = Path("/models/test.gguf.part")

        detector.add_pending(path)
        removed = detector.remove_pending(path)

        assert removed is not None
        assert path not in detector._pending
        assert detector.pending_count == 0

    def test_remove_pending_not_found(self) -> None:
        """Test removing a non-existent pending download."""
        detector = DownloadDetector()
        removed = detector.remove_pending(Path("/nonexistent"))
        assert removed is None

    def test_check_complete_not_tracked(self) -> None:
        """Test check_complete on non-tracked file."""
        detector = DownloadDetector()
        # When checking a file not tracked as pending, it should start tracking it
        is_complete, _final_path = detector.check_complete(Path("/models/test.gguf"))
        # Non-partial file will be tracked but not complete yet
        assert is_complete is False

    def test_pending_count_property(self) -> None:
        """Test pending_count property."""
        detector = DownloadDetector()
        assert detector.pending_count == 0

        detector.add_pending(Path("/models/test1.gguf.part"))
        assert detector.pending_count == 1

        detector.add_pending(Path("/models/test2.gguf.part"))
        assert detector.pending_count == 2

    def test_get_pending_paths(self) -> None:
        """Test get_pending_paths."""
        detector = DownloadDetector()
        detector.add_pending(Path("/models/test.gguf.part"))

        paths = detector.get_pending_paths()
        assert Path("/models/test.gguf.part") in paths


class TestFileSystemWatcher:
    """Tests for FileSystemWatcher."""

    def test_watcher_init(self) -> None:
        """Test FileSystemWatcher initialization."""
        callback = MagicMock()
        watcher = FileSystemWatcher(
            source_dirs=[Path("/models")],
            callback=callback,
        )
        assert watcher.source_dirs == [Path("/models")]
        assert watcher.callback == callback
        assert watcher._running is False

    def test_watcher_init_with_params(self) -> None:
        """Test FileSystemWatcher initialization with custom params."""
        callback = MagicMock()
        watcher = FileSystemWatcher(
            source_dirs=[Path("/models")],
            callback=callback,
            check_interval=1.0,
            stable_count=2,
            max_wait=60,
            recursive=False,
        )
        assert watcher.recursive is False
        assert watcher.download_detector.check_interval == 1.0

    @patch("fabric.core.watcher.Observer")
    def test_watcher_start(self, mock_observer_cls: MagicMock) -> None:
        """Test starting the watcher."""
        import tempfile

        with tempfile.TemporaryDirectory() as tmpdir:
            callback = MagicMock()
            mock_observer = MagicMock()
            mock_observer_cls.return_value = mock_observer

            watcher = FileSystemWatcher(
                source_dirs=[Path(tmpdir)],
                callback=callback,
            )
            watcher.start()

            assert watcher._running is True
            mock_observer.schedule.assert_called()
            mock_observer.start.assert_called_once()

    @patch("fabric.core.watcher.Observer")
    def test_watcher_stop(self, mock_observer_cls: MagicMock) -> None:
        """Test stopping the watcher."""
        import tempfile

        with tempfile.TemporaryDirectory() as tmpdir:
            callback = MagicMock()
            mock_observer = MagicMock()
            mock_observer_cls.return_value = mock_observer

            watcher = FileSystemWatcher(
                source_dirs=[Path(tmpdir)],
                callback=callback,
            )
            watcher._running = True
            watcher._observer = mock_observer

            watcher.stop()

            assert watcher._running is False
            mock_observer.stop.assert_called_once()
            mock_observer.join.assert_called_once()

    @patch("fabric.core.watcher.Observer")
    def test_watcher_context_manager(self, mock_observer_cls: MagicMock) -> None:
        """Test watcher as context manager."""
        import tempfile

        with tempfile.TemporaryDirectory() as tmpdir:
            callback = MagicMock()
            mock_observer = MagicMock()
            mock_observer_cls.return_value = mock_observer

            with FileSystemWatcher(
                source_dirs=[Path(tmpdir)],
                callback=callback,
            ) as watcher:
                assert watcher._running is True

            # After exiting context, should be stopped
            assert watcher._running is False


class TestWatcherEventHandling:
    """Tests for watcher event handling - testing method existence."""

    def test_watcher_has_start_method(self) -> None:
        """Test that watcher has start method."""
        import tempfile

        with tempfile.TemporaryDirectory() as tmpdir:
            callback = MagicMock()
            watcher = FileSystemWatcher(
                source_dirs=[Path(tmpdir)],
                callback=callback,
            )

            assert hasattr(watcher, "start")
            assert callable(watcher.start)

    def test_watcher_has_stop_method(self) -> None:
        """Test that watcher has stop method."""
        import tempfile

        with tempfile.TemporaryDirectory() as tmpdir:
            callback = MagicMock()
            watcher = FileSystemWatcher(
                source_dirs=[Path(tmpdir)],
                callback=callback,
            )

            assert hasattr(watcher, "stop")
            assert callable(watcher.stop)

    def test_watcher_has_run_method(self) -> None:
        """Test that watcher has run method (async)."""
        import tempfile

        with tempfile.TemporaryDirectory() as tmpdir:
            callback = MagicMock()
            watcher = FileSystemWatcher(
                source_dirs=[Path(tmpdir)],
                callback=callback,
            )

            assert hasattr(watcher, "run")
            assert callable(watcher.run)

    def test_watcher_has_download_detector(self) -> None:
        """Test that watcher has download_detector attribute."""
        import tempfile

        with tempfile.TemporaryDirectory() as tmpdir:
            callback = MagicMock()
            watcher = FileSystemWatcher(
                source_dirs=[Path(tmpdir)],
                callback=callback,
            )

            assert hasattr(watcher, "download_detector")
            assert watcher.download_detector is not None


class TestDownloadDetectorComplete:
    """Tests for download completion detection."""

    def test_is_partial_gguf_extensions(self) -> None:
        """Test is_partial with various GGUF extensions."""
        detector = DownloadDetector()
        assert detector.is_partial(Path("model.Q4_K_M.gguf")) is False
        assert detector.is_partial(Path("model.gguf.part")) is True
        assert detector.is_partial(Path("model.gguf.tmp")) is True
        assert detector.is_partial(Path("model.gguf.crdownload")) is True

    def test_get_real_name_removes_extensions(self) -> None:
        """Test get_real_name removes partial extensions."""
        detector = DownloadDetector()
        assert detector.get_real_name(Path("model.gguf.part")) == "model.gguf"
        assert detector.get_real_name(Path("model.gguf.tmp")) == "model.gguf"
        assert detector.get_real_name(Path("model.gguf.crdownload")) == "model.gguf"
        assert detector.get_real_name(Path("model.gguf")) == "model.gguf"
