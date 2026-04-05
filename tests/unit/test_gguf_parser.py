"""Tests for GGUF parser."""

from __future__ import annotations

from fabric.core.models import GGUFMetadata


class TestGGUFMetadata:
    """Tests for GGUFMetadata class."""

    def test_default_values(self) -> None:
        """Test GGUFMetadata default values."""
        metadata = GGUFMetadata()
        assert metadata.architecture is None
        assert metadata.name is None
        assert metadata.context_length is None
        assert metadata.quantization is None
        assert metadata.vocab_size is None
        assert metadata.num_hidden_layers is None
        assert metadata.chat_template is None
        assert metadata.stop_tokens == []

    def test_constructor_with_values(self) -> None:
        """Test GGUFMetadata constructor with values."""
        metadata = GGUFMetadata(
            architecture="llama",
            name="test-model",
            context_length=4096,
            quantization=7,
            vocab_size=32000,
            num_hidden_layers=32,
            chat_template="{{ bos_token }}{% for message in messages }}...",
            stop_tokens=["<|endoftext|>"],
        )
        assert metadata.architecture == "llama"
        assert metadata.name == "test-model"
        assert metadata.context_length == 4096
        assert metadata.quantization == 7
        assert metadata.vocab_size == 32000
        assert metadata.num_hidden_layers == 32
        assert metadata.chat_template == "{{ bos_token }}{% for message in messages }}..."
        assert metadata.stop_tokens == ["<|endoftext|>"]

    def test_to_dict(self) -> None:
        """Test converting GGUFMetadata to dictionary."""
        metadata = GGUFMetadata(
            architecture="llama",
            name="test-model",
            context_length=4096,
            quantization=7,
            vocab_size=32000,
            num_hidden_layers=32,
            chat_template="{{ bos_token }}",
            stop_tokens=["<|endoftext|>"],
        )
        d = metadata.to_dict()
        assert d["architecture"] == "llama"
        assert d["name"] == "test-model"
        assert d["context_length"] == 4096
        assert d["quantization"] == 7
        assert d["vocab_size"] == 32000
        assert d["num_hidden_layers"] == 32
        assert d["chat_template"] == "{{ bos_token }}"
        assert d["stop_tokens"] == ["<|endoftext|>"]

    def test_to_dict_empty(self) -> None:
        """Test converting empty GGUFMetadata to dictionary."""
        metadata = GGUFMetadata()
        d = metadata.to_dict()
        assert d["architecture"] is None
        assert d["name"] is None
        assert d["context_length"] is None
        assert d["quantization"] is None
        assert d["vocab_size"] is None
        assert d["num_hidden_layers"] is None
        assert d["chat_template"] is None
        assert d["stop_tokens"] == []

    def test_get_backend_default(self) -> None:
        """Test get_backend returns default for empty metadata."""
        metadata = GGUFMetadata()
        backend = metadata.get_backend()
        assert backend == "llama-cpp"

    def test_get_backend_llama(self) -> None:
        """Test get_backend returns llama-cpp for llama architecture."""
        metadata = GGUFMetadata(architecture="llama")
        assert metadata.get_backend() == "llama-cpp"

    def test_get_backend_mistral(self) -> None:
        """Test get_backend returns llama-cpp for mistral architecture."""
        metadata = GGUFMetadata(architecture="mistral")
        assert metadata.get_backend() == "llama-cpp"

    def test_get_backend_unknown(self) -> None:
        """Test get_backend returns default for unknown architecture."""
        metadata = GGUFMetadata(architecture="unknown_arch")
        assert metadata.get_backend() == "llama-cpp"

    def test_repr(self) -> None:
        """Test string representation."""
        metadata = GGUFMetadata(
            architecture="llama",
            name="test-model",
        )
        s = repr(metadata)
        assert "GGUFMetadata" in s
        assert "llama" in s
        assert "test-model" in s
