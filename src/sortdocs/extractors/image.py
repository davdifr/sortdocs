from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional, Protocol

from PIL import ExifTags, Image, UnidentifiedImageError

from sortdocs.extractors.base import BaseExtractor
from sortdocs.models import ExtractedContent, ExtractedFileType


@dataclass
class OCRResult:
    text: str = ""
    detected_language: Optional[str] = None
    metadata: dict[str, object] = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)


class OCRBackend(Protocol):
    def extract_text(self, path: Path, *, max_chars: int) -> OCRResult:
        ...


class StubOCRBackend:
    def extract_text(self, path: Path, *, max_chars: int) -> OCRResult:
        return OCRResult(
            text="",
            detected_language=None,
            metadata={"backend": "stub", "requested_max_chars": max_chars},
            warnings=["OCR is not implemented yet for images; metadata-only extraction was used."],
        )


class ImageExtractor(BaseExtractor):
    file_type = ExtractedFileType.IMAGE
    supported_extensions = (".jpg", ".jpeg", ".png")

    def __init__(self, *, max_chars: int = 4000, ocr_backend: Optional[OCRBackend] = None) -> None:
        super().__init__(max_chars=max_chars)
        self._ocr_backend = ocr_backend or StubOCRBackend()

    def _extract(self, path: Path) -> ExtractedContent:
        try:
            with Image.open(path) as image:
                metadata = self._extract_metadata(image)
        except UnidentifiedImageError as exc:
            return self._build_failure_content(path=path, warning=f"ImageExtractor failed: {exc}")

        ocr_result = self._ocr_backend.extract_text(path, max_chars=self.max_chars)
        merged_metadata = {
            **metadata,
            "ocr": dict(ocr_result.metadata),
        }

        return ExtractedContent(
            file_type=self.file_type,
            title_guess=self._guess_title(path=path, text=ocr_result.text),
            plain_text_excerpt=ocr_result.text,
            detected_language=ocr_result.detected_language,
            metadata=merged_metadata,
            extraction_warnings=list(ocr_result.warnings),
        )

    def _extract_metadata(self, image: Image.Image) -> dict[str, object]:
        exif_data = image.getexif()
        parsed_exif: dict[str, object] = {}
        for tag_id, value in exif_data.items():
            tag_name = ExifTags.TAGS.get(tag_id, str(tag_id))
            if tag_name in {"DateTime", "Make", "Model", "Software", "ImageDescription"}:
                parsed_exif[tag_name] = value

        return {
            "width": image.width,
            "height": image.height,
            "mode": image.mode,
            "format": image.format,
            "exif": parsed_exif,
        }
