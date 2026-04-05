# Multi-Provider Sync Design

## Overview

This document describes the design for bidirectional model synchronization across multiple LLM inference backends on a single filesystem using hardlinks exclusively.

## Core Principles

1. **Single Filesystem Only**: All backend directories must be on the same filesystem
2. **Hardlinks Only**: No symlinks, no copies - only hardlinks for zero-duplication
3. **Add-Only Mode**: Never delete models, only distribute new arrivals
4. **Inode-Based Identity**: Use filesystem inodes to identify identical content

## Architecture

### 1. Directory Structure

```
/srv/models/                    # Unified model storage (single source of truth)
├── .fabric/                 # Sync system metadata
│   ├── origins/                # Origin tracking files
│   │   ├── model-a.gguf.origin
│   │   └── model-b.gguf.origin
│   └── conflicts/              # Conflict resolution logs
│       └── model-c.gguf.conflict
├── model-a.gguf                # Actual file data (stored here)
├── model-b.gguf
└── model-c.gguf

/var/lib/LocalAI/models/        # Backend directories (hardlinks only)
├── model-a.gguf -> (same inode as /srv/models/model-a.gguf)
└── model-b.gguf

~/llama.cpp/models/
├── model-a.gguf -> (same inode)
└── model-c.gguf
```

### 2. Key Components

#### 2.1 UnifiedIndex

Replaces the single-source model index with a multi-source view:

```python
@dataclass
class ModelInstance:
    """A specific instance of a model in a specific location."""
    path: Path
    backend_id: str  # 'localai', 'llama_cpp', 'source', etc.
    inode: int
    mtime: float
    size: int
    checksum: str | None  # Lazy-computed for conflict resolution

@dataclass  
class UnifiedModelEntry:
    """Aggregated view of a model across all locations."""
    model_id: str  # Normalized model name
    instances: list[ModelInstance]  # All known instances
    origin: str | None  # Which backend first introduced this model
    
    @property
    def has_conflicts(self) -> bool:
        """Check if different instances have different content."""
        inodes = {i.inode for i in self.instances}
        return len(inodes) > 1
    
    @property
    def newest_instance(self) -> ModelInstance:
        """Get the most recently modified instance."""
        return max(self.instances, key=lambda i: i.mtime)
```

#### 2.2 Origin Tracking

Prevents circular syncs and identifies model provenance:

```python
class OriginTracker:
    """
    Tracks which backend first introduced each model.
    Stored as sidecar files: {model_name}.gguf.origin
    """
    
    def record_origin(self, model_id: str, backend_id: str) -> None:
        """Record that this model originated from backend_id."""
        origin_file = self.metadata_dir / f"{model_id}.gguf.origin"
        origin_file.write_text(backend_id)
    
    def get_origin(self, model_id: str) -> str | None:
        """Get the originating backend for a model."""
        origin_file = self.metadata_dir / f"{model_id}.gguf.origin"
        if origin_file.exists():
            return origin_file.read_text().strip()
        return None
    
    def is_origin(self, model_id: str, backend_id: str) -> bool:
        """Check if backend_id is the origin of this model."""
        return self.get_origin(model_id) == backend_id
```

#### 2.3 ConflictResolver

Handles cases where the same model name exists with different content:

```python
class ConflictResolutionStrategy(Enum):
    """Strategies for resolving model conflicts."""
    KEEP_NEWEST = "newest"          # Keep most recently modified
    KEEP_LARGEST = "largest"        # Keep largest file (assumes more complete)
    KEEP_ALL = "all"                # Keep all versions with suffixes
    MANUAL = "manual"               # Flag for manual review, skip auto-sync

@dataclass
class ConflictResolution:
    """Result of conflict resolution."""
    winning_instance: ModelInstance
    losing_instances: list[ModelInstance]
    action: Literal["replace", "keep_both", "skip"]
    reason: str

class ConflictResolver:
    """
    Resolves conflicts when same model name exists with different content.
    """
    
    def resolve(
        self, 
        model_id: str,
        instances: list[ModelInstance],
        strategy: ConflictResolutionStrategy
    ) -> ConflictResolution:
        """
        Determine which instance should be the canonical version.
        """
        if strategy == ConflictResolutionStrategy.KEEP_NEWEST:
            return self._resolve_by_newest(model_id, instances)
        elif strategy == ConflictResolutionStrategy.KEEP_LARGEST:
            return self._resolve_by_size(model_id, instances)
        elif strategy == ConflictResolutionStrategy.KEEP_ALL:
            return self._resolve_keep_all(model_id, instances)
        else:
            return self._resolve_manual(model_id, instances)
    
    def _resolve_by_newest(
        self, 
        model_id: str, 
        instances: list[ModelInstance]
    ) -> ConflictResolution:
        """Keep the most recently modified instance."""
        winner = max(instances, key=lambda i: i.mtime)
        losers = [i for i in instances if i.inode != winner.inode]
        return ConflictResolution(
            winning_instance=winner,
            losing_instances=losers,
            action="replace",
            reason=f"Newest file (mtime={winner.mtime})"
        )
```

