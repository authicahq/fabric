"""Conflict detection and resolution for multi-source sync."""

from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING

from .logging import get_logger
from .models import ConflictStrategy, normalize_model_id

if TYPE_CHECKING:
    from .unified_index import ModelInstance, UnifiedModelEntry

logger = get_logger(__name__)


@dataclass
class ConflictInstance:
    """One version of a conflicting model."""
    backend_id: str
    path: str
    inode: int
    size: int
    mtime: float
    status: str  # 'original' or 'conflict'


@dataclass
class ConflictRecord:
    """Persistent record of a conflict."""
    model_id: str
    detected_at: datetime
    resolved_at: datetime | None = None
    status: str = "unresolved"  # 'unresolved', 'resolved', 'manual_resolution_required'
    resolution: str | None = None  # 'keep_original', 'keep_conflict', 'keep_both'
    winning_backend: str | None = None
    instances: list[ConflictInstance] = field(default_factory=list)
    
    def to_dict(self) -> dict:
        return {
            "model_id": self.model_id,
            "detected_at": self.detected_at.isoformat(),
            "resolved_at": self.resolved_at.isoformat() if self.resolved_at else None,
            "status": self.status,
            "resolution": self.resolution,
            "winning_backend": self.winning_backend,
            "instances": [
                {
                    "backend_id": i.backend_id,
                    "path": i.path,
                    "inode": i.inode,
                    "size": i.size,
                    "mtime": i.mtime,
                    "status": i.status,
                }
                for i in self.instances
            ],
        }
    
    @classmethod
    def from_dict(cls, data: dict) -> ConflictRecord:
        return cls(
            model_id=data["model_id"],
            detected_at=datetime.fromisoformat(data["detected_at"]),
            resolved_at=datetime.fromisoformat(data["resolved_at"]) if data.get("resolved_at") else None,
            status=data["status"],
            resolution=data.get("resolution"),
            winning_backend=data.get("winning_backend"),
            instances=[
                ConflictInstance(
                    backend_id=i["backend_id"],
                    path=i["path"],
                    inode=i["inode"],
                    size=i["size"],
                    mtime=i["mtime"],
                    status=i["status"],
                )
                for i in data.get("instances", [])
            ],
        )


