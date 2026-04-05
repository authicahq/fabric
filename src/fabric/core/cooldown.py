"""Cooldown-based circular sync prevention."""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass
from pathlib import Path

from .logging import get_logger

logger = get_logger(__name__)


@dataclass
class CooldownEntry:
    """A path currently in cooldown."""
    key: str  # device:inode or path
    path: Path
    backend_id: str | None
    expires_at: float


class SyncCooldownManager:
    """
    Manages cooldown periods to prevent circular sync loops.
    
    After we create a hardlink, we enter a brief cooldown period
    during which we ignore filesystem events for that path.
    """
    
    # Default cooldown period in seconds (200ms is usually sufficient)
    DEFAULT_COOLDOWN = 0.2
    
    def __init__(self, cooldown_seconds: float = DEFAULT_COOLDOWN):
        self.cooldown_seconds = cooldown_seconds
        self._cooldowns: dict[str, CooldownEntry] = {}
        self._lock = threading.Lock()
    
    def _get_key(self, path: Path) -> str:
        """Generate a unique key for a path (using inode when possible)."""
        try:
            stat = path.stat()
            return f"{stat.st_dev}:{stat.st_ino}"
        except OSError:
            # Fallback to resolved path string
            return str(path.resolve())
    
    def enter_cooldown(
        self, 
        path: Path, 
        backend_id: str | None = None
    ) -> None:
        """
        Enter cooldown for a path after we just modified it.
        Call this immediately after creating a hardlink.
        """
        key = self._get_key(path)
        
        entry = CooldownEntry(
            key=key,
            path=path,
            backend_id=backend_id,
            expires_at=time.time() + self.cooldown_seconds,
        )
        
        with self._lock:
            self._cooldowns[key] = entry
        
        logger.debug(
            "Entered cooldown",
            path=str(path),
            backend_id=backend_id,
            duration=self.cooldown_seconds,
        )
        
        # Schedule cleanup
        cleanup_delay = self.cooldown_seconds + 0.1
        threading.Timer(cleanup_delay, self._remove_cooldown, args=[key]).start()
    
    def is_in_cooldown(self, path: Path) -> bool:
        """
        Check if a path is currently in cooldown.
        Returns True if we should ignore this event.
        """
        key = self._get_key(path)
        
        with self._lock:
            entry = self._cooldowns.get(key)
            if entry is None:
                return False
            
            # Check if expired
            if time.time() > entry.expires_at:
                # Will be cleaned up by timer, but remove now to be safe
                self._cooldowns.pop(key, None)
                return False
            
            logger.debug(
                "Path in cooldown, ignoring event",
                path=str(path),
            )
            return True
    
    def _remove_cooldown(self, key: str) -> None:
        """Remove expired cooldown entry."""
        with self._lock:
            self._cooldowns.pop(key, None)
    
    def clear(self) -> None:
        """Clear all cooldowns (e.g., on shutdown)."""
        with self._lock:
            self._cooldowns.clear()
    
    def get_active_count(self) -> int:
        """Get number of paths currently in cooldown."""
        with self._lock:
            now = time.time()
            # Clean expired entries
            expired = [k for k, e in self._cooldowns.items() if now > e.expires_at]
            for k in expired:
                self._cooldowns.pop(k, None)
            return len(self._cooldowns)
