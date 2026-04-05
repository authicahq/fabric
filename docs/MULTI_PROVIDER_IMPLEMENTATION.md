# Multi-Provider Sync Implementation Guide

## File Modifications Overview

### New Files
- `core/unified_index.py` - Unified model index across all backends
- `core/origin_tracker.py` - Origin tracking for models
- `core/conflict_resolver.py` - Conflict detection and resolution
- `core/multi_sync.py` - MultiSourceSyncEngine implementation

### Modified Files
- `core/models.py` - Add new configuration classes
- `core/config.py` - Parse multi-source configuration
- `core/watcher.py` - Support watching multiple directories
- `backends/base.py` - Add backend_id and scan_models()
- `main.py` - Add multi-sync command

## Detailed Implementation

### 1. Core Models (`core/models.py`)

Add these new classes:

```python
# Add to existing imports
from enum import Enum

class SyncMode(Enum):
    """Synchronization mode."""
    SINGLE_SOURCE = "single_source"
    MULTI_SOURCE = "multi_source"

class ConflictStrategy(Enum):
    """Conflict resolution strategies."""
    KEEP_NEWEST = "newest"
    KEEP_LARGEST = "largest"
    KEEP_ALL = "all"
    MANUAL = "manual"

# Add to SyncConfig class
class SyncConfig(BaseModel):
    """Extended sync configuration."""
    
    # Existing fields...
    mode: SyncMode = SyncMode.SINGLE_SOURCE
    conflict_resolution: ConflictStrategy = ConflictStrategy.KEEP_NEWEST
    metadata_dir: Path | None = None
    unified_storage_dir: Path | None = None
    
    @field_validator("mode", mode="before")
    @classmethod
    def validate_mode(cls, v):
        if isinstance(v, str):
            return SyncMode(v)
        return v
    
    @field_validator("conflict_resolution", mode="before")
    @classmethod
    def validate_conflict_strategy(cls, v):
        if isinstance(v, str):
            return ConflictStrategy(v)
        return v

# New configuration class
class MultiSourceConfig(BaseModel):
    """Configuration specific to multi-source mode."""
    
    metadata_dir: Path = Field(default_factory=lambda: Path("/var/lib/fabric"))
    unified_storage_dir: Path | None = None  # None = use first backend as canonical
    
    # Backend priority for conflict resolution (lower = higher priority)
    backend_priority: dict[str, int] = Field(default_factory=dict)
    
    @field_validator("metadata_dir", "unified_storage_dir")
    @classmethod
    def validate_dirs(cls, v: Path | None) -> Path | None:
        if v is not None:
            return v.expanduser().resolve()
        return v
```

### 2. Origin Tracker (`core/origin_tracker.py`)

