from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any, Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator


class StringEnum(str, Enum):
    pass


class ExtractedFileType(StringEnum):
    PDF = "pdf"
    TEXT = "text"
    IMAGE = "image"
    DOCX = "docx"
    FALLBACK = "fallback"


class ActionType(StringEnum):
    MOVE = "move"
    RENAME = "rename"
    MOVE_AND_RENAME = "move_and_rename"
    REVIEW = "review"
    SKIP = "skip"


@dataclass
class ExtractedContent:
    file_type: ExtractedFileType
    title_guess: Optional[str]
    plain_text_excerpt: str
    detected_language: Optional[str]
    metadata: dict[str, Any] = field(default_factory=dict)
    extraction_warnings: list[str] = field(default_factory=list)


class ClassificationResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    category: str = Field(min_length=1, max_length=64)
    subcategory: str = Field(min_length=1, max_length=64)
    suggested_path: Optional[str] = Field(default=None, max_length=240)
    suggested_filename: str = Field(min_length=1, max_length=120)
    confidence: float = Field(ge=0.0, le=1.0)
    reason: str = Field(min_length=1, max_length=500)
    tags: list[str] = Field(default_factory=list, max_length=16)
    needs_review: bool = False

    @field_validator("category", "subcategory", "suggested_filename", "reason")
    @classmethod
    def strip_values(cls, value: str) -> str:
        cleaned = value.strip()
        if not cleaned:
            raise ValueError("Value cannot be blank.")
        return cleaned

    @field_validator("suggested_path")
    @classmethod
    def strip_optional_path(cls, value: Optional[str]) -> Optional[str]:
        if value is None:
            return None
        cleaned = value.strip()
        return cleaned or None

    @field_validator("tags")
    @classmethod
    def normalize_tags(cls, value: list[str]) -> list[str]:
        normalized: list[str] = []
        seen: set[str] = set()
        for item in value:
            cleaned = item.strip()
            if not cleaned:
                continue
            lowered = cleaned.lower()
            if lowered in seen:
                continue
            seen.add(lowered)
            normalized.append(lowered[:32])
        return normalized


@dataclass
class PlannedAction:
    source_path: Path
    target_directory: Path
    target_filename: str
    target_path: Path
    action_type: ActionType
    confidence: float
    reason: str
    category: Optional[str] = None
    subcategory: Optional[str] = None
    tags: list[str] = field(default_factory=list)
    suggested_path: Optional[str] = None
    warnings: list[str] = field(default_factory=list)
    approved_roots: tuple[Path, ...] = field(default_factory=tuple)
    cleanup_root: Optional[Path] = None


@dataclass
class ExecutionResult:
    action: PlannedAction
    final_destination: Optional[Path]
    executed: bool
    success: bool
    operation: str
    message: str
    error: Optional[str] = None
    error_code: Optional[str] = None
    guardrail_blocked: bool = False
    source_size_bytes: int = 0


@dataclass
class ExecutionCounts:
    moved: int = 0
    renamed: int = 0
    reviewed: int = 0
    skipped: int = 0
    failed: int = 0


@dataclass
class ExecutionIssue:
    source_path: Path
    code: str
    message: str


@dataclass
class ExecutionMetrics:
    total_actions: int = 0
    dry_run_actions: int = 0
    warnings_total: int = 0
    guardrail_failures: int = 0
    bytes_considered: int = 0
    bytes_written: int = 0


@dataclass
class ExecutionReport:
    dry_run: bool
    copy_mode: bool
    results: list[ExecutionResult] = field(default_factory=list)
    counts: ExecutionCounts = field(default_factory=ExecutionCounts)
    metrics: ExecutionMetrics = field(default_factory=ExecutionMetrics)
    errors: list[ExecutionIssue] = field(default_factory=list)
