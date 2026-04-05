# Multi-Provider Sync - Complete Design Summary

## Overview

This document provides the complete design for multi-provider bidirectional model synchronization using hardlinks only, with safe conflict preservation.

## Key Design Decisions

| Decision | Rationale |
|----------|-----------|
| **Hardlinks only** | Zero duplication, atomic updates, cross-backend visibility |
| **Single filesystem** | Required for hardlinks; use bind mounts for flexibility |
| **Add-only mode** | Never delete models automatically |
| **Conflict preservation** | Never auto-resolve conflicts in sync mode; preserve all versions |
| **Non-interactive sync** | Watch mode must never block for user input |
| **Interactive resolution** | Separate CLI command for user-driven conflict resolution |

## Architecture Diagram

```
┌─────────────────────────────────────────────────────────────────────────┐
│                           MULTI-SOURCE SYNC                              │
├─────────────────────────────────────────────────────────────────────────┤
│                                                                          │
│  ┌──────────────────┐     ┌──────────────────┐     ┌──────────────────┐ │
│  │  llama.cpp/      │     │   LocalAI/       │     │   Ollama/        │ │
│  │  models/         │     │   models/        │     │   models/        │ │
│  │                  │     │                  │     │                  │ │
│  │  model-a.gguf ───┼─────┼──► model-a.gguf  │     │                  │ │
│  │  (original)      │     │  (hardlink)      │     │                  │ │
│  │                  │     │                  │     │                  │ │
│  │  model-b.gguf ◄──┼─────┼─── model-b.gguf  │     │                  │ │
│  │  (hardlink)      │     │  (original)      │     │                  │ │
│  │                  │     │                  │     │                  │ │
│  │  model-c.conflict│     │                  │     │  model-c.gguf    │ │
│  │    .llama_cpp.gguf     │                  │     │  (original)      │ │
│  └──────────────────┘     └──────────────────┘     └──────────────────┘ │
│           │                        │                        │           │
│           │                        │                        │           │
│           └────────────────────────┼────────────────────────┘           │
│                                    │                                    │
│                                    ▼                                    │
│  ┌──────────────────────────────────────────────────────────────────┐  │
│  │                    FileSystemWatcher                              │  │
│  │         (watches ALL backend directories)                         │  │
│  └──────────────────────────────────────────────────────────────────┘  │
│                                    │                                    │
│                                    ▼                                    │
│  ┌──────────────────────────────────────────────────────────────────┐  │
│  │                 MultiSourceSyncEngine                             │  │
│  ├──────────────────────────────────────────────────────────────────┤  │
│  │                                                                  │  │
│  │  ┌─────────────────┐  ┌─────────────────┐  ┌─────────────────┐  │  │
│  │  │  UnifiedIndex   │  │ OriginTracker   │  │ ConflictPreser- │  │  │
│  │  │                 │  │                 │  │ vationHandler   │  │  │
│  │  │ - Scan all dirs │  │ - Record origin │  │                 │  │  │
│  │  │ - Track inodes  │  │ - Track where   │  │ - Detect        │  │  │
│  │  │ - Detect        │  │   models first  │  │   conflicts     │  │  │
│  │  │   conflicts     │  │   appeared      │  │ - Rename with   │  │  │
│  │  └─────────────────┘  └─────────────────┘  │   .conflict.    │  │  │
│  │                                            │   suffix        │  │  │
│  │                                            └─────────────────┘  │  │
│  └──────────────────────────────────────────────────────────────────┘  │
│                                    │                                    │
│                                    ▼                                    │
│  ┌──────────────────────────────────────────────────────────────────┐  │
│  │              ConflictDatabase (JSON file)                         │  │
│  │         /srv/models/.fabric/conflicts.json                     │  │
│  └──────────────────────────────────────────────────────────────────┘  │
│                                    │                                    │
│                                    ▼                                    │
│  ┌──────────────────────────────────────────────────────────────────┐  │
│  │           Interactive Conflict Resolution CLI                     │  │
│  │              fabric conflicts <command>                        │  │
│  └──────────────────────────────────────────────────────────────────┘  │
│                                                                          │
└─────────────────────────────────────────────────────────────────────────┘
```

