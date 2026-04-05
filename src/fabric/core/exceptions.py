"""Custom exceptions for fabric."""

from __future__ import annotations


class FabricError(Exception):
    """Base exception for all fabric errors."""

    def __init__(self, message: str, *, details: dict[str, object] | None = None) -> None:
        super().__init__(message)
        self.message = message
        self.details = details or {}


class ConfigError(FabricError):
    """Configuration-related errors."""

    pass


class GGUFError(FabricError):
    """GGUF parsing errors."""

    pass


class SyncError(FabricError):
    """File synchronization errors."""

    pass


class BackendError(FabricError):
    """Backend-specific errors."""

    def __init__(
        self,
        message: str,
        *,
        backend_name: str | None = None,
        details: dict[str, object] | None = None,
    ) -> None:
        super().__init__(message, details=details)
        self.backend_name = backend_name


class WatchError(FabricError):
    """Filesystem watching errors."""

    pass


class ServiceError(FabricError):
    """Service installation/management errors."""

    pass
