from __future__ import annotations

import json
from pathlib import Path

import pytest

from sortdocs.ai_client import (
    CLASSIFICATION_JSON_SCHEMA,
    APIRequestError,
    MissingAPIKeyError,
    OpenAIClassificationClient,
    OpenAIResponsesAdapter,
    ResponseValidationError,
    RetryableAIClientError,
    SYSTEM_PROMPT,
    build_classification_signature,
    classify_file,
)
from sortdocs.config import SortdocsConfig
from sortdocs.models import ExtractedContent, ExtractedFileType


class FakeAdapter:
    def __init__(self, responses: list[object], *, model: str = "fake-model") -> None:
        self._responses = list(responses)
        self.model = model
        self.calls: list[dict[str, object]] = []

    def create_classification_response(self, **kwargs):
        self.calls.append(kwargs)
        current = self._responses.pop(0)
        if isinstance(current, Exception):
            raise current
        return current


class FakeResponse:
    def __init__(self, output_text: str, *, model: str = "gpt-4.1-mini", response_id: str = "resp_123") -> None:
        self.output_text = output_text
        self.model = model
        self.id = response_id


class FakeResponsesAPI:
    def __init__(self, response: FakeResponse) -> None:
        self._response = response
        self.calls: list[dict[str, object]] = []

    def create(self, **kwargs):
        self.calls.append(kwargs)
        return self._response


class FakeOpenAIClient:
    def __init__(self, response: FakeResponse) -> None:
        self.responses = FakeResponsesAPI(response)
        self.last_timeout = None

    def with_options(self, *, timeout: float):
        self.last_timeout = timeout
        return self


def make_extracted_content() -> ExtractedContent:
    return ExtractedContent(
        file_type=ExtractedFileType.TEXT,
        title_guess="March Invoice",
        plain_text_excerpt="Invoice for March 2026",
        detected_language="en",
        metadata={"source": "unit-test"},
        extraction_warnings=[],
    )


def test_classify_file_success_uses_responses_api_and_schema(monkeypatch: pytest.MonkeyPatch) -> None:
    fake_response = FakeResponse(
        output_text=json.dumps(
            {
                "category": "Finance",
                "subcategory": "Invoices",
                "suggested_path": "Finance/Invoices",
                "suggested_filename": "March Invoice FINAL.docx",
                "confidence": 0.92,
                "reason": "The excerpt clearly looks like a monthly invoice.",
                "tags": ["invoice", "monthly", "Invoice"],
                "needs_review": False,
            }
        )
    )
    fake_client = FakeOpenAIClient(fake_response)
    monkeypatch.setattr("sortdocs.ai_client.OpenAI", lambda **kwargs: fake_client)
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")

    config = SortdocsConfig.model_validate(
        {
            "openai": {"temperature": 0.2},
            "planner": {"allowed_categories": ["Finance", "Admin"]},
        }
    )
    result = classify_file(
        extracted_content=make_extracted_content(),
        original_filename="march.docx",
        relative_path=Path("Inbox/march.docx"),
        config=config,
        directory_context={"top_level_directories": ["finance", "travel"]},
    )

    assert result.category == "finance"
    assert result.subcategory == "invoices"
    assert result.suggested_path == "finance/invoices"
    assert result.suggested_filename == "march_invoice_final.docx"
    assert result.tags == ["invoice", "monthly"]
    assert result.needs_review is False
    assert fake_client.last_timeout == config.openai.timeout_seconds
    assert fake_client.responses.calls[0]["store"] is False
    assert fake_client.responses.calls[0]["model"] == config.openai.model
    assert fake_client.responses.calls[0]["temperature"] == 0.2
    assert fake_client.responses.calls[0]["text"]["format"]["type"] == "json_schema"
    assert fake_client.responses.calls[0]["text"]["format"]["schema"] == CLASSIFICATION_JSON_SCHEMA
    payload_text = fake_client.responses.calls[0]["input"][0]["content"][0]["text"]
    assert "\"existing_directory_context\"" in payload_text
    assert "\"top_level_directories\"" in payload_text
    assert "\"visual_file_attached\": false" in payload_text