## Component Interactions

### 1. Initial Sync Flow

```
1. User runs: fabric multi-sync

2. MultiSourceSyncEngine.full_sync()
   ├─ UnifiedIndex.build()
   │  ├─ Scan all backend directories
   │  ├─ Collect ModelInstance for each file
   │  │  └─ (path, backend_id, inode, mtime, size)
   │  └─ Group by model_id
   │
   ├─ Detect conflicts (same model_id, different inodes)
   │
   ├─ For each conflict:
   │  └─ ConflictPreservationHandler.handle_conflict()
   │     ├─ Rename incoming file: model.gguf → model.conflict.backend.gguf
   │     └─ Record in ConflictDatabase
   │
   └─ For each non-conflicting model:
      └─ Distribute to all backends via hardlinks

3. Report results:
   - Models synced: N
   - Conflicts preserved: M (run 'fabric conflicts list' to review)
```

### 2. Watch Mode Flow

```
1. User runs: fabric multi-sync --watch

2. FileSystemWatcher monitors ALL backend directories

3. New file detected in Ollama/models/:
   ├─ DownloadDetector confirms download complete
   ├─ ModelInstance created
   ├─ UnifiedIndex.add_instance()
   ├─ Check for conflicts:
   │  ├─ NO: Distribute to all other backends via hardlinks
   │  └─ YES: ConflictPreservationHandler.handle_conflict()
   │     └─ Rename and log, DO NOT block
   └─ Continue watching

4. File modified in LocalAI/models/:
   ├─ Check if content changed (inode comparison)
   ├─ If changed: Treat as new conflict
   └─ If same (metadata update): Ignore

5. File deleted (ignored in add-only mode):
   └─ Log only, do not propagate deletion
```

### 3. Conflict Resolution Flow

```
1. User runs: fabric conflicts list
   └─ Read ConflictDatabase
   └─ Display table of unresolved conflicts

2. User runs: fabric conflicts resolve model.gguf
   └─ Interactive menu:
      ├─ Show all versions with details
      ├─ Options: Keep [1], Keep [2], Keep Both, Skip
      └─ Apply user choice:
         ├─ Keep A: Hardlink A to B, delete conflict file
         ├─ Keep B: Hardlink B to A, delete conflict file
         ├─ Keep Both: Rename to permanent suffixes
         └─ Skip: Do nothing
   └─ Update ConflictDatabase

3. User runs: fabric conflicts resolve-all --strategy keep-newest
   └─ For each unresolved conflict:
      ├─ Compare mtimes
      ├─ Keep newest, hardlink to others
      └─ Mark resolved
```

## Data Structures

### UnifiedIndex

```python
class UnifiedIndex:
    """Maps model_id → UnifiedModelEntry across all backends."""
    
    entries: dict[str, UnifiedModelEntry]
    
class UnifiedModelEntry:
    """All instances of a model across backends."""
    
    model_id: str
    instances: list[ModelInstance]
    
    @property
    def has_conflicts(self) -> bool:
        """True if multiple unique content versions exist."""
        return len({(i.inode, i.device) for i in self.instances}) > 1

class ModelInstance:
    """A specific file in a specific backend."""
    
    path: Path
    backend_id: str
    inode: int      # For content identity
    device: int     # Filesystem verification
    mtime: float    # For conflict resolution
    size: int       # For conflict resolution
```

### ConflictDatabase