```python
"""Origin tracking for multi-source synchronization."""

from __future__ import annotations

import json
import threading
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
    Thread-safe singleton per metadata directory.
    """
    
    _instances: dict[Path, "OriginTracker"] = {}
    _lock = threading.Lock()
    
    def __new__(cls, metadata_dir: Path) -> "OriginTracker":
        metadata_dir = metadata_dir.resolve()
        with cls._lock:
            if metadata_dir not in cls._instances:
                instance = super().__new__(cls)
                instance._initialized = False
                cls._instances[metadata_dir] = instance
            return cls._instances[metadata_dir]
    
    def __init__(self, metadata_dir: Path) -> None:
        if self._initialized:
            return
            
        self.metadata_dir = metadata_dir.resolve()
        self.origins_dir = self.metadata_dir / "origins"
        self._cache: dict[str, ModelOrigin] = {}
        self._file_lock = threading.Lock()
        
        self._ensure_directories()
        self._load_cache()
        self._initialized = True
    
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
    ) -> None:
        """
        Record that this model originated from the given backend.
        Idempotent - only records if not already set.
        """
        if model_id in self._cache:
            return
            
        origin = ModelOrigin(
            backend_id=backend_id,
            first_seen=time.time(),
            original_path=original_path,
        )
        
        with self._file_lock:
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
            except OSError as e:
                logger.error(f"Failed to write origin file {origin_file}", error=str(e))
    
    def get_origin(self, model_id: str) -> ModelOrigin | None:
        """Get the origin information for a model."""
        return self._cache.get(model_id)
    
    def is_origin(self, model_id: str, backend_id: str) -> bool:
        """Check if the given backend is the origin of this model."""
        origin = self._cache.get(model_id)
        return origin is not None and origin.backend_id == backend_id
    
    def update_origin_backend(self, model_id: str, new_backend_id: str) -> None:
        """
        Update the origin backend (used after conflict resolution).
        """
        origin = self._cache.get(model_id)
        if origin is None:
            return
            
        new_origin = ModelOrigin(
            backend_id=new_backend_id,
            first_seen=origin.first_seen,
            original_path=origin.original_path,
        )
        
        with self._file_lock:
            origin_file = self._origin_file(model_id)
            try:
                data = {
                    "backend_id": new_origin.backend_id,
                    "first_seen": new_origin.first_seen,
                    "original_path": str(new_origin.original_path),
                }
                origin_file.write_text(json.dumps(data, indent=2))
                self._cache[model_id] = new_origin
            except OSError as e:
                logger.error(f"Failed to update origin file {origin_file}", error=str(e))
    
    def list_origins(self) -> dict[str, ModelOrigin]:
        """List all tracked origins."""
        return dict(self._cache)
```

### 3. Unified Index (`core/unified_index.py`)

