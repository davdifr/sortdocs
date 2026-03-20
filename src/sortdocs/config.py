from __future__ import annotations

from string import Formatter
from pathlib import Path
from typing import Optional

import yaml
from pydantic import AliasChoices, BaseModel, ConfigDict, Field, ValidationError, field_validator

from sortdocs.utils import sanitize_path_component


DEFAULT_CONFIG_FILENAMES = ("sortdocs.yaml", ".sortdocs.yaml")
VALID_LOG_LEVELS = {"CRITICAL", "ERROR", "WARNING", "INFO", "DEBUG"}
ALLOWED_PATTERN_FIELDS = {"category", "subcategory", "year"}


class ConfigError(RuntimeError):
    pass


class CLISettings(BaseModel):
    model_config = ConfigDict(extra="forbid")

    dry_run: bool = False
    recursive: bool = Field(
        default=True,
        validation_alias=AliasChoices("recursive", "recursive_default"),
    )
    review_dir: Path = Field(
        default=Path("."),
        validation_alias=AliasChoices("review_dir", "review_directory"),
    )
    library_dir: Path = Field(
        default=Path("."),
        validation_alias=AliasChoices("library_dir", "library_directory"),
    )
    max_files: Optional[int] = Field(
        default=None,
        ge=1,
        validation_alias=AliasChoices("max_files", "max_files_per_run"),
    )

    @field_validator("review_dir", "library_dir", mode="before")
    @classmethod
    def validate_directory_value(cls, value: object) -> Path:
        if isinstance(value, Path):
            return value
        if not isinstance(value, str) or not value.strip():
            raise ValueError("Directory values must be non-empty strings.")
        return Path(value.strip())

    @property
    def recursive_default(self) -> bool:
        return self.recursive

    @property
    def max_files_per_run(self) -> Optional[int]:
        return self.max_files


class LoggingSettings(BaseModel):
    model_config = ConfigDict(extra="forbid")

    level: str = "INFO"

    @field_validator("level")
    @classmethod
    def normalize_level(cls, value: str) -> str:
        normalized = value.strip().upper()
        if normalized not in VALID_LOG_LEVELS:
            supported = ", ".join(sorted(VALID_LOG_LEVELS))
            raise ValueError(f"Unsupported logging level: {value!r}. Expected one of: {supported}.")
        return normalized


class ExtractionSettings(BaseModel):
    model_config = ConfigDict(extra="forbid")

    max_chars: int = Field(
        default=4000,
        ge=128,
        le=100_000,
        validation_alias=AliasChoices("max_chars", "max_excerpt_chars"),
    )

    @property
    def max_excerpt_chars(self) -> int:
        return self.max_chars


class ScannerSettings(BaseModel):
    model_config = ConfigDict(extra="forbid")

    exclude_patterns: list[str] = Field(
        default_factory=list,
        validation_alias=AliasChoices("exclude_patterns", "exclude"),
    )
    ignore_filename: str = ".sortdocsignore"

    @field_validator("exclude_patterns")
    @classmethod
    def normalize_exclude_patterns(cls, value: list[str]) -> list[str]:
        normalized: list[str] = []
        seen: set[str] = set()

        for raw_item in value:
            if not isinstance(raw_item, str):
                raise ValueError("Exclude patterns must be strings.")
            cleaned = raw_item.strip().replace("\\", "/")
            if not cleaned:
                raise ValueError("Exclude patterns cannot be blank.")
            if cleaned in seen:
                continue
            seen.add(cleaned)
            normalized.append(cleaned)

        return normalized

    @field_validator("ignore_filename")
    @classmethod
    def validate_ignore_filename(cls, value: str) -> str:
        filename = value.strip()
        if not filename:
            raise ValueError("Ignore filename cannot be blank.")
        path = Path(filename)
        if path.is_absolute():
            raise ValueError("Ignore filename must be relative.")
        if any(part == ".." for part in path.parts):
            raise ValueError("Ignore filename cannot traverse parent directories.")
        return filename


class OpenAISettings(BaseModel):
    model_config = ConfigDict(extra="forbid")

    model: str = "gpt-4.1-mini"
    temperature: Optional[float] = Field(default=None, ge=0.0, le=2.0)
    timeout_seconds: float = Field(default=30.0, gt=0.0, le=600.0)
    max_retries: int = Field(default=2, ge=0, le=10)
    backoff_base_seconds: float = Field(default=0.5, gt=0.0, le=60.0)
    backoff_max_seconds: float = Field(default=8.0, gt=0.0, le=300.0)
    max_output_tokens: int = Field(default=300, ge=64, le=4096)


class MemorySettings(BaseModel):
    model_config = ConfigDict(extra="forbid")

    enabled: bool = True
    filename: str = ".sortdocs-memory.json"
    max_token_hints: int = Field(default=8, ge=1, le=50)
    max_path_examples: int = Field(default=12, ge=1, le=100)
    max_examples_per_hint: int = Field(default=3, ge=1, le=10)

    @field_validator("filename")
    @classmethod
    def validate_filename(cls, value: str) -> str:
        filename = value.strip()
        if not filename:
            raise ValueError("Memory filename cannot be blank.")
        path = Path(filename)
        if path.is_absolute():
            raise ValueError("Memory filename must be relative.")
        if any(part == ".." for part in path.parts):
            raise ValueError("Memory filename cannot traverse parent directories.")
        return filename


