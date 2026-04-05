"""Main entry point for fabric."""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import TYPE_CHECKING, Any

import anyio
import typer
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from .backends import (
    GPT4AllBackend,
    JanBackend,
    KoboldCppBackend,
    LlamaCppBackend,
    LlamaCppPythonBackend,
    LMStudioBackend,
    LocalAIBackend,
    OllamaBackend,
    TextGenBackend,
    vLLMBackend,
)
from .core.config import ConfigLoader
from .core.conflict_resolver import ConflictDatabase
from .core.constants import (
    DEFAULT_LMSTUDIO_DIR,
    DEFAULT_LOCALAI_DIR,
    DEFAULT_MODELS_DST,
    DEFAULT_MODELS_SRC,
    DEFAULT_SERVICE_NAME,
)
from .core.discovery import BackendDiscovery, create_config_from_discovered
from .core.exceptions import FabricError
from .core.logging import get_logger, is_verbose, setup_logging
from .core.models import (
    AppConfig,
    ConflictStrategy,
    GPT4AllConfig,
    JanConfig,
    KoboldCppConfig,
    LlamaCppConfig,
    LlamaCppPythonConfig,
    LMStudioConfig,
    LocalAIConfig,
    OllamaConfig,
    TextGenConfig,
    vLLMConfig,
)
from .core.multi_sync import MultiSourceSyncEngine
from .core.service import ServiceInstaller
from .core.sync import SyncEngine
from .core.watcher import FileSystemWatcher

if TYPE_CHECKING:
    from .backends.base import Backend

# Rich console for pretty output
console = Console()
app = typer.Typer(
    name="fabric",
    help="Cross-platform model linker for LLM inference engines",
    rich_markup_mode="rich",
)

logger = get_logger(__name__)


def version_callback(value: bool) -> None:
    """Display version information."""
    if value:
        from . import __version__

        console.print(f"fabric version {__version__}")
        raise typer.Exit()


def get_backends(config: AppConfig) -> list[Backend]:
    """Create backend instances from configuration.

    Args:
        config: Application configuration

    Returns:
        List of initialized backends
    """
    backends: list[Backend] = []

    for name, backend_config in config.backends.items():
        if not backend_config.enabled:
            continue

        if isinstance(backend_config, LlamaCppConfig):
            backends.append(LlamaCppBackend(backend_config))
        elif isinstance(backend_config, LocalAIConfig):
            backends.append(LocalAIBackend(backend_config))
        elif isinstance(backend_config, LMStudioConfig):
            backends.append(LMStudioBackend(backend_config))
        elif isinstance(backend_config, OllamaConfig):
            backends.append(OllamaBackend(backend_config))
        elif isinstance(backend_config, TextGenConfig):
            backends.append(TextGenBackend(backend_config))
        elif isinstance(backend_config, GPT4AllConfig):
            backends.append(GPT4AllBackend(backend_config))
        elif isinstance(backend_config, KoboldCppConfig):
            backends.append(KoboldCppBackend(backend_config))
        elif isinstance(backend_config, vLLMConfig):
            backends.append(vLLMBackend(backend_config))
        elif isinstance(backend_config, JanConfig):
            backends.append(JanBackend(backend_config))
        elif isinstance(backend_config, LlamaCppPythonConfig):
            backends.append(LlamaCppPythonBackend(backend_config))
        else:
            logger.warning(f"Unknown backend type for {name}: {type(backend_config).__name__}")

    return backends


@app.callback()
def main(
    version: bool = typer.Option(
        None,
        "--version",
        "-v",
        callback=version_callback,
        is_eager=True,
        help="Show version information",
    ),
    config_file: Path | None = typer.Option(
        None,
        "--config",
        "-c",
        help="Path to configuration file",
        exists=True,
        dir_okay=False,
    ),
    verbose: bool = typer.Option(
        False,
        "--verbose",
        "-V",
        help="Enable verbose output",
    ),
    json_logs: bool = typer.Option(
        False,
        "--json",
        help="Output logs as JSON",
    ),
) -> None:
    """Link Models - Cross-platform model linker for LLM inference engines."""
    # Setup logging early
    setup_logging(
        verbose=verbose,
        json_format=json_logs,
    )


