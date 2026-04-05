# Multi-Provider Sync - Quick Reference

## New Files to Create

### Core Components

| File | Purpose | Key Classes |
|------|---------|-------------|
| `core/unified_index.py` | Scan and index all models across backends | `UnifiedIndex`, `UnifiedModelEntry`, `ModelInstance` |
| `core/origin_tracker.py` | Track where models first appeared | `OriginTracker`, `ModelOrigin` |
| `core/conflict_resolver.py` | Conflict detection and resolution | `ConflictPreservationHandler`, `ConflictDatabase` |
| `core/multi_sync.py` | Main sync engine | `MultiSourceSyncEngine` |

### CLI

| File | Purpose | Key Functions |
|------|---------|---------------|
| `main.py` additions | New CLI commands | `multi_sync()`, `conflicts_cmd()` |

## Modified Files

| File | Changes |
|------|---------|
| `core/models.py` | Add `SyncMode`, `ConflictStrategy` enums; extend `SyncConfig` |
| `core/config.py` | Parse new `mode`, `conflict_resolution`, `metadata_dir` settings |
| `core/watcher.py` | Support multiple `source_dirs`; add backend identification |
| `backends/base.py` | Add `backend_id` property, `scan_models()` method |

## Class Hierarchy

```
Backend (base.py) - modified
  └─ backend_id: str [NEW]
  └─ scan_models() → list[Path] [NEW]

ModelInstance (unified_index.py) [NEW]
  ├─ path: Path
  ├─ backend_id: str
  ├─ inode: int
  ├─ device: int
  ├─ mtime: float
  ├─ size: int
  └─ same_content(other) → bool

UnifiedModelEntry (unified_index.py) [NEW]
  ├─ model_id: str
  ├─ instances: list[ModelInstance]
  ├─ has_conflicts → bool
  ├─ newest_instance → ModelInstance
  └─ largest_instance → ModelInstance

UnifiedIndex (unified_index.py) [NEW]
  ├─ entries: dict[str, UnifiedModelEntry]
  ├─ build() → void
  ├─ get_entry(model_id) → UnifiedModelEntry
  └─ get_conflicts() → list[UnifiedModelEntry]

ModelOrigin (origin_tracker.py) [NEW]
  ├─ backend_id: str
  ├─ first_seen: float
  └─ original_path: Path

OriginTracker (origin_tracker.py) [NEW]
  ├─ record_origin(model_id, backend_id, path)
  ├─ get_origin(model_id) → ModelOrigin
  └─ is_origin(model_id, backend_id) → bool

ConflictRecord (conflict_resolver.py) [NEW]
  ├─ model_id: str
  ├─ detected_at: datetime
  ├─ resolved_at: datetime
  ├─ status: str
  ├─ resolution: str
  └─ instances: list[ConflictInstance]

ConflictDatabase (conflict_resolver.py) [NEW]
  ├─ add_conflict(model_id, new_instance, existing)
  ├─ resolve_conflict(model_id, resolution)
  └─ get_unresolved() → list[ConflictRecord]

ConflictPreservationHandler (conflict_resolver.py) [NEW]
  └─ handle_conflict(new_instance, existing_entry) → bool

MultiSourceSyncEngine (multi_sync.py) [NEW]
  ├─ unified_index: UnifiedIndex
  ├─ origin_tracker: OriginTracker
  ├─ conflict_handler: ConflictPreservationHandler
  ├─ full_sync() → SyncResult
  └─ handle_event(event) → void
```

## Key Algorithms

### Conflict Detection
```python
def has_conflicts(entry: UnifiedModelEntry) -> bool:
    # Group instances by (inode, device)
    content_ids = {(i.inode, i.device) for i in entry.instances}
    return len(content_ids) > 1
```

### Conflict Preservation
```python
def preserve_conflict(instance: ModelInstance) -> Path:
    new_name = f"{instance.model_id}.conflict.{instance.backend_id}.gguf"
    new_path = instance.path.parent / new_name
    instance.path.rename(new_path)
    return new_path
```

### Distribute Model
```python
def distribute_model(source: ModelInstance, target_backend: Backend):
    if target_backend.has_model(source.model_id):
        if target_backend.get_inode(source.model_id) == source.inode:
            return  # Already hardlinked
        else:
            # Conflict - will be handled separately
            return
    
    target_path = target_backend.get_model_path(source.model_id)
    os.link(source.path, target_path)  # Create hardlink
```

### Origin Tracking
```python
def on_new_model_detected(instance: ModelInstance):
    existing = index.get_entry(instance.model_id)
    
    if not existing:
        # First time seeing this model
        origin_tracker.record_origin(
            model_id=instance.model_id,
            backend_id=instance.backend_id,
            original_path=instance.path
        )
        distribute_to_all_backends(instance)
    elif existing.has_conflicts:
        conflict_handler.handle_conflict(instance, existing)
    else:
        # Model exists elsewhere, hardlink this backend
        hardlink_from_canonical(instance, existing)
```

## Configuration Snippets

