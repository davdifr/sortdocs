from __future__ import annotations

import fnmatch
import hashlib
import mimetypes
import os
from dataclasses import dataclass, field
from datetime import datetime, timezone
from os import stat_result
from pathlib import Path
from typing import Optional


DEFAULT_SUPPORTED_EXTENSIONS = frozenset(
    {
        ".pdf",
        ".txt",
        ".md",
        ".docx",
        ".jpg",
        ".jpeg",
        ".png",
    }
)
TEMPORARY_SUFFIXES = (".tmp", ".temp", ".swp", ".swo", ".part", ".crdownload", ".download")
TEMPORARY_FILENAMES = {".ds_store"}
TEMPORARY_PREFIXES = ("~$",)
TEXT_LIKE_EXTENSIONS = frozenset({".txt", ".md"})
DEFAULT_EXCLUDED_DIRECTORIES = ("Library", "Review")
DEFAULT_MAX_FILE_SIZE_BYTES = 25 * 1024 * 1024
MAX_BINARY_SAMPLE_BYTES = 8192
PROJECT_ROOT_MARKER_FILENAMES = frozenset(
    {
        "package.json",
        "pyproject.toml",
        "cargo.toml",
        "go.mod",
        "gemfile",
        "composer.json",
        "podfile",
    }
)
PROJECT_ROOT_MARKER_DIRECTORIES = frozenset({".git", ".hg", ".svn"})
PROTECTED_PROJECT_DIRECTORIES = frozenset(
    {
        ".git",
        ".hg",
        ".svn",
        "node_modules",
        ".venv",
        "venv",
        "dist",
        "build",
        "target",
        "vendor",
        "pods",
        "__pycache__",
        ".next",
        ".nuxt",
    }
)
PROJECT_BUNDLE_SUFFIXES = (".xcodeproj", ".xcworkspace")


@dataclass(frozen=True)
class DiscoveredFile:
    absolute_path: Path
    relative_path: Path
    extension: str
    mime_type: Optional[str]
    size_bytes: int
    created_at: Optional[datetime]
    modified_at: datetime
    sha256: Optional[str]
    is_supported: bool
    warnings: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class SkippedDirectory:
    absolute_path: Path
    relative_path: Path
    reason: str


@dataclass(frozen=True)
class DirectoryScanReport:
    discovered_files: list[DiscoveredFile]
    skipped_directories: list[SkippedDirectory] = field(default_factory=list)


@dataclass(frozen=True)
class ScannerOptions:
    recursive: bool = False
    max_files: Optional[int] = None
    compute_sha256: bool = False
    include_unsupported: bool = False
    allow_project_root: bool = False
    max_file_size_bytes: int = DEFAULT_MAX_FILE_SIZE_BYTES
    excluded_directories: tuple[str, ...] = DEFAULT_EXCLUDED_DIRECTORIES
    excluded_patterns: tuple[str, ...] = ()
    supported_extensions: frozenset[str] = field(default_factory=lambda: DEFAULT_SUPPORTED_EXTENSIONS)

    def __post_init__(self) -> None:
        normalized_extensions = frozenset(_normalize_extension(item) for item in self.supported_extensions)
        object.__setattr__(self, "supported_extensions", normalized_extensions)
        normalized_excluded = tuple(item.strip().lower() for item in self.excluded_directories if item.strip())
        object.__setattr__(self, "excluded_directories", normalized_excluded)
        normalized_patterns = tuple(
            item.strip().replace("\\", "/")
            for item in self.excluded_patterns
            if isinstance(item, str) and item.strip()
        )
        object.__setattr__(self, "excluded_patterns", normalized_patterns)
        if self.max_files is not None and self.max_files < 1:
            raise ValueError("max_files must be greater than zero.")
        if self.max_file_size_bytes < 1:
            raise ValueError("max_file_size_bytes must be greater than zero.")


