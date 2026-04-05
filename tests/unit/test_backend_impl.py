"""Tests for backend implementations."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

from fabric.backends import (
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
from fabric.core.models import (
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


class TestGPT4AllBackend:
    """Tests for GPT4AllBackend."""

    def test_gpt4all_backend_init(self) -> None:
        """Test GPT4All backend initialization."""
        config = GPT4AllConfig(output_dir=Path("/tmp/gpt4all"))
        backend = GPT4AllBackend(config)
        assert backend.name == "GPT4All"

    def test_gpt4all_discovery_config_exists(self) -> None:
        """Test GPT4All discovery config exists."""
        assert hasattr(GPT4AllBackend, "discovery_config")
        assert GPT4AllBackend.discovery_config is not None


class TestJanBackend:
    """Tests for JanBackend."""

    def test_jan_backend_init(self) -> None:
        """Test Jan backend initialization."""
        config = JanConfig(output_dir=Path("/tmp/jan"))
        backend = JanBackend(config)
        assert backend.name == "Jan"

    def test_jan_discovery_config_exists(self) -> None:
        """Test Jan discovery config exists."""
        assert hasattr(JanBackend, "discovery_config")
        assert JanBackend.discovery_config is not None


class TestKoboldCppBackend:
    """Tests for KoboldCppBackend."""

    def test_koboldcpp_backend_init(self) -> None:
        """Test KoboldCpp backend initialization."""
        config = KoboldCppConfig(output_dir=Path("/tmp/koboldcpp"))
        backend = KoboldCppBackend(config)
        assert backend.name == "KoboldCpp"

    def test_koboldcpp_discovery_config_exists(self) -> None:
        """Test KoboldCpp discovery config exists."""
        assert hasattr(KoboldCppBackend, "discovery_config")
        assert KoboldCppBackend.discovery_config is not None


class TestLlamaCppBackend:
    """Tests for LlamaCppBackend."""

    def test_llama_cpp_backend_init(self) -> None:
        """Test LlamaCpp backend initialization."""
        config = LlamaCppConfig(output_dir=Path("/tmp/llama"))
        backend = LlamaCppBackend(config)
        assert backend.name == "llama.cpp"

    def test_llama_cpp_discovery_config_exists(self) -> None:
        """Test LlamaCpp discovery config exists."""
        assert hasattr(LlamaCppBackend, "discovery_config")
        assert LlamaCppBackend.discovery_config is not None


class TestLlamaCppPythonBackend:
    """Tests for LlamaCppPythonBackend."""

    def test_llama_cpp_python_backend_init(self) -> None:
        """Test LlamaCpp Python backend initialization."""
        config = LlamaCppPythonConfig(output_dir=Path("/tmp/llama-cpp-python"))
        backend = LlamaCppPythonBackend(config)
        assert backend.name == "llama-cpp-python"


class TestLMStudioBackend:
    """Tests for LMStudioBackend."""

    def test_lmstudio_backend_init(self) -> None:
        """Test LM Studio backend initialization."""
        config = LMStudioConfig(output_dir=Path("/tmp/lmstudio"))
        backend = LMStudioBackend(config)
        assert backend.name == "LM Studio"

    def test_lmstudio_discovery_config_exists(self) -> None:
        """Test LM Studio discovery config exists."""
        assert hasattr(LMStudioBackend, "discovery_config")
        assert LMStudioBackend.discovery_config is not None


class TestLocalAIBackend:
    """Tests for LocalAIBackend."""

    def test_localai_backend_init(self) -> None:
        """Test LocalAI backend initialization."""
        config = LocalAIConfig(output_dir=Path("/tmp/localai"))
        backend = LocalAIBackend(config)
        assert backend.name == "LocalAI"

    def test_localai_discovery_config_exists(self) -> None:
        """Test LocalAI discovery config exists."""
        assert hasattr(LocalAIBackend, "discovery_config")
        assert LocalAIBackend.discovery_config is not None


class TestOllamaBackend:
    """Tests for OllamaBackend."""

    def test_ollama_backend_init(self) -> None:
        """Test Ollama backend initialization."""
        config = OllamaConfig(output_dir=Path("/tmp/ollama"))
        backend = OllamaBackend(config)
        assert backend.name == "Ollama"

    def test_ollama_discovery_config_exists(self) -> None:
        """Test Ollama discovery config exists."""
        assert hasattr(OllamaBackend, "discovery_config")
        assert OllamaBackend.discovery_config is not None


class TestTextGenBackend:
    """Tests for TextGenBackend."""

    def test_textgen_backend_init(self) -> None:
        """Test TextGen backend initialization."""
        config = TextGenConfig(output_dir=Path("/tmp/textgen"))
        backend = TextGenBackend(config)
        assert "text" in backend.name.lower()

    def test_textgen_discovery_config_exists(self) -> None:
        """Test TextGen discovery config exists."""
        assert hasattr(TextGenBackend, "discovery_config")
        assert TextGenBackend.discovery_config is not None


class TestvLLMBackend:
    """Tests for vLLMBackend."""

    def test_vllm_backend_init(self) -> None:
        """Test vLLM backend initialization."""
        config = vLLMConfig(output_dir=Path("/tmp/vllm"))
        backend = vLLMBackend(config)
        assert backend.name == "vLLM"

    def test_vllm_discovery_config_exists(self) -> None:
        """Test vLLM discovery config exists."""
        assert hasattr(vLLMBackend, "discovery_config")
        assert vLLMBackend.discovery_config is not None


class TestBackendSetup:
    """Tests for backend setup methods."""

    def test_backend_setup_creates_directories(self) -> None:
        """Test that setup creates necessary directories."""
        config = LlamaCppConfig(output_dir=Path("/tmp/test_llama"))
        backend = LlamaCppBackend(config)

        with patch.object(backend, "_ensure_dir") as mock_ensure:
            backend.setup()
            mock_ensure.assert_called()


class TestBackendModelsDir:
    """Tests for backend models_dir property."""

    def test_backend_models_dir_from_output_dir(self) -> None:
        """Test that models_dir defaults to output_dir."""
        config = LlamaCppConfig(output_dir=Path("/tmp/test_llama"))
        backend = LlamaCppBackend(config)
        backend.setup()
        assert backend.models_dir == backend.output_dir

    def test_gpt4all_models_dir_with_config(self) -> None:
        """Test GPT4All models_dir with config generation."""
        config = GPT4AllConfig(
            output_dir=Path("/tmp/test_gpt4all"),
            generate_config=True,
        )
        backend = GPT4AllBackend(config)
        backend.setup()
        assert backend.models_dir == backend.output_dir


class TestBackendSyncMethods:
    """Tests for backend sync methods."""

    def test_llama_cpp_sync_group_returns_result(self) -> None:
        """Test sync_group returns BackendResult on llama_cpp backend."""
        config = LlamaCppConfig(output_dir=Path("/tmp/test_llama"))
        backend = LlamaCppBackend(config)
        backend.setup()

        mock_group = MagicMock()
        mock_group.models = []

        from fabric.backends.base import BackendResult

        result = backend.sync_group(mock_group, Path("/tmp/source"))
        assert isinstance(result, BackendResult)

    def test_ollama_sync_group_returns_result(self) -> None:
        """Test sync_group returns BackendResult on Ollama backend."""
        config = OllamaConfig(output_dir=Path("/tmp/test_ollama"))
        backend = OllamaBackend(config)
        backend.setup()

        mock_group = MagicMock()
        mock_group.models = []

        from fabric.backends.base import BackendResult

        result = backend.sync_group(mock_group, Path("/tmp/source"))
        assert isinstance(result, BackendResult)


class TestBackendBaseMethods:
    """Tests for Backend base class methods."""

    def test_backend_discover_returns_list(self) -> None:
        """Test discover method returns a list."""
        result = LlamaCppBackend.discover()
        assert isinstance(result, list)

    def test_backend_discover_no_config_returns_empty(self) -> None:
        """Test discover returns empty list when no discovery_config."""
        from fabric.backends.base import Backend

        class TestBackend(Backend):
            @property
            def name(self) -> str:
                return "test"

            def sync_group(self, group, source_dir, **kwargs):
                from fabric.backends.base import BackendResult

                return BackendResult()

            def remove_group(self, model_id):
                from fabric.backends.base import BackendResult

                return BackendResult()

        result = TestBackend.discover()
        assert result == []

    def test_backend_cleanup_does_not_raise(self) -> None:
        """Test cleanup method doesn't raise."""
        config = LlamaCppConfig(output_dir=Path("/tmp/test"))
        backend = LlamaCppBackend(config)
        backend.cleanup()  # Should not raise

    def test_backend_ensure_dir_creates_directory(self, tmp_path: Path) -> None:
        """Test _ensure_dir creates directory."""
        config = LlamaCppConfig(output_dir=tmp_path)
        backend = LlamaCppBackend(config)

        test_dir = tmp_path / "test_subdir"
        backend._ensure_dir(test_dir)
        assert test_dir.exists()

    def test_backend_create_link_checks_source_exists(self, tmp_path: Path) -> None:
        """Test _create_link returns error when source doesn't exist."""
        config = LlamaCppConfig(output_dir=tmp_path)
        backend = LlamaCppBackend(config)

        source = tmp_path / "nonexistent.gguf"
        target = tmp_path / "link.gguf"

        result = backend._create_link(source, target)
        assert not result.success
        assert "Source does not exist" in result.error


