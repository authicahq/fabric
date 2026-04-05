# Loop Prevention via Delayed Trigger / Cooldown

## Principle

Instead of complex inode tracking or event filtering, use a simple **cooldown period** after performing hardlink operations.

**Key insight:** Filesystem events triggered by our own hardlink operations arrive within milliseconds. If we pause briefly after creating hardlinks, we can safely ignore any events that occur during this window.

## Implementation

### Cooldown Manager

```python
import time
import threading
from dataclasses import dataclass
from pathlib import Path

@dataclass
class CooldownEntry:
    """A path currently in cooldown."""
    path: Path
    backend_id: str
    expires_at: float

class SyncCooldownManager:
    """
    Manages cooldown periods to prevent circular sync loops.
    
    After we create a hardlink, we enter a brief cooldown period
    during which we ignore filesystem events for that path.
    """
    
    # Cooldown period in seconds (100-500ms is usually sufficient)
    DEFAULT_COOLDOWN = 0.2  # 200ms
    
    def __init__(self, cooldown_seconds: float = DEFAULT_COOLDOWN):
        self.cooldown_seconds = cooldown_seconds
        self._cooldowns: dict[str, CooldownEntry] = {}
        self._lock = threading.Lock()
    
    def enter_cooldown(self, path: Path, backend_id: str) -> None:
        """
        Enter cooldown for a path after we just modified it.
        Call this immediately after creating a hardlink.
        """
        # Use inode+device as key for path-independent matching
        try:
            stat = path.stat()
            key = f"{stat.st_dev}:{stat.st_ino}"
        except OSError:
            # Fallback to path string if stat fails
            key = str(path.resolve())
        
        entry = CooldownEntry(
            path=path,
            backend_id=backend_id,
            expires_at=time.time() + self.cooldown_seconds,
        )
        
        with self._lock:
            self._cooldowns[key] = entry
        
        # Schedule cleanup
        threading.Timer(
            self.cooldown_seconds + 0.1,  # Slightly longer to be safe
            self._remove_cooldown,
            args=[key]
        ).start()
    
    def is_in_cooldown(self, path: Path) -> bool:
        """
        Check if a path is currently in cooldown.
        Returns True if we should ignore this event.
        """
        try:
            stat = path.stat()
            key = f"{stat.st_dev}:{stat.st_ino}"
        except OSError:
            key = str(path.resolve())
        
        with self._lock:
            entry = self._cooldowns.get(key)
            if entry is None:
                return False
            
            # Check if expired
            if time.time() > entry.expires_at:
                del self._cooldowns[key]
                return False
            
            return True
    
    def _remove_cooldown(self, key: str) -> None:
        """Remove expired cooldown entry."""
        with self._lock:
            self._cooldowns.pop(key, None)
    
    def clear(self) -> None:
        """Clear all cooldowns (e.g., on shutdown)."""
        with self._lock:
            self._cooldowns.clear()
```

### Integration with Event Handler

```python
class ModelEventHandler(FileSystemEventHandler):
    """Watchdog event handler with cooldown support."""
    
    def __init__(
        self,
        callback: EventHandler,
        source_dirs: list[Path],
        download_detector: DownloadDetector,
        cooldown_manager: SyncCooldownManager,  # [NEW]
    ):
        self.callback = callback
        self.source_dirs = source_dirs
        self.download_detector = download_detector
        self.cooldown_manager = cooldown_manager  # [NEW]
    
    def on_created(self, event: FileSystemEvent) -> None:
        """Handle file creation."""
        if event.is_directory:
            return
        
        path = Path(event.src_path)
        
        # [NEW] Check if this file is in cooldown (our own hardlink)
        if self.cooldown_manager.is_in_cooldown(path):
            logger.debug("Ignoring self-triggered event (cooldown)", path=str(path))
            return
        
        self._handle_file_event(event, SyncEventType.FILE_CREATED)
    
    def on_modified(self, event: FileSystemEvent) -> None:
        """Handle file modification."""
        if event.is_directory:
            return
        
        path = Path(event.src_path)
        
        # [NEW] Check cooldown
        if self.cooldown_manager.is_in_cooldown(path):
            logger.debug("Ignoring self-triggered event (cooldown)", path=str(path))
            return
        
        self._handle_file_event(event, SyncEventType.FILE_MODIFIED)
```

### Integration with Sync Engine

```python
class MultiSourceSyncEngine:
    """Main sync engine with cooldown-aware distribution."""
    
    def __init__(self, config: MultiSourceConfig, backends: list[Backend]):
        self.config = config
        self.backends = {b.backend_id: b for b in backends}
        self.cooldown_manager = SyncCooldownManager(
            cooldown_seconds=config.sync.cooldown_seconds or 0.2
        )
        # ... other initializers
    
    def _create_hardlink(
        self,
        source: ModelInstance,
        target_backend: Backend,
    ) -> bool:
        """
        Create a hardlink and enter cooldown to prevent loops.
        """
        target_path = target_backend.get_model_path(source.model_id)
        
        try:
            import os
            os.link(source.path, target_path)
            
            logger.debug(
                "Created hardlink",
                source=str(source.path),
                target=str(target_path),
                target_backend=target_backend.backend_id,
            )
            
            # [NEW] Enter cooldown for the target path
            # This prevents us from processing the filesystem event
            # that our own hardlink just generated
            self.cooldown_manager.enter_cooldown(
                path=target_path,
                backend_id=target_backend.backend_id,
            )
            
            return True
            
        except OSError as e:
            logger.error(
                "Failed to create hardlink",
                error=str(e),
                source=str(source.path),
                target=str(target_path),
            )
            return False
    
    def handle_event(self, event: SyncEvent) -> None:
        """
        Handle a filesystem event from any watched directory.
        """
        # [NEW] Double-check cooldown at event level
        if self.cooldown_manager.is_in_cooldown(event.path):
            logger.debug(
                "Skipping event for path in cooldown",
                path=str(event.path),
                event_type=event.event_type.name,
            )
            return
        
        # Determine source backend
        source_backend = self._identify_backend(event.source_dir)
        
        if event.event_type == SyncEventType.FILE_CREATED:
            self._handle_new_model(event.path, source_backend)
        elif event.event_type == SyncEventType.FILE_MODIFIED:
            self._handle_model_update(event.path, source_backend)
        # FILE_DELETED ignored in add-only mode
```

