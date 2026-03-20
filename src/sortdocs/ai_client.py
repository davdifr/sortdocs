from __future__ import annotations

import base64
import json
import logging
import mimetypes
import os
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Mapping, Optional, Protocol

from openai import (
    APIConnectionError,
    APIStatusError,
    APITimeoutError,
    InternalServerError,
    OpenAI,
    RateLimitError,
)

from sortdocs.config import SortdocsConfig
from sortdocs.guardrails import apply_classification_guardrails
from sortdocs.models import ClassificationResult, ExtractedContent, ExtractedFileType
from sortdocs.utils import sanitize_path_component


LOGGER = logging.getLogger(__name__)
VISUAL_FILE_MAX_BYTES = 10 * 1024 * 1024
VISUAL_PDF_MAX_PAGES = 8

CLASSIFICATION_JSON_SCHEMA: dict[str, object] = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "category": {"type": "string", "minLength": 1, "maxLength": 64},
        "subcategory": {"type": "string", "minLength": 1, "maxLength": 64},
        "suggested_path": {"type": ["string", "null"], "minLength": 1, "maxLength": 240},
        "suggested_filename": {"type": "string", "minLength": 1, "maxLength": 120},
        "confidence": {"type": "number", "minimum": 0, "maximum": 1},
        "reason": {"type": "string", "minLength": 1, "maxLength": 500},
        "tags": {
            "type": "array",
            "items": {"type": "string", "minLength": 1, "maxLength": 32},
            "maxItems": 16,
        },
        "needs_review": {"type": "boolean"},
    },
    "required": [
        "category",
        "subcategory",
        "suggested_path",
        "suggested_filename",
        "confidence",
        "reason",
        "tags",
        "needs_review",
    ],
}

SYSTEM_PROMPT = """
You classify files for a personal document library.
You must propose:
- a category
- a subcategory
- a suggested_path relative to the managed root when you can infer a good folder path
- a short, clear, and stable filename

Folder selection rules:
- Use the provided existing_directory_context to reuse existing folder names when appropriate.
- Avoid creating near-duplicate folders such as travel vs travel_documents when one existing option already fits.
- suggested_path must be relative, must not start with / or ~, and must not contain .. segments.
- If the existing folder context is unclear, return suggested_path=null and rely on category/subcategory.
- Prefer English folder names when proposing or reusing paths, unless a proper noun or official product name must stay unchanged.

Evidence rules:
- You must preserve the original file extension in suggested_filename.
- You must not invent dates, names, or facts that are not present in the input.
- If extracted text is empty or weak, you may still use strong evidence from original_filename, relative_path, title_guess, metadata, and existing_directory_context.
- If a PDF file is attached as input_file, inspect its visual content directly instead of relying only on extracted text.
- If you are uncertain, lower confidence and set needs_review=true.

Naming rules:
- Use English for category, subcategory, suggested_path, suggested_filename, and tags whenever possible.
- Keep proper nouns, brand names, product names, acronyms, and official course titles when they are the clearest identifiers.
- Prefer short, readable, lowercase snake_case names.
- Avoid mixing languages inside the same filename.

Return only output that conforms to the provided JSON schema.
""".strip()


class AIClientError(RuntimeError):
    pass


class MissingAPIKeyError(AIClientError):
    pass


class RetryableAIClientError(AIClientError):
    pass


class APIRequestError(AIClientError):
    pass


class ResponseValidationError(AIClientError):
    pass


@dataclass(frozen=True)
class AdapterResponse:
    output_text: str
    model: str
    response_id: Optional[str] = None


class ModelAdapter(Protocol):
    model: str

    def create_classification_response(
        self,
        *,
        instructions: str,
        input_items: list[dict[str, object]],
        schema_name: str,
        schema: Mapping[str, object],
        max_output_tokens: int,
        timeout_seconds: float,
        temperature: Optional[float],
    ) -> AdapterResponse:
        ...


