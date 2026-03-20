from __future__ import annotations

import hashlib
import logging
import re
import unicodedata
from pathlib import Path

from sortdocs.logging_utils import configure_logging as configure_logging

LOGGER = logging.getLogger(__name__)
INVALID_PATH_CHARS = re.compile(r"[^A-Za-z0-9._ -]+")
NORMALIZE_SEPARATORS = re.compile(r"[\s_-]+")


def limit_text(value: str, max_chars: int) -> str:
    if len(value) <= max_chars:
        return value
    return value[: max_chars - 1].rstrip() + "…"


def sanitize_path_component(
    value: str,
    *,
    default: str,
    lowercase: bool = True,
) -> str:
    normalized = unicodedata.normalize("NFKD", value)
    ascii_value = normalized.encode("ascii", "ignore").decode("ascii")
    cleaned = INVALID_PATH_CHARS.sub(" ", ascii_value)
    cleaned = NORMALIZE_SEPARATORS.sub("_", cleaned.strip())
    cleaned = cleaned.strip("._-")
    if lowercase:
        cleaned = cleaned.lower()
    return cleaned or default


def build_output_filename(raw_name: str, extension: str, max_length: int) -> str:
    stem = Path(raw_name).stem
    safe_stem = sanitize_path_component(stem, default="document", lowercase=True)
    max_stem_length = max(1, max_length - len(extension))
    safe_stem = safe_stem[:max_stem_length].rstrip("._-") or "document"
    return f"{safe_stem}{extension.lower()}"


def hash_file(path: Path, algorithm: str = "sha256") -> str:
    digest = hashlib.new(algorithm)
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def is_hidden_path(relative_path: Path) -> bool:
    return any(part.startswith(".") for part in relative_path.parts)


def should_skip_path(relative_path: Path, excluded_directories: tuple[str, ...]) -> bool:
    return any(part in excluded_directories for part in relative_path.parts)


def reserve_unique_path(path: Path, occupied: set[Path]) -> Path:
    if path not in occupied and not path.exists():
        occupied.add(path)
        return path

    counter = 1
    while True:
        candidate = path.with_name(f"{path.stem}__{counter}{path.suffix}")
        if candidate not in occupied and not candidate.exists():
            occupied.add(candidate)
            LOGGER.debug("Resolved name collision for %s -> %s", path, candidate)
            return candidate
        counter += 1


def relativize(path: Path, base: Path) -> str:
    try:
        return str(path.relative_to(base))
    except ValueError:
        return str(path)
