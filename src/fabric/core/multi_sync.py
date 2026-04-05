"""Multi-source synchronization engine."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING

from .conflict_resolver import ConflictPreservationHandler
from .cooldown import SyncCooldownManager
from .logging import get_logger
from .models import SyncEvent, SyncEventType
from .origin_tracker import OriginTracker
from .unified_index import ModelInstance, UnifiedIndex, UnifiedModelEntry

if TYPE_CHECKING:
    from ..backends.base import Backend, BackendResult
    from .models import AppConfig

logger = get_logger(__name__)


@dataclass
class MultiSyncResult:
    """Result of a multi-source sync operation."""
    success: bool
    linked: int = 0
    conflicts: int = 0
    errors: list[str] = field(default_factory=list)
    backend_results: dict[str, BackendResult] = field(default_factory=dict)


class MultiSourceSyncEngine:
    """
    Main synchronization engine for multi-source mode.
    Distributes models across all backends via hardlinks.
    """

    def __init__(self, config: AppConfig, backends: list[Backend]):
        self.config = config
        self.backends: dict[str, Backend] = {}

        # Ensure all backends have backend_id
        for backend in backends:
            backend_id = getattr(backend, 'backend_id', None) or backend.name.lower().replace(" ", "_")
            self.backends[backend_id] = backend

        # Initialize components
        metadata_dir = config.sync.metadata_dir or Path.home() / ".fabric"
        self.origin_tracker = OriginTracker(metadata_dir)
        self.conflict_handler = ConflictPreservationHandler(metadata_dir)
        self.cooldown_manager = SyncCooldownManager(
            cooldown_seconds=config.sync.cooldown_seconds
        )
        self.unified_index = UnifiedIndex(self.backends)

        self._setup_metadata_dir(metadata_dir)

    def _setup_metadata_dir(self, metadata_dir: Path) -> None:
        """Ensure metadata directory exists and is accessible."""
        try:
            metadata_dir.mkdir(parents=True, exist_ok=True)
        except OSError as e:
            logger.error(f"Failed to create metadata directory {metadata_dir}", error=str(e))
            raise RuntimeError(f"Cannot create metadata directory: {metadata_dir}") from e

    def setup(self) -> None:
        """Setup the sync engine and all backends."""
        logger.info(
            "Setting up multi-source sync engine",
            backends=list(self.backends.keys()),
        )

        # Verify all backends are on same filesystem
        self._verify_filesystem()

        # Setup all backends
        for backend in self.backends.values():
            backend.setup()

    def _verify_filesystem(self) -> None:
        """Verify all backend directories are on the same filesystem."""
        devices: set[int] = set()
        paths_checked: list[tuple[Path, int]] = []

        for backend_id, backend in self.backends.items():
            path = backend.output_dir

            # Check existing dir or find first existing parent
            check_path = path
            while check_path and not check_path.exists():
                check_path = check_path.parent

            if check_path and check_path.exists():
                try:
                    device = check_path.stat().st_dev
                    devices.add(device)
                    paths_checked.append((path, device))
                except OSError as e:
                    logger.warning(
                        "Failed to stat backend directory",
                        backend_id=backend_id,
                        path=str(path),
                        error=str(e),
                    )

        if len(devices) > 1:
            device_info = ", ".join(f"{p} (dev {d})" for p, d in paths_checked)
            raise RuntimeError(
                f"Backends are on different filesystems. Multi-source mode requires "
                f"all backends to be on the same filesystem for hardlink support. "
                f"Use bind mounts to unify directories. Paths: {device_info}"
            )

        if devices:
            logger.debug(
                "All backends on same filesystem",
                device_id=next(iter(devices)),
                backends=len(self.backends),
            )

    def full_sync(self) -> MultiSyncResult:
        """
        Perform a full synchronization across all backends.
        """
        logger.info("Starting full multi-source synchronization")

        result = MultiSyncResult(success=True)

        # Build unified index
        self.unified_index.build()

        # Handle conflicts - record them in database (files are left in place)
        conflicts = self.unified_index.get_conflicts()
        for entry in conflicts:
            logger.warning(
                "Existing conflict detected",
                model_id=entry.model_id,
                instances=len(entry.instances),
            )
            # Record each conflict that's not already in database
            for instance in entry.instances[1:]:  # Skip first (original)
                existing = UnifiedModelEntry(model_id=entry.model_id)
                existing.add_instance(entry.instances[0])  # Add original

                # Check if already recorded
                existing_record = self.conflict_handler.conflicts_db.get_record(entry.model_id)
                if existing_record:
                    already_recorded = any(
                        i.backend_id == instance.backend_id
                        for i in existing_record.instances
                    )
                    if already_recorded:
                        continue

                preserved = self.conflict_handler.handle_conflict(instance, existing)
                if preserved:
                    result.conflicts += 1

            # Update the entry
            self.unified_index.entries[entry.model_id] = entry

        # Distribute models to all backends
        for model_id, entry in self.unified_index.entries.items():
            if entry.has_conflicts:
                continue  # Skip conflicting models

            linked_count = self._distribute_model(entry)
            result.linked += linked_count

        logger.info(
            "Full synchronization complete",
            linked=result.linked,
            conflicts=result.conflicts,
        )

        return result

    def handle_event(self, event: SyncEvent) -> MultiSyncResult:
        """
        Handle a filesystem event from any watched directory.
        """
        result = MultiSyncResult(success=True)

        # Check cooldown
        if self.cooldown_manager.is_in_cooldown(event.path):
            logger.debug(
                "Ignoring event for path in cooldown",
                path=str(event.path),
                event_type=event.event_type.name,
            )
            return result

        # Identify source backend
        source_backend = self._identify_backend(event.source_dir)
        if not source_backend:
            logger.warning(
                "Could not identify backend for event",
                path=str(event.path),
                source_dir=str(event.source_dir),
            )
            return result

        logger.debug(
            "Handling event",
            event_type=event.event_type.name,
            path=str(event.path),
            backend_id=source_backend,
        )

        if event.event_type in (
            SyncEventType.FILE_CREATED,
            SyncEventType.FILE_MODIFIED,
            SyncEventType.DOWNLOAD_COMPLETED,
        ):
            result = self._handle_creation(event.path, source_backend)
        elif event.event_type == SyncEventType.FILE_DELETED:
            # In add-only mode, we don't propagate deletions
            logger.debug(
                "Ignoring deletion event (add-only mode)",
                path=str(event.path),
                backend_id=source_backend,
            )

        return result

    def _identify_backend(self, source_dir: Path) -> str | None:
        """Identify which backend a path belongs to."""
        resolved = source_dir.resolve()
        for backend_id, backend in self.backends.items():
            backend_dir = backend.output_dir.resolve()
            try:
                resolved.relative_to(backend_dir)
                return backend_id
            except ValueError:
                continue
        return None

    def _handle_creation(
        self,
        path: Path,
        source_backend: str
    ) -> MultiSyncResult:
        """Handle a file creation/modification event."""
        result = MultiSyncResult(success=True)

        try:
            stat = path.stat()
            model_id = self._extract_model_id(path.name)

            instance = ModelInstance(
                path=path,
                backend_id=source_backend,
                inode=stat.st_ino,
                device=stat.st_dev,
                mtime=stat.st_mtime,
                size=stat.st_size,
            )

            # Check for existing entry
            existing = self.unified_index.get_entry(model_id)

            if not existing:
                # New model - record origin and distribute
                self.origin_tracker.record_origin(
                    model_id=model_id,
                    backend_id=source_backend,
                    original_path=path,
                )
                self.unified_index.add_instance(model_id, instance)

                # Distribute to all other backends
                linked = self._distribute_model(
                    self.unified_index.get_entry(model_id)
                )
                result.linked = linked

            elif any(i.same_content(instance) for i in existing.instances):
                # Same content already exists - just ensure hardlinked everywhere
                self.unified_index.add_instance(model_id, instance)
                linked = self._distribute_model(
                    self.unified_index.get_entry(model_id)
                )
                result.linked = linked

            else:
                # CONFLICT - record it (files are left in place)
                preserved = self.conflict_handler.handle_conflict(
                    instance, existing
                )
                if preserved:
                    result.conflicts += 1
                    # Still add instance to index for tracking
                    self.unified_index.add_instance(model_id, instance)
                else:
                    result.errors.append(f"Failed to record conflict for {model_id}")

            return result

        except OSError as e:
            logger.error(
                "Failed to handle creation event",
                path=str(path),
                error=str(e),
            )
            result.errors.append(str(e))
            return result

    def _extract_model_id(self, filename: str) -> str:
        """Extract normalized model_id from filename."""
        # Handle conflict files
        if ".conflict." in filename.lower():
            parts = filename.split(".")
            if len(parts) >= 4 and parts[-3].lower() == "conflict":
                from .models import normalize_model_id
                return normalize_model_id(".".join(parts[:-3]))

        # Standard handling
        from .models import get_mmproj_base, get_multipart_base, normalize_model_id

        if multipart_base := get_multipart_base(filename):
            return normalize_model_id(multipart_base)

        if "mmproj" in filename.lower():
            base = get_mmproj_base(filename)
            if base:
                return normalize_model_id(base)

        base = filename.replace(".gguf", "")
        return normalize_model_id(base)

    def _distribute_model(self, entry) -> int:
        """
        Distribute a model to all backends via hardlinks.
        Returns the number of new hardlinks created.
        """
        if not entry or not entry.instances:
            return 0

        # Get the canonical source (first instance)
        source = entry.instances[0]

        linked_count = 0
        for backend_id, backend in self.backends.items():
            # Skip if backend already has this content
            if any(i.backend_id == backend_id and i.inode == source.inode
                   for i in entry.instances):
                continue

            # Skip if this backend is the origin (already has it)
            if self.origin_tracker.is_origin(entry.model_id, backend_id):
                continue

            # Create hardlink
            target_path = self._get_model_path(backend, entry.model_id)
            if self._create_hardlink(source.path, target_path, backend_id):
                linked_count += 1
                # Add to index
                try:
                    stat = target_path.stat()
                    new_instance = ModelInstance(
                        path=target_path,
                        backend_id=backend_id,
                        inode=stat.st_ino,
                        device=stat.st_dev,
                        mtime=stat.st_mtime,
                        size=stat.st_size,
                    )
                    entry.add_instance(new_instance)
                except OSError:
                    pass

        return linked_count

    def _get_model_path(self, backend: Backend, model_id: str) -> Path:
        """Get the path where a model should be stored in a backend."""
        return backend.output_dir / f"{model_id}.gguf"

    def _create_hardlink(
        self,
        source: Path,
        target: Path,
        target_backend_id: str | None = None,
    ) -> bool:
        """
        Create a hardlink from source to target.
        Returns True if successful.
        """
        try:
            # Ensure target directory exists
            target.parent.mkdir(parents=True, exist_ok=True)

            # Remove existing file if present
            if target.exists() or target.is_symlink():
                target.unlink()

            # Create hardlink
            os.link(source, target)

            logger.debug(
                "Created hardlink",
                source=str(source),
                target=str(target),
                target_backend=target_backend_id,
            )

            # Enter cooldown to prevent circular sync
            self.cooldown_manager.enter_cooldown(target, target_backend_id)

            return True

        except OSError as e:
            if e.errno == 18:  # EXDEV - cross-device link
                logger.error(
                    "Cross-device hardlink attempted",
                    source=str(source),
                    target=str(target),
                    hint="Ensure all backends are on the same filesystem or use bind mounts",
                )
            else:
                logger.error(
                    "Failed to create hardlink",
                    source=str(source),
                    target=str(target),
                    error=str(e),
                )
            return False

    def get_stats(self) -> dict:
        """Get sync engine statistics."""
        return {
            "backends": list(self.backends.keys()),
            "cooldown_active": self.cooldown_manager.get_active_count(),
            **self.unified_index.get_stats(),
        }