class OpenAIResponsesAdapter:
    def __init__(self, *, client: OpenAI, model: str) -> None:
        self._client = client
        self.model = model

    def create_classification_response(
        self,
        *,
        instructions: str,
        input_items: list[dict[str, object]],
        schema_name: str,
        schema: Mapping[str, object],
        max_output_tokens: int,
        timeout_seconds: float,
        temperature: Optional[float],
    ) -> AdapterResponse:
        request_kwargs: dict[str, object] = {
            "model": self.model,
            "instructions": instructions,
            "input": input_items,
            "max_output_tokens": max_output_tokens,
            "store": False,
            "text": {
                "format": {
                    "type": "json_schema",
                    "name": schema_name,
                    "strict": True,
                    "schema": dict(schema),
                }
            },
        }
        if temperature is not None:
            request_kwargs["temperature"] = temperature

        try:
            response = self._client.with_options(timeout=timeout_seconds).responses.create(**request_kwargs)
        except (APITimeoutError, APIConnectionError, RateLimitError, InternalServerError) as exc:
            raise RetryableAIClientError(_format_openai_error(exc)) from exc
        except APIStatusError as exc:
            if _is_retryable_status(exc.status_code):
                raise RetryableAIClientError(_format_openai_error(exc)) from exc
            raise APIRequestError(_format_openai_error(exc)) from exc
        except Exception as exc:
            raise APIRequestError(f"Unexpected error while contacting OpenAI: {exc}") from exc

        raw_output = (response.output_text or "").strip()
        if not raw_output:
            response_id = getattr(response, "id", None)
            raise APIRequestError(
                f"OpenAI returned an empty structured response"
                f"{_suffix_request_id(response_id)}."
            )

        return AdapterResponse(
            output_text=raw_output,
            model=getattr(response, "model", self.model),
            response_id=getattr(response, "id", None),
        )


