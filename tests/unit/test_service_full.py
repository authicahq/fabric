"""Tests for service installation."""

from __future__ import annotations

import subprocess
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from fabric.core.exceptions import ServiceError
from fabric.core.service import VALID_SERVICE_NAME_PATTERN, ServiceInstaller


class TestServiceInstallerValidation:
    """Tests for ServiceInstaller validation."""

    def test_valid_service_names(self) -> None:
        """Test valid service names are accepted."""
        ServiceInstaller("valid-service")
        ServiceInstaller("valid_service")
        ServiceInstaller("MyService123")
        ServiceInstaller("a")
        ServiceInstaller("service-name_123")

    def test_invalid_service_names(self) -> None:
        """Test invalid service names raise ServiceError."""
        with pytest.raises(ServiceError) as exc_info:
            ServiceInstaller("my service")
        assert "Invalid service name" in str(exc_info.value)

        with pytest.raises(ServiceError) as exc_info:
            ServiceInstaller("/etc/passwd")
        assert "Invalid service name" in str(exc_info.value)

        with pytest.raises(ServiceError) as exc_info:
            ServiceInstaller("")
        assert "Invalid service name" in str(exc_info.value)

        with pytest.raises(ServiceError) as exc_info:
            ServiceInstaller("service$name")
        assert "Invalid service name" in str(exc_info.value)

        with pytest.raises(ServiceError) as exc_info:
            ServiceInstaller("service.name")
        assert "Invalid service name" in str(exc_info.value)


class TestServiceInstaller:
    """Tests for ServiceInstaller."""

    def test_default_values(self) -> None:
        """Test ServiceInstaller default values."""
        installer = ServiceInstaller()
        assert installer.service_name == "fabric"
        assert installer.executable_path == Path(__import__("sys").executable)
        assert installer.system is not None

    def test_custom_values(self) -> None:
        """Test ServiceInstaller with custom values."""
        installer = ServiceInstaller(
            service_name="my-service",
            executable_path=Path("/usr/bin/python"),
        )
        assert installer.service_name == "my-service"
        assert installer.executable_path == Path("/usr/bin/python")

    def test_platform_is_set(self) -> None:
        """Test that platform.system() is used."""
        installer = ServiceInstaller()
        assert installer.system in ["Linux", "Darwin", "Windows"]


class TestServiceInstallerStart:
    """Tests for service start command."""

    @patch("subprocess.run")
    def test_start_linux(self, mock_run: MagicMock) -> None:
        """Test start on Linux."""
        mock_run.return_value = MagicMock(returncode=0, stderr="")

        installer = ServiceInstaller("test-service")
        installer.start()

        mock_run.assert_called_once()
        call_args = mock_run.call_args[0][0]
        assert call_args[0] == "systemctl"
        assert call_args[1] == "start"
        assert call_args[2] == "test-service"

    @patch("subprocess.run")
    def test_start_darwin(self, mock_run: MagicMock) -> None:
        """Test start on macOS using monkeypatch."""
        mock_run.return_value = MagicMock(returncode=0, stderr="")

        with patch.object(ServiceInstaller, "__init__", lambda self, **kw: None):
            installer = ServiceInstaller.__new__(ServiceInstaller)
            installer.service_name = "test-service"
            installer.system = "Darwin"
            installer.start()

        call_args = mock_run.call_args[0][0]
        assert call_args[0] == "launchctl"
        assert call_args[1] == "start"
        assert call_args[2] == "test-service"

    @patch("subprocess.run")
    def test_start_failure(self, mock_run: MagicMock) -> None:
        """Test start command failure."""
        mock_run.side_effect = subprocess.CalledProcessError(
            1, "systemctl", stderr="Service not found"
        )

        installer = ServiceInstaller("test-service")
        with pytest.raises(ServiceError) as exc:
            installer.start()
        assert "Failed to start" in str(exc.value)

    @patch("subprocess.run")
    def test_start_command_not_found(self, mock_run: MagicMock) -> None:
        """Test start when systemctl not found."""
        mock_run.side_effect = FileNotFoundError("systemctl")

        installer = ServiceInstaller("test-service")
        with pytest.raises(ServiceError) as exc:
            installer.start()
        assert "not found" in str(exc.value)


