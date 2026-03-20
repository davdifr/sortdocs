from __future__ import annotations

from pathlib import Path
from typing import Optional

from sortdocs.extractors.base import BaseExtractor
from sortdocs.extractors.docx import DocxExtractor
from sortdocs.extractors.fallback import FallbackExtractor
from sortdocs.extractors.image import ImageExtractor, OCRBackend, OCRResult, StubOCRBackend
from sortdocs.extractors.pdf import PdfExtractor
from sortdocs.extractors.text import TextExtractor


def get_extractor(
    path: Path,
    *,
    max_chars: int = 4000,
    ocr_backend: Optional[OCRBackend] = None,
) -> BaseExtractor:
    extension = path.suffix.lower()
    if extension in PdfExtractor.supported_extensions:
        return PdfExtractor(max_chars=max_chars)
    if extension in TextExtractor.supported_extensions:
        return TextExtractor(max_chars=max_chars)
    if extension in DocxExtractor.supported_extensions:
        return DocxExtractor(max_chars=max_chars)
    if extension in ImageExtractor.supported_extensions:
        return ImageExtractor(max_chars=max_chars, ocr_backend=ocr_backend)
    return FallbackExtractor(max_chars=max_chars)


__all__ = [
    "BaseExtractor",
    "DocxExtractor",
    "FallbackExtractor",
    "ImageExtractor",
    "OCRBackend",
    "OCRResult",
    "PdfExtractor",
    "StubOCRBackend",
    "TextExtractor",
    "get_extractor",
]
