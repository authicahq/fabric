# Conflict Resolution Design v2 - Non-Interactive Preservation

## Philosophy

**Never destroy data during automated sync.**

When conflicts are detected, the system must:
1. Preserve ALL versions of the model
2. Rename conflicting arrivals with clear suffixes
3. Log the conflict for later review
4. Continue syncing other models without pause
5. Let the user resolve conflicts in a separate, interactive session

## Conflict Handling in Sync Mode

### Detection

When a new model arrives and a different version already exists:

```python
def handle_potential_conflict(new_instance: ModelInstance) -> None:
    """
    Handle a newly detected model that may conflict with existing ones.
    Called during sync/watch mode - MUST be non-interactive.
    """
    existing = index.get_entry(new_instance.model_id)
    
    if not existing:
        # No conflict - normal flow
        return distribute_model(new_instance)
    
    # Check if same content (hardlinked or identical file)
    if any(i.same_content(new_instance) for i in existing.instances):
        # Already have this content - ensure hardlinked everywhere
        return ensure_hardlinked_everywhere(new_instance)
    
    # CONFLICT DETECTED: Same name, different content
    return preserve_conflict(new_instance, existing)
```

### Preservation Strategy

**Files are left in place** - we only log the conflict to the database:

```
Scenario:
  localai/model.gguf (existing, 4GB, modified yesterday)
  ollama/model.gguf (new arrival, 3.9GB, modified today)

Action:
  1. Keep localai/model.gguf as-is (original)
  2. Keep ollama/model.gguf as-is (conflicting)
  3. Log conflict to database with both paths
  4. Continue syncing (skip hardlinking this model)

Result:
  localai/model.gguf (4GB) - original
  ollama/model.gguf (3.9GB) - conflicting version still in place
  ~/.fabric/conflicts.json - contains conflict details
```

**Why not rename files?**
- Backend might be actively using the file
- Could cause "file not found" errors or crashes
- File might be memory-mapped
- Better to let user decide when to resolve

**Conflict is recorded in database with:**
- Model ID
- All backend paths with different content
- File sizes, mtimes, inodes
- Detection timestamp

This makes conflicts:
- **Visible** in directory listings
- **Identifiable** by backend
- **Loadable** by users who want to test both versions
- **Resolvable** by simple rename operations

### Why Rename Incoming (Not Existing)?

1. **Predictability** - The first version keeps its name
2. **Minimal disruption** - Existing backends continue working
3. **Clear provenance** - Conflict suffix shows which backend brought the conflicting version
4. **Easy resolution** - Just rename the conflict file

### Conflict Database

A simple JSON/JSONL file tracks all conflicts:

```json
{
  "conflicts": [
    {
      "model_id": "llama-3-8b-q4",
      "detected_at": "2026-03-25T14:30:00Z",
      "status": "unresolved",
      "instances": [
        {
          "backend_id": "localai",
          "path": "/var/lib/localai/models/llama-3-8b-q4.gguf",
          "inode": 1234567,
          "size": 4089448832,
          "mtime": "2026-03-24T10:00:00Z",
          "status": "original"
        },
        {
          "backend_id": "ollama", 
          "path": "/var/lib/ollama/models/llama-3-8b-q4.conflict.ollama.gguf",
          "inode": 7654321,
          "size": 3999999999,
          "mtime": "2026-03-25T14:30:00Z",
          "status": "conflict"
        }
      ]
    }
  ]
}
```

## Interactive Resolution Mode

A separate CLI command for user-driven resolution:

```bash
# List all unresolved conflicts
fabric conflicts list

# Output:
# CONFLICTS (2 unresolved)
# 
# [1] llama-3-8b-q4.gguf
#     localai:  3.9GB, 2026-03-24 (original)
#     ollama:   3.8GB, 2026-03-25 (conflict)
# 
# [2] mistral-7b-q5.gguf  
#     llama_cpp: 4.5GB, 2026-03-20 (original)
#     ollama:    4.4GB, 2026-03-25 (conflict)

# Resolve a specific conflict
fabric conflicts resolve llama-3-8b-q4.gguf

# Interactive prompt:
# Model: llama-3-8b-q4.gguf
# 
# [1] Keep localai version (3.9GB)
# [2] Keep ollama version (3.8GB)  
# [3] Keep both (rename conflict to llama-3-8b-q4.ollama.gguf)
# [4] Inspect files (show file details, hashes)
# [5] Skip for now
# 
# Choice: _
```

### Resolution Actions

1. **Keep Specific Version** 
   - Hardlink chosen version to all backends
   - Replaces conflicting files atomically (same inode)
   - Mark resolved in database

2. **Keep Both**
   - Rename one version manually first (user must ensure safe to rename)
   - Then hardlink
   - Mark resolved

3. **Manual** (default)
   - Do nothing, let user handle manually
   - Mark as "manual_resolution_required"

**Note:** Resolution uses hardlinking, not simple renaming. The winning file's inode replaces the losing file(s), ensuring atomic updates and data consistency.

### Batch Resolution

```bash
# Resolve all conflicts by keeping newest
fabric conflicts resolve-all --strategy keep-newest

# Resolve all conflicts by keeping largest  
fabric conflicts resolve-all --strategy keep-largest

# Dry run to see what would happen
fabric conflicts resolve-all --strategy keep-newest --dry-run
```

## Implementation Changes

### 1. ConflictPreservationHandler

```python
class ConflictPreservationHandler:
    """
    Handles conflicts in non-interactive mode by preserving all versions.
    """
    
    CONFLICT_SUFFIX = "conflict"
    CONFLICT_DB_FILE = "conflicts.json"
    
    def __init__(self, metadata_dir: Path):
        self.metadata_dir = metadata_dir
        self.conflicts_db = ConflictDatabase(metadata_dir / self.CONFLICT_DB_FILE)
    
    def handle_conflict(
        self,
        new_instance: ModelInstance,
        existing_entry: UnifiedModelEntry,
    ) -> bool:
        """
        Preserve a conflict by renaming the incoming file.
        Returns True if successfully preserved.
        """
        # Generate conflict filename
        conflict_name = (
            f"{new_instance.model_id}."
            f"{self.CONFLICT_SUFFIX}."
            f"{new_instance.backend_id}.gguf"
        )
        conflict_path = new_instance.path.parent / conflict_name
        
        try:
            # Rename the incoming file
            new_instance.path.rename(conflict_path)
            
            # Update the instance path
            new_instance.path = conflict_path
            
            # Record in conflict database
            self.conflicts_db.add_conflict(
                model_id=new_instance.model_id,
                new_instance=new_instance,
                existing_instances=existing_entry.instances,
            )
            
            logger.warning(
                "Conflict preserved",
                model_id=new_instance.model_id,
                renamed_to=conflict_name,
                backend=new_instance.backend_id,
            )
            
            return True
            
        except OSError as e:
            logger.error(
                "Failed to preserve conflict",
                model_id=new_instance.model_id,
                error=str(e),
            )
            return False
```

### 2. ConflictDatabase

