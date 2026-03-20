from __future__ import annotations

from pathlib import Path

from pypdf import PdfReader

from sortdocs.extractors.base import BaseExtractor
from sortdocs.models import ExtractedContent, ExtractedFileType


class PdfExtractor(BaseExtractor):
    file_type = ExtractedFileType.PDF
    supported_extensions = (".pdf",)

    def _extract(self, path: Path) -> ExtractedContent:
        reader = PdfReader(str(path))
        metadata = reader.metadata or {}
        page_text: list[str] = []
        warnings: list[str] = []

        for index, page in enumerate(reader.pages, start=1):
            try:
                extracted = page.extract_text() or ""
            except Exception as exc:
                warnings.append(f"Could not extract text from page {index}: {exc}")
                continue

            if extracted.strip():
                page_text.append(extracted)
            if len("\n".join(page_text)) >= self.max_chars:
                break

        combined_text = "\n".join(page_text)
        if not combined_text.strip():
            warnings.append("No readable text was extracted from the PDF.")

        title_guess = getattr(metadata, "title", None) or self._guess_title(path=path, text=combined_text)
        extracted_metadata = {
            "page_count": len(reader.pages),
            "title": getattr(metadata, "title", None),
            "author": getattr(metadata, "author", None),
            "subject": getattr(metadata, "subject", None),
            "producer": getattr(metadata, "producer", None),
        }

        return ExtractedContent(
            file_type=self.file_type,
            title_guess=title_guess,
            plain_text_excerpt=combined_text,
            detected_language=None,
            metadata=extracted_metadata,
            extraction_warnings=warnings,
        )