@app.command()
def sync(
    source: Path | None = typer.Option(
        None,
        "--source",
        "--src",
        "-s",
        help=f"Source directory (default: {DEFAULT_MODELS_SRC})",
    ),
    llama_cpp_dir: Path | None = typer.Option(
        None,
        "--llama-cpp",
        "--llama",
        help=f"llama.cpp output directory (default: {DEFAULT_MODELS_DST})",
    ),
    localai_dir: Path | None = typer.Option(
        None,
        "--localai",
        "-l",
        help=f"LocalAI output directory (default: {DEFAULT_LOCALAI_DIR})",
    ),
    lmstudio_dir: Path | None = typer.Option(
        None,
        "--lmstudio",
        help=f"LM Studio output directory (default: {DEFAULT_LMSTUDIO_DIR})",
    ),
    config_file: Path | None = typer.Option(
        None,
        "--config",
        "-c",
        help="Path to configuration file",
        exists=True,
    ),
    no_llama_cpp: bool = typer.Option(
        False,
        "--no-llama-cpp",
        help="Disable llama.cpp backend",
    ),
    no_localai: bool = typer.Option(
        False,
        "--no-localai",
        help="Disable LocalAI backend",
    ),
    no_lmstudio: bool = typer.Option(
        False,
        "--no-lmstudio",
        help="Disable LM Studio backend",
    ),
    dry_run: bool = typer.Option(
        False,
        "--dry-run",
        "-n",
        help="Show what would be done without making changes",
    ),
) -> None:
    """Run a one-time synchronization."""
    try:
        # Load configuration
        loader = ConfigLoader()
        cli_args: dict[str, Any] = {
            "sync": {"dry_run": dry_run},
        }

        if source:
            cli_args["source_dir"] = source

        # Build backend config from CLI args
        backends_config = {}

        if not no_llama_cpp:
            llama_config = {"enabled": True}
            if llama_cpp_dir:
                llama_config["output_dir"] = llama_cpp_dir
            else:
                # Use default if not specified
                llama_config["output_dir"] = Path(DEFAULT_MODELS_DST)
            backends_config["llama_cpp"] = llama_config

        if not no_localai:
            localai_config = {"enabled": True}
            if localai_dir:
                localai_config["output_dir"] = localai_dir
            else:
                # Use default if not specified
                localai_config["output_dir"] = Path(DEFAULT_LOCALAI_DIR)
            backends_config["localai"] = localai_config

        if lmstudio_dir and not no_lmstudio:
            backends_config["lmstudio"] = {
                "enabled": True,
                "output_dir": lmstudio_dir,
            }

        if backends_config:
            cli_args["backends"] = backends_config

        config = loader.load(config_path=config_file, cli_args=cli_args)

        # Create backends
        backends = get_backends(config)

        if not backends:
            console.print("[red]Error: No backends enabled[/red]")
            raise typer.Exit(1)

        # Create and run sync engine
        engine = SyncEngine(config, backends)
        engine.setup()

        console.print(
            Panel.fit(
                f"[bold green]Starting synchronization[/bold green]\n"
                f"Source: [cyan]{config.source_dir}[/cyan]\n"
                f"Backends: [yellow]{', '.join(b.name for b in backends)}[/yellow]"
            )
        )

        results = engine.full_sync()

        # Display results
        table = Table(title="Synchronization Results")
        table.add_column("Backend", style="cyan")
        table.add_column("Linked", justify="right", style="green")
        table.add_column("Updated", justify="right", style="yellow")
        table.add_column("Skipped", justify="right", style="blue")
        table.add_column("Removed", justify="right", style="red")
        table.add_column("Errors", justify="right", style="red")

        for name, result in results.items():
            table.add_row(
                name,
                str(result.linked),
                str(result.updated),
                str(result.skipped),
                str(result.removed),
                str(len(result.errors)) if result.errors else "0",
            )

        console.print(table)

        # Display skip reasons if any
        for name, result in results.items():
            if result.skip_reasons:
                console.print(f"\n[yellow]{name}:[/yellow] Skipped items:")
                # Group by reason for summary
                reason_counts: dict[str, int] = {}
                for reason in result.skip_reasons:
                    reason_type = reason.get("reason", "unknown")
                    reason_counts[reason_type] = reason_counts.get(reason_type, 0) + 1

                for reason_type, count in sorted(reason_counts.items()):
                    console.print(f"  [blue]{count}[/blue] {reason_type}")

                # Show details in verbose mode
                if is_verbose() and result.skip_reasons:
                    console.print("  [dim]Details:[/dim]")
                    for reason in result.skip_reasons[:20]:  # Limit to first 20
                        item = reason.get("item", "unknown")
                        reason_type = reason.get("reason", "unknown")
                        console.print(f"    [dim]- {item}: {reason_type}[/dim]")
                    if len(result.skip_reasons) > 20:
                        console.print(
                            f"    [dim]... and {len(result.skip_reasons) - 20} more[/dim]"
                        )

        # Check for errors
        has_errors = any(r.errors for r in results.values())
        if has_errors:
            console.print("[yellow]Some errors occurred during synchronization[/yellow]")
            for name, result in results.items():
                for error in result.errors:
                    console.print(f"  [red]{name}:[/red] {error}")

        console.print("[bold green]Synchronization complete![/bold green]")

    except FabricError as e:
        console.print(f"[red]Error: {e.message}[/red]")
        if e.details:
            console.print(f"[dim]{e.details}[/dim]")
        raise typer.Exit(1)
    except Exception as e:
        logger.exception("Unexpected error")
        console.print(f"[red]Unexpected error: {e}[/red]")
        raise typer.Exit(1)