## Alternative: Delayed Sync Pattern

Another approach is to delay the sync operation itself, not just ignore events:

```python
class DelayedSyncManager:
    """
    Buffers sync operations and executes them after a delay.
    If multiple events occur for the same file, only process once.
    """
    
    def __init__(self, delay_seconds: float = 0.5):
        self.delay_seconds = delay_seconds
        self._pending: dict[str, threading.Timer] = {}
        self._lock = threading.Lock()
    
    def schedule_sync(
        self,
        model_id: str,
        sync_func: callable,
    ) -> None:
        """
        Schedule a sync operation after the delay.
        Cancels any pending sync for the same model.
        """
        with self._lock:
            # Cancel existing timer for this model
            if model_id in self._pending:
                self._pending[model_id].cancel()
            
            # Create new timer
            timer = threading.Timer(
                self.delay_seconds,
                self._execute_sync,
                args=[model_id, sync_func]
            )
            self._pending[model_id] = timer
            timer.start()
    
    def _execute_sync(self, model_id: str, sync_func: callable) -> None:
        """Execute the sync and clean up."""
        with self._lock:
            self._pending.pop(model_id, None)
        
        try:
            sync_func()
        except Exception as e:
            logger.error("Sync failed", model_id=model_id, error=str(e))
```

## Comparison of Approaches

| Approach | Pros | Cons | Best For |
|----------|------|------|----------|
| **Cooldown (recommended)** | Simple, low latency, reliable | Brief window where legit events might be ignored | Most deployments |
| **Delayed sync** | Debounces rapid changes, deduplicates events | Higher latency for sync | High-churn environments |
| **Inode tracking** | Precise, no delay | Complex, race conditions possible | Not recommended |

## Configuration

```yaml
sync:
  mode: multi_source
  add_only: true
  
  # Cooldown period in seconds (default: 0.2)
  # Increase if you see circular sync issues
  cooldown_seconds: 0.2
  
  # Alternative: Use delayed sync instead
  use_delayed_sync: false
  delay_seconds: 0.5
```

## Testing Loop Prevention

```python
def test_cooldown_prevents_loops():
    """Verify that cooldown prevents circular sync."""
    cooldown = SyncCooldownManager(cooldown_seconds=0.1)
    
    path = Path("/tmp/test_model.gguf")
    path.touch()
    
    # Enter cooldown
    cooldown.enter_cooldown(path, "backend_a")
    
    # Should be in cooldown immediately
    assert cooldown.is_in_cooldown(path) == True
    
    # Wait for cooldown to expire
    time.sleep(0.15)
    
    # Should no longer be in cooldown
    assert cooldown.is_in_cooldown(path) == False


def test_no_infinite_loop():
    """
    Integration test: Create model in backend A,
    verify it syncs to B exactly once (not back to A infinitely).
    """
    # Setup
    backend_a = create_backend("a", "/tmp/backend_a")
    backend_b = create_backend("b", "/tmp/backend_b")
    engine = MultiSourceSyncEngine(config, [backend_a, backend_b])
    
    # Create model in backend A
    model_path = backend_a.output_dir / "model.gguf"
    model_path.write_bytes(b"test content")
    
    # Process event
    event = SyncEvent(
        event_type=SyncEventType.FILE_CREATED,
        path=model_path,
        source_dir=backend_a.output_dir,
    )
    engine.handle_event(event)
    
    # Give time for any potential loops
    time.sleep(1.0)
    
    # Count total hardlinks (should be exactly 2 - one in each backend)
    import os
    target_path = backend_b.output_dir / "model.gguf"
    stat = target_path.stat()
    
    # Inode should have link count of exactly 2 (A and B)
    assert stat.st_nlink == 2, f"Expected 2 hardlinks, got {stat.st_nlink}"
```

## Monitoring

Log entries to watch for:

```
# Successful cooldown prevention
DEBUG: Ignoring self-triggered event (cooldown) path=/var/lib/ollama/models/model.gguf

# Cooldown entry created
DEBUG: Entered cooldown path=/var/lib/ollama/models/model.gguf backend=ollama duration=0.2s

# Event processed after cooldown
DEBUG: Processing event path=/var/lib/localai/models/model.gguf type=FILE_CREATED
```

## Tuning

If you see circular sync issues:

1. **Increase cooldown**: Try `0.3` or `0.5` seconds
2. **Enable delayed sync**: Use `use_delayed_sync: true` with `delay_seconds: 0.5`
3. **Check filesystem**: Network filesystems (NFS, CIFS) may need longer delays
4. **Monitor logs**: Look for "Ignoring self-triggered event" to verify it's working

## Summary

The cooldown approach is:
- **Simple**: ~50 lines of code
- **Effective**: Prevents loops with minimal delay
- **Configurable**: Tune delay for your environment
- **Observable**: Clear logging for debugging

This is the recommended approach for production deployments.
