"""Tests for optional vision frame analysis safety and parsing."""

import csv
from pathlib import Path

from src.models.source import FrameRecord, FrameRole
from src.services.frame_summary import frame_risk_notes
from src.services.model_advisor import advise_vision_model
from src.services.project_service import ProjectService
from src.services.vision_frame_analyser import (
    apply_ai_frame_prefill,
    build_frame_analysis_messages,
    parse_frame_analysis_response,
)


def make_frame(tmp_path: Path) -> FrameRecord:
    """Return a frame record for vision tests."""
    path = tmp_path / "frame.jpg"
    path.write_bytes(b"image")
    return FrameRecord(
        frame_id="frame-1",
        source_id="video-1",
        file_name="frame.jpg",
        relative_path=Path("content/project/frames/frame.jpg"),
        absolute_path=path,
        timestamp_seconds=2.0,
        label="50pct",
        description="Keep this manual description",
    )


def test_vision_response_parser_accepts_plain_and_fenced_json() -> None:
    """Parse both strict JSON and common markdown-fenced JSON locally."""
    raw = '{"selected_role":"visual_reference","description":"A stage","confidence":"medium"}'
    fenced = f"```json\n{raw}\n```"

    assert parse_frame_analysis_response(raw)["parsed_successfully"] is True
    assert parse_frame_analysis_response(fenced)["analysis"]["description"] == "A stage"


def test_failed_or_default_ai_analysis_does_not_overwrite_manual_values(tmp_path) -> None:
    """Preserve frame data on failure and unless replacement is explicitly selected."""
    frame = make_frame(tmp_path)
    analysis = {
        "selected_role": FrameRole.VISUAL_REFERENCE,
        "description": "AI description",
        "visible_subject": "Person",
        "confidence": "medium",
    }

    assert apply_ai_frame_prefill(frame, None, "provider/model") == frame
    preserved = apply_ai_frame_prefill(frame, analysis, "provider/model")
    replaced = apply_ai_frame_prefill(frame, analysis, "provider/model", replace_existing=True)

    assert preserved.description == "Keep this manual description"
    assert preserved.visible_subject == "Person"
    assert replaced.description == "AI description"
    assert preserved.needs_human_review is True


def test_vision_advisor_excludes_router_helpers_and_prompt_has_no_paths(tmp_path, content_project) -> None:
    """Recommend a concrete vision model and keep local paths out of request text."""
    catalog = {
        "fetched_at": "2026-06-19T00:00:00+00:00",
        "models": [
            {"model_id": "openrouter/auto", "name": "Auto", "vision_input_supported": True, "text_output_supported": True, "structured_output_supported": True},
            {"model_id": "vendor/vision-small", "name": "Vision Small", "vision_input_supported": True, "text_output_supported": True, "structured_output_supported": True, "pricing_prompt": 0.000001, "pricing_completion": 0.000002},
        ],
    }
    recommendation = advise_vision_model(catalog)
    frame = make_frame(tmp_path)
    content_project.project_name = "Project C:\\private\\source.mp4"
    content_project.topic = "Token sk-or-v1-1234567890abcdefghijklmnop"
    messages = build_frame_analysis_messages(content_project, frame, "data:image/jpeg;base64,abc")
    serialized = str(messages)

    assert recommendation is not None
    assert recommendation.selected_model_id == "vendor/vision-small"
    assert str(frame.absolute_path) not in serialized
    assert "C:\\private\\source.mp4" not in serialized
    assert "sk-or-v1-1234567890abcdefghijklmnop" not in serialized
    assert "OPENROUTER_API_KEY" not in serialized
    assert "data:image/jpeg;base64,abc" in serialized


def test_ai_prefill_risk_and_asset_log_are_deduplicated(tmp_path, app_config, content_project) -> None:
    """Flag AI-prefilled frames for review and upsert one analysis asset row."""
    frame = apply_ai_frame_prefill(
        make_frame(tmp_path),
        {"selected_role": FrameRole.VISUAL_REFERENCE, "visible_subject": "Person", "confidence": "low"},
        "vendor/vision-small",
    )
    service = ProjectService(app_config)

    service.upsert_frame_analysis_asset_log(content_project, frame, "vendor/vision-small", "low")
    service.upsert_frame_analysis_asset_log(content_project, frame, "vendor/vision-small", "low")
    with (content_project.project_path / "asset-log.csv").open("r", encoding="utf-8", newline="") as handle:
        rows = list(csv.DictReader(handle))

    assert frame_risk_notes([frame]) == ["AI-prefilled frame descriptions require human review before publication."]
    assert len(rows) == 1
    assert rows[0]["asset_id"] == "frame-analysis-frame-1"