```python
@dataclass
class ConflictRecord:
    """A recorded conflict."""
    model_id: str
    detected_at: datetime
    resolved_at: datetime | None
    resolution: str | None  # 'keep_original', 'keep_conflict', 'keep_both', 'manual'
    instances: list[ConflictInstance]
    status: str  # 'unresolved', 'resolved', 'manual_resolution_required'

class ConflictDatabase:
    """JSON-based conflict tracking."""
    
    def __init__(self, db_path: Path):
        self.db_path = db_path
        self._cache: dict[str, ConflictRecord] = {}
        self._load()
    
    def add_conflict(
        self,
        model_id: str,
        new_instance: ModelInstance,
        existing_instances: list[ModelInstance],
    ) -> None:
        """Add a new conflict record."""
        # Check if we already have this conflict
        existing = self._cache.get(model_id)
        
        if existing:
            # Add new instance to existing conflict
            existing.instances.append(self._to_conflict_instance(new_instance, "conflict"))
        else:
            # Create new conflict record
            record = ConflictRecord(
                model_id=model_id,
                detected_at=datetime.now(),
                resolved_at=None,
                resolution=None,
                instances=[
                    self._to_conflict_instance(i, "original")
                    for i in existing_instances
                ] + [self._to_conflict_instance(new_instance, "conflict")],
                status="unresolved",
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
        record.resolved_at = datetime.now()
        
        self._save()
        return True
    
    def get_unresolved(self) -> list[ConflictRecord]:
        """Get all unresolved conflicts."""
        return [r for r in self._cache.values() if r.status == "unresolved"]
    
    def _save(self) -> None:
        """Persist to disk."""
        data = {
            "conflicts": [
                self._record_to_dict(r) for r in self._cache.values()
            ]
        }
        self.db_path.write_text(json.dumps(data, indent=2, default=str))
```

### 3. ConflictResolutionCLI

```python
@app.command(name="conflicts")
def conflicts_cmd(
    action: str = typer.Argument(..., help="list, resolve, resolve-all"),
    model_id: str | None = typer.Argument(None, help="Model ID for resolve"),
    strategy: str = typer.Option(None, "--strategy", help="For resolve-all: keep-newest, keep-largest"),
    dry_run: bool = typer.Option(False, "--dry-run"),
):
    """Manage model conflicts interactively."""
    
    if action == "list":
        return list_conflicts()
    elif action == "resolve":
        if not model_id:
            console.print("[red]Error: model_id required for resolve[/red]")
            raise typer.Exit(1)
        return resolve_conflict_interactive(model_id, dry_run)
    elif action == "resolve-all":
        return resolve_all_conflicts(strategy, dry_run)
    else:
        console.print(f"[red]Unknown action: {action}[/red]")

def list_conflicts():
    """Display all unresolved conflicts."""
    db = ConflictDatabase(get_metadata_dir())
    unresolved = db.get_unresolved()
    
    if not unresolved:
        console.print("[green]No unresolved conflicts![/green]")
        return
    
    table = Table(title=f"Unresolved Conflicts ({len(unresolved)})")
    table.add_column("#", style="cyan")
    table.add_column("Model ID", style="white")
    table.add_column("Backends", style="yellow")
    table.add_column("Sizes", style="blue")
    table.add_column("Detected", style="dim")
    
    for i, conflict in enumerate(unresolved, 1):
        backends = ", ".join(
            f"{ins.backend_id}({'conflict' if ins.status == 'conflict' else 'orig'})"
            for ins in conflict.instances
        )
        sizes = ", ".join(str(ins.size) for ins in conflict.instances)
        detected = conflict.detected_at.strftime("%Y-%m-%d %H:%M")
        
        table.add_row(str(i), conflict.model_id, backends, sizes, detected)
    
    console.print(table)
    console.print("\n[dim]Resolve with: fabric conflicts resolve <model_id>[/dim]")

def resolve_conflict_interactive(model_id: str, dry_run: bool):
    """Interactive conflict resolution."""
    db = ConflictDatabase(get_metadata_dir())
    record = db._cache.get(model_id)
    
    if not record:
        console.print(f"[red]No conflict found for: {model_id}[/red]")
        return
    
    # Display conflict details
    console.print(Panel.fit(f"[bold]Resolving: {model_id}[/bold]"))
    
    for i, instance in enumerate(record.instances, 1):
        status_color = "green" if instance.status == "original" else "yellow"
        console.print(
            f"[{i}] [{status_color}]{instance.backend_id}[/{status_color}]: "
            f"{instance.size:,} bytes, mtime={instance.mtime}"
        )
        console.print(f"    Path: {instance.path}")
    
    # Interactive menu
    console.print("\n[bold]Options:[/bold]")
    for i, instance in enumerate(record.instances, 1):
        console.print(f"  {i}. Keep {instance.backend_id} version (replace others)")
    console.print(f"  {len(record.instances) + 1}. Keep both (rename conflicts)")
    console.print(f"  {len(record.instances) + 2}. Skip")
    
    choice = Prompt.ask("Choice", choices=[str(i) for i in range(1, len(record.instances) + 3)])
    choice = int(choice)
    
    if choice <= len(record.instances):
        # Keep specific version
        winner = record.instances[choice - 1]
        apply_resolution(record, winner, dry_run)
    elif choice == len(record.instances) + 1:
        # Keep both
        apply_keep_all(record, dry_run)
    else:
        console.print("Skipped.")
```