def test_classification_client_retries_with_backoff() -> None:
    delays: list[float] = []
    adapter = FakeAdapter(
        [
            RetryableAIClientError("temporary issue"),
            type(
                "AdapterResponse",
                (),
                {
                    "output_text": json.dumps(
                        {
                            "category": "Admin",
                            "subcategory": "Reference",
                            "suggested_filename": "Tax Notes",
                            "confidence": 0.61,
                            "reason": "The input is short so this should be reviewed.",
                            "tags": ["tax"],
                            "needs_review": False,
                        }
                    ),
                    "model": "fake-model",
                    "response_id": "resp_retry",
                },
            )(),
        ]
    )
    config = SortdocsConfig.model_validate(
        {
            "openai": {
                "max_retries": 2,
                "backoff_base_seconds": 0.25,
                "backoff_max_seconds": 2.0,
            },
            "planner": {"confidence_threshold": 0.7},
        }
    )
    client = OpenAIClassificationClient(
        config,
        adapter=adapter,
        sleep_func=delays.append,
    )

    result = client.classify_file(
        extracted_content=make_extracted_content(),
        original_filename="notes.pdf",
        relative_path="Inbox/notes.pdf",
    )

    assert delays == [0.25]
    assert len(adapter.calls) == 2
    assert result.suggested_filename == "tax_notes.pdf"
    assert result.needs_review is True


def test_classify_file_raises_on_invalid_json() -> None:
    adapter = FakeAdapter(
        [
            type(
                "AdapterResponse",
                (),
                {"output_text": "{not-json", "model": "fake-model", "response_id": "resp_bad"},
            )()
        ]
    )
    client = OpenAIClassificationClient(SortdocsConfig(), adapter=adapter)

    with pytest.raises(ResponseValidationError):
        client.classify_file(
            extracted_content=make_extracted_content(),
            original_filename="broken.pdf",
            relative_path="Inbox/broken.pdf",
        )


def test_classify_file_raises_when_api_key_missing(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)

    with pytest.raises(MissingAPIKeyError):
        OpenAIClassificationClient(SortdocsConfig())


def test_openai_adapter_wraps_empty_output_as_error() -> None:
    adapter = OpenAIResponsesAdapter(
        client=FakeOpenAIClient(FakeResponse(output_text="")),
        model="gpt-4.1-mini",
    )

    with pytest.raises(APIRequestError):
        adapter.create_classification_response(
            instructions="test",
            input_items=[{"role": "user", "content": [{"type": "input_text", "text": "hello"}]}],
            schema_name="sortdocs_classification",
            schema=CLASSIFICATION_JSON_SCHEMA,
            max_output_tokens=200,
            timeout_seconds=5.0,
            temperature=None,
        )


def test_classify_file_caps_confidence_when_extracted_text_is_too_weak() -> None:
    adapter = FakeAdapter(
        [
            type(
                "AdapterResponse",
                (),
                {
                    "output_text": json.dumps(
                        {
                            "category": "Finance",
                            "subcategory": "Invoices",
                            "suggested_filename": "Invoice",
                            "confidence": 0.97,
                            "reason": "Looks like an invoice.",
                            "tags": ["invoice"],
                            "needs_review": False,
                        }
                    ),
                    "model": "fake-model",
                    "response_id": "resp_guardrail",
                },
            )()
        ]
    )
    client = OpenAIClassificationClient(SortdocsConfig(), adapter=adapter)
    extracted_content = ExtractedContent(
        file_type=ExtractedFileType.FALLBACK,
        title_guess=None,
        plain_text_excerpt="",
        detected_language=None,
        metadata={},
        extraction_warnings=["No readable text extracted."],
    )

    result = client.classify_file(
        extracted_content=extracted_content,
        original_filename="unknown.pdf",
        relative_path="Inbox/unknown.pdf",
    )

    # This guardrail prevents the tool from trusting a high-confidence answer
    # when extraction produced little or no evidence.
    assert result.confidence == 0.35
    assert result.needs_review is True
    assert "Local guardrail lowered confidence" in result.reason


