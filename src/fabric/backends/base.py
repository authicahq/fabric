"""Base class for all backends."""

from __future__ import annotations

import os
import platform
import shutil
import socket
import subprocess
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from ..core.constants import DIR_PERMISSIONS, FILE_PERMISSIONS
from ..core.logging import get_logger, log_action
from ..core.models import BackendConfig, ModelGroup, SyncAction

logger = get_logger(__name__)


@dataclass
class DiscoveredBackend:
    """Represents a discovered backend installation."""

    name: str
    backend_type: str
    install_dir: Path
    models_dir: Path | None
    is_running: bool = False
    port: int | None = None


@dataclass
class BackendDiscoveryConfig:
    """Configuration for backend discovery.

    Attributes:
        name: Display name
        backend_type: Type identifier
        search_paths: Directories to check for installation
        executables: Executable names to find in PATH
        default_models_subdir: Default subdir for models (relative to install)
        ports: Port range to check for running server
        docker_images: Docker image patterns to look for
        models_path_patterns: Patterns to extract model dir from process args
    """

    name: str
    backend_type: str
    search_paths: list[str] = field(default_factory=list)
    executables: list[str] = field(default_factory=list)
    default_models_subdir: str = "models"
    ports: tuple[int, int] = (0, 0)
    docker_images: list[str] = field(default_factory=list)
    models_path_patterns: list[str] = field(default_factory=list)


def _check_port(port: int) -> bool:
    """Check if a port is listening."""
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.settimeout(1)
    try:
        result = sock.connect_ex(("localhost", port))
        return result == 0
    except Exception:
        return False
    finally:
        sock.close()


def _get_system_info() -> tuple[str, Path]:
    """Get system info for discovery.

    Returns:
        Tuple of (system: str, home: Path)
    """
    return platform.system(), Path.home()


def _get_config_dir() -> Path:
    """Get platform-specific config directory."""
    system, home = _get_system_info()
    if system == "Windows":
        return Path(os.environ.get("APPDATA", home / "AppData" / "Roaming"))
    elif system == "Darwin":
        return home / "Library" / "Application Support"
    else:
        xdg_config = os.environ.get("XDG_CONFIG_HOME", home / ".config")
        return Path(xdg_config)


def _get_data_dir() -> Path:
    """Get platform-specific data directory."""
    system, home = _get_system_info()
    if system == "Windows":
        return Path(os.environ.get("APPDATA", home / "AppData" / "Roaming"))
    elif system == "Darwin":
        return home / "Library" / "Application Support"
    else:
        xdg_data = os.environ.get("XDG_DATA_HOME", home / ".local" / "share")
        return Path(xdg_data)

    def _resolve_path(path: Path) -> Path:
        """Resolve a path to its absolute, real form."""
        try:
            resolved = path.expanduser()
            return resolved.resolve()
        except Exception:
            return path.absolute()


def _find_process_model_dir() -> Path | None:
    """Find model directory from running process command lines."""
    try:
        result = subprocess.run(
            ["ps", "ax", "--no-headers", "-o", "args"],
            capture_output=True,
            text=True,
            timeout=5,
        )
        patterns = [
            r"[-/]models[/\s]",
            r"--model-dir[=\s]+(\S+)",
            r"-m\s+(\S+)",
            r"MODEL_DIR[=\s]+(\S+)",
        ]
        import re

        for line in result.stdout.split("\n"):
            for pattern in patterns:
                match = re.search(pattern, line, re.IGNORECASE)
                if match:
                    potential = Path(match.group(1) if match.lastindex else match.group(0))
                    if potential.exists():
                        return potential
    except Exception:
        pass
    return None