```python
"""Unified model index across all backend directories."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING

from .gguf_parser import ParallelGGUFParser, parse_gguf_file
from .logging import get_logger
from .models import GGUFMetadata, ModelGroup, get_multipart_base, get_mmproj_base, is_partial_download

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
        return self.path.stem
    
    def same_content(self, other: ModelInstance) -> bool:
        """Check if this instance has the same content as another."""
        # Same inode = same file (hardlinked)
        if self.inode == other.inode and self.device == other.device:
            return True
        # Different size = definitely different
        if self.size != other.size:
            return False
        # Same size and mtime = probably same (heuristic)
        if self.mtime == other.mtime:
            return True
        return False


@dataclass
class UnifiedModelEntry:
    """Aggregated view of a model across all backends."""
    model_id: str
    instances: list[ModelInstance] = field(default_factory=list)
    group: ModelGroup | None = None
    
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


class UnifiedIndex:
    """
    Unified index of all models across all backend directories.
    """
    
    def __init__(self, backends: dict[str, Backend]):
        self.backends = backends
        self.entries: dict[str, UnifiedModelEntry] = {}
        self._multipart_files: dict[str, list[ModelInstance]] = {}
        self._mmproj_files: dict[str, ModelInstance] = {}
    
    def build(self, parse_metadata: bool = False) -> None:
        """
        Build the unified index by scanning all backend directories.
        """
        logger.info("Building unified index", backends=list(self.backends.keys()))
        
        self.entries = {}
        self._multipart_files = {}
        self._mmproj_files = {}
        
        # First pass: scan all backends and collect file info
        for backend_id, backend in self.backends.items():
            self._scan_backend(backend_id, backend)
        
        # Second pass: build model groups (handle multipart/mmproj)
        self._build_groups()
        
        # Third pass: parse metadata if requested
        if parse_metadata:
            self._parse_metadata()
        
        # Report conflicts
        conflicts = [e for e in self.entries.values() if e.has_conflicts]
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
        
        for root, _dirs, files in os.walk(output_dir):
            for filename in files:
                if not filename.endswith(".gguf"):
                    continue
                if is_partial_download(filename):
                    continue
                
                file_path = Path(root) / filename
                
                try:
                    stat = file_path.stat()
                    instance = ModelInstance(
                        path=file_path,
                        backend_id=backend_id,
                        inode=stat.st_ino,
                        device=stat.st_dev,
                        mtime=stat.st_mtime,
                        size=stat.st_size,
                    )
                    
                    # Categorize file
                    if "mmproj" in filename.lower():
                        base = get_mmproj_base(filename)
                        if base:
                            self._mmproj_files[base] = instance
                    elif multipart_base := get_multipart_base(filename):
                        self._multipart_files.setdefault(multipart_base, []).append(instance)
                    else:
                        # Single file model
                        model_id = filename.replace(".gguf", "")
                        self._add_instance(model_id, instance)
                        
                except OSError as e:
                    logger.warning("Failed to stat file", path=str(file_path), error=str(e))
    
    def _add_instance(self, model_id: str, instance: ModelInstance) -> None:
        """Add an instance to the appropriate entry."""
        if model_id not in self.entries:
            self.entries[model_id] = UnifiedModelEntry(model_id=model_id)
        self.entries[model_id].instances.append(instance)
    
    def _build_groups(self) -> None:
        """Build model groups for multipart models."""
        # Handle multipart models
        for base_name, instances in self._multipart_files.items():
            # All instances should be for the same model
            # Pick the newest as the canonical info
            newest = max(instances, key=lambda i: i.mtime)
            
            # Add to entries
            for instance in instances:
                self._add_instance(base_name, instance)
            
            # Try to find mmproj
            if base_name in self._mmproj_files:
                mmproj = self._mmproj_files[base_name]
                self._add_instance(base_name, mmproj)
        
        # Try to match unmatched mmproj files
        for mmproj_base, mmproj_instance in self._mmproj_files.items():
            if any(mmproj_base in e.model_id for e in self.entries.values()):
                continue  # Already matched
            
            # Try to find matching model
            for entry in self.entries.values():
                if mmproj_base.lower() in entry.model_id.lower():
                    self._add_instance(entry.model_id, mmproj_instance)
                    break
    
    def _parse_metadata(self) -> None:
        """Parse GGUF metadata for all model files."""
        # Collect all unique file paths
        all_paths: set[Path] = set()
        for entry in self.entries.values():
            for instance in entry.instances:
                all_paths.add(instance.path)
        
        if not all_paths:
            return
        
        # Parse in parallel
        with ParallelGGUFParser() as parser:
            metadata_map = parser.parse_files(list(all_paths))
        
        # Assign metadata to instances
        for entry in self.entries.values():
            for instance in entry.instances:
                if instance.path in metadata_map:
                    instance.metadata = metadata_map[instance.path]
    
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
        
        entry.instances = [i for i in entry.instances if i.backend_id != backend_id]
        
        if not entry.instances:
            del self.entries[model_id]
        
        return True
```

### 4. Conflict Resolver (`core/conflict_resolver.py`)

