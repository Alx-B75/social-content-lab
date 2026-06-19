"""Tests for OpenRouter client fallbacks and LLM save safety."""

import json
import re

import httpx
import pytest

from src.config import AppConfig
from src.models.planning import ClarifyingAnswers
from src.services.llm_planner import (
    build_llm_planning_context,
    can_save_structured_llm_result,
    generate_llm_content_pack,
    generate_tiny_llm_test,
    parse_llm_content_pack_response,
    repair_llm_content_pack_response,
    requires_high_token_warning,
    save_failed_llm_output,
    save_llm_content_pack,
)
from src.services.model_advisor import ModelAdvisorRecommendation
from src.services.openrouter_client import call_openrouter_chat, is_openrouter_configured, safe_openrouter_error_message
from src.services.project_service import ProjectService


class FakeResponse:
    """Small fake httpx response for client tests."""

    def __init__(self, payload: dict, status_code: int = 200) -> None:
        """Initialise the fake response."""
        self.payload = payload
        self.status_code = status_code

    def json(self) -> dict:
        """Return the fake JSON payload."""
        return self.payload

    def raise_for_status(self) -> None:
        """Raise for non-success statuses."""
        if self.status_code >= 400:
            request = httpx.Request("POST", "https://openrouter.ai/api/v1/chat/completions")
            response = httpx.Response(self.status_code, json=self.payload, request=request)
            raise httpx.HTTPStatusError("bad request", request=request, response=response)


def test_openrouter_missing_key_and_empty_response(monkeypatch, app_config) -> None:
    """Classify missing keys and empty selected-model responses safely."""
    assert is_openrouter_configured(app_config) is False
    missing = call_openrouter_chat(app_config, "sample/model", [], 0.5, 100)
    assert missing["error_type"] == "missing_api_key"

    configured = app_config.model_copy(update={"openrouter_api_key": "sk-test-secret"})

    def fake_post(*args, **kwargs):
        return FakeResponse({"choices": [{"message": {"content": ""}}], "usage": {"total_tokens": 12}})

    monkeypatch.setattr("src.services.openrouter_client.httpx.post", fake_post)
    empty = call_openrouter_chat(configured, "sample/model", [{"role": "user", "content": "Return JSON"}], 0.5, 100)

    assert empty["ok"] is False
    assert empty["error_type"] == "empty_model_response"
    assert empty["usage"]["total_tokens"] == 12
    assert "empty response" in empty["error"]


def test_safe_error_message_redacts_secret_like_tokens() -> None:
    """Redact secret-like fragments from HTTP error messages."""
    request = httpx.Request("POST", "https://openrouter.ai/api/v1/chat/completions")
    response = httpx.Response(
        401,
        json={"error": {"message": "bad key sk-1234567890abcdefghijklmnop"}},
        request=request,
    )
    error = httpx.HTTPStatusError("bad request", request=request, response=response)

    message = safe_openrouter_error_message(error)

    assert "sk-1234567890abcdefghijklmnop" not in message
    assert "[redacted]" in message


def test_llm_context_omits_paths_and_save_flow_is_separate(app_config, content_project) -> None:
    """Build safe text context and save parsed LLM output without raw fallback files."""
    project_service = ProjectService(app_config)
    advisor = ModelAdvisorRecommendation(
        selected_model_id="sample/quality",
        display_name="Sample Quality",
        tier="balanced_recommended",
        estimated_cost_band="very low",
        confidence="medium",
    )
    context = build_llm_planning_context(
        content_project,
        [],
        ClarifyingAnswers(platform="LinkedIn", output_format="short video", call_to_action="Ask Shakespeare a question."),
        None,
        [],
        advisor,
    )
    parsed = {
        "core_message": "Invite people to ask Shakespeare a question.",
        "hook_options": ["What if Shakespeare could answer back?"],
        "script_outline": ["Open with the question."],
        "shot_list": ["Opening title card."],
        "image_prompt": "A restrained LinkedIn teaser visual.",
        "video_prompts": ["Create a concise 10-second LinkedIn teaser."],
        "caption_drafts": ["Ask Shakespeare a question."],
        "risk_notes": ["Review before publication."],
        "next_actions": ["Review copy."],
        "rationale": "Short teaser.",
    }
    result = {
        "ok": True,
        "selected_model": advisor.selected_model_id,
        "text": json.dumps(parsed),
        "usage": {"total_tokens": 200, "cost": 0.00001},
        "parsed_successfully": True,
        "parsed": parsed,
    }

    metadata_first = save_llm_content_pack(project_service, content_project, result, advisor, "sample-time")
    metadata_second = save_llm_content_pack(project_service, content_project, result, advisor, "sample-time")
    combined_output = (content_project.project_path / "llm-output.json").read_text(encoding="utf-8")
    project_json = (content_project.project_path / "project.json").read_text(encoding="utf-8")
    asset_log = (content_project.project_path / "asset-log.csv").read_text(encoding="utf-8")

    assert "project_path" not in json.dumps(context)
    assert not re.search(r"[A-Za-z]:\\|[A-Za-z]:/", combined_output + project_json)
    assert not (content_project.project_path / "llm-raw-output.txt").exists()
    assert metadata_first["output_hash"] == metadata_second["output_hash"]
    assert asset_log.count("generated_text") == 1


