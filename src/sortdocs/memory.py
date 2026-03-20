from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from sortdocs.config import MemorySettings
from sortdocs.models import ActionType, ClassificationResult, PlannedAction


LOGGER = logging.getLogger(__name__)
MEMORY_VERSION = 1
TOKEN_RE = re.compile(r"[a-z0-9]+")
GENERIC_FILENAME_TOKENS = {
    "copy",
    "doc",
    "document",
    "file",
    "final",
    "img",
    "image",
    "new",
    "page",
    "pdf",
    "scan",
    "untitled",
}


@dataclass
class LocalMemoryStore:
    root_dir: Path
    file_path: Path
    config: MemorySettings
    token_targets: dict[str, dict[str, int]] = field(default_factory=dict)
    classification_targets: dict[str, dict[str, int]] = field(default_factory=dict)
    path_examples: dict[str, list[str]] = field(default_factory=dict)
    _dirty: bool = False

    @classmethod
    def load(cls, *, root_dir: Path, config: MemorySettings) -> LocalMemoryStore:
        resolved_root = root_dir.expanduser().resolve()
        file_path = (resolved_root / config.filename).resolve()
        store = cls(
            root_dir=resolved_root,
            file_path=file_path,
            config=config,
        )
        if not config.enabled or not file_path.exists():
            return store

        try:
            payload = json.loads(file_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            LOGGER.warning("Could not read local memory file %s: %s", file_path, exc)
            return store

        if not isinstance(payload, dict) or payload.get("version") != MEMORY_VERSION:
            return store

        store.token_targets = _normalize_nested_counts(payload.get("token_targets"))
        store.classification_targets = _normalize_nested_counts(payload.get("classification_targets"))
        store.path_examples = _normalize_examples(payload.get("path_examples"), max_items=config.max_examples_per_hint)
        return store

    def remember(
        self,
        *,
        classification: ClassificationResult,
        action: PlannedAction,
        source_filename: str,
    ) -> None:
        if not self.config.enabled:
            return
        if action.action_type == ActionType.REVIEW:
            return

        target_path_label = self._relative_target_directory(action.target_directory)
        if not target_path_label:
            return

        classification_key = f"{classification.category}/{classification.subcategory}"
        _increment_nested_count(self.classification_targets, classification_key, target_path_label)

        filename_tokens = tokenize_filename(source_filename)
        for token in filename_tokens:
            _increment_nested_count(self.token_targets, token, target_path_label)

        for tag in classification.tags:
            for token in tokenize_value(tag):
                _increment_nested_count(self.token_targets, token, target_path_label)

        examples = self.path_examples.setdefault(target_path_label, [])
        if source_filename not in examples:
            examples.append(source_filename)
            del examples[self.config.max_examples_per_hint :]

        self._dirty = True

    def save(self) -> Optional[Path]:
        if not self.config.enabled or not self._dirty:
            return None

        payload = {
            "version": MEMORY_VERSION,
            "token_targets": self.token_targets,
            "classification_targets": self.classification_targets,
            "path_examples": self.path_examples,
        }
        self.file_path.parent.mkdir(parents=True, exist_ok=True)
        temp_path = self.file_path.with_name(f".{self.file_path.name}.tmp")
        temp_path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
        temp_path.replace(self.file_path)
        self._dirty = False
        LOGGER.info("Updated local memory file %s", self.file_path)
        return self.file_path

    def build_context_for_file(self, *, original_filename: str) -> dict[str, object]:
        if not self.config.enabled:
            return {}

        token_hints = self._build_token_hints(original_filename)
        path_hints = self._build_top_path_hints()
        if not token_hints and not path_hints:
            return {}

        return {
            "memory_file": self.file_path.name,
            "filename_token_hints": token_hints,
            "known_path_hints": path_hints,
        }

    def _build_token_hints(self, original_filename: str) -> list[dict[str, object]]:
        token_scores: dict[str, int] = {}
        token_matches: dict[str, set[str]] = {}
        tokens = tokenize_filename(original_filename)
        for token in tokens:
            for target_path, count in self.token_targets.get(token, {}).items():
                token_scores[target_path] = token_scores.get(target_path, 0) + count
                token_matches.setdefault(target_path, set()).add(token)

        ranked_paths = sorted(
            token_scores.items(),
            key=lambda item: (-item[1], item[0]),
        )[: self.config.max_token_hints]
        hints: list[dict[str, object]] = []
        for target_path, score in ranked_paths:
            hints.append(
                {
                    "target_path": target_path,
                    "score": score,
                    "matched_tokens": sorted(token_matches.get(target_path, set())),
                    "example_filenames": list(self.path_examples.get(target_path, []))[: self.config.max_examples_per_hint],
                }
            )
        return hints

    def _build_top_path_hints(self) -> list[dict[str, object]]:
        path_counts: dict[str, int] = {}
        for target_map in self.classification_targets.values():
            for target_path, count in target_map.items():
                path_counts[target_path] = path_counts.get(target_path, 0) + count

        ranked_paths = sorted(
            path_counts.items(),
            key=lambda item: (-item[1], item[0]),
        )[: self.config.max_path_examples]
        return [
            {
                "target_path": target_path,
                "count": count,
                "example_filenames": list(self.path_examples.get(target_path, []))[: self.config.max_examples_per_hint],
            }
            for target_path, count in ranked_paths
        ]

    def _relative_target_directory(self, target_directory: Path) -> Optional[str]:
        resolved_target = target_directory.expanduser().resolve()
        try:
            relative = resolved_target.relative_to(self.root_dir)
        except ValueError:
            return None
        if str(relative) == ".":
            return None
        return str(relative).replace("\\", "/")


def tokenize_filename(filename: str) -> list[str]:
    return tokenize_value(Path(filename).stem)


def tokenize_value(value: str) -> list[str]:
    tokens = [
        token
        for token in TOKEN_RE.findall(value.lower())
        if token not in GENERIC_FILENAME_TOKENS
        and len(token) >= 3
    ]
    return sorted(set(tokens))


def _increment_nested_count(container: dict[str, dict[str, int]], key: str, target_path: str) -> None:
    target_map = container.setdefault(key, {})
    target_map[target_path] = target_map.get(target_path, 0) + 1


def _normalize_nested_counts(value: object) -> dict[str, dict[str, int]]:
    if not isinstance(value, dict):
        return {}
    normalized: dict[str, dict[str, int]] = {}
    for outer_key, inner_value in value.items():
        if not isinstance(outer_key, str) or not isinstance(inner_value, dict):
            continue
        normalized_inner: dict[str, int] = {}
        for target_path, count in inner_value.items():
            if not isinstance(target_path, str):
                continue
            try:
                normalized_count = int(count)
            except (TypeError, ValueError):
                continue
            if normalized_count < 1:
                continue
            normalized_inner[target_path] = normalized_count
        if normalized_inner:
            normalized[outer_key] = normalized_inner
    return normalized


def _normalize_examples(value: object, *, max_items: int) -> dict[str, list[str]]:
    if not isinstance(value, dict):
        return {}
    normalized: dict[str, list[str]] = {}
    for path_label, examples in value.items():
        if not isinstance(path_label, str) or not isinstance(examples, list):
            continue
        clean_examples = [example for example in examples if isinstance(example, str) and example.strip()]
        if clean_examples:
            normalized[path_label] = clean_examples[:max_items]
    return normalized