def test_classify_file_can_trust_strong_filename_signal_when_text_is_missing() -> None:
    adapter = FakeAdapter(
        [
            type(
                "AdapterResponse",
                (),
                {
                    "output_text": json.dumps(
                        {
                            "category": "Personal",
                            "subcategory": "Identity Documents",
                            "suggested_path": "personal_documents/identity",
                            "suggested_filename": "drivers_license",
                            "confidence": 0.97,
                            "reason": "The filename clearly indicates a driver's license.",
                            "tags": ["id", "license"],
                            "needs_review": False,
                        }
                    ),
                    "model": "fake-model",
                    "response_id": "resp_filename_signal",
                },
            )()
        ]
    )
    client = OpenAIClassificationClient(SortdocsConfig(), adapter=adapter)
    extracted_content = ExtractedContent(
        file_type=ExtractedFileType.PDF,
        title_guess="drivers_license",
        plain_text_excerpt="",
        detected_language=None,
        metadata={},
        extraction_warnings=["No readable text extracted."],
    )

    result = client.classify_file(
        extracted_content=extracted_content,
        original_filename="drivers_license.pdf",
        relative_path="drivers_license.pdf",
        directory_context={"top_level_directories": ["personal_documents", "finance"]},
    )

    assert result.suggested_path == "personal_documents/identity"
    assert result.confidence == 0.75
    assert result.needs_review is False


def test_classify_file_attaches_pdf_input_for_visual_fallback(tmp_path: Path) -> None:
    pdf_path = tmp_path / "scan.pdf"
    pdf_path.write_bytes(b"%PDF-1.4\n%stub\n")
    adapter = FakeAdapter(
        [
            type(
                "AdapterResponse",
                (),
                {
                    "output_text": json.dumps(
                        {
                            "category": "Personal",
                            "subcategory": "Identity",
                            "suggested_path": "personal_documents/identity",
                            "suggested_filename": "drivers_license",
                            "confidence": 0.88,
                            "reason": "The attached PDF visually looks like an ID document.",
                            "tags": ["id"],
                            "needs_review": False,
                        }
                    ),
                    "model": "fake-model",
                    "response_id": "resp_pdf_visual",
                },
            )()
        ]
    )
    client = OpenAIClassificationClient(SortdocsConfig(), adapter=adapter)
    extracted_content = ExtractedContent(
        file_type=ExtractedFileType.PDF,
        title_guess="scan",
        plain_text_excerpt="",
        detected_language=None,
        metadata={"page_count": 1},
        extraction_warnings=["No readable text was extracted from the PDF."],
    )

    result = client.classify_file(
        extracted_content=extracted_content,
        original_filename="scan.pdf",
        relative_path="scan.pdf",
        absolute_path=pdf_path,
    )

    content_items = adapter.calls[0]["input_items"][0]["content"]
    assert content_items[0]["type"] == "input_file"
    assert content_items[0]["filename"] == "scan.pdf"
    assert content_items[0]["file_data"].startswith("data:application/pdf;base64,")
    assert result.confidence == 0.88
    assert result.needs_review is False


def test_system_prompt_requires_english_naming() -> None:
    assert "Use English for category, subcategory, suggested_path, suggested_filename, and tags" in SYSTEM_PROMPT


def test_classification_signature_changes_when_model_changes() -> None:
    base_config = SortdocsConfig.model_validate({"openai": {"model": "gpt-4.1-mini"}})
    changed_config = SortdocsConfig.model_validate({"openai": {"model": "gpt-5-mini"}})

    assert build_classification_signature(base_config) != build_classification_signature(changed_config)