```python
class ConflictRecord:
    """Persistent record of a conflict."""
    
    model_id: str
    detected_at: datetime
    resolved_at: datetime | None
    status: "unresolved" | "resolved" | "manual_resolution_required"
    resolution: str | None  # "keep_original", "keep_conflict", "keep_both"
    instances: list[ConflictInstance]

class ConflictInstance:
    """One version of a conflicting model."""
    
    backend_id: str
    path: Path
    inode: int
    size: int
    mtime: float
    status: "original" | "conflict"
```

## Configuration

```yaml
# /etc/fabric.yaml

sync:
  # Mode selection
  mode: multi_source  # or single_source
  
  # Required for multi_source
  add_only: true
  
  # Conflict handling (only for initial auto-resolution, if any)
  conflict_resolution: preserve  # always preserve in multi_source
  
  # Metadata storage
  metadata_dir: /srv/models/.fabric
  
  # Optional: Central storage for canonical files
  # If not set, uses first backend where model appeared
  unified_storage_dir: /srv/models

backends:
  # Each backend needs a unique backend_id
  localai:
    enabled: true
    backend_id: localai
    output_dir: /var/lib/localai/models
    
  ollama:
    enabled: true
    backend_id: ollama
    output_dir: /var/lib/ollama/models
    
  llama_cpp:
    enabled: true
    backend_id: llama_cpp
    output_dir: /home/user/llama.cpp/models

watch:
  enabled: true
  # In multi_source mode, this is implied:
  # watch_backend_dirs: true
```

## CLI Commands

### Multi-Source Sync

```bash
# One-time sync
fabric multi-sync

# With dry-run
fabric multi-sync --dry-run

# Watch mode
fabric multi-sync --watch

# With custom config
fabric multi-sync --config /path/to/config.yaml
```

### Conflict Management

```bash
# List all unresolved conflicts
fabric conflicts list

# Resolve specific conflict interactively
fabric conflicts resolve model-name.gguf

# Batch resolve by strategy
fabric conflicts resolve-all --strategy keep-newest
fabric conflicts resolve-all --strategy keep-largest

# Dry run to preview
fabric conflicts resolve-all --strategy keep-newest --dry-run

# Show conflict details
fabric conflicts show model-name.gguf

# Export conflicts to file
fabric conflicts export --format json > conflicts.json
```

### Diagnostics

```bash
# Verify filesystem setup
fabric doctor
# Checks:
# - All backend dirs on same filesystem
# - Hardlink capability
# - Write permissions
# - Metadata directory writable
```

## File Naming Convention

### Normal Models
```
{model_id}.gguf

Examples:
- llama-3-8b-q4.gguf
- mistral-7b-instruct-v0.2.gguf
```

### Conflicts
**Files are NOT renamed during conflict detection** - they remain in place:
```
backend_a/model.gguf (4GB)  - first version
backend_b/model.gguf (3.9GB)  - conflicting version
```

Both files continue to exist. The conflict is logged in the database at `~/.fabric/conflicts.json`.

### After Resolution

Resolution uses **hardlinking** (not renaming) to atomically replace files:

If user chooses "keep backend_a version":
```
backend_a/model.gguf (4GB, inode=123)
backend_b/model.gguf (4GB, inode=123)  # hardlinked to backend_a
```

If user chooses "keep both" (manual rename first):
```
backend_a/model.gguf
backend_b/model.backend_b.gguf  # user renamed first
```

## Filesystem Layout Example

```
/srv/models/                       # Optional unified storage
├── .fabric/
│   ├── origins/                   # Origin tracking
│   │   ├── llama-3-8b-q4.gguf.origin
│   │   └── mistral-7b.gguf.origin
│   └── conflicts.json             # Conflict database
│
├── llama-3-8b-q4.gguf            # Original from localai
└── mistral-7b.gguf               # Original from ollama

/var/lib/localai/models/          # LocalAI backend
├── llama-3-8b-q4.gguf            # Hardlink to /srv/models/
├── mistral-7b.gguf               # Hardlink
└── gemma-2b.gguf                 # Original (localai first)

/var/lib/ollama/models/           # Ollama backend
├── llama-3-8b-q4.gguf            # Hardlink
├── mistral-7b.gguf               # Original (ollama first)
└── llama-3-8b-q4.conflict.ollama.gguf  # Conflict preserved

~/llama.cpp/models/               # llama.cpp backend
├── llama-3-8b-q4.gguf            # Hardlink
├── mistral-7b.gguf               # Hardlink
└── gemma-2b.gguf                 # Hardlink
```

