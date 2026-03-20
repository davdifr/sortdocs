from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable, Optional

from sortdocs.models import ClassificationResult, ExtractedContent, ExtractedFileType, PlannedAction


# These caps prevent the local validator from trusting a confident model response
# when extraction produced very little usable evidence.
EMPTY_TEXT_CONFIDENCE_CAP = 0.35
WEAK_TEXT_CONFIDENCE_CAP = 0.60
STRONG_NAME_SIGNAL_CONFIDENCE_CAP = 0.75
VISUAL_INPUT_CONFIDENCE_CAP = 0.90
WEAK_TEXT_CHAR_LIMIT = 16
HIGH_CONFIDENCE_MIN_TEXT_CHARS = 48

INVALID_FILENAME_RE = re.compile(r'[\/\\:\x00-\x1F]')
TOKEN_RE = re.compile(r"[a-z0-9]+")
UNRELIABLE_WARNING_MARKERS = (
    "incomplete",
    "insufficient",
    "failed",
    "corrupt",
    "ocr",
    "no readable text",
    "stub",
)
GENERIC_NAME_TOKENS = {
    "copy",
    "doc",
    "document",
    "file",
    "final",
    "image",
    "img",
    "new",
    "page",
    "pdf",
    "photo",
    "scan",
    "screenshot",
    "untitled",
}
HIGH_SIGNAL_NAME_TOKENS = {
    "agreement",
    "bank",
    "boarding",
    "card",
    "certificate",
    "contract",
    "degree",
    "driver",
    "drivers",
    "flight",
    "health",
    "id",
    "insurance",
    "invoice",
    "lab",
    "lease",
    "license",
    "medical",
    "passport",
    "receipt",
    "report",
    "statement",
    "ticket",
    "train",
    "transfer",
}


@dataclass(frozen=True)
class ActionValidationResult:
    is_valid: bool
    warnings: list[str] = field(default_factory=list)
    error_code: Optional[str] = None
    error_message: Optional[str] = None
    guardrail_blocked: bool = False


def apply_classification_guardrails(
    result: ClassificationResult,
    extracted_content: ExtractedContent,
    *,
    original_filename: str,
    relative_path: str,
    review_confidence_threshold: float,
    visual_input_used: bool = False,
) -> tuple[ClassificationResult, list[str]]:
    warnings: list[str] = []
    excerpt = extracted_content.plain_text_excerpt.strip()
    lowered_warnings = " ".join(extracted_content.extraction_warnings).lower()
    strong_name_signal = has_strong_name_signal(
        original_filename=original_filename,
        relative_path=relative_path,
    )

    confidence_cap: Optional[float] = None
    force_review = result.needs_review
    if not excerpt:
        if visual_input_used:
            confidence_cap = VISUAL_INPUT_CONFIDENCE_CAP
            warnings.append(
                "No extracted text was available; classification relied on visual PDF analysis."
            )
        else:
            confidence_cap = (
                STRONG_NAME_SIGNAL_CONFIDENCE_CAP if strong_name_signal else EMPTY_TEXT_CONFIDENCE_CAP
            )
        if not visual_input_used and strong_name_signal:
            warnings.append(
                "No extracted text was available; confidence was capped using filename/path evidence."
            )
        elif not visual_input_used:
            force_review = True
            warnings.append("No extracted text was available; confidence was capped and review was forced.")
    elif len(excerpt) < WEAK_TEXT_CHAR_LIMIT:
        if visual_input_used:
            confidence_cap = VISUAL_INPUT_CONFIDENCE_CAP
            warnings.append(
                "Extracted text was short, so classification relied partly on visual PDF analysis."
            )
        else:
            confidence_cap = (
                STRONG_NAME_SIGNAL_CONFIDENCE_CAP if strong_name_signal else EMPTY_TEXT_CONFIDENCE_CAP
            )
        if not visual_input_used and strong_name_signal:
            warnings.append(
                "Extracted text was too short for full trust, so filename/path evidence was used conservatively."
            )
        elif not visual_input_used:
            force_review = True
            warnings.append("Extracted text was too short to justify a strong classification.")
    elif len(excerpt) < HIGH_CONFIDENCE_MIN_TEXT_CHARS and result.confidence > 0.95:
        confidence_cap = WEAK_TEXT_CONFIDENCE_CAP
        warnings.append("Extracted text was limited, so model confidence was capped conservatively.")

    if extracted_content.file_type == ExtractedFileType.FALLBACK:
        confidence_cap = _min_optional(confidence_cap, WEAK_TEXT_CONFIDENCE_CAP)
        force_review = True
        warnings.append("Fallback extraction provided weak evidence; review was forced.")

    active_warning_markers = UNRELIABLE_WARNING_MARKERS
    if visual_input_used:
        active_warning_markers = tuple(
            marker
            for marker in UNRELIABLE_WARNING_MARKERS
            if marker not in {"no readable text", "ocr"}
        )

    if any(marker in lowered_warnings for marker in active_warning_markers):
        warning_cap = STRONG_NAME_SIGNAL_CONFIDENCE_CAP if strong_name_signal else WEAK_TEXT_CONFIDENCE_CAP
        if visual_input_used:
            warning_cap = min(warning_cap, VISUAL_INPUT_CONFIDENCE_CAP)
        confidence_cap = _min_optional(confidence_cap, warning_cap)
        if not strong_name_signal:
            force_review = True
        warnings.append("Extractor warnings indicated unreliable content; confidence was capped.")

    final_confidence = min(result.confidence, confidence_cap) if confidence_cap is not None else result.confidence
    if final_confidence < review_confidence_threshold:
        force_review = True

    reason = result.reason
    if confidence_cap is not None and result.confidence > final_confidence:
        reason = _append_reason_note(
            result.reason,
            "Local guardrail lowered confidence due to limited extracted evidence.",
        )

    normalized_result = ClassificationResult(
        category=result.category,
        subcategory=result.subcategory,
        suggested_path=result.suggested_path,
        suggested_filename=result.suggested_filename,
        confidence=final_confidence,
        reason=reason,
        tags=result.tags,
        needs_review=force_review,
    )
    return normalized_result, warnings


