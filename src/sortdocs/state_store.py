from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from sortdocs.config import StateSettings
from sortdocs.models import ClassificationResult
from sortdocs.scanner import DiscoveredFile


LOGGER = logging.getLogger(__name__)
STATE_VERSION = 1


@dataclass
class ProcessingStateStore:
    root_dir: Path
    file_path: Path
    config: StateSettings
    signature: str
    entries: dict[str, dict[str, object]] = field(default_factory=dict)
    _dirty: bool = False

    @classmethod
    def load(cls, *, root_dir: Path, config: StateSettings, signature: str) -> ProcessingStateStore:
        resolved_root = root_dir.expanduser().resolve()
        file_path = (resolved_root / config.filename).resolve()
        store = cls(
            root_dir=resolved_root,
            file_path=file_path,
            config=config,
            signature=signature,
        )
        if not config.enabled or not file_path.exists():
            return store

        try:
            payload = json.loads(file_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            LOGGER.warning("Could not read processing state file %s: %s", file_path, exc)
            return store

        if not isinstance(payload, dict) or payload.get("version") != STATE_VERSION:
            return store
        if payload.get("signature") != signature:
            LOGGER.info("Ignoring stale processing state file %s because its signature changed.", file_path)
            return store

        raw_entries = payload.get("entries")
        if isinstance(raw_entries, dict):
            store.entries = {
                path_label: entry
                for path_label, entry in raw_entries.items()
                if isinstance(path_label, str) and isinstance(entry, dict)
            }
        return store

    def lookup(self, discovered_file: DiscoveredFile) -> Optional[ClassificationResult]:
        if not self.config.enabled:
            return None

        key = self._relative_label(discovered_file.relative_path)
        entry = self.entries.get(key)
        if entry is None:
            return None
        if entry.get("size_bytes") != discovered_file.size_bytes:
            return None
        if entry.get("modified_at") != discovered_file.modified_at.isoformat():
            return None

        raw_classification = entry.get("classification")
        if not isinstance(raw_classification, dict):
            return None

        try:
            return ClassificationResult.model_validate(raw_classification)
        except Exception:
            return None

    def remember(
        self,
        *,
        file_path: Path,
        classification: ClassificationResult,
    ) -> None:
        if not self.config.enabled:
            return

        resolved_path = file_path.expanduser().resolve()
        try:
            relative_path = resolved_path.relative_to(self.root_dir)
        except ValueError:
            return

        try:
            stat_info = resolved_path.stat()
        except OSError:
            return

        key = self._relative_label(relative_path)
        self.entries[key] = {
            "size_bytes": stat_info.st_size,
            "modified_at": discovered_file_modified_at(stat_info.st_mtime),
            "classification": classification.model_dump(mode="json"),
        }
        self._dirty = True

    def forget(self, relative_path: Path) -> None:
        if not self.config.enabled:
            return
        key = self._relative_label(relative_path)
        if key in self.entries:
            del self.entries[key]
            self._dirty = True

    def save(self) -> Optional[Path]:
        if not self.config.enabled or not self._dirty:
            return None

        payload = {
            "version": STATE_VERSION,
            "signature": self.signature,
            "entries": self.entries,
        }
        self.file_path.parent.mkdir(parents=True, exist_ok=True)
        temp_path = self.file_path.with_name(f".{self.file_path.name}.tmp")
        temp_path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
        temp_path.replace(self.file_path)
        self._dirty = False
        return self.file_path

    @staticmethod
    def _relative_label(relative_path: Path) -> str:
        return str(relative_path).replace("\\", "/")


def discovered_file_modified_at(timestamp: float) -> str:
    from datetime import datetime, timezone

    return datetime.fromtimestamp(timestamp, tz=timezone.utc).isoformat()