class StateSettings(BaseModel):
    model_config = ConfigDict(extra="forbid")

    enabled: bool = True
    filename: str = ".sortdocs-state.json"

    @field_validator("filename")
    @classmethod
    def validate_filename(cls, value: str) -> str:
        filename = value.strip()
        if not filename:
            raise ValueError("State filename cannot be blank.")
        path = Path(filename)
        if path.is_absolute():
            raise ValueError("State filename must be relative.")
        if any(part == ".." for part in path.parts):
            raise ValueError("State filename cannot traverse parent directories.")
        return filename


class PlannerSettings(BaseModel):
    model_config = ConfigDict(extra="forbid")

    review_confidence_threshold: float = Field(
        default=0.65,
        ge=0.0,
        le=1.0,
        validation_alias=AliasChoices("review_confidence_threshold", "confidence_threshold"),
    )
    allowed_categories: Optional[list[str]] = None
    target_path_pattern: str = Field(
        default="{category}/{subcategory}",
        validation_alias=AliasChoices("target_path_pattern", "folder_pattern"),
    )
    max_filename_length: int = Field(default=120, ge=24, le=255)

    @field_validator("allowed_categories")
    @classmethod
    def normalize_allowed_categories(cls, value: Optional[list[str]]) -> Optional[list[str]]:
        if value is None:
            return None

        normalized: list[str] = []
        seen: set[str] = set()

        for raw_item in value:
            if not isinstance(raw_item, str) or not raw_item.strip():
                raise ValueError("Allowed categories must be non-empty strings.")

            cleaned = sanitize_path_component(raw_item, default="", lowercase=True)
            if not cleaned:
                raise ValueError(f"Invalid category value: {raw_item!r}")
            if cleaned in seen:
                continue
            seen.add(cleaned)
            normalized.append(cleaned)

        return normalized or None

    @field_validator("target_path_pattern")
    @classmethod
    def validate_target_path_pattern(cls, value: str) -> str:
        pattern = value.strip().replace("\\", "/")
        if not pattern:
            raise ValueError("Target path pattern cannot be empty.")
        if pattern.startswith("/") or pattern.startswith("~"):
            raise ValueError("Target path pattern must be relative.")
        if "//" in pattern:
            raise ValueError("Target path pattern cannot contain empty path segments.")

        segments = pattern.split("/")
        if any(not segment.strip() for segment in segments):
            raise ValueError("Target path pattern cannot contain blank path segments.")
        if any(segment == ".." for segment in segments):
            raise ValueError("Target path pattern cannot traverse parent directories.")

        formatter = Formatter()
        for _, field_name, format_spec, conversion in formatter.parse(pattern):
            if not field_name:
                continue
            if conversion or format_spec:
                raise ValueError("Target path pattern does not support format conversions or specs.")
            if field_name not in ALLOWED_PATTERN_FIELDS:
                supported = ", ".join(sorted(ALLOWED_PATTERN_FIELDS))
                raise ValueError(
                    f"Unsupported target path placeholder: {field_name!r}. "
                    f"Expected one of: {supported}."
                )

        return pattern

    @property
    def confidence_threshold(self) -> float:
        return self.review_confidence_threshold

    @property
    def folder_pattern(self) -> str:
        return self.target_path_pattern


class SortdocsConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    cli: CLISettings = CLISettings()
    scanner: ScannerSettings = ScannerSettings()
    extraction: ExtractionSettings = ExtractionSettings()
    openai: OpenAISettings = OpenAISettings()
    memory: MemorySettings = MemorySettings()
    state: StateSettings = StateSettings()
    planner: PlannerSettings = PlannerSettings()
    logging: LoggingSettings = LoggingSettings()


def discover_config_path(base_dir: Optional[Path] = None) -> Optional[Path]:
    search_root = (base_dir or Path.cwd()).expanduser().resolve()
    for filename in DEFAULT_CONFIG_FILENAMES:
        candidate = search_root / filename
        if candidate.exists():
            return candidate.resolve()
    return None


def load_config(
    config_path: Optional[Path] = None,
    *,
    base_dir: Optional[Path] = None,
) -> tuple[SortdocsConfig, Optional[Path]]:
    resolved_path = config_path.expanduser().resolve() if config_path else discover_config_path(base_dir)
    if resolved_path is None:
        return SortdocsConfig(), None
    if not resolved_path.exists():
        raise ConfigError(f"Config file does not exist: {resolved_path}")
    if not resolved_path.is_file():
        raise ConfigError(f"Config path is not a file: {resolved_path}")

    try:
        with resolved_path.open("r", encoding="utf-8") as handle:
            raw_data = yaml.safe_load(handle) or {}
    except OSError as exc:
        raise ConfigError(f"Unable to read config file: {resolved_path}") from exc
    except yaml.YAMLError as exc:
        raise ConfigError(f"Invalid YAML in config file: {resolved_path}") from exc

    if not isinstance(raw_data, dict):
        raise ConfigError("Config file must contain a YAML mapping at the top level.")

    try:
        config = SortdocsConfig.model_validate(raw_data)
    except ValidationError as exc:
        messages = []
        for error in exc.errors():
            location = ".".join(str(part) for part in error.get("loc", ()))
            message = error.get("msg", "Invalid value.")
            messages.append(f"{location}: {message}")
        details = "; ".join(messages) if messages else "Validation failed."
        raise ConfigError(f"Invalid config file: {details}") from exc

    return config, resolved_path