def test_llm_raw_output_saved_only_for_unparsed_response(app_config, content_project) -> None:
    """Save raw selected-model output only when parsing fails."""
    advisor = ModelAdvisorRecommendation(
        selected_model_id="sample/quality",
        display_name="Sample Quality",
        tier="balanced_recommended",
    )
    failed_result = {
        "selected_model": advisor.selected_model_id,
        "text": "not json",
        "usage": {},
        "parsed_successfully": False,
        "parsed": None,
    }

    save_failed_llm_output(content_project, failed_result)

    assert (content_project.project_path / "llm-raw-output.txt").exists()
    assert not list(content_project.project_path.glob("*.llm.md"))
    assert parse_llm_content_pack_response("not json")["parsed_successfully"] is False


def test_json_parse_failure_blocks_structured_save(monkeypatch, app_config, content_project) -> None:
    """Classify malformed model text and reject structured pack saving."""
    configured = app_config.model_copy(update={"openrouter_api_key": "sk-test-secret"})

    def fake_call(*args, **kwargs):
        return {"ok": True, "text": "not valid json", "usage": {"total_tokens": 20}, "error": None, "error_type": None}

    monkeypatch.setattr("src.services.llm_planner.call_openrouter_chat", fake_call)
    result = generate_llm_content_pack(configured, "sample/model", {}, 0.5, 600)

    assert result["ok"] is False
    assert result["error_type"] == "json_parse_failed"
    assert can_save_structured_llm_result(result) is False
    with pytest.raises(ValueError):
        save_llm_content_pack(ProjectService(app_config), content_project, result, None, None)
    assert not list(content_project.project_path.glob("*.llm.md"))


def test_local_json_repair_handles_fences_and_surrounding_text() -> None:
    """Repair JSON wrapped in Markdown or explanatory text without a model call."""
    fenced = '```json\n{"hook_options": ["Hook"], "caption_drafts": [], "rationale": "Short"}\n```'
    surrounded = 'Here is the result:\n{"hook_options": ["Hook"], "caption_drafts": [], "rationale": "Short"}\nThanks.'

    assert parse_llm_content_pack_response(fenced)["parsed_successfully"] is True
    repaired = repair_llm_content_pack_response(surrounded)

    assert repaired["parsed_successfully"] is True
    assert repaired["content"]["hook_options"] == ["Hook"]


def test_high_token_warning_threshold() -> None:
    """Warn only when the output cap exceeds the normal 1000-token limit."""
    assert requires_high_token_warning(1000) is False
    assert requires_high_token_warning(1001) is True


def test_tiny_generation_caps_max_tokens(monkeypatch, app_config) -> None:
    """Keep tiny test generation within the 300-500 token safety range."""
    captured = {}

    def fake_call(config, selected_model, messages, temperature, max_tokens):
        captured["max_tokens"] = max_tokens
        return {
            "ok": True,
            "text": '{"hook_options": [], "caption_drafts": [], "rationale": "ok"}',
            "usage": {},
            "error": None,
            "error_type": None,
        }

    monkeypatch.setattr("src.services.llm_planner.call_openrouter_chat", fake_call)
    result = generate_tiny_llm_test(app_config, "sample/model", {}, max_tokens=2000)

    assert captured["max_tokens"] == 500
    assert result["parsed_successfully"] is True