## Example Workflow

### Day 1: Setup

```bash
# Configure multi-source sync
cat > /etc/fabric.yaml <<EOF
sync:
  mode: multi_source
  add_only: true
  metadata_dir: /srv/models/.fabric

backends:
  localai:
    enabled: true
    output_dir: /var/lib/localai/models
  ollama:
    enabled: true
    output_dir: /var/lib/ollama/models
  llama_cpp:
    enabled: true
    output_dir: /home/user/llama.cpp/models
EOF

# Start watching
fabric multi-sync --watch
```

### Day 2: First Conflict

```
# User downloads model to ollama folder
# But slightly different version already in localai

# System logs:
[WARNING] Conflict preserved: llama-3-8b-q4.gguf
          localai has original (4.0GB)
          ollama renamed to llama-3-8b-q4.conflict.ollama.gguf (3.9GB)

# User checks status
fabric conflicts list
# CONFLICTS (1 unresolved)
# [1] llama-3-8b-q4.gguf
#     localai: 4.0GB (original)
#     ollama:  3.9GB (conflict)
```

### Day 3: User Resolves

```bash
# Interactive resolution
fabric conflicts resolve llama-3-8b-q4.gguf

# System shows:
# Resolving: llama-3-8b-q4.gguf
# [1] localai: 4.0GB
# [2] ollama:  3.9GB
# 
# Options:
#   1. Keep localai version
#   2. Keep ollama version
#   3. Keep both
#   4. Skip
# 
# Choice: 2

# Result:
# - localai/llama-3-8b-q4.gguf → hardlinked to ollama version
# - ollama/llama-3-8b-q4.conflict.ollama.gguf → deleted
# - Conflict marked resolved
```

## Advantages of This Approach

1. **No data loss** - All versions preserved until user decides
2. **Non-interactive sync** - Watch mode never blocks
3. **Visible conflicts** - `.conflict.{backend}.gguf` naming makes issues obvious
4. **Flexible resolution** - User can choose per-conflict or batch resolve
5. **Backwards compatible** - Existing single-source mode unchanged
6. **Audit trail** - Conflict database tracks all issues and resolutions

## Edge Cases

### Multiple Conflicts for Same Model

If 3+ backends have different versions:
```
model.gguf (localai - original)
model.conflict.ollama.gguf (ollama)
model.conflict.llama_cpp.gguf (llama_cpp)
```

All preserved until resolved.

### Resolving Then Re-conflicting

If user resolves to keep ollama version, then localai gets a DIFFERENT file:
```
# Original conflict resolved - now all have ollama version
# Then localai downloads NEW different version

model.gguf (ollama - original)
model.conflict.localai.gguf (localai - new conflict)
```

New conflict is treated independently.

### Conflict File Deleted Manually

If user deletes `.conflict.` file manually:
- Next scan detects missing instance
- Conflict record updated
- If all conflicts resolved, mark record resolved

### User Manually Renames Conflict

If user renames `model.conflict.ollama.gguf` → `model.gguf`:
- Next scan detects this
- Treats as new conflict (if still different from others)
- Or normalizes if now same content
