from __future__ import annotations

from pathlib import Path

from sortdocs.extractors.base import BaseExtractor
from sortdocs.models import ExtractedContent, ExtractedFileType


class FallbackExtractor(BaseExtractor):
    file_type = ExtractedFileType.FALLBACK
    supported_extensions: tuple[str, ...] = ()

    def _extract(self, path: Path) -> ExtractedContent:
        return ExtractedContent(
            file_type=self.file_type,
            title_guess=path.stem or None,
            plain_text_excerpt="",
            detected_language=None,
            metadata={
                "extension": path.suffix.lower(),
            },
            extraction_warnings=[
                f"No specialized extractor is available for {path.suffix.lower() or 'files without an extension'}.",
            ],
        )