```python
"""Conflict detection and resolution for multi-source sync."""

from __future__ import annotations

import shutil
import time
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Callable

from .logging import get_logger
from .models import ConflictStrategy

if TYPE_CHECKING:
    from .unified_index import ModelInstance, UnifiedModelEntry

logger = get_logger(__name__)


@dataclass
class ConflictResolution:
    """Result of conflict resolution."""
    model_id: str
    winning_instance: ModelInstance
    losing_instances: list[ModelInstance]
    action: str  # 'replace', 'keep_both', 'skip', 'manual'
    reason: str
    new_paths: dict[str, Path] | None = None  # For 'keep_both' strategy


class ConflictResolver:
    """
    Detects and resolves model conflicts across backends.
    """
    
    def __init__(
        self, 
        strategy: ConflictStrategy,
        backend_priority: dict[str, int] | None = None,
    ):
        self.strategy = strategy
        self.backend_priority = backend_priority or {}
    
    def detect_conflicts(
        self, 
        entries: dict[str, UnifiedModelEntry]
    ) -> dict[str, UnifiedModelEntry]:
        """
        Detect all entries with conflicting content.
        """
        conflicts = {}
        for model_id, entry in entries.items():
            if entry.has_conflicts:
                conflicts[model_id] = entry
        return conflicts
    
    def resolve(
        self, 
        model_id: str, 
        entry: UnifiedModelEntry
    ) -> ConflictResolution | None:
        """
        Resolve a conflict for the given entry.
        Returns None if resolution should be skipped.
        """
        if not entry.has_conflicts:
            return None
        
        if self.strategy == ConflictStrategy.KEEP_NEWEST:
            return self._resolve_by_newest(model_id, entry)
        elif self.strategy == ConflictStrategy.KEEP_LARGEST:
            return self._resolve_by_size(model_id, entry)
        elif self.strategy == ConflictStrategy.KEEP_ALL:
            return self._resolve_keep_all(model_id, entry)
        elif self.strategy == ConflictStrategy.MANUAL:
            return self._resolve_manual(model_id, entry)
        else:
            return self._resolve_by_newest(model_id, entry)
    
    def _resolve_by_newest(
        self, 
        model_id: str, 
        entry: UnifiedModelEntry
    ) -> ConflictResolution:
        """Keep the most recently modified instance."""
        winner = entry.newest_instance
        losers = [i for i in entry.instances if not i.same_content(winner)]
        
        return ConflictResolution(
            model_id=model_id,
            winning_instance=winner,
            losing_instances=losers,
            action="replace",
            reason=f"Newest file (mtime={winner.mtime})",
        )
    
    def _resolve_by_size(
        self, 
        model_id: str, 
        entry: UnifiedModelEntry
    ) -> ConflictResolution:
        """Keep the largest instance."""
        winner = entry.largest_instance
        losers = [i for i in entry.instances if not i.same_content(winner)]
        
        return ConflictResolution(
            model_id=model_id,
            winning_instance=winner,
            losing_instances=losers,
            action="replace",
            reason=f"Largest file ({winner.size} bytes)",
        )
    
    def _resolve_keep_all(
        self, 
        model_id: str, 
        entry: UnifiedModelEntry
    ) -> ConflictResolution:
        """
        Keep all versions by renaming with backend suffix.
        """
        content_groups = entry.get_instances_by_content()
        
        if len(content_groups) <= 1:
            return None
        
        # Pick newest group as the "winner" (gets original name)
        winner = entry.newest_instance
        losers = [i for i in entry.instances if not i.same_content(winner)]
        
        # Calculate new paths for losers
        new_paths = {}
        for instance in losers:
            # Rename to model.backend_id.gguf
            new_name = f"{entry.model_id}.{instance.backend_id}.gguf"
            new_path = instance.path.parent / new_name
            new_paths[instance.backend_id] = new_path
        
        return ConflictResolution(
            model_id=model_id,
            winning_instance=winner,
            losing_instances=losers,
            action="keep_both",
            reason="Multiple versions kept with backend suffixes",
            new_paths=new_paths,
        )
    
    def _resolve_manual(
        self, 
        model_id: str, 
        entry: UnifiedModelEntry
    ) -> ConflictResolution:
        """
        Don't auto-resolve, flag for manual review.
        """
        content_groups = entry.get_instances_by_content()
        
        # Just pick the first as "winner" for reporting purposes
        winner = entry.instances[0]
        losers = entry.instances[1:]
        
        return ConflictResolution(
            model_id=model_id,
            winning_instance=winner,
            losing_instances=losers,
            action="manual",
            reason=f"Conflict requires manual resolution ({len(content_groups)} unique versions)",
        )
    
    def apply_resolution(
        self, 
        resolution: ConflictResolution,
        dry_run: bool = False
    ) -> bool:
        """
        Apply a conflict resolution to the filesystem.
        Returns True if successful.
        """
        if resolution.action == "manual":
            logger.info(
                "Skipping manual conflict (requires admin intervention)",
                model_id=resolution.model_id,
            )
            return False
        
        if resolution.action == "keep_both":
            return self._apply_keep_all(resolution, dry_run)
        
        # For 'replace' action
        winner = resolution.winning_instance
        
        for loser in resolution.losing_instances:
            try:
                if dry_run:
                    logger.info(
                        "[DRY RUN] Would replace with hardlink",
                        from_file=str(winner.path),
                        to_file=str(loser.path),
                    )
                    continue
                
                # Remove the old file
                loser.path.unlink()
                
                # Create hardlink to winner
                import os
                os.link(winner.path, loser.path)
                
                logger.info(
                    "Replaced conflicting model with hardlink",
                    model_id=resolution.model_id,
                    winner_backend=winner.backend_id,
                    loser_backend=loser.backend_id,
                )
                
            except OSError as e:
                logger.error(
                    "Failed to apply conflict resolution",
                    model_id=resolution.model_id,
                    error=str(e),
                )
                return False
        
        return True
    
    def _apply_keep_all(
        self, 
        resolution: ConflictResolution, 
        dry_run: bool
    ) -> bool:
        """Apply the 'keep_all' resolution by renaming files."""
        if not resolution.new_paths:
            return True
        
        for instance in resolution.losing_instances:
            new_path = resolution.new_paths.get(instance.backend_id)
            if not new_path:
                continue
            
            try:
                if dry_run:
                    logger.info(
                        "[DRY RUN] Would rename file",
                        from_file=str(instance.path),
                        to_file=str(new_path),
                    )
                    continue
                
                shutil.move(str(instance.path), str(new_path))
                
                logger.info(
                    "Renamed model to avoid conflict",
                    model_id=resolution.model_id,
                    backend=instance.backend_id,
                    new_path=str(new_path),
                )
                
            except OSError as e:
                logger.error(
                    "Failed to rename file",
                    from_file=str(instance.path),
                    error=str(e),
                )
                return False
        
        return True
```