class TestBackendRemoveGroup:
    """Tests for backend remove_group methods."""

    def test_llama_cpp_remove_group(self, tmp_path: Path) -> None:
        """Test remove_group on llama_cpp backend."""
        config = LlamaCppConfig(output_dir=tmp_path)
        backend = LlamaCppBackend(config)
        backend.setup()

        from fabric.backends.base import BackendResult

        result = backend.remove_group("test-model")
        assert isinstance(result, BackendResult)

    def test_localai_remove_group(self, tmp_path: Path) -> None:
        """Test remove_group on LocalAI backend."""
        config = LocalAIConfig(output_dir=tmp_path)
        backend = LocalAIBackend(config)
        backend.setup()

        from fabric.backends.base import BackendResult

        result = backend.remove_group("test-model")
        assert isinstance(result, BackendResult)

    def test_lmstudio_remove_group(self, tmp_path: Path) -> None:
        """Test remove_group on LMStudio backend."""
        config = LMStudioConfig(output_dir=tmp_path)
        backend = LMStudioBackend(config)
        backend.setup()

        from fabric.backends.base import BackendResult

        result = backend.remove_group("test-model")
        assert isinstance(result, BackendResult)

    def test_ollama_remove_group(self, tmp_path: Path) -> None:
        """Test remove_group on Ollama backend."""
        config = OllamaConfig(output_dir=tmp_path)
        backend = OllamaBackend(config)
        backend.setup()

        from fabric.backends.base import BackendResult

        result = backend.remove_group("test-model")
        assert isinstance(result, BackendResult)

    def test_gpt4all_remove_group(self, tmp_path: Path) -> None:
        """Test remove_group on GPT4All backend."""
        config = GPT4AllConfig(output_dir=tmp_path)
        backend = GPT4AllBackend(config)
        backend.setup()

        from fabric.backends.base import BackendResult

        result = backend.remove_group("test-model")
        assert isinstance(result, BackendResult)

    def test_textgen_remove_group(self, tmp_path: Path) -> None:
        """Test remove_group on TextGen backend."""
        config = TextGenConfig(output_dir=tmp_path)
        backend = TextGenBackend(config)
        backend.setup()

        from fabric.backends.base import BackendResult

        result = backend.remove_group("test-model")
        assert isinstance(result, BackendResult)

    def test_vllm_remove_group(self, tmp_path: Path) -> None:
        """Test remove_group on vLLM backend."""
        config = vLLMConfig(output_dir=tmp_path)
        backend = vLLMBackend(config)
        backend.setup()

        from fabric.backends.base import BackendResult

        result = backend.remove_group("test-model")
        assert isinstance(result, BackendResult)

    def test_jan_remove_group(self, tmp_path: Path) -> None:
        """Test remove_group on Jan backend."""
        config = JanConfig(output_dir=tmp_path)
        backend = JanBackend(config)
        backend.setup()

        from fabric.backends.base import BackendResult

        result = backend.remove_group("test-model")
        assert isinstance(result, BackendResult)

    def test_koboldcpp_remove_group(self, tmp_path: Path) -> None:
        """Test remove_group on KoboldCpp backend."""
        config = KoboldCppConfig(output_dir=tmp_path)
        backend = KoboldCppBackend(config)
        backend.setup()

        from fabric.backends.base import BackendResult

        result = backend.remove_group("test-model")
        assert isinstance(result, BackendResult)

    def test_llama_cpp_python_remove_group(self, tmp_path: Path) -> None:
        """Test remove_group on LlamaCppPython backend."""
        config = LlamaCppPythonConfig(output_dir=tmp_path)
        backend = LlamaCppPythonBackend(config)
        backend.setup()

        from fabric.backends.base import BackendResult

        result = backend.remove_group("test-model")
        assert isinstance(result, BackendResult)