class ConflictDatabase:
    """JSON-based conflict tracking."""
    
    DB_FILENAME = "conflicts.json"
    
    def __init__(self, metadata_dir: Path):
        self.db_path = Path(metadata_dir).resolve() / self.DB_FILENAME
        self._cache: dict[str, ConflictRecord] = {}
        self._ensure_directory()
        self._load()
    
    def _ensure_directory(self) -> None:
        """Ensure the metadata directory exists."""
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
    
    def _load(self) -> None:
        """Load conflicts from disk."""
        if not self.db_path.exists():
            return
        
        try:
            data = json.loads(self.db_path.read_text())
            for conflict_data in data.get("conflicts", []):
                record = ConflictRecord.from_dict(conflict_data)
                self._cache[record.model_id] = record
        except (json.JSONDecodeError, KeyError, OSError) as e:
            logger.error(f"Failed to load conflict database {self.db_path}", error=str(e))
    
    def _save(self) -> None:
        """Persist to disk."""
        data = {
            "conflicts": [r.to_dict() for r in self._cache.values()],
        }
        try:
            self.db_path.write_text(json.dumps(data, indent=2, default=str))
        except OSError as e:
            logger.error(f"Failed to save conflict database {self.db_path}", error=str(e))
    
    def add_conflict(
        self,
        model_id: str,
        new_instance: ModelInstance,
        existing_instances: list[ModelInstance],
    ) -> None:
        """Add a new conflict record."""
        existing = self._cache.get(model_id)
        
        if existing:
            # Add new instance to existing conflict
            existing.instances.append(
                ConflictInstance(
                    backend_id=new_instance.backend_id,
                    path=str(new_instance.path),
                    inode=new_instance.inode,
                    size=new_instance.size,
                    mtime=new_instance.mtime,
                    status="conflict",
                )
            )
        else:
            # Create new conflict record
            record = ConflictRecord(
                model_id=model_id,
                detected_at=datetime.now(),
                instances=[
                    ConflictInstance(
                        backend_id=i.backend_id,
                        path=str(i.path),
                        inode=i.inode,
                        size=i.size,
                        mtime=i.mtime,
                        status="original",
                    )
                    for i in existing_instances
                ] + [
                    ConflictInstance(
                        backend_id=new_instance.backend_id,
                        path=str(new_instance.path),
                        inode=new_instance.inode,
                        size=new_instance.size,
                        mtime=new_instance.mtime,
                        status="conflict",
                    )
                ],
            )
            self._cache[model_id] = record
        
        self._save()
    
    def resolve_conflict(
        self,
        model_id: str,
        resolution: str,
        winning_backend: str | None = None,
    ) -> bool:
        """Mark a conflict as resolved."""
        record = self._cache.get(model_id)
        if not record:
            return False
        
        record.status = "resolved"
        record.resolution = resolution
        record.winning_backend = winning_backend
        record.resolved_at = datetime.now()
        
        self._save()
        return True
    
    def get_unresolved(self) -> list[ConflictRecord]:
        """Get all unresolved conflicts."""
        return [r for r in self._cache.values() if r.status == "unresolved"]
    
    def get_record(self, model_id: str) -> ConflictRecord | None:
        """Get a specific conflict record."""
        return self._cache.get(model_id)
    
    def remove_conflict(self, model_id: str) -> bool:
        """Remove a conflict record."""
        if model_id not in self._cache:
            return False
        del self._cache[model_id]
        self._save()
        return True


class ConflictPreservationHandler:
    """
    Handles conflicts in non-interactive mode by logging them.
    Files are left in place - only the conflict is recorded in the database.
    This prevents disrupting running backends that may be using the files.
    """
    
    def __init__(self, metadata_dir: Path):
        self.metadata_dir = Path(metadata_dir).resolve()
        self.conflicts_db = ConflictDatabase(self.metadata_dir)
        # Track which conflicts we've already warned about to prevent log spam
        self._warned_conflicts: set[str] = set()
    
    def handle_conflict(
        self,
        new_instance: ModelInstance,
        existing_entry: UnifiedModelEntry,
    ) -> bool:
        """
        Record a conflict in the database. Files are NOT renamed.
        Returns True if conflict was recorded successfully.
        
        The files are left in place to avoid disrupting running backends.
        The user must resolve conflicts manually via 'fabric conflicts resolve'.
        """
        # Check if this exact conflict is already recorded
        existing_record = self.conflicts_db.get_record(new_instance.model_id)
        if existing_record:
            # Check if this instance is already recorded
            for instance in existing_record.instances:
                if instance.backend_id == new_instance.backend_id:
                    # Already recorded, skip
                    return True
        
        # Record the conflict
        self.conflicts_db.add_conflict(
            model_id=new_instance.model_id,
            new_instance=new_instance,
            existing_instances=existing_entry.instances,
        )
        
        # Only warn once per conflict to prevent log spam
        warn_key = f"{new_instance.model_id}:{new_instance.backend_id}"
        if warn_key not in self._warned_conflicts:
            self._warned_conflicts.add(warn_key)
            logger.warning(
                "Conflict detected (files unchanged)",
                model_id=new_instance.model_id,
                backends=[i.backend_id for i in existing_entry.instances] + [new_instance.backend_id],
                hint="Run 'fabric conflicts list' to review and resolve",
            )
        
        return True
    
    def clear_warned_cache(self) -> None:
        """Clear the warned conflicts cache (e.g., on restart)."""
        self._warned_conflicts.clear()
    
    def get_unresolved_conflicts(self) -> list[ConflictRecord]:
        """Get all unresolved conflicts."""
        return self.conflicts_db.get_unresolved()
