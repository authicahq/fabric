"""Backend implementations for different LLM inference engines."""

from .base import Backend, BackendResult, LinkResult
from .gpt4all import GPT4AllBackend
from .jan import JanBackend
from .koboldcpp import KoboldCppBackend
from .llama_cpp import LlamaCppBackend
from .llama_cpp_python import LlamaCppPythonBackend
from .lmstudio import LMStudioBackend
from .localai import LocalAIBackend
from .ollama import OllamaBackend
from .textgen import TextGenBackend
from .vllm import vLLMBackend

__all__ = [
    "Backend",
    "BackendResult",
    "GPT4AllBackend",
    "JanBackend",
    "KoboldCppBackend",
    "LMStudioBackend",
    "LinkResult",
    "LlamaCppBackend",
    "LlamaCppPythonBackend",
    "LocalAIBackend",
    "OllamaBackend",
    "TextGenBackend",
    "vLLMBackend",
]