def _discover_from_config(config: BackendDiscoveryConfig) -> list[DiscoveredBackend]:
    """Generic discovery from config."""
    backends: list[DiscoveredBackend] = []
    _, home = _get_system_info()

    resolved_paths = []
    for path in config.search_paths:
        path = path.replace("{HOME}", str(home))
        path = path.replace("{XDG_DATA}", str(_get_data_dir()))
        path = path.replace("{XDG_CONFIG}", str(_get_config_dir()))
        path = path.replace(
            "{APPDATA}", os.environ.get("APPDATA", str(home / "AppData" / "Roaming"))
        )

        if "{LOCALAPPDATA}" in path:
            path = path.replace("{LOCALAPPDATA}", os.environ.get("LOCALAPPDATA", ""))
        if "{PROGRAMDATA}" in path:
            path = path.replace("{PROGRAMDATA}", os.environ.get("PROGRAMDATA", "C:\\ProgramData"))

        p = Path(path)
        if p.exists():
            resolved_paths.append(p.resolve())

    for path in resolved_paths:
        is_running = False
        port = None
        if config.ports[1] > 0:
            for p in range(config.ports[0], config.ports[1]):
                if _check_port(p):
                    is_running = True
                    port = p
                    break

        models_dir = path / config.default_models_subdir
        if not models_dir.exists():
            models_dir = path

        backends.append(
            DiscoveredBackend(
                name=config.name,
                backend_type=config.backend_type,
                install_dir=path,
                models_dir=models_dir if models_dir.exists() else None,
                is_running=is_running,
                port=port,
            )
        )

    for exe in config.executables:
        exe_path = shutil.which(exe)
        if exe_path:
            is_running = False
            port = None
            if config.ports[1] > 0:
                for p in range(config.ports[0], config.ports[1]):
                    if _check_port(p):
                        is_running = True
                        port = p
                        break

            if not any(b.install_dir == Path(exe_path).parent.resolve() for b in backends):
                process_model_dir = _find_process_model_dir()
                backends.append(
                    DiscoveredBackend(
                        name=config.name,
                        backend_type=config.backend_type,
                        install_dir=Path(exe_path).parent.resolve(),
                        models_dir=process_model_dir,
                        is_running=is_running,
                        port=port,
                    )
                )

    if config.docker_images and shutil.which("docker"):
        try:
            result = subprocess.run(
                ["docker", "ps", "--format", "{{.ID}}|{{.Names}}|{{.Image}}|{{.Ports}}"],
                capture_output=True,
                text=True,
                timeout=10,
            )
            import re

            for line in result.stdout.strip().split("\n"):
                if not line.strip():
                    continue
                parts = line.split("|")
                if len(parts) < 3:
                    continue
                container_id, name, image = parts[0], parts[1], parts[2].lower()
                ports = parts[3] if len(parts) > 3 else ""

                for img_pattern in config.docker_images:
                    if img_pattern.lower() in image or img_pattern.lower() in name:
                        port = None
                        port_match = re.search(r":(\d+)->", ports)
                        if port_match:
                            port = int(port_match.group(1))

                        models_dir = None
                        for path in ["/models", "/app/models", "/localai/models"]:
                            try:
                                subprocess.run(
                                    ["docker", "exec", container_id, "test", "-d", path],
                                    capture_output=True,
                                    timeout=5,
                                )
                                models_dir = Path(path)
                                break
                            except Exception:
                                continue

                        backends.append(
                            DiscoveredBackend(
                                name=f"{config.name}_docker",
                                backend_type=config.backend_type,
                                install_dir=Path(f"/var/lib/docker/containers/{container_id}"),
                                models_dir=models_dir,
                                is_running=port is not None,
                                port=port,
                            )
                        )
                        break
        except Exception:
            pass

    return backends


@dataclass
class LinkResult:
    """Result of a single link operation."""

    success: bool
    action: SyncAction
    source: Path
    target: Path
    is_hardlink: bool = False
    error: str | None = None


@dataclass
class BackendResult:
    """Result of a backend sync operation."""

    success: bool
    linked: int = 0
    updated: int = 0
    removed: int = 0
    skipped: int = 0
    errors: list[str] = field(default_factory=list)
    details: dict[str, Any] = field(default_factory=dict)
    skip_reasons: list[dict[str, str]] = field(default_factory=list)


