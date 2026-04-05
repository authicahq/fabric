"""Tests for ModelFilter in sync engine."""

from __future__ import annotations

from pathlib import Path

from fabric.core.sync import ModelFilter


class TestModelFilter:
    """Tests for ModelFilter class."""

    def test_empty_filter_accepts_all(self) -> None:
        """Test that empty filter accepts all models."""
        filter = ModelFilter()
        assert not filter.should_ignore("any-model")
        assert not filter.should_ignore("model-q4_k_m")

    def test_exact_match_pattern(self) -> None:
        """Test that exact match patterns work."""
        filter = ModelFilter(patterns=["test-model"])
        assert filter.should_ignore("test-model")
        assert not filter.should_ignore("other-model")

    def test_glob_pattern_star(self) -> None:
        """Test glob pattern with star."""
        filter = ModelFilter(patterns=["test-*"])
        assert filter.should_ignore("test-model1")
        assert filter.should_ignore("test-model2")
        assert not filter.should_ignore("other-model")

    def test_glob_pattern_question(self) -> None:
        """Test glob pattern with question mark."""
        filter = ModelFilter(patterns=["model-?"])
        assert filter.should_ignore("model-a")
        assert filter.should_ignore("model-1")
        assert not filter.should_ignore("model-12")

    def test_glob_pattern_brackets(self) -> None:
        """Test glob pattern with brackets."""
        filter = ModelFilter(patterns=["model-[12]"])
        assert filter.should_ignore("model-1")
        assert filter.should_ignore("model-2")
        assert not filter.should_ignore("model-3")

    def test_case_insensitive_pattern(self) -> None:
        """Test case insensitive matching."""
        filter = ModelFilter(patterns=["TEST-MODEL"])
        assert filter.should_ignore("test-model")
        assert filter.should_ignore("TEST-MODEL")
        assert filter.should_ignore("Test-Model")

    def test_multiple_patterns(self) -> None:
        """Test multiple patterns are OR'd together."""
        filter = ModelFilter(patterns=["skip-*", "ignore-*"])
        assert filter.should_ignore("skip-me")
        assert filter.should_ignore("ignore-me")
        assert not filter.should_ignore("keep-me")

    def test_comments_ignored_in_file(self, temp_dir: Path) -> None:
        """Test that comments are ignored in ignore files."""
        ignore_file = temp_dir / ".ggufignore"
        ignore_file.write_text("# This is a comment\npattern1\n# Another comment\npattern2\n")

        filter = ModelFilter()
        filter.load_from_file(ignore_file)

        assert filter.should_ignore("pattern1")
        assert filter.should_ignore("pattern2")
        assert not filter.should_ignore("other")

    def test_empty_lines_ignored_in_file(self, temp_dir: Path) -> None:
        """Test that empty lines are ignored in ignore files."""
        ignore_file = temp_dir / ".ggufignore"
        ignore_file.write_text("pattern1\n\n\npattern2\n")

        filter = ModelFilter()
        filter.load_from_file(ignore_file)

        assert filter.should_ignore("pattern1")
        assert filter.should_ignore("pattern2")

    def test_load_from_nonexistent_file(self) -> None:
        """Test loading from nonexistent file doesn't crash."""
        filter = ModelFilter()
        filter.load_from_file(Path("/nonexistent/ignore"))
        # Should still be empty
        assert filter.patterns == []

    def test_load_from_invalid_file(self, temp_dir: Path) -> None:
        """Test loading from file with invalid content doesn't crash."""
        ignore_file = temp_dir / ".fabricignore"
        # Write with encoding issues or other problems that won't parse
        ignore_file.write_bytes(b"\x00\x01\x02")

        filter = ModelFilter()
        filter.load_from_file(ignore_file)
        # Should still be empty or have partial results


class TestSyncEngineConfig:
    """Tests for SyncEngine configuration."""

    def test_default_config_values(self) -> None:
        """Test default sync configuration values."""
        from fabric.core.models import SyncConfig

        config = SyncConfig()
        assert config.dry_run is False
        assert config.preserve_orphans is False
        assert config.follow_symlinks is False
        assert config.prefer_hardlinks is True
        assert config.add_only is False

    def test_add_only_config(self) -> None:
        """Test add_only flag configuration."""
        from fabric.core.models import SyncConfig

        config = SyncConfig(add_only=True)
        assert config.add_only is True

    def test_preserve_orphans_config(self) -> None:
        """Test preserve_orphans flag configuration."""
        from fabric.core.models import SyncConfig

        config = SyncConfig(preserve_orphans=True)
        assert config.preserve_orphans is True

    def test_dry_run_config(self) -> None:
        """Test dry_run flag configuration."""
        from fabric.core.models import SyncConfig

        config = SyncConfig(dry_run=True)
        assert config.dry_run is True