class TestServiceInstallerStop:
    """Tests for service stop command."""

    @patch("subprocess.run")
    def test_stop_linux(self, mock_run: MagicMock) -> None:
        """Test stop on Linux."""
        mock_run.return_value = MagicMock(returncode=0, stderr="")

        installer = ServiceInstaller("test-service")
        installer.stop()

        call_args = mock_run.call_args[0][0]
        assert call_args[0] == "systemctl"
        assert call_args[1] == "stop"


class TestServiceInstallerStatus:
    """Tests for service status command."""

    @patch("subprocess.run")
    def test_status_linux_active(self, mock_run: MagicMock) -> None:
        """Test status on Linux when active."""
        mock_run.return_value = MagicMock(
            returncode=0,
            stdout="Active: active (running)",
        )

        installer = ServiceInstaller("test-service")
        status = installer.status()

        assert status["installed"] is True
        assert status["active"] is True

    @patch("subprocess.run")
    def test_status_linux_not_active(self, mock_run: MagicMock) -> None:
        """Test status on Linux when not active."""
        mock_run.return_value = MagicMock(
            returncode=3,
            stdout="Active: inactive (dead)",
        )

        installer = ServiceInstaller("test-service")
        status = installer.status()

        assert status["installed"] is True
        assert status["active"] is False

    @patch("subprocess.run")
    def test_status_linux_not_installed(self, mock_run: MagicMock) -> None:
        """Test status on Linux when not installed."""
        mock_run.return_value = MagicMock(returncode=4, stdout="")

        installer = ServiceInstaller("test-service")
        status = installer.status()

        assert status["installed"] is False


class TestServiceInstallerInstall:
    """Tests for service install command."""

    @patch("subprocess.run")
    def test_install_unsupported_platform(self, mock_run: MagicMock) -> None:
        """Test install on unsupported platform."""
        with patch.object(ServiceInstaller, "__init__", lambda self, **kw: None):
            installer = ServiceInstaller.__new__(ServiceInstaller)
            installer.service_name = "test-service"
            installer.system = "FreeBSD"

            with pytest.raises(ServiceError) as exc:
                installer.install()
            assert "Unsupported platform" in str(exc.value)

    @patch("subprocess.run")
    def test_install_linux_systemd(self, mock_run: MagicMock) -> None:
        """Test install on Linux with systemd."""
        mock_run.return_value = MagicMock(returncode=0)

        with patch.object(ServiceInstaller, "__init__", lambda self, **kw: None):
            installer = ServiceInstaller.__new__(ServiceInstaller)
            installer.service_name = "test-service"
            installer.executable_path = Path("/usr/bin/python")
            installer.system = "Linux"

            with patch("builtins.open", MagicMock()), patch("os.chmod", MagicMock()):
                installer.install()

            calls = mock_run.call_args_list
            call_cmds = [c[0][0] for c in calls]
            assert any("systemctl" in c and "daemon-reload" in c for c in call_cmds)

    @patch("subprocess.run")
    def test_install_linux_permission_error(self, mock_run: MagicMock) -> None:
        """Test install on Linux with permission error."""
        mock_run.return_value = MagicMock(returncode=0)

        with patch.object(ServiceInstaller, "__init__", lambda self, **kw: None):
            installer = ServiceInstaller.__new__(ServiceInstaller)
            installer.service_name = "test-service"
            installer.executable_path = Path("/usr/bin/python")
            installer.system = "Linux"

            with (
                pytest.raises(ServiceError) as exc,
                patch("builtins.open", side_effect=PermissionError("Permission denied")),
            ):
                installer.install()
            assert "Permission denied" in str(exc.value)