class Backend(ABC):
    """Abstract base class for all backends."""

    discovery_config: BackendDiscoveryConfig | None = None

    def __init__(self, config: BackendConfig) -> None:
        """Initialize backend.

        Args:
            config: Backend configuration
        """
        self.config = config
        self.output_dir = config.output_dir
        self.logger = get_logger(self.__class__.__name__)

    @property
    @abstractmethod
    def name(self) -> str:
        """Return the backend name."""
        pass
    
    @property
    def backend_id(self) -> str:
        """Return the unique backend ID for multi-source mode."""
        # Use configured backend_id if available, otherwise derive from name
        if self.config.backend_id:
            return self.config.backend_id
        return self.name.lower().replace(" ", "_").replace("-", "_")

    @classmethod
    def discover(cls) -> list[DiscoveredBackend]:
        """Discover this backend type on the system.

        Returns:
            List of discovered backend instances
        """
        if cls.discovery_config is None:
            return []
        return _discover_from_config(cls.discovery_config)

    @abstractmethod
    def sync_group(
        self,
        group: ModelGroup,
        source_dir: Path,
        context_size: int | None = None,
        gpu_layers: int | None = None,
        threads: int | None = None,
    ) -> BackendResult:
        """Sync a model group to this backend.

        Args:
            group: Model group to sync
            source_dir: Source directory (ground truth)
            context_size: Optional context size override
            gpu_layers: Optional GPU layers override
            threads: Optional threads override

        Returns:
            BackendResult with operation results
        """
        pass

    @abstractmethod
    def remove_group(self, model_id: str) -> BackendResult:
        """Remove a model group from this backend.

        Args:
            model_id: Normalized model ID to remove

        Returns:
            BackendResult with operation results
        """
        pass

    def setup(self) -> None:
        """Setup the backend (create directories, etc.)."""
        if not self.config.enabled:
            return

        self.output_dir.mkdir(parents=True, exist_ok=True)
        self._set_permissions(self.output_dir)
        self.logger.debug("Backend setup complete", output_dir=str(self.output_dir))

    def cleanup(self) -> None:  # noqa: B027
        """Cleanup any resources. Called during shutdown."""
        pass

    def _ensure_dir(self, path: Path) -> None:
        """Ensure a directory exists with proper permissions.

        Args:
            path: Directory path to ensure exists
        """
        if not path.exists():
            path.mkdir(parents=True, exist_ok=True)
            self._set_permissions(path)

    def _set_permissions(self, path: Path) -> None:
        """Set appropriate permissions on a file or directory.

        Args:
            path: Path to set permissions on
        """
        try:
            if path.is_dir():
                path.chmod(DIR_PERMISSIONS)
            else:
                path.chmod(FILE_PERMISSIONS)
        except OSError as e:
            self.logger.warning("Failed to set permissions", path=str(path), error=str(e))

    def _create_link(
        self,
        source: Path,
        target: Path,
        *,
        dry_run: bool = False,
        prefer_hardlink: bool = True,
    ) -> LinkResult:
        """Create a link from source to target.

        Args:
            source: Source file (must exist)
            target: Target path to create
            dry_run: If True, don't actually create the link
            prefer_hardlink: Try hardlink first, fallback to symlink

        Returns:
            LinkResult with operation details
        """
        if not source.exists():
            return LinkResult(
                success=False,
                action=SyncAction.SKIP,
                source=source,
                target=target,
                error=f"Source does not exist: {source}",
            )

        # Ensure target directory exists
        if not dry_run:
            self._ensure_dir(target.parent)

        # Check if target already exists and is up to date
        target_existed = target.exists() or target.is_symlink()
        if target_existed:
            if self._is_same_file(source, target):
                return LinkResult(
                    success=True,
                    action=SyncAction.SKIP,
                    source=source,
                    target=target,
                    is_hardlink=self._is_hardlink(target),
                )

            if not dry_run:
                # Remove existing file/link
                if target.is_dir():
                    shutil.rmtree(target)
                else:
                    target.unlink()

        if dry_run:
            log_action(
                self.logger,
                "link",
                f"{source.name} -> {target}",
                dry_run=True,
                source=str(source),
                target=str(target),
            )
            return LinkResult(
                success=True,
                action=SyncAction.UPDATE if target_existed else SyncAction.CREATE,
                source=source,
                target=target,
                is_hardlink=prefer_hardlink,
            )

        # Try to create link
        is_hardlink = False
        try:
            if prefer_hardlink:
                try:
                    os.link(source, target)  # Hardlink
                    is_hardlink = True
                    action = "HARDLINK"
                except OSError:
                    # Cross-device or other error, try symlink
                    target.symlink_to(source)
                    action = "SYMLINK"
            else:
                target.symlink_to(source)
                action = "SYMLINK"

            self._set_permissions(target)

            log_action(
                self.logger,
                action,
                f"{source.name} -> {target}",
                source=str(source),
                target=str(target),
            )

            return LinkResult(
                success=True,
                action=SyncAction.UPDATE if target_existed else SyncAction.CREATE,
                source=source,
                target=target,
                is_hardlink=is_hardlink,
            )

        except OSError as e:
            error_msg = f"Failed to create link: {e}"
            self.logger.error(error_msg, source=str(source), target=str(target))
            return LinkResult(
                success=False,
                action=SyncAction.SKIP,
                source=source,
                target=target,
                error=error_msg,
            )

    def _is_same_file(self, path1: Path, path2: Path) -> bool:
        """Check if two paths point to the same file.

        Compares by inode if on same filesystem, otherwise by size and mtime.

        Args:
            path1: First path
            path2: Second path

        Returns:
            True if files are the same
        """
        try:
            # Try inode comparison first (fastest)
            stat1 = path1.stat()
            stat2 = path2.stat()

            if stat1.st_ino == stat2.st_ino and stat1.st_dev == stat2.st_dev:
                return True

            # Fallback to size and mtime comparison
            if stat1.st_size != stat2.st_size:
                return False

            # If size matches and mtime matches, assume same file
            return int(stat1.st_mtime) == int(stat2.st_mtime)

        except (OSError, FileNotFoundError):
            return False

    def _is_hardlink(self, path: Path) -> bool:
        """Check if path is a hardlink (not a symlink).

        Args:
            path: Path to check

        Returns:
            True if path is a hardlink (has multiple links)
        """
        try:
            return path.exists() and not path.is_symlink() and path.stat().st_nlink > 1
        except OSError:
            return False

    def _remove_path(self, path: Path, *, dry_run: bool = False) -> bool:
        """Remove a file or directory.

        Args:
            path: Path to remove
            dry_run: If True, don't actually remove

        Returns:
            True if removal succeeded or path didn't exist
        """
        if not path.exists() and not path.is_symlink():
            return True

        if dry_run:
            log_action(
                self.logger,
                "remove",
                str(path),
                dry_run=True,
                path=str(path),
            )
            return True

        try:
            if path.is_dir():
                shutil.rmtree(path)
            else:
                path.unlink()

            self.logger.info("REMOVED", path=str(path))
            return True

        except OSError as e:
            self.logger.error("Failed to remove", path=str(path), error=str(e))
            return False

    def _link_model_files(
        self,
        group: ModelGroup,
        model_dir: Path,
        source_dir: Path,
    ) -> BackendResult:
        """Link all files in a model group to a directory.

        Args:
            group: Model group to link
            model_dir: Target directory for links
            source_dir: Source directory (ground truth) for validation

        Returns:
            BackendResult with operation results
        """
        result = BackendResult(success=True)

        for model_file in group.files:
            if not model_file.path.is_relative_to(source_dir):
                logger.warning(
                    "File not in source directory, skipping",
                    file=model_file.name,
                    source=str(source_dir),
                )
                result.skipped += 1
                continue

            target = model_dir / model_file.name
            link_result = self._create_link(
                model_file.path,
                target,
                prefer_hardlink=self.config.prefer_hardlinks,
            )

            if link_result.success:
                if link_result.action == SyncAction.CREATE:
                    result.linked += 1
                elif link_result.action == SyncAction.SKIP:
                    result.skipped += 1
                elif link_result.action == SyncAction.UPDATE:
                    result.updated += 1
            else:
                result.errors.append(link_result.error or "Unknown error")

        if group.mmproj_file:
            mmproj_target = model_dir / group.mmproj_file.name
            link_result = self._create_link(
                group.mmproj_file.path,
                mmproj_target,
                prefer_hardlink=self.config.prefer_hardlinks,
            )

            if link_result.success and link_result.action == SyncAction.CREATE:
                result.linked += 1

        return result

    def _cleanup_orphans_simple(
        self,
        models_dir: Path,
        valid_model_ids: set[str],
        skip_dirs: set[str] | None = None,
    ) -> BackendResult:
        """Simple orphan cleanup - removes directories not in valid_model_ids.

        Args:
            models_dir: Directory to scan for orphans
            valid_model_ids: Set of valid model IDs to preserve
            skip_dirs: Optional set of directory names to skip (e.g., {".manifests"})

        Returns:
            BackendResult with cleanup results
        """
        result = BackendResult(success=True)
        skip_dirs = skip_dirs or set()

        if not models_dir.exists():
            return result

        for item in models_dir.iterdir():
            if item.name in skip_dirs:
                continue

            if item.is_dir() and item.name not in valid_model_ids:
                if self._remove_path(item):
                    result.removed += 1
                else:
                    result.errors.append(f"Failed to remove orphan: {item}")

        return result

    def _load_existing_config(self, path: Path, format: str = "json") -> dict | None:
        """Load existing config file if it exists.

        Args:
            path: Path to config file
            format: "json" or "yaml"

        Returns:
            Existing config dict, or None if doesn't exist
        """
        if not path.exists():
            return None

        try:
            if format == "json":
                import json

                with open(path) as f:
                    return json.load(f)
            elif format == "yaml":
                import yaml

                with open(path) as f:
                    return yaml.safe_load(f)
        except Exception as e:
            self.logger.warning("Failed to load existing config", path=str(path), error=str(e))
            return None

    def _merge_config(
        self,
        existing: dict | None,
        defaults: dict,
        protected_keys: set[str] | None = None,
    ) -> dict:
        """Merge existing config with defaults, protecting user-set values.

        Args:
            existing: Existing config (may be None)
            defaults: Default values to apply
            protected_keys: Keys that should NOT be overwritten from defaults

        Returns:
            Merged config dict
        """
        protected_keys = protected_keys or set()

        if existing is None:
            return defaults.copy()

        # Start with defaults, then overlay existing values
        result = defaults.copy()

        for key, value in existing.items():
            # Protected keys keep their existing value
            if key in protected_keys and value is not None:
                continue
            # None values in existing are treated as "not set", use default
            if value is not None:
                result[key] = value

        return result