def validate_planned_action(action: PlannedAction) -> ActionValidationResult:
    warnings: list[str] = []
    target_path = action.target_path
    target_filename = action.target_filename

    if not target_path.is_absolute():
        return ActionValidationResult(
            is_valid=False,
            error_code="TARGET_NOT_ABSOLUTE",
            error_message="Target path must be absolute.",
            guardrail_blocked=True,
        )

    if contains_path_traversal(target_path):
        return ActionValidationResult(
            is_valid=False,
            error_code="PATH_TRAVERSAL_BLOCKED",
            error_message="Target path contains parent-directory traversal segments.",
            guardrail_blocked=True,
        )

    if has_invalid_filename(target_filename):
        return ActionValidationResult(
            is_valid=False,
            error_code="INVALID_FILENAME",
            error_message="Target filename contains invalid filesystem characters.",
            guardrail_blocked=True,
        )

    source_suffix = action.source_path.suffix.lower()
    target_suffix = target_path.suffix.lower()
    if source_suffix != target_suffix:
        return ActionValidationResult(
            is_valid=False,
            error_code="EXTENSION_MISMATCH",
            error_message="Target extension differs from the source extension.",
            guardrail_blocked=True,
        )

    approved_roots = tuple(path.expanduser().resolve() for path in action.approved_roots)
    if approved_roots and not path_is_within_roots(target_path, approved_roots):
        return ActionValidationResult(
            is_valid=False,
            error_code="TARGET_OUTSIDE_ALLOWED_ROOTS",
            error_message="Target path escaped the approved destination roots.",
            guardrail_blocked=True,
        )

    if len(target_filename) > 255:
        warnings.append("Target filename is unusually long and may be rejected by some filesystems.")

    return ActionValidationResult(is_valid=True, warnings=warnings)


def has_invalid_filename(filename: str) -> bool:
    stripped = filename.strip()
    if not stripped or stripped in {".", ".."}:
        return True
    if INVALID_FILENAME_RE.search(stripped):
        return True
    return Path(stripped).name != stripped


def contains_path_traversal(path: Path) -> bool:
    return any(part == ".." for part in path.parts)


def path_is_within_roots(path: Path, roots: Iterable[Path]) -> bool:
    resolved_path = path.expanduser().resolve()
    for root in roots:
        try:
            resolved_path.relative_to(root)
            return True
        except ValueError:
            continue
    return False


def _append_reason_note(reason: str, note: str) -> str:
    stripped = reason.strip()
    if note.lower() in stripped.lower():
        return stripped[:500]
    combined = f"{stripped} {note}".strip()
    return combined[:500]


def _min_optional(current: Optional[float], candidate: float) -> float:
    if current is None:
        return candidate
    return min(current, candidate)


def has_strong_name_signal(*, original_filename: str, relative_path: str) -> bool:
    stem = Path(original_filename).stem.lower()
    tokens = set(TOKEN_RE.findall(stem))
    _ = relative_path

    informative_tokens = {
        token
        for token in tokens
        if token not in GENERIC_NAME_TOKENS
        and (len(token) >= 4 or token in HIGH_SIGNAL_NAME_TOKENS)
    }
    high_signal_hits = informative_tokens & HIGH_SIGNAL_NAME_TOKENS
    return len(informative_tokens) >= 2 or len(high_signal_hits) >= 2
