"""Backend auto-discovery for common LLM inference engines."""

from __future__ import annotations

import platform
import socket
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from ..core.logging import get_logger

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


class BackendDiscovery:
    """Auto-discovers installed LLM inference backends."""

    def __init__(self) -> None:
        self._system = platform.system()
        self._home = Path.home()

    def discover_all(self) -> list[DiscoveredBackend]:
        """Discover all available backends on the system.

        Returns:
            List of discovered backends
        """
        from ..backends import (
            GPT4AllBackend,
            JanBackend,
            KoboldCppBackend,
            LlamaCppBackend,
            LlamaCppPythonBackend,
            LMStudioBackend,
            LocalAIBackend,
            OllamaBackend,
            TextGenBackend,
            vLLMBackend,
        )

        backends: list[DiscoveredBackend] = []
        seen: set[tuple[str, Path]] = set()

        backend_classes = [
            LlamaCppBackend,
            LocalAIBackend,
            LMStudioBackend,
            OllamaBackend,
            TextGenBackend,
            GPT4AllBackend,
            KoboldCppBackend,
            vLLMBackend,
            JanBackend,
            LlamaCppPythonBackend,
        ]

        for backend_cls in backend_classes:
            try:
                discovered = backend_cls.discover()
                for d in discovered:
                    key = (d.backend_type, d.install_dir)
                    if key not in seen:
                        seen.add(key)
                        if d.install_dir:
                            d.install_dir = self._resolve_path(d.install_dir)
                        if d.models_dir:
                            d.models_dir = self._resolve_path(d.models_dir)
                        backends.append(d)
            except Exception as e:
                logger.debug("Discovery error", backend=backend_cls.__name__, error=str(e))

        logger.info("Backend discovery complete", count=len(backends))
        return backends

    def _resolve_backend_paths(self, backends: list[DiscoveredBackend]) -> list[DiscoveredBackend]:
        """Resolve paths in discovered backends to their absolute, real forms.

        Args:
            backends: List of discovered backends

        Returns:
            Same list with resolved paths
        """
        for backend in backends:
            if backend.install_dir:
                backend.install_dir = self._resolve_path(backend.install_dir)
            if backend.models_dir:
                backend.models_dir = self._resolve_path(backend.models_dir)
        return backends

    def _check_port(self, port: int) -> bool:
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

    def _resolve_path(self, path: Path) -> Path:
        """Resolve a path to its absolute, real form.

        Handles:
        - Relative paths (., ./foo)
        - Symlinks
        - Home directory expansion

        Args:
            path: Path to resolve

        Returns:
            Resolved absolute path
        """
        try:
            resolved = path.expanduser()
            return resolved.resolve()
        except Exception:
            return path.absolute()


def create_config_from_discovered(
    discovered: list[DiscoveredBackend],
) -> dict[str, dict[str, Any]]:
    """Create backend configuration dict from discovered backends.

    Args:
        discovered: List of discovered backends

    Returns:
        Dictionary suitable for backend configuration
    """
    config: dict[str, dict[str, Any]] = {}

    # Map backend types to config keys
    type_to_key = {
        "llama_cpp": "llama_cpp",
        "localai": "localai",
        "lmstudio": "lmstudio",
        "ollama": "ollama",
        "textgen": "textgen",
        "gpt4all": "gpt4all",
        "koboldcpp": "koboldcpp",
        "vllm": "vllm",
        "jan": "jan",
        "llama_cpp_python": "llama_cpp_python",
    }

    for backend in discovered:
        key = type_to_key.get(backend.backend_type, backend.backend_type)
        if key not in config:
            config[key] = {
                "enabled": True,
            }

        if backend.models_dir:
            config[key]["output_dir"] = str(backend.models_dir)

        if backend.is_running:
            config[key]["is_running"] = True
        if backend.port:
            config[key]["port"] = backend.port

    return config
