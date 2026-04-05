# Backend Configuration Guide

This guide explains how to configure each supported backend.

## llama.cpp

```yaml
backends:
  llama_cpp:
    enabled: true
    output_dir: /path/to/models
    generate_models_ini: true
    use_subdirs: true
    context_size: 4096
    gpu_layers: 32
    threads: 8
```

- `generate_models_ini`: Generate models.ini file with model list
- `use_subdirs`: Create subdirectory for each model

## LocalAI

```yaml
backends:
  localai:
    enabled: true
    output_dir: /localai/models
    generate_yaml: true
    gpu_layers: -1
    mmap: true
    f16: true
    context_size: 4096
```

- `gpu_layers`: Number of layers to offload to GPU (-1 = all)
- `mmap`: Use memory mapping for model loading
- `f16`: Use float16 precision

## LM Studio

```yaml
backends:
  lmstudio:
    enabled: true
    output_dir: /lmstudio/models
    generate_manifests: true
```

## Ollama

```yaml
backends:
  ollama:
    enabled: true
    output_dir: /ollama/models
    generate_modelfile: true
    context_size: 4096
    gpu_layers: 32
```

- `generate_modelfile`: Generate Ollama Modelfile with parameters

## TextGen WebUI (oobabooga)

```yaml
backends:
  textgen:
    enabled: true
    output_dir: /textgen/models
    generate_settings_yaml: true
    generate_model_configs: true
    context_size: 4096
    gpu_layers: 32
```

## GPT4All

```yaml
backends:
  gpt4all:
    enabled: true
    output_dir: /gpt4all/models
    generate_config: true
    gpu_layers: -1
    context_size: 4096
```

## KoboldCpp

```yaml
backends:
  koboldcpp:
    enabled: true
    output_dir: /koboldcpp/models
    generate_kcpps: true
    context_size: 4096
    gpu_layers: 32
    threads: 8
```

- `generate_kcpps`: Generate .kcpps configuration files

## vLLM

```yaml
backends:
  vllm:
    enabled: true
    output_dir: /vllm/models
    generate_config: true
    trust_remote_code: true
    context_size: 4096
    gpu_layers: -1
```

- `trust_remote_code`: Allow custom model code execution

## Jan

```yaml
backends:
  jan:
    enabled: true
    output_dir: /jan/models
    generate_metadata: true
    context_size: 4096
```

- `generate_metadata`: Generate model.json metadata files

## llama-cpp-python

```yaml
backends:
  llama_cpp_python:
    enabled: true
    output_dir: /lcpp/models
    server_port: 8000
    server_host: 0.0.0.0
    gpu_layers: -1
    context_size: 4096
    threads: 8
```

- This backend creates symlinks to model files for the Python API server
- No configuration files are generated (server reads model files directly)

## Ignoring Models

Create a `.fabricignore` file in your source directory:

```
# Ignore all small models
*small*

# Ignore test models
test-*

# Ignore Q4 quantized models
*-q4_*
```

Or configure per-backend ignore files:

```yaml
backends:
  ollama:
    ignore_file: /path/to/ollama.ignore
```

## Add-Only Mode

To add models to backends without deleting when removed from source:

```yaml
sync:
  add_only: true
```

This is useful when you want to keep models in some backends even if they're removed from your source directory.