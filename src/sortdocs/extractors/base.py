from __future__ import annotations

import re
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Optional

from sortdocs.models import ExtractedContent, ExtractedFileType
from sortdocs.utils import limit_text


LINE_WHITESPACE_RE = re.compile(r"[^\S\n]+")
MARKDOWN_HEADING_RE = re.compile(r"^#{1,6}\s*")
LANGUAGE_HINTS = {
    "en": {"the", "and", "for", "with", "from", "invoice", "document", "report"},
    "it": {"il", "lo", "la", "gli", "per", "con", "fattura", "documento"},
}


class BaseExtractor(ABC):
    file_type: ExtractedFileType
    supported_extensions: tuple[str, ...] = ()

    def __init__(self, *, max_chars: int = 4000) -> None:
        if max_chars < 1:
            raise ValueError("max_chars must be greater than zero.")
        self.max_chars = max_chars

    def can_handle(self, path: Path) -> bool:
        return path.suffix.lower() in self.supported_extensions

    def extract(self, path: Path) -> ExtractedContent:
        try:
            content = self._extract(path)
        except Exception as exc:
            content = self._build_failure_content(
                path=path,
                warning=f"{self.__class__.__name__} failed: {exc}",
            )
        return self._finalize_content(path=path, content=content)

    @abstractmethod
    def _extract(self, path: Path) -> ExtractedContent:
        raise NotImplementedError

    def _finalize_content(self, *, path: Path, content: ExtractedContent) -> ExtractedContent:
        normalized_text = self._normalize_text(content.plain_text_excerpt)
        excerpt = limit_text(normalized_text, self.max_chars) if normalized_text else ""
        title_guess = self._normalize_title(content.title_guess) or self._guess_title(path=path, text=excerpt)
        detected_language = content.detected_language or self._detect_language(excerpt)
        warnings = [warning.strip() for warning in content.extraction_warnings if warning.strip()]

        return ExtractedContent(
            file_type=content.file_type,
            title_guess=title_guess,
            plain_text_excerpt=excerpt,
            detected_language=detected_language,
            metadata=dict(content.metadata),
            extraction_warnings=warnings,
        )

    def _normalize_text(self, text: str) -> str:
        normalized = text.replace("\r\n", "\n").replace("\r", "\n")
        lines: list[str] = []
        saw_blank = False

        for raw_line in normalized.split("\n"):
            clean_line = LINE_WHITESPACE_RE.sub(" ", raw_line).strip()
            if not clean_line:
                if not saw_blank and lines:
                    lines.append("")
                saw_blank = True
                continue
            lines.append(clean_line)
            saw_blank = False

        return "\n".join(lines).strip()

    def _guess_title(self, *, path: Path, text: str) -> Optional[str]:
        for line in text.splitlines():
            candidate = MARKDOWN_HEADING_RE.sub("", line).strip(" -_\t")
            if candidate:
                return limit_text(candidate, 160)
        stem = path.stem.strip()
        return limit_text(stem, 160) if stem else None

    def _normalize_title(self, title: Optional[str]) -> Optional[str]:
        if not title:
            return None
        normalized = self._normalize_text(title)
        return limit_text(normalized, 160) if normalized else None

    def _detect_language(self, text: str) -> Optional[str]:
        if not text:
            return None

        words = {part.lower() for part in re.findall(r"[A-Za-zÀ-ÿ]{2,}", text)}
        scores = {
            language: len(words & markers)
            for language, markers in LANGUAGE_HINTS.items()
        }
        best_language, best_score = max(scores.items(), key=lambda item: item[1])
        return best_language if best_score >= 2 else None

    def _build_failure_content(self, *, path: Path, warning: str) -> ExtractedContent:
        return ExtractedContent(
            file_type=self.file_type,
            title_guess=path.stem or None,
            plain_text_excerpt="",
            detected_language=None,
            metadata={},
            extraction_warnings=[warning],
        )