#### 2.4 MultiSourceSyncEngine

The main orchestrator:

```python
class MultiSourceSyncEngine:
    """
    Synchronizes models across multiple backend directories.
    """
    
    def __init__(
        self,
        config: MultiSourceConfig,
        backends: list[Backend],
        conflict_strategy: ConflictResolutionStrategy
    ):
        self.config = config
        self.backends = {b.backend_id: b for b in backends}
        self.conflict_resolver = ConflictResolver(strategy=conflict_strategy)
        self.origin_tracker = OriginTracker(config.metadata_dir)
        self.unified_index: dict[str, UnifiedModelEntry] = {}
    
    def full_sync(self) -> SyncResult:
        """
        Perform full synchronization across all backends.
        """
        # 1. Build unified index from ALL directories
        self._build_unified_index()
        
        # 2. Detect and resolve conflicts
        conflicts = self._detect_conflicts()
        for model_id, instances in conflicts.items():
            self._resolve_and_apply(model_id, instances)
        
        # 3. Distribute missing models
        for model_id, entry in self.unified_index.items():
            self._distribute_model(model_id, entry)
        
        return self._build_result()
    
    def handle_event(self, event: SyncEvent) -> None:
        """
        Handle a filesystem event from any watched directory.
        """
        # Determine which backend this event came from
        source_backend = self._identify_source_backend(event.path)
        
        if event.event_type == SyncEventType.FILE_CREATED:
            self._handle_new_model(event.path, source_backend)
        elif event.event_type == SyncEventType.FILE_MODIFIED:
            self._handle_model_update(event.path, source_backend)
        # Note: FILE_DELETED is ignored in add-only mode
    
    def _distribute_model(self, model_id: str, entry: UnifiedModelEntry) -> None:
        """
        Ensure model exists in all backends via hardlinks.
        """
        # Get the canonical source (newest instance)
        source = entry.newest_instance
        
        for backend_id, backend in self.backends.items():
            # Skip if already present with same inode
            if any(i.backend_id == backend_id and i.inode == source.inode 
                   for i in entry.instances):
                continue
            
            # Skip if this backend is the origin (it already has it)
            if self.origin_tracker.is_origin(model_id, backend_id):
                continue
            
            # Create hardlink
            target_path = backend.get_model_path(model_id)
            self._create_hardlink(source.path, target_path)
            
            # Trigger backend-specific metadata generation
            backend.on_model_linked(model_id, target_path)
```

### 3. Configuration

```yaml
# fabric.yaml

# Multi-source mode configuration
sync:
  mode: "multi_source"  # or "single_source" for legacy behavior
  add_only: true        # Required for multi_source
  conflict_resolution: "newest"  # newest, largest, all, manual
  
  # Metadata storage for origins and conflict logs
  metadata_dir: "/srv/models/.fabric"
  
  # Unified storage - where canonical files are stored
  # If null, uses the backend where model first appeared
  unified_storage_dir: "/srv/models"

# All backends are peers - no single "source"
backends:
  llama_cpp:
    enabled: true
    backend_id: "llama_cpp"  # Used for origin tracking
    output_dir: "/var/lib/llama.cpp/models"
    # ... other config
    
  localai:
    enabled: true
    backend_id: "localai"
    output_dir: "/var/lib/LocalAI/models"
    
  lmstudio:
    enabled: true
    backend_id: "lmstudio"
    output_dir: "/home/user/.lmstudio/models"
    
  ollama:
    enabled: true
    backend_id: "ollama"
    output_dir: "/var/lib/ollama/models"

# Watch all backend directories
watch:
  enabled: true
  watch_backend_dirs: true  # NEW: watch all backend output_dirs
  check_interval: 2.0
```

