"""Tests for service installation with mocked filesystem operations.

This module uses mocked file operations to test the service installation
functionality without requiring root privileges or actually installing services.
"""

from __future__ import annotations

import stat
from pathlib import Path
from unittest.mock import MagicMock, mock_open, patch

import pytest

from fabric.core.exceptions import ServiceError
from fabric.core.service import ServiceInstaller


class TestServiceInstallerSystemdInstall:
    """Tests for systemd service installation with mocked filesystem."""

    @pytest.fixture
    def linux_installer(self) -> ServiceInstaller:
        """Create a Linux installer with mocked system."""
        with patch.object(ServiceInstaller, "__init__", lambda self, **kw: None):
            installer = ServiceInstaller.__new__(ServiceInstaller)
            installer.service_name = "test-service"
            installer.executable_path = Path("/usr/bin/python3")
            installer.system = "Linux"
            return installer

    @patch("subprocess.run")
    def test_install_systemd_writes_service_file(
        self, mock_run: MagicMock, linux_installer: ServiceInstaller
    ) -> None:
        """Test that install writes systemd service file."""
        mock_run.return_value = MagicMock(returncode=0)

        m = mock_open()
        with (
            patch("builtins.open", m),
            patch("os.chmod") as mock_chmod,
            patch("pathlib.Path.exists", return_value=True),
        ):
            linux_installer._install_systemd()

        # Check that file was opened for writing
        m.assert_called()
        # Check that chmod was called to set permissions
        mock_chmod.assert_called()

    @patch("subprocess.run")
    def test_install_systemd_calls_daemon_reload(
        self, mock_run: MagicMock, linux_installer: ServiceInstaller
    ) -> None:
        """Test that install calls daemon-reload."""
        mock_run.return_value = MagicMock(returncode=0)

        with (
            patch("builtins.open", mock_open()),
            patch("os.chmod"),
            patch("pathlib.Path.exists", return_value=True),
        ):
            linux_installer._install_systemd()

        # Check that daemon-reload was called
        calls = mock_run.call_args_list
        call_cmds = [c[0][0] for c in calls]
        assert any("daemon-reload" in str(c) for c in call_cmds)

    @patch("subprocess.run")
    def test_install_systemd_handles_permission_error(
        self, mock_run: MagicMock, linux_installer: ServiceInstaller
    ) -> None:
        """Test that permission error raises ServiceError."""
        mock_run.return_value = MagicMock(returncode=0)

        with (
            pytest.raises(ServiceError) as exc_info,
            patch("builtins.open", side_effect=PermissionError("Permission denied")),
        ):
            linux_installer._install_systemd()

        assert "Permission denied" in str(exc_info.value)


class TestServiceInstallerUninstall:
    """Tests for service uninstallation with mocked filesystem."""

    @pytest.fixture
    def linux_installer(self) -> ServiceInstaller:
        """Create a Linux installer."""
        with patch.object(ServiceInstaller, "__init__", lambda self, **kw: None):
            installer = ServiceInstaller.__new__(ServiceInstaller)
            installer.service_name = "test-service"
            installer.executable_path = Path("/usr/bin/python3")
            installer.system = "Linux"
            return installer

    @patch("subprocess.run")
    def test_uninstall_systemd_stops_service(
        self, mock_run: MagicMock, linux_installer: ServiceInstaller
    ) -> None:
        """Test that uninstall stops the service."""
        mock_run.return_value = MagicMock(returncode=0)

        with patch("pathlib.Path.exists", return_value=True), patch(
            "pathlib.Path.unlink"
        ):
            linux_installer._uninstall_systemd()

        # Check that stop was called
        calls = mock_run.call_args_list
        call_cmds = [c[0][0] for c in calls]
        assert any("stop" in str(c) for c in call_cmds)

    @patch("subprocess.run")
    def test_uninstall_systemd_disables_service(
        self, mock_run: MagicMock, linux_installer: ServiceInstaller
    ) -> None:
        """Test that uninstall disables the service."""
        mock_run.return_value = MagicMock(returncode=0)

        with patch("pathlib.Path.exists", return_value=True), patch(
            "pathlib.Path.unlink"
        ):
            linux_installer._uninstall_systemd()

        # Check that disable was called
        calls = mock_run.call_args_list
        call_cmds = [c[0][0] for c in calls]
        assert any("disable" in str(c) for c in call_cmds)

    @patch("subprocess.run")
    def test_uninstall_systemd_removes_service_file(
        self, mock_run: MagicMock, linux_installer: ServiceInstaller
    ) -> None:
        """Test that uninstall removes service file."""
        mock_run.return_value = MagicMock(returncode=0)

        mock_unlink = MagicMock()
        with patch("pathlib.Path.exists", return_value=True), patch(
            "pathlib.Path.unlink", mock_unlink
        ):
            linux_installer._uninstall_systemd()

        # Check that unlink was called
        mock_unlink.assert_called()

    @patch("subprocess.run")
    def test_uninstall_systemd_handles_missing_file(
        self, mock_run: MagicMock, linux_installer: ServiceInstaller
    ) -> None:
        """Test that uninstall handles missing service file gracefully."""
        mock_run.return_value = MagicMock(returncode=0)

        mock_unlink = MagicMock()
        with patch("pathlib.Path.exists", return_value=False), patch(
            "pathlib.Path.unlink", mock_unlink
        ):
            # Should not raise even if file doesn't exist
            linux_installer._uninstall_systemd()

        # Unlink should not be called if file doesn't exist
        mock_unlink.assert_not_called()


class TestServiceInstallerFilePermissions:
    """Tests for service file permission handling."""

    @pytest.fixture
    def linux_installer(self) -> ServiceInstaller:
        """Create a Linux installer."""
        with patch.object(ServiceInstaller, "__init__", lambda self, **kw: None):
            installer = ServiceInstaller.__new__(ServiceInstaller)
            installer.service_name = "test-service"
            installer.executable_path = Path("/usr/bin/python3")
            installer.system = "Linux"
            return installer

    @patch("subprocess.run")
    def test_service_file_permissions_set_correctly(
        self, mock_run: MagicMock, linux_installer: ServiceInstaller
    ) -> None:
        """Test that service file gets correct permissions (0o600)."""
        mock_run.return_value = MagicMock(returncode=0)

        chmod_mode = None

        def capture_chmod(path, mode):
            nonlocal chmod_mode
            chmod_mode = mode

        with (
            patch("builtins.open", mock_open()),
            patch("os.chmod", side_effect=capture_chmod),
            patch("pathlib.Path.exists", return_value=True),
        ):
            linux_installer._install_systemd()

        # Check that chmod was called with restricted permissions
        assert chmod_mode is not None
        # Should be 0o600 (read/write owner only) or similar
        assert chmod_mode & stat.S_IRWXU  # Owner has some permissions
        assert not (chmod_mode & stat.S_IRWXG)  # No group permissions
        assert not (chmod_mode & stat.S_IRWXO)  # No other permissions