class OpenAIClassificationClient:
    def __init__(
        self,
        config: SortdocsConfig,
        *,
        api_key: Optional[str] = None,
        adapter: Optional[ModelAdapter] = None,
        sleep_func: Callable[[float], None] = time.sleep,
    ) -> None:
        self._config = config
        self._sleep = sleep_func

        if adapter is not None:
            self._adapter = adapter
            return

        resolved_api_key = api_key or os.getenv("OPENAI_API_KEY")
        if not resolved_api_key:
            raise MissingAPIKeyError("OPENAI_API_KEY is not set.")

        client = OpenAI(
            api_key=resolved_api_key,
            timeout=config.openai.timeout_seconds,
            max_retries=0,
        )
        self._adapter = OpenAIResponsesAdapter(client=client, model=config.openai.model)

    def classify_file(
        self,
        extracted_content: ExtractedContent,
        original_filename: str,
        relative_path: str | Path,
        directory_context: Optional[Mapping[str, object]] = None,
        absolute_path: Optional[Path] = None,
    ) -> ClassificationResult:
        path_label = str(relative_path)
        visual_input_used = self._should_attach_visual_file(
            extracted_content=extracted_content,
            absolute_path=absolute_path,
        )
        input_items = self._build_input(
            extracted_content=extracted_content,
            original_filename=original_filename,
            relative_path=path_label,
            directory_context=directory_context,
            absolute_path=absolute_path,
            visual_input_used=visual_input_used,
        )
        response = self._request_with_retry(input_items=input_items, relative_path=path_label)
        result = self._parse_classification_output(
            response.output_text,
            original_filename=original_filename,
            extracted_content=extracted_content,
            relative_path=path_label,
            visual_input_used=visual_input_used,
        )
        LOGGER.info(
            "Classified file %s with model %s (confidence=%.2f, needs_review=%s)",
            path_label,
            response.model,
            result.confidence,
            result.needs_review,
        )
        return result

    def _request_with_retry(
        self,
        *,
        input_items: list[dict[str, object]],
        relative_path: str,
    ) -> AdapterResponse:
        max_attempts = self._config.openai.max_retries + 1
        attempt = 0
        last_error: Optional[Exception] = None

        while attempt < max_attempts:
            attempt += 1
            try:
                LOGGER.debug(
                    "Submitting OpenAI classification request for %s (attempt %d/%d)",
                    relative_path,
                    attempt,
                    max_attempts,
                )
                return self._adapter.create_classification_response(
                    instructions=SYSTEM_PROMPT,
                    input_items=input_items,
                    schema_name="sortdocs_classification",
                    schema=CLASSIFICATION_JSON_SCHEMA,
                    max_output_tokens=self._config.openai.max_output_tokens,
                    timeout_seconds=self._config.openai.timeout_seconds,
                    temperature=self._config.openai.temperature,
                )
            except RetryableAIClientError as exc:
                last_error = exc
                if attempt >= max_attempts:
                    break
                delay = _compute_backoff_delay(
                    attempt=attempt,
                    base_seconds=self._config.openai.backoff_base_seconds,
                    max_seconds=self._config.openai.backoff_max_seconds,
                )
                LOGGER.warning(
                    "Transient OpenAI error while classifying %s. Retrying in %.2fs (%d/%d).",
                    relative_path,
                    delay,
                    attempt,
                    max_attempts,
                )
                self._sleep(delay)
            except AIClientError:
                raise

        raise APIRequestError(
            f"OpenAI request failed after {max_attempts} attempts for {relative_path}: {last_error}"
        ) from last_error

    def _build_input(
        self,
        *,
        extracted_content: ExtractedContent,
        original_filename: str,
        relative_path: str,
        directory_context: Optional[Mapping[str, object]],
        absolute_path: Optional[Path],
        visual_input_used: bool,
    ) -> list[dict[str, object]]:
        payload = {
            "original_filename": original_filename,
            "relative_path": relative_path,
            "original_extension": Path(original_filename).suffix,
            "file_type": extracted_content.file_type.value,
            "title_guess": extracted_content.title_guess,
            "detected_language": extracted_content.detected_language,
            "plain_text_excerpt": extracted_content.plain_text_excerpt,
            "allowed_categories": self._config.planner.allowed_categories,
            "metadata": _json_safe_value(extracted_content.metadata),
            "extraction_warnings": extracted_content.extraction_warnings[:8],
            "existing_directory_context": _json_safe_value(directory_context or {}),
            "visual_file_attached": visual_input_used,
        }
        content_items: list[dict[str, object]] = []
        visual_file_item = self._build_visual_file_item(
            absolute_path=absolute_path,
            extracted_content=extracted_content,
            enabled=visual_input_used,
        )
        if visual_file_item is not None:
            content_items.append(visual_file_item)
        content_items.append(
            {
                "type": "input_text",
                "text": json.dumps(payload, ensure_ascii=False, default=str, indent=2),
            }
        )
        return [
            {
                "role": "user",
                "content": content_items,
            }
        ]

    def _parse_classification_output(
        self,
        raw_output: str,
        *,
        original_filename: str,
        extracted_content: ExtractedContent,
        relative_path: str,
        visual_input_used: bool,
    ) -> ClassificationResult:
        try:
            payload = json.loads(raw_output)
        except json.JSONDecodeError as exc:
            raise ResponseValidationError("OpenAI returned invalid JSON.") from exc

        try:
            result = ClassificationResult.model_validate(payload)
        except Exception as exc:
            raise ResponseValidationError("OpenAI returned data that does not match the expected schema.") from exc

        return self._normalize_result(
            result,
            original_filename=original_filename,
            extracted_content=extracted_content,
            relative_path=relative_path,
            visual_input_used=visual_input_used,
        )

    def _normalize_result(
        self,
        result: ClassificationResult,
        *,
        original_filename: str,
        extracted_content: ExtractedContent,
        relative_path: str,
        visual_input_used: bool,
    ) -> ClassificationResult:
        category = sanitize_path_component(result.category, default="", lowercase=True)
        subcategory = sanitize_path_component(result.subcategory, default="", lowercase=True)
        suggested_path = _normalize_suggested_path(result.suggested_path)
        suggested_filename = _normalize_filename(
            result.suggested_filename,
            original_filename=original_filename,
        )
        if not category or not subcategory or not suggested_filename:
            raise ResponseValidationError("OpenAI returned unsafe path components.")

        needs_review = result.needs_review or (
            result.confidence < self._config.planner.review_confidence_threshold
        )

        normalized = ClassificationResult(
            category=category,
            subcategory=subcategory,
            suggested_path=suggested_path,
            suggested_filename=suggested_filename,
            confidence=result.confidence,
            reason=result.reason.strip(),
            tags=_normalize_tags(result.tags),
            needs_review=needs_review,
        )
        guarded_result, guardrail_warnings = apply_classification_guardrails(
            normalized,
            extracted_content,
            original_filename=original_filename,
            relative_path=relative_path,
            review_confidence_threshold=self._config.planner.review_confidence_threshold,
            visual_input_used=visual_input_used,
        )
        for warning in guardrail_warnings:
            log_method = LOGGER.warning if guarded_result.needs_review else LOGGER.info
            log_method("Classification guardrail for %s: %s", original_filename, warning)
        return guarded_result

    def _should_attach_visual_file(
        self,
        *,
        extracted_content: ExtractedContent,
        absolute_path: Optional[Path],
    ) -> bool:
        if absolute_path is None:
            return False
        if extracted_content.file_type != ExtractedFileType.PDF:
            return False
        if absolute_path.suffix.lower() != ".pdf":
            return False
        if len(extracted_content.plain_text_excerpt.strip()) >= WEAK_VISUAL_ATTACHMENT_CHAR_LIMIT:
            return False

        try:
            stat_info = absolute_path.stat()
        except OSError:
            return False

        if stat_info.st_size > VISUAL_FILE_MAX_BYTES:
            LOGGER.info(
                "Skipping visual PDF fallback for %s because it exceeds %d bytes.",
                absolute_path.name,
                VISUAL_FILE_MAX_BYTES,
            )
            return False

        page_count = extracted_content.metadata.get("page_count")
        if isinstance(page_count, int) and page_count > VISUAL_PDF_MAX_PAGES:
            LOGGER.info(
                "Skipping visual PDF fallback for %s because it has %d pages.",
                absolute_path.name,
                page_count,
            )
            return False

        return True

    def _build_visual_file_item(
        self,
        *,
        absolute_path: Optional[Path],
        extracted_content: ExtractedContent,
        enabled: bool,
    ) -> Optional[dict[str, object]]:
        if not enabled or absolute_path is None:
            return None

        try:
            mime_type = mimetypes.guess_type(absolute_path.name)[0] or "application/pdf"
            encoded = base64.b64encode(absolute_path.read_bytes()).decode("ascii")
        except OSError as exc:
            LOGGER.warning("Could not attach PDF visual input for %s: %s", absolute_path.name, exc)
            return None

        _ = extracted_content
        return {
            "type": "input_file",
            "filename": absolute_path.name,
            "file_data": f"data:{mime_type};base64,{encoded}",
        }