## Remaining Implementation Notes

### 5. MultiSourceSyncEngine (`core/multi_sync.py`)

This would be the main orchestrator class that:
1. Coordinates the UnifiedIndex, OriginTracker, and ConflictResolver
2. Handles filesystem events from multiple directories
3. Distributes models via hardlinks
4. Prevents circular syncs

Key methods needed:
- `full_sync()` - Complete synchronization pass
- `handle_event()` - Process a filesystem event
- `_distribute_model()` - Hardlink to all backends
- `_verify_filesystem()` - Ensure all dirs on same filesystem

### 6. Backend Modifications (`backends/base.py`)

Each backend needs:
```python
@property
def backend_id(self) -> str:
    """Unique identifier for this backend."""
    return self.config.backend_id or self.name.lower().replace(" ", "_")

def scan_models(self) -> list[Path]:
    """Return all model files currently in this backend."""
    # Default implementation walks output_dir
    
def get_model_path(self, model_id: str) -> Path:
    """Return the expected path for a model in this backend."""
    return self.output_dir / f"{model_id}.gguf"
```

### 7. Filesystem Verification

```python
def verify_same_filesystem(paths: list[Path]) -> tuple[bool, list[tuple[Path, int]]]:
    """
    Verify all paths are on the same filesystem.
    Returns (success, list of (path, device_id) for verification).
    """
    devices = []
    for path in paths:
        if path.exists():
            device = path.stat().st_dev
            devices.append((path, device))
        else:
            # Try parent directory
            parent = path.parent
            while parent and not parent.exists():
                parent = parent.parent
            if parent and parent.exists():
                device = parent.stat().st_dev
                devices.append((path, device))
    
    unique_devices = {d for _, d in devices}
    return len(unique_devices) <= 1, devices
```

### 8. CLI Command

```python
@app.command(name="multi-sync")
def multi_sync(
    config_file: Path | None = typer.Option(None, "--config", "-c"),
    dry_run: bool = typer.Option(False, "--dry-run", "-n"),
    conflict_strategy: ConflictStrategy = typer.Option(
        ConflictStrategy.KEEP_NEWEST,
        "--conflict-strategy",
    ),
    watch: bool = typer.Option(False, "--watch", "-w"),
):
    """Run multi-source synchronization across all backends."""
    # Implementation...
```