## Implementation Checklist

### Phase 1: Core Infrastructure

- [ ] Create `ModelInstance`, `UnifiedModelEntry` dataclasses
- [ ] Implement `UnifiedIndex` with scanning logic
- [ ] Add `backend_id` property to all backends
- [ ] Implement `Backend.scan_models()` method
- [ ] Create filesystem verification function

### Phase 2: Conflict Preservation

- [ ] Implement `ConflictPreservationHandler`
- [ ] Create `ConflictDatabase` with JSON persistence
- [ ] Add conflict detection logic to `UnifiedIndex`
- [ ] Implement rename-on-conflict behavior
- [ ] Add conflict logging

### Phase 3: Multi-Source Engine

- [ ] Create `MultiSourceSyncEngine` class
- [ ] Implement `full_sync()` with conflict handling
- [ ] Implement `handle_event()` for watch mode
- [ ] Add hardlink distribution logic
- [ ] Implement circular sync prevention

### Phase 4: Watch Mode

- [ ] Modify `FileSystemWatcher` for multiple directories
- [ ] Add backend identification from event path
- [ ] Integrate with `MultiSourceSyncEngine`
- [ ] Test event handling for conflict scenarios

### Phase 5: CLI

- [ ] Add `multi-sync` command
- [ ] Add `conflicts` subcommand with list/resolve/resolve-all
- [ ] Implement interactive resolution UI
- [ ] Add `doctor` command for diagnostics
- [ ] Create configuration migration command

### Phase 6: Testing

- [ ] Unit tests for `UnifiedIndex`
- [ ] Unit tests for `ConflictDatabase`
- [ ] Integration test: two backends, no conflicts
- [ ] Integration test: two backends, conflict detected
- [ ] Integration test: conflict resolution
- [ ] Test watch mode with file creation
- [ ] Test filesystem boundary detection

## Security Considerations

1. **Metadata directory permissions** - Should be writable only by sync service
2. **Conflict database integrity** - Validate JSON on load, handle corruption gracefully
3. **Path traversal** - Sanitize model_id when creating conflict file names
4. **Symlink attacks** - Verify files are regular files (not symlinks) before hardlinking

## Performance Considerations

1. **Index building** - Use `os.scandir()` for faster directory traversal
2. **Inode comparison** - Much faster than content hashing
3. **Lazy metadata parsing** - Only parse GGUF metadata when needed
4. **Conflict database** - Keep in memory, flush periodically
5. **Event batching** - Process multiple filesystem events together

## Error Handling

| Scenario | Handling |
|----------|----------|
| Backend dir not mounted | Log warning, skip backend |
| Cross-filesystem hardlink | Log error, skip file, suggest bind mount |
| Conflict rename fails | Log error, keep original name, flag for manual review |
| Conflict DB corrupt | Backup and recreate, log warning |
| Permission denied | Log error, skip file |
| File in use (locked) | Retry with backoff, log warning |

## Migration from Single-Source

```bash
# 1. Backup existing config
cp fabric.yaml fabric.yaml.backup

# 2. Run migration
fabric migrate --to multi-source

# This:
# - Detects all backends from existing config
# - Sets mode: multi_source
# - Scans existing files and records origins
# - Detects existing conflicts
# - Generates new config

# 3. Review and apply
# Review fabric.yaml
# Fix any paths if needed

# 4. Start multi-source sync
fabric multi-sync --watch
```
