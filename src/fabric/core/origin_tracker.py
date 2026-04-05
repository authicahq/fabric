"""Origin tracking for multi-source synchronization."""

from __future__ import annotations

import json
import os
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .logging import get_logger

logger = get_logger(__name__)


@dataclass(frozen=True)
class ModelOrigin:
    """Origin information for a model."""
    backend_id: str
    first_seen: float
    original_path: Path


class OriginTracker:
    """
    Tracks which backend first introduced each model.
    Persists to JSON files in metadata directory.
    """
    
    def __init__(self, metadata_dir: Path):
        self.metadata_dir = Path(metadata_dir).resolve()
        self.origins_dir = self.metadata_dir / "origins"
        self._cache: dict[str, ModelOrigin] = {}
        
        self._ensure_directories()
        self._load_cache()
    
    def _ensure_directories(self) -> None:
        """Create metadata directories if they don't exist."""
        self.metadata_dir.mkdir(parents=True, exist_ok=True)
        self.origins_dir.mkdir(exist_ok=True)
    
    def _origin_file(self, model_id: str) -> Path:
        """Get the origin file path for a model."""
        # Sanitize model_id for filesystem
        safe_id = model_id.replace("/", "_").replace("\\", "_")
        return self.origins_dir / f"{safe_id}.origin"
    
    def _load_cache(self) -> None:
        """Load all origins into memory cache."""
        if not self.origins_dir.exists():
            return
            
        for origin_file in self.origins_dir.glob("*.origin"):
            model_id = origin_file.stem
            try:
                data = json.loads(origin_file.read_text())
                self._cache[model_id] = ModelOrigin(
                    backend_id=data["backend_id"],
                    first_seen=data["first_seen"],
                    original_path=Path(data["original_path"]),
                )
            except (json.JSONDecodeError, KeyError, OSError) as e:
                logger.warning(f"Failed to load origin file {origin_file}", error=str(e))
    
    def record_origin(
        self, 
        model_id: str, 
        backend_id: str, 
        original_path: Path
    ) -> bool:
        """
        Record that this model originated from the given backend.
        Idempotent - only records if not already set.
        Returns True if this is a new origin (first time seeing this model).
        """
        if model_id in self._cache:
            return False
            
        origin = ModelOrigin(
            backend_id=backend_id,
            first_seen=time.time(),
            original_path=original_path,
        )
        
        origin_file = self._origin_file(model_id)
        try:
            data = {
                "backend_id": origin.backend_id,
                "first_seen": origin.first_seen,
                "original_path": str(origin.original_path),
            }
            origin_file.write_text(json.dumps(data, indent=2))
            self._cache[model_id] = origin
            logger.debug(
                "Recorded model origin",
                model_id=model_id,
                backend_id=backend_id,
            )
            return True
        except OSError as e:
            logger.error(f"Failed to write origin file {origin_file}", error=str(e))
            return False
    
    def get_origin(self, model_id: str) -> ModelOrigin | None:
        """Get the origin information for a model."""
        return self._cache.get(model_id)
    
    def is_origin(self, model_id: str, backend_id: str) -> bool:
        """Check if the given backend is the origin of this model."""
        origin = self._cache.get(model_id)
        return origin is not None and origin.backend_id == backend_id
    
    def update_origin_backend(self, model_id: str, new_backend_id: str) -> bool:
        """
        Update the origin backend (used after conflict resolution).
        """
        origin = self._cache.get(model_id)
        if origin is None:
            return False
            
        new_origin = ModelOrigin(
            backend_id=new_backend_id,
            first_seen=origin.first_seen,
            original_path=origin.original_path,
        )
        
        origin_file = self._origin_file(model_id)
        try:
            data = {
                "backend_id": new_origin.backend_id,
                "first_seen": new_origin.first_seen,
                "original_path": str(new_origin.original_path),
            }
            origin_file.write_text(json.dumps(data, indent=2))
            self._cache[model_id] = new_origin
            return True
        except OSError as e:
            logger.error(f"Failed to update origin file {origin_file}", error=str(e))
            return False
    
    def remove_origin(self, model_id: str) -> bool:
        """Remove origin tracking for a model."""
        if model_id not in self._cache:
            return False
        
        origin_file = self._origin_file(model_id)
        try:
            if origin_file.exists():
                origin_file.unlink()
            del self._cache[model_id]
            return True
        except OSError as e:
            logger.error(f"Failed to remove origin file {origin_file}", error=str(e))
            return False
    
    def list_origins(self) -> dict[str, ModelOrigin]:
        """List all tracked origins."""
        return dict(self._cache)
    
    def clear(self) -> None:
        """Clear all origins (use with caution)."""
        for model_id in list(self._cache.keys()):
            self.remove_origin(model_id)