class TestServiceInstallerUninstall:
    """Tests for service uninstall command."""

    @patch("subprocess.run")
    def test_uninstall_unsupported_platform(self, mock_run: MagicMock) -> None:
        """Test uninstall on unsupported platform."""
        with patch.object(ServiceInstaller, "__init__", lambda self, **kw: None):
            installer = ServiceInstaller.__new__(ServiceInstaller)
            installer.service_name = "test-service"
            installer.system = "FreeBSD"

            with pytest.raises(ServiceError) as exc:
                installer.uninstall()
            assert "Unsupported platform" in str(exc.value)

    @patch("subprocess.run")
    def test_uninstall_linux_systemd(self, mock_run: MagicMock) -> None:
        """Test uninstall on Linux with systemd."""
        mock_run.return_value = MagicMock(returncode=0)

        with patch.object(ServiceInstaller, "__init__", lambda self, **kw: None):
            installer = ServiceInstaller.__new__(ServiceInstaller)
            installer.service_name = "test-service"
            installer.system = "Linux"

            with (
                patch("pathlib.Path.exists", return_value=True),
                patch("pathlib.Path.unlink", MagicMock()),
            ):
                installer.uninstall()

            calls = mock_run.call_args_list
            call_cmds = [c[0][0] for c in calls]
            assert any("systemctl" in c and "stop" in c for c in call_cmds)
            assert any("systemctl" in c and "disable" in c for c in call_cmds)


class TestServiceInstallerStatusDarwin:
    """Tests for service status on macOS."""

    @patch("subprocess.run")
    def test_status_darwin_installed(self, mock_run: MagicMock) -> None:
        """Test status on macOS when installed."""
        mock_run.return_value = MagicMock(returncode=0, stdout="test-service")

        with patch.object(ServiceInstaller, "__init__", lambda self, **kw: None):
            installer = ServiceInstaller.__new__(ServiceInstaller)
            installer.service_name = "test-service"
            installer.system = "Darwin"
            status = installer.status()

            assert status["installed"] is True

    @patch("subprocess.run")
    def test_status_darwin_not_installed(self, mock_run: MagicMock) -> None:
        """Test status on macOS when not installed."""
        mock_run.return_value = MagicMock(returncode=1, stdout="")

        with patch.object(ServiceInstaller, "__init__", lambda self, **kw: None):
            installer = ServiceInstaller.__new__(ServiceInstaller)
            installer.service_name = "test-service"
            installer.system = "Darwin"
            status = installer.status()

            assert status["installed"] is False


class TestServiceInstallerStatusWindows:
    """Tests for service status on Windows."""

    @patch("subprocess.run")
    def test_status_windows_installed_running(self, mock_run: MagicMock) -> None:
        """Test status on Windows when installed and running."""
        mock_run.return_value = MagicMock(returncode=0, stdout="STATE: RUNNING")

        with patch.object(ServiceInstaller, "__init__", lambda self, **kw: None):
            installer = ServiceInstaller.__new__(ServiceInstaller)
            installer.service_name = "test-service"
            installer.system = "Windows"
            status = installer.status()

            assert status["installed"] is True
            assert status["active"] is True

    @patch("subprocess.run")
    def test_status_windows_not_installed(self, mock_run: MagicMock) -> None:
        """Test status on Windows when not installed."""
        mock_run.return_value = MagicMock(returncode=1, stdout="")

        with patch.object(ServiceInstaller, "__init__", lambda self, **kw: None):
            installer = ServiceInstaller.__new__(ServiceInstaller)
            installer.service_name = "test-service"
            installer.system = "Windows"
            status = installer.status()

            assert status["installed"] is False


class TestServiceInstallerStopDarwin:
    """Tests for service stop on macOS."""

    @patch("subprocess.run")
    def test_stop_darwin(self, mock_run: MagicMock) -> None:
        """Test stop on macOS."""
        mock_run.return_value = MagicMock(returncode=0, stderr="")

        with patch.object(ServiceInstaller, "__init__", lambda self, **kw: None):
            installer = ServiceInstaller.__new__(ServiceInstaller)
            installer.service_name = "test-service"
            installer.system = "Darwin"
            installer.stop()

            call_args = mock_run.call_args[0][0]
            assert call_args[0] == "launchctl"
            assert call_args[1] == "stop"