### 4. Conflict Resolution Flow

```
┌─────────────────────────────────────────────────────────────┐
│                    DETECT CONFLICT                          │
│  Same model_id, different inodes across backends            │
└─────────────────────────────────────────────────────────────┘
                            │
                            ▼
┌─────────────────────────────────────────────────────────────┐
│              APPLY CONFLICT STRATEGY                        │
├─────────────────────────────────────────────────────────────┤
│  KEEP_NEWEST:                                               │
│    - Compare mtime across all instances                     │
│    - Select newest as winner                                │
│    - Replace older versions with hardlink to winner         │
├─────────────────────────────────────────────────────────────┤
│  KEEP_LARGEST:                                              │
│    - Compare size across all instances                      │
│    - Select largest as winner (assumes complete download)   │
│    - Replace smaller versions                               │
├─────────────────────────────────────────────────────────────┤
│  KEEP_ALL:                                                  │
│    - Rename conflicting versions:                           │
│      model.gguf → model.llama_cpp.gguf                      │
│      model.gguf → model.localai.gguf                        │
│    - All versions coexist                                   │
├─────────────────────────────────────────────────────────────┤
│  MANUAL:                                                    │
│    - Log conflict to file                                   │
│    - Skip automatic resolution                              │
│    - Admin resolves manually                                │
└─────────────────────────────────────────────────────────────┘
                            │
                            ▼
┌─────────────────────────────────────────────────────────────┐
│              UPDATE ORIGIN TRACKING                         │
│  Record which backend now holds the canonical version       │
└─────────────────────────────────────────────────────────────┘
```

### 5. Event Handling Flow

```
┌─────────────────────────────────────────────────────────────┐
│              FILESYSTEM EVENT                               │
│  New/modified .gguf file detected in any backend dir        │
└─────────────────────────────────────────────────────────────┘
                            │
                            ▼
┌─────────────────────────────────────────────────────────────┐
│            IDENTIFY SOURCE BACKEND                          │
│  Determine which backend directory the event came from      │
└─────────────────────────────────────────────────────────────┘
                            │
                            ▼
┌─────────────────────────────────────────────────────────────┐
│            CHECK IF COMPLETE DOWNLOAD                       │
│  Wait for file size to stabilize (handle .part files)       │
└─────────────────────────────────────────────────────────────┘
                            │
                            ▼
┌─────────────────────────────────────────────────────────────┐
│            CHECK FOR CONFLICTS                              │
│  Does this model_id exist elsewhere with different inode?   │
└─────────────────────────────────────────────────────────────┘
            │                               │
            ▼                               ▼
    ┌───────────────┐               ┌───────────────┐
    │     YES       │               │      NO       │
    │   (Conflict)  │               │  (New model)  │
    └───────┬───────┘               └───────┬───────┘
            │                               │
            ▼                               ▼
┌───────────────────────┐       ┌───────────────────────┐
│  RESOLVE CONFLICT     │       │  RECORD ORIGIN        │
│  Apply strategy       │       │  Mark source backend  │
│  Pick winner          │       │  as origin            │
└───────────┬───────────┘       └───────────┬───────────┘
            │                               │
            └───────────────┬───────────────┘
                            ▼
┌─────────────────────────────────────────────────────────────┐
│           DISTRIBUTE TO ALL BACKENDS                        │
│  Create hardlinks in all other backend directories          │
│  Skip backends that already have correct inode              │
│  Skip origin backend (already has it)                       │
└─────────────────────────────────────────────────────────────┘
                            │
                            ▼
┌─────────────────────────────────────────────────────────────┐
│           GENERATE BACKEND METADATA                         │
│  Create/update backend-specific config files                │
│  (YAML for LocalAI, Modelfile for Ollama, etc.)             │
└─────────────────────────────────────────────────────────────┘
```

### 6. Circular Sync Prevention (Cooldown-Based)