@app.command()
def watch(
    source: Path | None = typer.Option(
        None,
        "--source",
        "--src",
        "-s",
        help=f"Source directory (default: {DEFAULT_MODELS_SRC})",
    ),
    llama_cpp_dir: Path | None = typer.Option(
        None,
        "--llama-cpp",
        "--llama",
        help="llama.cpp output directory",
    ),
    localai_dir: Path | None = typer.Option(
        None,
        "--localai",
        "-l",
        help="LocalAI output directory",
    ),
    config_file: Path | None = typer.Option(
        None,
        "--config",
        "-c",
        help="Path to configuration file",
        exists=True,
    ),
    interval: float = typer.Option(
        2.0,
        "--interval",
        "-i",
        help="Download check interval in seconds",
    ),
    no_initial_sync: bool = typer.Option(
        False,
        "--no-initial-sync",
        help="Skip initial full sync on startup",
    ),
) -> None:
    """Run as a filesystem watcher (continuous monitoring)."""

    async def run_watcher() -> None:
        try:
            # Load configuration
            loader = ConfigLoader()
            cli_args: dict[str, Any] = {
                "watch": {"enabled": True, "check_interval": interval},
            }

            if source:
                cli_args["source_dir"] = source

            config = loader.load(config_path=config_file, cli_args=cli_args)

            # Create backends
            backends = get_backends(config)

            if not backends:
                console.print("[red]Error: No backends enabled[/red]")
                raise typer.Exit(1)

            # Create sync engine
            engine = SyncEngine(config, backends)
            engine.setup()

            # Initial sync (optional)
            console.print(
                Panel.fit(
                    f"[bold green]Starting filesystem watcher[/bold green]\n"
                    f"Source: [cyan]{config.source_dir}[/cyan]\n"
                    f"Backends: [yellow]{', '.join(b.name for b in backends)}[/yellow]\n"
                    f"Press [bold]Ctrl+C[/bold] to stop"
                )
            )

            if not no_initial_sync:
                console.print("[dim]Performing initial synchronization...[/dim]")
                engine.full_sync()
                console.print("[green]Initial sync complete. Watching for changes...[/green]")
            else:
                console.print(
                    "[dim]Skipping initial sync (--no-initial-sync). Watching for changes...[/dim]"
                )

            # Create and run watcher - only watch source directory
            # Watching backend directories causes duplicate events when hardlinks are created
            def on_event(event: Any) -> None:
                try:
                    engine.handle_event(event)
                except Exception as e:
                    logger.error("Error handling event", error=str(e))

            watcher = FileSystemWatcher(
                source_dirs=[config.source_dir],
                callback=on_event,
                check_interval=config.watch.check_interval,
                stable_count=config.watch.stable_count,
            )

            await watcher.run()

        except asyncio.CancelledError:
            console.print("\n[yellow]Watcher stopped[/yellow]")
        except FabricError as e:
            console.print(f"[red]Error: {e.message}[/red]")
            raise typer.Exit(1)
        except Exception as e:
            logger.exception("Unexpected error")
            console.print(f"[red]Unexpected error: {e}[/red]")
            raise typer.Exit(1)

    try:
        anyio.run(run_watcher)
    except KeyboardInterrupt:
        console.print("\n[yellow]Interrupted by user[/yellow]")