class TestServiceInstallerStopWindows:
    """Tests for service stop on Windows."""

    @patch("subprocess.run")
    def test_stop_windows(self, mock_run: MagicMock) -> None:
        """Test stop on Windows."""
        mock_run.return_value = MagicMock(returncode=0, stderr="")

        with patch.object(ServiceInstaller, "__init__", lambda self, **kw: None):
            installer = ServiceInstaller.__new__(ServiceInstaller)
            installer.service_name = "test-service"
            installer.system = "Windows"
            installer.stop()

            call_args = mock_run.call_args[0][0]
            assert call_args[0] == "sc"
            assert call_args[1] == "stop"


class TestServiceInstallerStartStopErrors:
    """Tests for service start/stop error handling."""

    @patch("subprocess.run")
    def test_stop_failure_linux(self, mock_run: MagicMock) -> None:
        """Test stop failure on Linux."""
        mock_run.side_effect = subprocess.CalledProcessError(
            1, "systemctl", stderr="Service not loaded"
        )

        installer = ServiceInstaller("test-service")
        with pytest.raises(ServiceError) as exc:
            installer.stop()
        assert "Failed to stop" in str(exc.value)

    @patch("subprocess.run")
    def test_stop_command_not_found_linux(self, mock_run: MagicMock) -> None:
        """Test stop when systemctl not found."""
        mock_run.side_effect = FileNotFoundError("systemctl")

        installer = ServiceInstaller("test-service")
        with pytest.raises(ServiceError) as exc:
            installer.stop()
        assert "not found" in str(exc.value)

    @patch("subprocess.run")
    def test_start_darwin_failure(self, mock_run: MagicMock) -> None:
        """Test start failure on Darwin."""
        mock_run.side_effect = subprocess.CalledProcessError(
            1, "launchctl", stderr="Service not found"
        )

        with patch.object(ServiceInstaller, "__init__", lambda self, **kw: None):
            installer = ServiceInstaller.__new__(ServiceInstaller)
            installer.service_name = "test-service"
            installer.system = "Darwin"

            with pytest.raises(ServiceError) as exc:
                installer.start()
            assert "Failed to start" in str(exc.value)

    @patch("subprocess.run")
    def test_stop_darwin_failure(self, mock_run: MagicMock) -> None:
        """Test stop failure on Darwin."""
        mock_run.side_effect = subprocess.CalledProcessError(
            1, "launchctl", stderr="Service not found"
        )

        with patch.object(ServiceInstaller, "__init__", lambda self, **kw: None):
            installer = ServiceInstaller.__new__(ServiceInstaller)
            installer.service_name = "test-service"
            installer.system = "Darwin"

            with pytest.raises(ServiceError) as exc:
                installer.stop()
            assert "Failed to stop" in str(exc.value)


class TestServiceInstallerStatusErrors:
    """Tests for service status error handling."""

    @patch("subprocess.run")
    def test_status_exception_returns_error(self, mock_run: MagicMock) -> None:
        """Test status returns error dict on exception."""
        mock_run.side_effect = Exception("Unexpected error")

        installer = ServiceInstaller("test-service")
        status = installer.status()

        assert status["installed"] is False
        assert "error" in status


class TestValidServiceNamePattern:
    """Tests for the service name pattern."""

    def test_pattern_valid_names(self) -> None:
        """Test pattern matches valid names."""
        assert VALID_SERVICE_NAME_PATTERN.match("valid") is not None
        assert VALID_SERVICE_NAME_PATTERN.match("valid-name") is not None
        assert VALID_SERVICE_NAME_PATTERN.match("valid_name") is not None
        assert VALID_SERVICE_NAME_PATTERN.match("Valid123") is not None

    def test_pattern_invalid_names(self) -> None:
        """Test pattern rejects invalid names."""
        assert VALID_SERVICE_NAME_PATTERN.match("invalid space") is None
        assert VALID_SERVICE_NAME_PATTERN.match("/invalid") is None
        assert VALID_SERVICE_NAME_PATTERN.match("invalid$name") is None
        assert VALID_SERVICE_NAME_PATTERN.match("") is None
