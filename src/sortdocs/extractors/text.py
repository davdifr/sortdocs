from __future__ import annotations

from pathlib import Path

from sortdocs.extractors.base import BaseExtractor
from sortdocs.models import ExtractedContent, ExtractedFileType


TEXT_READ_MULTIPLIER = 4
TEXT_READ_PADDING = 1024


class TextExtractor(BaseExtractor):
    file_type = ExtractedFileType.TEXT
    supported_extensions = (".txt", ".md")

    def _extract(self, path: Path) -> ExtractedContent:
        raw_bytes = self._read_excerpt_bytes(path)
        decoded_text, encoding, warning = self._decode_bytes(raw_bytes)
        line_count = decoded_text.count("\n") + 1 if decoded_text else 0
        title_guess = self._guess_title(path=path, text=decoded_text)
        metadata = {
            "encoding": encoding,
            "line_count": line_count,
            "character_count": len(decoded_text),
        }
        warnings = [warning] if warning else []

        return ExtractedContent(
            file_type=self.file_type,
            title_guess=title_guess,
            plain_text_excerpt=decoded_text,
            detected_language=None,
            metadata=metadata,
            extraction_warnings=warnings,
        )

    def _read_excerpt_bytes(self, path: Path) -> bytes:
        byte_budget = max(self.max_chars * TEXT_READ_MULTIPLIER, TEXT_READ_PADDING)
        with path.open("rb") as handle:
            return handle.read(byte_budget)

    def _decode_bytes(self, payload: bytes) -> tuple[str, str, str | None]:
        for encoding in ("utf-8", "utf-8-sig", "cp1252", "latin-1"):
            try:
                return payload.decode(encoding), encoding, None
            except UnicodeDecodeError:
                continue

        decoded = payload.decode("utf-8", errors="replace")
        return decoded, "utf-8", "Some characters could not be decoded cleanly."
