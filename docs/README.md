# Fabric

A cross-platform model linker for LLM inference engines that synchronizes GGUF model files across multiple backends using hardlinks or symlinks (no file copying).

## Features

- **Multi-backend support**: llama.cpp, LocalAI, LM Studio, Ollama, TextGen WebUI, GPT4All, KoboldCpp, vLLM, Jan, llama-cpp-python
- **Add-only sync mode**: Add models to backends without deleting on removal
- **Per-backend ignore files**: Exclude models from specific backends using glob patterns
- **Configurable parameters**: context_size, gpu_layers, threads at global and per-backend levels
- **Config preservation**: Never overwrites user settings in existing backend configs
- **Watch mode**: Continuously monitor for new downloads and sync automatically
- **Auto-discovery**: Automatically detect installed backends and their configurations
- **Service mode**: Run as a systemd service for automatic background sync

## Installation

```bash
pip install fabric
```

Or install from source:

```bash
git clone https://github.com/yourrepo/fabric.git
cd fabric
pip install -e .
```

## Quick Start

### Auto-Discovery (Recommended)

The easiest way to get started is to let fabric discover your installed backends:

```bash
fabric discover
```

This scans your system for:
- Installed backend binaries in PATH (lmstudio, llama-server, localai, ollama, etc.)
- Running backend processes and their command lines
- Docker containers running inference servers
- Common installation directories

Generate a config file from discovered backends:

```bash
fabric discover --generate-config --output fabric.yaml
```

The generated config will include:
- Detected models directories
- Running servers and their ports
- Enabled backends ready to sync

### Manual Setup

If you prefer manual configuration:

```bash
fabric config --generate
```

Edit `fabric.yaml` to enable your backends:

```yaml
source_dir: /path/to/models

backends:
  llama_cpp:
    enabled: true
    output_dir: /path/to/llama.cpp/models
    generate_models_ini: true
    
  ollama:
    enabled: true
    output_dir: /ollama/models
    generate_modelfile: true
    
  localai:
    enabled: true
    output_dir: /localai/models
    gpu_layers: -1
```

### Run Synchronization

```bash
fabric sync
```

Or watch for changes:

```bash
fabric watch
```

### Run as a Service

Install as a systemd service for automatic background sync:

```bash
fabric service install
fabric service start
```

## Auto-Discovery Details

The discovery system uses multiple methods to find backends:

| Method | What it finds |
|--------|---------------|
| PATH search | Binaries like `lmstudio`, `ollama`, `llama-server` |
| Process scanning | Running servers, extracts model dirs from command line |
| Docker inspection | LocalAI, Ollama, llama.cpp in containers |
| Port scanning | Detects API ports for running backends |
| Directory search | Standard install and model locations |

Discovery tries common ports for each backend type:
- LM Studio: 1234
- llama.cpp: 8080-8090
- LocalAI: 8080
- Ollama: 11434
- TextGen: 5000
- KoboldCpp: 5001
- GPT4All: 4891
- Jan: 1337
- llama-cpp-python: 8000

## Service Installation

Install as a systemd service for automatic background sync:

```bash
fabric service install
fabric service start
```

Check status:
```bash
fabric service status
```

View logs:
```bash
journalctl -u fabric -f
```

## Configuration Reference

### Global Settings

| Setting | Type | Default | Description |
|---------|------|---------|-------------|
| `source_dir` | path | `/models` | Source directory containing GGUF models |
| `sync.dry_run` | bool | `false` | Show what would be done without making changes |
| `sync.prefer_hardlinks` | bool | `true` | Use hardlinks instead of symlinks |
| `sync.add_only` | bool | `false` | Only add models, never delete on removal |
| `sync.default_context_size` | int | `-1` | Default context size (-1 = unlimited) |
| `sync.default_gpu_layers` | int | `-1` | Default GPU layers (-1 = all) |
| `sync.default_threads` | int | `null` | Default thread count |

### Backend Settings

Each backend supports these common settings:

| Setting | Type | Default | Description |
|---------|------|---------|-------------|
| `enabled` | bool | varies | Enable or disable this backend |
| `output_dir` | path | varies | Where to create model links |
| `ignore_file` | path | `null` | Path to per-backend ignore file |
| `context_size` | int | `-1` | Per-backend context size override |
| `gpu_layers` | int | `-1` | Per-backend GPU layers override |
| `threads` | int | `null` | Per-backend threads override |

### Ignore Files

Ignore files use glob patterns, one per line:

```
# Ignore small models
*small*

# Ignore test models
test-*

# Ignore Q4 quantized models
*-q4_*
```

- Lines starting with `#` are comments
- Matching is case-insensitive
- Use `global_ignore_file` in sync config for global patterns

## Context Size Resolution

The context size is resolved in this priority order:
1. `sync_group(context_size)` parameter
2. Backend config `context_size` setting
3. Global `sync.default_context_size` setting
4. Model metadata `context_length`
5. Backend default (unlimited / -1)

## Backend-Specific Notes

### llama.cpp
- Creates subdirectories for each model
- Generates `models.ini` with model info

### LocalAI
- Uses YAML configuration files
- Creates `model-{name}.yaml` sidecar files

### LM Studio
- Uses `.manifests/` directory structure
- Requires MMND format models

### Ollama
- Generates `Modelfile` for each model
- Uses `manifest.json` structure

### TextGen WebUI
- Creates `models.yaml` configs
- Stores in `user_data/models/`

### GPT4All
- Creates `config.json` for each model
- Flat directory structure

### KoboldCpp
- Generates `.kcpps` configuration files
- Includes context size and GPU settings

### vLLM
- Uses HuggingFace-style config.json
- Requires GGUF support in vLLM

### Jan
- Creates `model.json` metadata
- Uses `models/` subdirectory

### llama-cpp-python
- Direct model file access (no config)
- Requires API server to be running

## Configuration File Locations

Configuration is searched for in order:
1. `./fabric.yaml` (current directory)
2. `./fabric.yml`
3. `~/.config/fabric/config.yaml`
4. `~/.fabric.yaml`
5. `/etc/fabric/config.yaml`

## Environment Variables

Override config with environment variables:

```bash
FABRIC_SOURCE_DIR=/my/models
FABRIC_BACKENDS__LLAMA_CPP__OUTPUT_DIR=/llama
FABRIC_SYNC__ADD_ONLY=true
```

## Development

Run tests:
```bash
pytest tests/
```

Run specific test file:
```bash
pytest tests/integration/test_new_backends.py -v
```

## License

MIT