### Minimal Multi-Source Config
```yaml
sync:
  mode: multi_source
  add_only: true
  metadata_dir: /srv/models/.fabric

backends:
  backend_a:
    enabled: true
    backend_id: backend_a
    output_dir: /path/to/backend_a/models
  backend_b:
    enabled: true
    backend_id: backend_b
    output_dir: /path/to/backend_b/models
```

### With Unified Storage
```yaml
sync:
  mode: multi_source
  add_only: true
  metadata_dir: /srv/models/.fabric
  unified_storage_dir: /srv/models  # All models stored here

backends:
  backend_a:
    enabled: true
    backend_id: backend_a
    output_dir: /path/to/backend_a/models  # Hardlinks to /srv/models
```

## Common Operations

### Check Filesystem Compatibility
```python
def check_filesystem_compatibility(backends: list[Backend]) -> bool:
    devices = set()
    for backend in backends:
        # Check existing dir or parent
        path = backend.output_dir
        while path and not path.exists():
            path = path.parent
        if path and path.exists():
            devices.add(path.stat().st_dev)
    return len(devices) <= 1
```

### Get Backend from Path
```python
def identify_backend_from_path(
    path: Path, 
    backends: dict[str, Backend]
) -> str | None:
    resolved = path.resolve()
    for backend_id, backend in backends.items():
        try:
            resolved.relative_to(backend.output_dir.resolve())
            return backend_id
        except ValueError:
            continue
    return None
```

### Create Hardlink
```python
def create_hardlink(source: Path, target: Path) -> bool:
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        os.link(source, target)  # Unix hardlink
        return True
    except OSError as e:
        if e.errno == 18:  # EXDEV - cross-device link
            logger.error("Cross-device hardlink attempted. Use bind mounts.")
        return False
```

## Testing Checklist

### Unit Tests
- [ ] `ModelInstance.same_content()` correctly compares inodes
- [ ] `UnifiedModelEntry.has_conflicts` correctly identifies conflicts
- [ ] `ConflictPreservationHandler` renames files correctly
- [ ] `OriginTracker` persists and loads correctly
- [ ] `ConflictDatabase` JSON serialization/deserialization

### Integration Tests
- [ ] Two backends, model added to A, syncs to B
- [ ] Two backends, model added to B, syncs to A
- [ ] Three backends, model added to A, syncs to B and C
- [ ] Conflict: different files same name in A and B
- [ ] Conflict resolution: keep original
- [ ] Conflict resolution: keep conflict
- [ ] Conflict resolution: keep both

### End-to-End Tests
- [ ] Watch mode detects new file in backend A
- [ ] Watch mode hardlinks to backend B
- [ ] Watch mode handles conflict correctly
- [ ] Restart maintains origin tracking
- [ ] Restart handles existing conflicts

## Debugging Tips

### Check Inodes
```bash
# Verify files are hardlinked (same inode)
ls -i /path/to/backend_a/model.gguf /path/to/backend_b/model.gguf
# Should show same inode number
```

### Monitor Conflicts
```bash
# Watch conflict database
tail -f /srv/models/.fabric/conflicts.json

# List all conflict files
find /var/lib -name "*.conflict.*.gguf" 2>/dev/null
```

### Verify Same Filesystem
```bash
# Check device IDs
df /path/to/backend_a /path/to/backend_b
# Should show same filesystem
```

### Trace Sync Events
```bash
# Verbose logging
fabric multi-sync --verbose

# Or with environment variable
GGUF_SYNC_LOGGING__LEVEL=DEBUG fabric multi-sync
```

## Error Messages

| Message | Cause | Solution |
|---------|-------|----------|
| `Cross-device hardlink attempted` | Backends on different filesystems | Use bind mounts to unify directories |
| `Conflict preserved: model.gguf` | Same name, different content detected | Run `fabric conflicts list` and resolve |
| `Backend directory does not exist` | Backend output_dir not mounted | Check mount points |
| `Failed to write origin file` | Metadata dir not writable | Check permissions on metadata_dir |

## Migration Script

```python
#!/usr/bin/env python3
"""Migrate from single-source to multi-source configuration."""

import yaml
from pathlib import Path

def migrate_config(config_path: Path) -> dict:
    with open(config_path) as f:
        config = yaml.safe_load(f)
    
    # Update sync mode
    config["sync"]["mode"] = "multi_source"
    config["sync"]["add_only"] = True
    config["sync"]["metadata_dir"] = "/srv/models/.fabric"
    
    # Ensure all backends have backend_id
    for name, backend_config in config.get("backends", {}).items():
        if "backend_id" not in backend_config:
            backend_config["backend_id"] = name
    
    # Remove source_dir (no longer used in multi_source)
    if "source_dir" in config:
        # Optionally migrate to unified_storage_dir
        # config["sync"]["unified_storage_dir"] = config.pop("source_dir")
        del config["source_dir"]
    
    return config

if __name__ == "__main__":
    import sys
    config_path = Path(sys.argv[1]) if len(sys.argv) > 1 else Path("fabric.yaml")
    new_config = migrate_config(config_path)
    print(yaml.dump(new_config, default_flow_style=False))
```