class DirectoryScanner:
    def __init__(self, options: Optional[ScannerOptions] = None) -> None:
        self._options = options or ScannerOptions()

    def scan(self, source_dir: Path) -> list[DiscoveredFile]:
        return self.scan_report(source_dir).discovered_files

    def scan_report(self, source_dir: Path) -> DirectoryScanReport:
        root = _validate_source_dir(source_dir)
        if not self._options.allow_project_root:
            project_markers = detect_project_root_markers(root)
            if project_markers:
                raise ProjectRootDetectedError(root=root, markers=project_markers)
        discovered: list[DiscoveredFile] = []
        skipped_directories: list[SkippedDirectory] = []
        self._scan_directory(
            root=root,
            current_dir=root,
            discovered=discovered,
            skipped_directories=skipped_directories,
        )
        return DirectoryScanReport(
            discovered_files=discovered,
            skipped_directories=skipped_directories,
        )

    def _scan_directory(
        self,
        *,
        root: Path,
        current_dir: Path,
        discovered: list[DiscoveredFile],
        skipped_directories: list[SkippedDirectory],
    ) -> None:
        with os.scandir(current_dir) as iterator:
            entries = sorted(iterator, key=lambda entry: entry.name.lower())

        for entry in entries:
            if self._limit_reached(discovered):
                return

            entry_path = Path(entry.path)
            relative_path = entry_path.relative_to(root)

            if entry.name.startswith("."):
                continue
            if entry.is_symlink():
                continue
            if _looks_temporary(entry.name):
                continue
            matched_pattern = _match_excluded_pattern(relative_path, self._options.excluded_patterns)

            if entry.is_dir(follow_symlinks=False):
                if entry.name.lower() in self._options.excluded_directories:
                    continue
                if matched_pattern is not None:
                    skipped_directories.append(
                        SkippedDirectory(
                            absolute_path=entry_path.resolve(),
                            relative_path=relative_path,
                            reason=f"Excluded by ignore pattern: {matched_pattern}",
                        )
                    )
                    continue
                protected_reason = detect_protected_subtree_reason(entry_path)
                if protected_reason is not None:
                    skipped_directories.append(
                        SkippedDirectory(
                            absolute_path=entry_path.resolve(),
                            relative_path=relative_path,
                            reason=protected_reason,
                        )
                    )
                    continue
                if self._options.recursive:
                    self._scan_directory(
                        root=root,
                        current_dir=entry_path,
                        discovered=discovered,
                        skipped_directories=skipped_directories,
                    )
                continue

            if not entry.is_file(follow_symlinks=False):
                continue
            if matched_pattern is not None:
                continue

            stat_info = entry.stat(follow_symlinks=False)
            discovered_file = self._build_discovered_file(
                absolute_path=entry_path.resolve(),
                relative_path=relative_path,
                stat_info=stat_info,
            )

            if not discovered_file.is_supported and not self._options.include_unsupported:
                continue

            discovered.append(discovered_file)

    def _build_discovered_file(
        self,
        *,
        absolute_path: Path,
        relative_path: Path,
        stat_info: stat_result,
    ) -> DiscoveredFile:
        extension = absolute_path.suffix.lower()
        mime_type = mimetypes.guess_type(absolute_path.name)[0]
        warnings: list[str] = []
        is_supported = extension in self._options.supported_extensions

        if stat_info.st_size > self._options.max_file_size_bytes:
            is_supported = False
            warnings.append("File exceeds the safe size limit and was skipped to avoid heavy processing.")

        if extension in TEXT_LIKE_EXTENSIONS and _is_probably_binary(absolute_path):
            is_supported = False
            warnings.append("Text-like file appears binary and was marked unsupported for safety.")
        elif not is_supported and _is_probably_binary(absolute_path):
            warnings.append("Unsupported binary file detected.")
        elif not is_supported:
            warnings.append("Unsupported file type detected.")

        sha256 = _compute_sha256(absolute_path) if self._options.compute_sha256 else None

        return DiscoveredFile(
            absolute_path=absolute_path,
            relative_path=relative_path,
            extension=extension,
            mime_type=mime_type,
            size_bytes=stat_info.st_size,
            created_at=_extract_created_at(stat_info),
            modified_at=datetime.fromtimestamp(stat_info.st_mtime, tz=timezone.utc),
            sha256=sha256,
            is_supported=is_supported,
            warnings=warnings,
        )

    def _limit_reached(self, discovered: list[DiscoveredFile]) -> bool:
        return self._options.max_files is not None and len(discovered) >= self._options.max_files