@app.command()
def service(
    action: str = typer.Argument(
        ...,
        help="Action to perform: install, uninstall, start, stop, status",
    ),
    name: str = typer.Option(
        DEFAULT_SERVICE_NAME,
        "--name",
        "-n",
        help="Service name",
    ),
) -> None:
    """Manage the fabric service."""
    installer = ServiceInstaller(service_name=name)

    if action == "install":
        try:
            installer.install()
            console.print(f"[green]Service '{name}' installed successfully[/green]")
            console.print("[dim]Start with: [bold]fabric service start[/bold][/dim]")
        except FabricError as e:
            console.print(f"[red]Failed to install service: {e.message}[/red]")
            raise typer.Exit(1)

    elif action == "uninstall":
        try:
            installer.uninstall()
            console.print(f"[green]Service '{name}' uninstalled successfully[/green]")
        except FabricError as e:
            console.print(f"[red]Failed to uninstall service: {e.message}[/red]")
            raise typer.Exit(1)

    elif action == "start":
        try:
            installer.start()
            console.print(f"[green]Service '{name}' started[/green]")
        except Exception as e:
            console.print(f"[red]Failed to start service: {e}[/red]")
            raise typer.Exit(1)

    elif action == "stop":
        try:
            installer.stop()
            console.print(f"[green]Service '{name}' stopped[/green]")
        except Exception as e:
            console.print(f"[red]Failed to stop service: {e}[/red]")
            raise typer.Exit(1)

    elif action == "status":
        status = installer.status()
        if status.get("installed"):
            state = "[green]active[/green]" if status.get("active") else "[yellow]inactive[/yellow]"
            console.print(f"Service '{name}': {state}")
        else:
            console.print(f"Service '{name}': [red]not installed[/red]")

    else:
        console.print(f"[red]Unknown action: {action}[/red]")
        console.print("Valid actions: install, uninstall, start, stop, status")
        raise typer.Exit(1)


@app.command()
def config(
    generate: bool = typer.Option(
        False,
        "--generate",
        "-g",
        help="Generate default configuration file",
    ),
    output: Path = typer.Option(
        Path("fabric.yaml"),
        "--output",
        "-o",
        help="Output path for generated config",
    ),
) -> None:
    """Configuration management."""
    if generate:
        loader = ConfigLoader()
        default_config = loader.generate_default_config()

        with open(output, "w") as f:
            f.write(default_config)

        console.print(f"[green]Default configuration written to: {output}[/green]")
        console.print("[dim]Edit this file and use with: fabric -c {output} <command>[/dim]")
    else:
        # Show current effective configuration
        loader = ConfigLoader()
        cfg = loader.load()

        console.print(Panel.fit("[bold]Current Configuration[/bold]"))
        console.print(f"Source: [cyan]{cfg.source_dir}[/cyan]")
        console.print("\nBackends:")
        for name, backend in cfg.backends.items():
            status = "[green]enabled[/green]" if backend.enabled else "[red]disabled[/red]"
            console.print(f"  {name}: {status} -> [cyan]{backend.output_dir}[/cyan]")


