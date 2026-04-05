"""Unified model index across all backend directories."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING

from .logging import get_logger
from .models import GGUFMetadata, get_multipart_base, get_mmproj_base, is_partial_download, normalize_model_id

if TYPE_CHECKING:
    from ..backends.base import Backend

logger = get_logger(__name__)


@dataclass(slots=True)
class ModelInstance:
    """A specific instance of a model file in a specific location."""
    path: Path
    backend_id: str
    inode: int
    device: int
    mtime: float
    size: int
    metadata: GGUFMetadata | None = None
    
    @property
    def model_id(self) -> str:
        """Get the normalized model ID from filename."""
        return normalize_model_id(self.path.stem)
    
    def same_content(self, other: ModelInstance) -> bool:
        """Check if this instance has the same content as another."""
        # Same inode + device = same file (hardlinked)
        if self.inode == other.inode and self.device == other.device:
            return True
        # Different size = definitely different
        if self.size != other.size:
            return False
        # Same size and mtime = probably same (heuristic)
        return abs(self.mtime - other.mtime) < 0.001
    
    def __hash__(self) -> int:
        return hash((self.path, self.backend_id))
    
    def __eq__(self, other: object) -> bool:
        if not isinstance(other, ModelInstance):
            return False
        return self.path == other.path and self.backend_id == other.backend_id


@dataclass
class UnifiedModelEntry:
    """Aggregated view of a model across all backends."""
    model_id: str
    instances: list[ModelInstance] = field(default_factory=list)
    
    @property
    def has_conflicts(self) -> bool:
        """Check if different instances have different content."""
        if len(self.instances) <= 1:
            return False
        # Group by (inode, device) - same tuple = same content
        content_ids = {(i.inode, i.device) for i in self.instances}
        return len(content_ids) > 1
    
    @property
    def unique_content_count(self) -> int:
        """Count how many unique versions of this model exist."""
        content_ids = {(i.inode, i.device) for i in self.instances}
        return len(content_ids)
    
    @property
    def newest_instance(self) -> ModelInstance | None:
        """Get the most recently modified instance."""
        if not self.instances:
            return None
        return max(self.instances, key=lambda i: i.mtime)
    
    @property
    def largest_instance(self) -> ModelInstance | None:
        """Get the largest instance by file size."""
        if not self.instances:
            return None
        return max(self.instances, key=lambda i: i.size)
    
    def get_instance_for_backend(self, backend_id: str) -> ModelInstance | None:
        """Get the instance (if any) for a specific backend."""
        for instance in self.instances:
            if instance.backend_id == backend_id:
                return instance
        return None
    
    def get_instances_by_content(self) -> dict[tuple[int, int], list[ModelInstance]]:
        """Group instances by their content (inode, device)."""
        groups: dict[tuple[int, int], list[ModelInstance]] = {}
        for instance in self.instances:
            key = (instance.inode, instance.device)
            groups.setdefault(key, []).append(instance)
        return groups
    
    def add_instance(self, instance: ModelInstance) -> None:
        """Add a new instance to this entry."""
        self.instances.append(instance)
    
    def remove_backend(self, backend_id: str) -> bool:
        """Remove all instances for a specific backend."""
        original_count = len(self.instances)
        self.instances = [i for i in self.instances if i.backend_id != backend_id]
        return len(self.instances) < original_count


class UnifiedIndex:
    """
    Unified index of all models across all backend directories.
    """
    
    def __init__(self, backends: dict[str, Backend]):
        self.backends = backends
        self.entries: dict[str, UnifiedModelEntry] = {}
    
    def build(self) -> None:
        """
        Build the unified index by scanning all backend directories.
        """
        logger.info("Building unified index", backends=list(self.backends.keys()))
        
        self.entries = {}
        
        # Scan all backends
        for backend_id, backend in self.backends.items():
            self._scan_backend(backend_id, backend)
        
        # Report conflicts
        conflicts = self.get_conflicts()
        if conflicts:
            logger.warning(
                "Detected model conflicts",
                conflict_count=len(conflicts),
                models=[e.model_id for e in conflicts],
            )
        
        logger.info(
            "Unified index complete",
            total_models=len(self.entries),
            conflicts=len(conflicts),
        )
    
    def _scan_backend(self, backend_id: str, backend: Backend) -> None:
        """Scan a single backend directory."""
        output_dir = backend.output_dir
        if not output_dir.exists():
            logger.debug("Backend directory does not exist", backend_id=backend_id)
            return
        
        logger.debug("Scanning backend directory", backend_id=backend_id, path=str(output_dir))
        
        try:
            for entry in os.scandir(output_dir):
                if not entry.is_file():
                    continue
                    
                filename = entry.name
                if not filename.endswith(".gguf"):
                    continue
                if is_partial_download(filename):
                    continue
                
                file_path = Path(entry.path)
                
                try:
                    stat = entry.stat(follow_symlinks=False)
                    instance = ModelInstance(
                        path=file_path,
                        backend_id=backend_id,
                        inode=stat.st_ino,
                        device=stat.st_dev,
                        mtime=stat.st_mtime,
                        size=stat.st_size,
                    )
                    
                    # Extract model_id from filename
                    model_id = self._extract_model_id(filename)
                    self._add_instance(model_id, instance)
                    
                except OSError as e:
                    logger.warning("Failed to stat file", path=str(file_path), error=str(e))
                    
        except OSError as e:
            logger.error("Failed to scan backend", backend_id=backend_id, error=str(e))
    
    def _extract_model_id(self, filename: str) -> str:
        """Extract normalized model_id from filename."""
        # Handle conflict files: model.conflict.backend.gguf -> model
        if ".conflict." in filename.lower():
            parts = filename.split(".")
            if len(parts) >= 4 and parts[-3].lower() == "conflict":
                return normalize_model_id(".".join(parts[:-3]))
        
        # Handle multipart files
        if multipart_base := get_multipart_base(filename):
            return normalize_model_id(multipart_base)
        
        # Handle mmproj files
        if "mmproj" in filename.lower():
            base = get_mmproj_base(filename)
            if base:
                return normalize_model_id(base)
        
        # Standard single file
        base = filename.replace(".gguf", "")
        return normalize_model_id(base)
    
    def _add_instance(self, model_id: str, instance: ModelInstance) -> None:
        """Add an instance to the appropriate entry."""
        if model_id not in self.entries:
            self.entries[model_id] = UnifiedModelEntry(model_id=model_id)
        self.entries[model_id].add_instance(instance)
    
    def get_entry(self, model_id: str) -> UnifiedModelEntry | None:
        """Get the unified entry for a model."""
        return self.entries.get(model_id)
    
    def get_conflicts(self) -> list[UnifiedModelEntry]:
        """Get all entries with conflicts."""
        return [e for e in self.entries.values() if e.has_conflicts]
    
    def add_instance(self, model_id: str, instance: ModelInstance) -> None:
        """Add a new instance (e.g., from a filesystem event)."""
        self._add_instance(model_id, instance)
    
    def remove_instance(self, model_id: str, backend_id: str) -> bool:
        """Remove an instance (e.g., backend deleted the file)."""
        entry = self.entries.get(model_id)
        if not entry:
            return False
        
        entry.remove_backend(backend_id)
        
        if not entry.instances:
            del self.entries[model_id]
        
        return True
    
    def get_stats(self) -> dict:
        """Get index statistics."""
        total_instances = sum(len(e.instances) for e in self.entries.values())
        conflicts = len(self.get_conflicts())
        
        return {
            "total_models": len(self.entries),
            "total_instances": total_instances,
            "conflicts": conflicts,
            "backends": list(self.backends.keys()),
        }
