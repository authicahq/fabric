"""Fabric - Cross-platform model linker for LLM inference engines."""

from __future__ import annotations

try:
    from importlib.metadata import version

    __version__ = version("authica-fabric")
except ImportError:
    # Fallback for Python < 3.8 or if package not installed
    __version__ = "unknown"

__all__ = ["__version__"]