def discover_files(source_dir: Path, options: Optional[ScannerOptions] = None) -> list[DiscoveredFile]:
    return DirectoryScanner(options=options).scan(source_dir)


class ProjectRootDetectedError(ValueError):
    def __init__(self, *, root: Path, markers: list[str]) -> None:
        markers_label = ", ".join(markers)
        super().__init__(
            f"Refusing to scan project-like root {root}. "
            f"Detected project markers: {markers_label}. "
            f"Use --allow-project-root if you really want to continue."
        )
        self.root = root
        self.markers = markers


def _validate_source_dir(source_dir: Path) -> Path:
    resolved = source_dir.expanduser().resolve()
    if not resolved.exists():
        raise ValueError(f"Source directory does not exist: {resolved}")
    if not resolved.is_dir():
        raise ValueError(f"Source path is not a directory: {resolved}")
    return resolved


def detect_project_root_markers(path: Path) -> list[str]:
    markers: list[str] = []
    try:
        entries = list(path.iterdir())
    except OSError:
        return markers

    for entry in entries:
        name_lower = entry.name.lower()
        if name_lower in PROJECT_ROOT_MARKER_DIRECTORIES and entry.is_dir():
            markers.append(entry.name)
        elif name_lower in PROJECT_ROOT_MARKER_FILENAMES and entry.exists():
            markers.append(entry.name)
        elif entry.name.endswith(PROJECT_BUNDLE_SUFFIXES):
            markers.append(entry.name)

    return sorted(set(markers), key=str.lower)


def detect_protected_subtree_reason(path: Path) -> Optional[str]:
    name_lower = path.name.lower()
    if name_lower in PROTECTED_PROJECT_DIRECTORIES:
        return f"Protected project/build directory '{path.name}' was skipped."

    markers = detect_project_root_markers(path)
    if markers:
        return (
            "Directory looks like a software project and was skipped "
            f"(markers: {', '.join(markers)})."
        )
    return None


def _normalize_extension(extension: str) -> str:
    if not extension:
        return ""
    return extension.lower() if extension.startswith(".") else f".{extension.lower()}"


def _match_excluded_pattern(relative_path: Path, patterns: tuple[str, ...]) -> Optional[str]:
    if not patterns:
        return None

    relative_label = relative_path.as_posix().strip("/")
    path_parts = tuple(part for part in relative_path.parts if part not in {"", "."})
    name = relative_path.name

    for pattern in patterns:
        normalized = pattern.strip().replace("\\", "/").strip("/")
        if not normalized:
            continue

        if any(token in normalized for token in "*?[]"):
            if fnmatch.fnmatch(relative_label, normalized) or fnmatch.fnmatch(name, normalized):
                return pattern
            continue

        if "/" in normalized:
            if relative_label == normalized or relative_label.startswith(f"{normalized}/"):
                return pattern
            continue

        if normalized == name or normalized in path_parts:
            return pattern

    return None


def _looks_temporary(filename: str) -> bool:
    lower_name = filename.lower()
    if lower_name in TEMPORARY_FILENAMES:
        return True
    if lower_name.endswith(TEMPORARY_SUFFIXES):
        return True
    return any(filename.startswith(prefix) for prefix in TEMPORARY_PREFIXES)


def _extract_created_at(stat_info: stat_result) -> Optional[datetime]:
    birth_time = getattr(stat_info, "st_birthtime", None)
    if birth_time is None:
        return None
    return datetime.fromtimestamp(birth_time, tz=timezone.utc)


def _compute_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _is_probably_binary(path: Path) -> bool:
    try:
        with path.open("rb") as handle:
            sample = handle.read(MAX_BINARY_SAMPLE_BYTES)
    except OSError:
        return False

    if not sample:
        return False
    if b"\x00" in sample:
        return True

    text_bytes = bytes(range(32, 127)) + b"\n\r\t\b\f"
    non_text_count = sum(byte not in text_bytes for byte in sample)
    return (non_text_count / len(sample)) > 0.30