def classify_file(
    extracted_content: ExtractedContent,
    original_filename: str,
    relative_path: str | Path,
    config: SortdocsConfig,
    directory_context: Optional[Mapping[str, object]] = None,
    absolute_path: Optional[Path] = None,
) -> ClassificationResult:
    client = OpenAIClassificationClient(config)
    return client.classify_file(
        extracted_content=extracted_content,
        original_filename=original_filename,
        relative_path=relative_path,
        directory_context=directory_context,
        absolute_path=absolute_path,
    )


def _normalize_filename(raw_filename: str, *, original_filename: str) -> str:
    original_suffix = Path(original_filename).suffix.lower()
    candidate_path = Path(raw_filename.strip())
    candidate_stem = candidate_path.stem if candidate_path.suffix else candidate_path.name
    safe_stem = sanitize_path_component(candidate_stem, default="", lowercase=True)
    if not safe_stem:
        raise ResponseValidationError("OpenAI returned an empty suggested filename.")
    return f"{safe_stem}{original_suffix}" if original_suffix else safe_stem


def _normalize_suggested_path(raw_path: Optional[str]) -> Optional[str]:
    if raw_path is None:
        return None

    candidate = raw_path.strip().replace("\\", "/")
    if not candidate:
        return None
    if candidate.startswith("/") or candidate.startswith("~"):
        raise ResponseValidationError("OpenAI returned an absolute suggested path.")

    sanitized_parts: list[str] = []
    for part in candidate.split("/"):
        stripped = part.strip()
        if not stripped:
            continue
        if stripped in {".", ".."}:
            raise ResponseValidationError("OpenAI returned a suggested path with traversal segments.")
        safe_part = sanitize_path_component(stripped, default="", lowercase=True)
        if safe_part:
            sanitized_parts.append(safe_part)

    if not sanitized_parts:
        raise ResponseValidationError("OpenAI returned an empty suggested path.")
    return "/".join(sanitized_parts[:5])


def _normalize_tags(tags: list[str]) -> list[str]:
    normalized: list[str] = []
    seen: set[str] = set()
    for item in tags:
        cleaned = " ".join(item.strip().split()).lower()
        if not cleaned or cleaned in seen:
            continue
        seen.add(cleaned)
        normalized.append(cleaned[:32])
    return normalized


def _json_safe_value(value: Any, *, max_string_length: int = 500, max_items: int = 20) -> Any:
    if isinstance(value, dict):
        trimmed_items = list(value.items())[:max_items]
        return {
            str(key): _json_safe_value(inner_value, max_string_length=max_string_length, max_items=max_items)
            for key, inner_value in trimmed_items
        }
    if isinstance(value, list):
        return [
            _json_safe_value(item, max_string_length=max_string_length, max_items=max_items)
            for item in value[:max_items]
        ]
    if isinstance(value, tuple):
        return [
            _json_safe_value(item, max_string_length=max_string_length, max_items=max_items)
            for item in value[:max_items]
        ]
    if isinstance(value, str):
        return value[:max_string_length]
    if isinstance(value, (int, float, bool)) or value is None:
        return value
    return str(value)[:max_string_length]


def _compute_backoff_delay(*, attempt: int, base_seconds: float, max_seconds: float) -> float:
    return min(base_seconds * (2 ** (attempt - 1)), max_seconds)


def _is_retryable_status(status_code: Optional[int]) -> bool:
    if status_code is None:
        return False
    return status_code in {408, 409, 429} or status_code >= 500


def _format_openai_error(exc: Exception) -> str:
    status_code = getattr(exc, "status_code", None)
    request_id = getattr(exc, "request_id", None)
    suffix = ""
    if status_code is not None:
        suffix += f" status={status_code}"
    if request_id:
        suffix += f" request_id={request_id}"
    return f"{exc.__class__.__name__}:{suffix or ' request failed'}".strip()


def _suffix_request_id(request_id: Optional[str]) -> str:
    return f" (request_id={request_id})" if request_id else ""


WEAK_VISUAL_ATTACHMENT_CHAR_LIMIT = 80
