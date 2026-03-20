from __future__ import annotations

from pathlib import Path

import pytest

from sortdocs.config import ConfigError, SortdocsConfig, load_config


def test_load_config_returns_defaults_when_file_is_missing() -> None:
    config, config_path = load_config(None)

    assert isinstance(config, SortdocsConfig)
    assert config_path is None
    assert config.cli.dry_run is False
    assert config.cli.recursive is True
    assert config.cli.review_dir == Path(".")
    assert config.cli.library_dir == Path(".")
    assert config.scanner.exclude_patterns == []
    assert config.scanner.ignore_filename == ".sortdocsignore"
    assert config.extraction.max_excerpt_chars == 4000
    assert config.memory.enabled is True
    assert config.memory.filename == ".sortdocs-memory.json"
    assert config.state.enabled is True
    assert config.state.filename == ".sortdocs-state.json"
    assert config.planner.target_path_pattern == "{category}/{subcategory}"


def test_load_config_parses_new_aliases_and_normalizes_values(tmp_path: Path) -> None:
    config_path = tmp_path / "sortdocs.yaml"
    config_path.write_text(
        """
cli:
  recursive_default: true
  review_directory: "Manual Review"
  library_directory: "Sorted Library"
  max_files_per_run: 25

extraction:
  max_excerpt_chars: 2500

openai:
  model: "gpt-4.1-mini"
  temperature: 0.2

planner:
  confidence_threshold: 0.72
  allowed_categories:
    - Finance
    - Travel
    - finance
  folder_pattern: "{year}/{category}"

logging:
  level: debug

memory:
  filename: ".memory.json"
  max_token_hints: 5

scanner:
  exclude:
    - "Projects"
    - "*.heic"
""".strip(),
        encoding="utf-8",
    )

    config, resolved_path = load_config(config_path)

    assert resolved_path == config_path.resolve()
    assert config.cli.recursive is True
    assert config.cli.review_dir == Path("Manual Review")
    assert config.cli.library_dir == Path("Sorted Library")
    assert config.cli.max_files == 25
    assert config.extraction.max_chars == 2500
    assert config.extraction.max_excerpt_chars == 2500
    assert config.openai.temperature == 0.2
    assert config.memory.filename == ".memory.json"
    assert config.memory.max_token_hints == 5
    assert config.scanner.exclude_patterns == ["Projects", "*.heic"]
    assert config.planner.review_confidence_threshold == 0.72
    assert config.planner.allowed_categories == ["finance", "travel"]
    assert config.planner.target_path_pattern == "{year}/{category}"
    assert config.logging.level == "DEBUG"


def test_load_config_rejects_unknown_pattern_placeholders(tmp_path: Path) -> None:
    config_path = tmp_path / "sortdocs.yaml"
    config_path.write_text(
        """
planner:
  folder_pattern: "{month}/{category}"
""".strip(),
        encoding="utf-8",
    )

    with pytest.raises(ConfigError, match="Unsupported target path placeholder"):
        load_config(config_path)


def test_load_config_rejects_invalid_allowed_categories(tmp_path: Path) -> None:
    config_path = tmp_path / "sortdocs.yaml"
    config_path.write_text(
        """
planner:
  allowed_categories:
    - "   "
""".strip(),
        encoding="utf-8",
    )

    with pytest.raises(ConfigError, match="Allowed categories must be non-empty strings"):
        load_config(config_path)


def test_load_config_rejects_invalid_memory_filename(tmp_path: Path) -> None:
    config_path = tmp_path / "sortdocs.yaml"
    config_path.write_text(
        """
memory:
  filename: "../escape.json"
""".strip(),
        encoding="utf-8",
    )

    with pytest.raises(ConfigError, match="Memory filename cannot traverse parent directories"):
        load_config(config_path)


def test_load_config_rejects_invalid_ignore_filename(tmp_path: Path) -> None:
    config_path = tmp_path / "sortdocs.yaml"
    config_path.write_text(
        """
scanner:
  ignore_filename: "../escape.ignore"
""".strip(),
        encoding="utf-8",
    )

    with pytest.raises(ConfigError, match="Ignore filename cannot traverse parent directories"):
        load_config(config_path)