Use a simple **cooldown period** (200ms default) after creating hardlinks. Filesystem events from our own operations arrive within milliseconds, so a brief delay prevents loops:

```python
class SyncCooldownManager:
    """Prevents circular sync via post-operation cooldown."""
    
    def __init__(self, cooldown_seconds: float = 0.2):
        self.cooldown_seconds = cooldown_seconds
        self._cooldowns: dict[str, float] = {}
        self._lock = threading.Lock()
    
    def enter_cooldown(self, path: Path) -> None:
        """Call immediately after creating a hardlink."""
        try:
            stat = path.stat()
            key = f"{stat.st_dev}:{stat.st_ino}"
        except OSError:
            key = str(path.resolve())
        
        with self._lock:
            self._cooldowns[key] = time.time() + self.cooldown_seconds
    
    def is_in_cooldown(self, path: Path) -> bool:
        """Check before processing filesystem events."""
        try:
            stat = path.stat()
            key = f"{stat.st_dev}:{stat.st_ino}"
        except OSError:
            key = str(path.resolve())
        
        with self._lock:
            expiry = self._cooldowns.get(key)
            if expiry is None:
                return False
            if time.time() > expiry:
                del self._cooldowns[key]
                return False
            return True
```

See [MULTI_PROVIDER_LOOP_PREVENTION.md](MULTI_PROVIDER_LOOP_PREVENTION.md) for alternative approaches and tuning.

## Implementation Phases

### Phase 1: Core Multi-Source Support

1. **New Configuration Schema**
   - Add `sync.mode: "multi_source"`
   - Add `sync.conflict_resolution` setting
   - Add `metadata_dir` configuration
   - Deprecate single `source_dir` in favor of unified storage

2. **UnifiedIndex Implementation**
   - Scan all backend directories
   - Build inode-based model registry
   - Detect conflicts (same name, different inode)

3. **Origin Tracking**
   - Implement sidecar file storage
   - Record origin on first detection
   - Query origin for sync decisions

### Phase 2: Conflict Resolution

1. **Conflict Detection**
   - Compare inodes across all instances
   - Flag models with divergent content

2. **Resolution Strategies**
   - Implement KEEP_NEWEST
   - Implement KEEP_LARGEST  
   - Implement KEEP_ALL (with suffix renaming)
   - Implement MANUAL (logging only)

3. **Conflict Logging**
   - Write conflict details to metadata dir
   - Provide CLI command to review conflicts

### Phase 3: Event Handling

1. **Multi-Directory Watch**
   - Watch all backend output directories
   - Identify event source backend

2. **Circular Sync Prevention**
   - Track recently created hardlinks
   - Ignore self-triggered events

3. **Distribution Logic**
   - Hardlink to all backends missing the model
   - Skip backends with matching inode
   - Skip origin backend

### Phase 4: Backend Integration

1. **Backend Notification**
   - Notify backends when models are hardlinked
   - Trigger metadata regeneration

2. **Per-Backend Filtering**
   - Respect ignore patterns even in multi-source
   - Allow backends to reject certain models

## Filesystem Constraints

### Requirements

- All backend directories MUST be on the same filesystem
- The unified storage directory (if used) MUST be on the same filesystem

### Verification

```python
def verify_same_filesystem(paths: list[Path]) -> bool:
    """Verify all paths are on the same filesystem."""
    devices = {p.stat().st_dev for p in paths if p.exists()}
    return len(devices) <= 1
```

### Error Handling

If backends are on different filesystems:
- Log ERROR on startup
- Suggest using bind mounts to unify
- Exit with helpful message

## CLI Additions

```bash
# Run multi-source sync
fabric multi-sync --conflict-strategy newest

# Review conflicts
fabric conflicts list
fabric conflicts resolve model-name.gguf --strategy largest

# Verify filesystem setup
fabric doctor
# Checks:
# - All backend dirs on same filesystem
# - Write permissions
# - Hardlink capability
```

## Migration from Single-Source

Existing users with single-source config:

```bash
# Auto-migration command
fabric migrate --from single --to multi

# This will:
# 1. Convert source_dir to unified_storage_dir
# 2. Enable multi_source mode
# 3. Scan existing backend dirs for models
# 4. Record origins based on existing hardlinks
```