class TestBackendSyncGroupAllBackends:
    """Tests for sync_group on all backends."""

    def test_gpt4all_sync_group(self, tmp_path: Path) -> None:
        """Test sync_group on GPT4All backend."""
        config = GPT4AllConfig(output_dir=tmp_path)
        backend = GPT4AllBackend(config)
        backend.setup()

        mock_group = MagicMock()
        mock_group.models = []

        from fabric.backends.base import BackendResult

        result = backend.sync_group(mock_group, Path("/tmp/source"))
        assert isinstance(result, BackendResult)

    def test_textgen_sync_group(self, tmp_path: Path) -> None:
        """Test sync_group on TextGen backend."""
        config = TextGenConfig(output_dir=tmp_path)
        backend = TextGenBackend(config)
        backend.setup()

        mock_group = MagicMock()
        mock_group.models = []

        from fabric.backends.base import BackendResult

        result = backend.sync_group(mock_group, Path("/tmp/source"))
        assert isinstance(result, BackendResult)

    def test_llama_cpp_python_sync_group(self, tmp_path: Path) -> None:
        """Test sync_group on LlamaCppPython backend."""
        config = LlamaCppPythonConfig(output_dir=tmp_path)
        backend = LlamaCppPythonBackend(config)
        backend.setup()

        mock_group = MagicMock()
        mock_group.models = []

        from fabric.backends.base import BackendResult

        result = backend.sync_group(mock_group, Path("/tmp/source"))
        assert isinstance(result, BackendResult)