@app.command()
def discover(
    generate_config: bool = typer.Option(
        False,
        "--generate-config",
        "-g",
        help="Generate config file with discovered backends",
    ),
    output: Path = typer.Option(
        Path("fabric.yaml"),
        "--output",
        "-o",
        help="Output path for generated config",
    ),
) -> None:
    """Auto-discover installed LLM inference backends."""
    try:
        discovery = BackendDiscovery()
        backends = discovery.discover_all()

        if not backends:
            console.print("[yellow]No backends discovered[/yellow]")
            return

        # Display discovered backends
        table = Table(title="Discovered Backends")
        table.add_column("Name", style="cyan")
        table.add_column("Type", style="blue")
        table.add_column("Install Dir", style="dim")
        table.add_column("Models Dir", style="green")
        table.add_column("Running", style="yellow")
        table.add_column("Port", style="magenta")

        for backend in backends:
            running = "[green]Yes[/green]" if backend.is_running else "[red]No[/red]"
            port = str(backend.port) if backend.port else "-"
            table.add_row(
                backend.name,
                backend.backend_type,
                str(backend.install_dir)[:40],
                str(backend.models_dir)[:40] if backend.models_dir else "-",
                running,
                port,
            )

        console.print(table)

        # Generate config if requested
        if generate_config:
            config_dict = create_config_from_discovered(backends)
            import yaml

            config_yaml = yaml.dump({"backends": config_dict}, default_flow_style=False)

            with open(output, "w") as f:
                f.write(config_yaml)

            console.print(f"\n[green]Configuration written to: {output}[/green]")
            console.print("[dim]Edit this file and use with: fabric -c {output} sync[/dim]")

    except Exception as e:
        logger.exception("Discovery failed")
        console.print(f"[red]Discovery failed: {e}[/red]")
        raise typer.Exit(1)


@app.command(name="multi-sync")
def multi_sync(
    config_file: Path | None = typer.Option(
        None,
        "--config",
        "-c",
        help="Path to configuration file",
        exists=True,
    ),
    dry_run: bool = typer.Option(
        False,
        "--dry-run",
        "-n",
        help="Show what would be done without making changes",
    ),
    watch: bool = typer.Option(
        False,
        "--watch",
        "-w",
        help="Run in continuous watch mode",
    ),
    cooldown: float = typer.Option(
        0.2,
        "--cooldown",
        help="Cooldown period in seconds to prevent circular syncs",
    ),
) -> None:
    """Run multi-source synchronization across all backends."""
    try:
        # Load configuration
        loader = ConfigLoader()
        cli_args: dict[str, Any] = {
            "sync": {
                "mode": "multi_source",
                "add_only": True,
                "dry_run": dry_run,
                "cooldown_seconds": cooldown,
            },
        }

        config = loader.load(config_path=config_file, cli_args=cli_args)

        # Verify we're in multi-source mode
        if not config.is_multi_source:
            console.print("[red]Error: Configuration is not in multi-source mode[/red]")
            console.print("[dim]Set sync.mode to 'multi_source' in your config file[/dim]")
            raise typer.Exit(1)

        # Create backends
        backends = get_backends(config)

        if not backends:
            console.print("[red]Error: No backends enabled[/red]")
            raise typer.Exit(1)

        # Create multi-source sync engine
        engine = MultiSourceSyncEngine(config, backends)
        engine.setup()

        console.print(
            Panel.fit(
                f"[bold green]Multi-Source Synchronization[/bold green]\n"
                f"Mode: [cyan]multi_source[/cyan]\n"
                f"Backends: [yellow]{', '.join(b.name for b in backends)}[/yellow]\n"
                f"Add-Only: [green]enabled[/green]"
            )
        )

        # Perform full sync
        console.print("[dim]Performing full synchronization...[/dim]")
        result = engine.full_sync()

        # Display results
        table = Table(title="Synchronization Results")
        table.add_column("Metric", style="cyan")
        table.add_column("Value", justify="right")

        table.add_row("Models Processed", str(len(engine.unified_index.entries)))
        table.add_row("Hardlinks Created", str(result.linked))
        table.add_row("Conflicts Detected", str(result.conflicts))
        table.add_row("Errors", str(len(result.errors)))

        console.print(table)

        if result.conflicts > 0:
            console.print(
                f"\n[yellow]{result.conflicts} conflict(s) detected.[/yellow] "
                "Run [bold]fabric conflicts list[/bold] to review."
            )

        if result.errors:
            console.print("\n[red]Errors:[/red]")
            for error in result.errors:
                console.print(f"  [red]- {error}[/red]")

        # Watch mode
        if watch:
            console.print("\n[dim]Starting watch mode... Press Ctrl+C to stop[/dim]")

            async def run_watcher() -> None:
                def on_event(event) -> None:
                    try:
                        result = engine.handle_event(event)
                        if result.linked > 0:
                            console.print(
                                f"[green]Synced {result.linked} model(s)[/green] "
                                f"from event: {event.path.name}"
                            )
                        if result.conflicts > 0:
                            console.print(
                                f"[yellow]Conflict detected:[/yellow] {event.path.name}"
                            )
                    except Exception as e:
                        logger.error("Error handling event", error=str(e))

                # Watch all backend directories
                watcher = FileSystemWatcher(
                    source_dirs=config.effective_source_dirs,
                    callback=on_event,
                    check_interval=config.watch.check_interval,
                    stable_count=config.watch.stable_count,
                    cooldown_manager=engine.cooldown_manager,
                )

                await watcher.run()

            try:
                anyio.run(run_watcher)
            except KeyboardInterrupt:
                console.print("\n[yellow]Interrupted by user[/yellow]")

        console.print("\n[bold green]Synchronization complete![/bold green]")

    except FabricError as e:
        console.print(f"[red]Error: {e.message}[/red]")
        if e.details:
            console.print(f"[dim]{e.details}[/dim]")
        raise typer.Exit(1)
    except Exception as e:
        logger.exception("Unexpected error")
        console.print(f"[red]Unexpected error: {e}[/red]")
        raise typer.Exit(1)