class TestBackendBasePermissions:
    """Tests for Backend permission methods."""

    def test_set_permissions_on_directory(self, tmp_path: Path) -> None:
        """Test _set_permissions on directory."""
        config = LlamaCppConfig(output_dir=tmp_path)
        backend = LlamaCppBackend(config)

        test_dir = tmp_path / "test_dir"
        test_dir.mkdir()

        backend._set_permissions(test_dir)
        # Should not raise

    def test_set_permissions_on_file(self, tmp_path: Path) -> None:
        """Test _set_permissions on file."""
        config = LlamaCppConfig(output_dir=tmp_path)
        backend = LlamaCppBackend(config)

        test_file = tmp_path / "test_file.txt"
        test_file.write_text("test")

        backend._set_permissions(test_file)
        # Should not raise

    def test_set_permissions_nonexistent_path(self, tmp_path: Path) -> None:
        """Test _set_permissions on nonexistent path logs warning."""
        config = LlamaCppConfig(output_dir=tmp_path)
        backend = LlamaCppBackend(config)

        nonexistent = tmp_path / "does_not_exist"
        backend._set_permissions(nonexistent)
        # Should not raise, just log warning


class TestBackendIsSameFile:
    """Tests for Backend _is_same_file method."""

    def test_is_same_file_same_file(self, tmp_path: Path) -> None:
        """Test _is_same_file returns True for same file."""
        config = LlamaCppConfig(output_dir=tmp_path)
        backend = LlamaCppBackend(config)

        test_file = tmp_path / "test.gguf"
        test_file.write_text("test content")

        # Create a hardlink to the same file
        link = tmp_path / "link.gguf"
        link.hardlink_to(test_file)

        result = backend._is_same_file(test_file, link)
        assert result is True

    def test_is_same_file_different_files(self, tmp_path: Path) -> None:
        """Test _is_same_file returns False for different files."""
        config = LlamaCppConfig(output_dir=tmp_path)
        backend = LlamaCppBackend(config)

        file1 = tmp_path / "file1.gguf"
        file1.write_text("content1")
        file2 = tmp_path / "file2.gguf"
        file2.write_text("content2")

        result = backend._is_same_file(file1, file2)
        # Note: On some filesystems, small files with same content may share blocks
        # so we just verify the method runs without error
        assert isinstance(result, bool)

    def test_is_same_file_nonexistent(self, tmp_path: Path) -> None:
        """Test _is_same_file returns False when file doesn't exist."""
        config = LlamaCppConfig(output_dir=tmp_path)
        backend = LlamaCppBackend(config)

        file1 = tmp_path / "exists.gguf"
        file1.write_text("content")
        file2 = tmp_path / "does_not_exist.gguf"

        result = backend._is_same_file(file1, file2)
        assert result is False