@app.command(name="conflicts")
def conflicts_cmd(
    action: str = typer.Argument(
        ...,
        help="Action to perform: list, resolve, resolve-all",
    ),
    model_id: str | None = typer.Argument(
        None,
        help="Model ID (for resolve action)",
    ),
    config_file: Path | None = typer.Option(
        None,
        "--config",
        "-c",
        help="Path to configuration file",
        exists=True,
    ),
    strategy: ConflictStrategy = typer.Option(
        ConflictStrategy.KEEP_NEWEST,
        "--strategy",
        "-s",
        help="Resolution strategy for resolve-all",
    ),
    dry_run: bool = typer.Option(
        False,
        "--dry-run",
        "-n",
        help="Show what would be done without making changes",
    ),
) -> None:
    """Manage model conflicts."""
    from rich.prompt import Prompt

    try:
        # Load configuration to get metadata directory
        loader = ConfigLoader()
        config = loader.load(config_path=config_file)

        metadata_dir = config.sync.metadata_dir or Path.home() / ".fabric"
        db = ConflictDatabase(metadata_dir)

        if action == "list":
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
                backends_str = ", ".join(
                    f"{ins.backend_id}({ins.status})"
                    for ins in conflict.instances
                )
                sizes_str = ", ".join(
                    f"{ins.size // 1024 // 1024}MB"
                    for ins in conflict.instances
                )
                detected = conflict.detected_at.strftime("%Y-%m-%d %H:%M")

                table.add_row(str(i), conflict.model_id, backends_str, sizes_str, detected)

            console.print(table)
            console.print(
                "\n[dim]Resolve with: fabric conflicts resolve <model_id>[/dim]"
            )

        elif action == "resolve":
            if not model_id:
                console.print("[red]Error: model_id is required for resolve action[/red]")
                raise typer.Exit(1)

            record = db.get_record(model_id)
            if not record:
                console.print(f"[red]No conflict found for: {model_id}[/red]")
                raise typer.Exit(1)

            if record.status == "resolved":
                console.print(f"[yellow]Conflict already resolved: {model_id}[/yellow]")
                return

            # Display conflict details
            console.print(Panel.fit(f"[bold]Resolving: {model_id}[/bold]"))

            for i, instance in enumerate(record.instances, 1):
                status_color = "green" if instance.status == "original" else "yellow"
                size_mb = instance.size // 1024 // 1024

                console.print(
                    f"[{i}] [{status_color}]{instance.backend_id}[/{status_color}]: "
                    f"{size_mb}MB"
                )
                console.print(f"    Path: {instance.path}")

            # Interactive menu
            console.print("\n[bold]Options:[/bold]")
            for i, instance in enumerate(record.instances, 1):
                console.print(f"  {i}. Keep {instance.backend_id} version")
            console.print(f"  {len(record.instances) + 1}. Keep all versions (rename)")
            console.print(f"  {len(record.instances) + 2}. Skip")

            choice = Prompt.ask(
                "Choice",
                choices=[str(i) for i in range(1, len(record.instances) + 3)],
            )
            choice = int(choice)

            if dry_run:
                console.print("[dim][DRY RUN] No changes made[/dim]")
                return

            if choice <= len(record.instances):
                # Keep specific version
                winner = record.instances[choice - 1]
                console.print(f"[green]Resolving: keeping {winner.backend_id} version[/green]")

                # Hardlink winner to all backends
                for instance in record.instances:
                    if instance.backend_id != winner.backend_id:
                        try:
                            src_path = Path(winner.path)
                            dst_path = Path(instance.path)
                            if dst_path.exists():
                                dst_path.unlink()
                            import os
                            os.link(src_path, dst_path)
                            console.print(f"  Hardlinked to {instance.backend_id}")
                        except Exception as e:
                            console.print(f"  [red]Failed: {e}[/red]")

                db.resolve_conflict(model_id, "keep_specific", winner.backend_id)
                console.print("[green]Conflict resolved![/green]")

            elif choice == len(record.instances) + 1:
                # Keep all - rename conflicts to permanent names
                console.print("[green]Keeping all versions with backend suffixes[/green]")

                for instance in record.instances:
                    if instance.status == "conflict":
                        try:
                            src_path = Path(instance.path)
                            new_name = f"{model_id}.{instance.backend_id}.gguf"
                            dst_path = src_path.parent / new_name
                            src_path.rename(dst_path)
                            console.print(f"  Renamed to {new_name}")
                        except Exception as e:
                            console.print(f"  [red]Failed to rename: {e}[/red]")

                db.resolve_conflict(model_id, "keep_all")
                console.print("[green]Conflict resolved![/green]")
            else:
                console.print("Skipped.")

        elif action == "resolve-all":
            unresolved = db.get_unresolved()

            if not unresolved:
                console.print("[green]No unresolved conflicts![/green]")
                return

            console.print(f"[yellow]Resolving {len(unresolved)} conflict(s) with strategy: {strategy.value}[/yellow]")

            if dry_run:
                console.print("[dim][DRY RUN] No changes made[/dim]")
                for conflict in unresolved:
                    console.print(f"  Would resolve: {conflict.model_id}")
                return

            resolved_count = 0
            for conflict in unresolved:
                if strategy == ConflictStrategy.KEEP_NEWEST:
                    winner = max(conflict.instances, key=lambda i: i.mtime)
                elif strategy == ConflictStrategy.KEEP_LARGEST:
                    winner = max(conflict.instances, key=lambda i: i.size)
                else:
                    console.print(f"[yellow]Skipping {conflict.model_id}: unsupported strategy[/yellow]")
                    continue

                try:
                    # Hardlink winner to all backends
                    for instance in conflict.instances:
                        if instance.backend_id != winner.backend_id:
                            src_path = Path(winner.path)
                            dst_path = Path(instance.path)
                            if dst_path.exists():
                                dst_path.unlink()
                            import os
                            os.link(src_path, dst_path)

                    db.resolve_conflict(conflict.model_id, f"keep_{strategy.value}", winner.backend_id)
                    resolved_count += 1
                    console.print(f"  [green]Resolved:[/green] {conflict.model_id} -> {winner.backend_id}")
                except Exception as e:
                    console.print(f"  [red]Failed:[/red] {conflict.model_id}: {e}")

            console.print(f"\n[green]Resolved {resolved_count}/{len(unresolved)} conflicts[/green]")

        else:
            console.print(f"[red]Unknown action: {action}[/red]")
            console.print("Valid actions: list, resolve, resolve-all")
            raise typer.Exit(1)

    except FabricError as e:
        console.print(f"[red]Error: {e.message}[/red]")
        raise typer.Exit(1)
    except Exception as e:
        logger.exception("Conflicts command failed")
        console.print(f"[red]Error: {e}[/red]")
        raise typer.Exit(1)


if __name__ == "__main__":
    app()
