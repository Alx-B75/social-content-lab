"""Tests for lightweight workflow-display helpers."""

from datetime import datetime
from pathlib import Path
from types import SimpleNamespace

from app import answers_are_ready, has_loaded_project
from src.models.planning import ClarifyingAnswers
from src.models.source import SourceRecord, SourceReferenceStrategy, SourceType
from src.ui.llm_planning_panel import llm_generation_controls_expanded
from src.ui.source_panel import (
    _default_source_type_index,
    duplicate_source_filenames,
    frame_extraction_action_label,
    frame_extraction_is_complete,
    vision_cost_notice,
)
from src.ui.video_generation_panel import (
    VIDEO_GENERATION_LOCK_KEY,
    active_generation_lock,
    clear_generation_lock,
    duplicate_generation_warning,
    finish_generation_lock,
    start_generation_lock,
)
from src.ui.workflow_navigation import default_workflow_stage, missing_stage_guidance, workflow_stage_statuses


def make_video_source(source_id: str, filename: str = "teaser.mp4", status: str = "not_started", frame_count: int = 0) -> SourceRecord:
    """Return a video source for UI helper tests."""
    return SourceRecord(
        source_id=source_id,
        source_type=SourceType.VIDEO,
        original_filename=filename,
        declared_purpose="visual reference",
        strategy=SourceReferenceStrategy.KEYFRAME_EXTRACTION_NEEDED,
        frame_extraction_status=status,
        frame_count=frame_count,
        created_at=datetime(2026, 6, 19, 12, 0, 0),
    )


def test_loaded_project_state_helpers(content_project) -> None:
    """Treat a real project and saved answers as loaded state."""
    assert has_loaded_project(content_project)
    assert not has_loaded_project(None)
    assert answers_are_ready(ClarifyingAnswers(), True)
    assert not answers_are_ready(ClarifyingAnswers(), False)


def test_duplicate_filename_detection() -> None:
    """Detect duplicate uploaded filenames so source IDs can disambiguate rows."""
    sources = [
        make_video_source("source-a", "same.mp4"),
        make_video_source("source-b", "same.mp4"),
        make_video_source("source-c", "other.mp4"),
    ]

    assert duplicate_source_filenames(sources) == {"same.mp4"}


def test_video_context_defaults_new_source_type_to_video_upload() -> None:
    """Prefer video upload when the loaded project already contains video sources."""
    options = ["image upload", "video upload", "URL"]

    assert _default_source_type_index([make_video_source("source-a")], options) == 1
    assert _default_source_type_index([], options) == 0


def test_completed_frame_extraction_maps_to_view_edit_state() -> None:
    """Completed frame extraction should not present extraction as the primary state."""
    completed = make_video_source("source-a", status="completed", frame_count=5)
    failed = make_video_source("source-b", status="failed", frame_count=0)

    assert frame_extraction_is_complete(completed)
    assert frame_extraction_action_label(completed) == "View/edit extracted frames"
    assert frame_extraction_action_label(failed) == "Try frame extraction again"


def test_vision_cost_notice_warns_when_catalogue_is_stale() -> None:
    """Ask users to refresh stale catalogue data before paid vision analysis."""
    message, is_warning = vision_cost_notice({"availability": "available", "freshness": "stale"}, None, 1, 600)

    assert is_warning
    assert "Refresh model catalogue" in message


def test_vision_cost_notice_estimates_when_pricing_is_available() -> None:
    """Show a rough estimate before consent when pricing is available."""
    model = {"pricing_prompt": 0.000001, "pricing_completion": 0.000002, "pricing_image": 0.0001}

    message, is_warning = vision_cost_notice({"availability": "available", "freshness": "fresh"}, model, 2, 500)

    assert not is_warning
    assert "Rough estimate for 2 frame(s)" in message


def test_stale_catalogue_collapses_llm_generation_controls() -> None:
    """Keep paid LLM controls visually secondary until catalogue data is fresh."""
    assert llm_generation_controls_expanded({"availability": "available", "freshness": "fresh"})
    assert not llm_generation_controls_expanded({"availability": "available", "freshness": "stale"})
    assert not llm_generation_controls_expanded({"availability": "unavailable", "freshness": "unavailable"})


def test_workflow_stage_statuses_detect_saved_state(tmp_path, content_project) -> None:
    """Report project, source, frame, final-pack, and video-output status."""
    video_source = make_video_source("source-a", status="completed", frame_count=3)
    (content_project.project_path / "final-pack.md").write_text("final", encoding="utf-8")
    output_dir = content_project.project_path / "outputs" / "video"
    output_dir.mkdir(parents=True)
    (output_dir / "video-output-v001.mp4").write_bytes(b"video")

    statuses = workflow_stage_statuses(content_project, [video_source], object(), object())

    assert statuses["Project"] == "loaded"
    assert statuses["Sources"] == "present"
    assert statuses["Frames"] == "extracted"
    assert statuses["Planning"] == "present"
    assert statuses["Review Pack"] == "present"
    assert statuses["Generate Video"] == "present"


def test_workflow_stage_defaults_and_guidance(content_project) -> None:
    """Default to Project without a project and allow explicit Generate Video route."""
    assert default_workflow_stage(None) == "Project"
    assert default_workflow_stage(content_project, "Generate Video") == "Generate Video"
    assert "custom prompt" in missing_stage_guidance("Generate Video")


def test_generation_lock_blocks_duplicate_and_clears_after_result(content_project) -> None:
    """Keep paid-generation lock active until terminal result is recorded."""
    session_state = {}
    request = SimpleNamespace(
        provider_name="openrouter",
        model_name="vendor/model",
        mode="text_to_video",
        duration_seconds=5,
        max_spend_usd=1.0,
        prompt_source_label="Smoke test",
    )

    lock = start_generation_lock(session_state, content_project.project_id, request, "Vendor Model")

    assert active_generation_lock(session_state, content_project.project_id) == lock
    assert duplicate_generation_warning() == "A generation job is already running. Wait for it to finish before submitting another paid request."

    result = SimpleNamespace(
        provider="openrouter",
        model="vendor/model",
        status="completed",
        provider_job_id="job-1",
        polling_url="https://openrouter.ai/api/v1/videos/job-1",
        error_type=None,
        error_message=None,
        metadata_path=Path("outputs/video/video-output-v001.json"),
        output_path=Path("outputs/video/video-output-v001.mp4"),
    )
    finish_generation_lock(session_state, content_project.project_id, result)

    assert active_generation_lock(session_state, content_project.project_id) is None
    assert session_state["video_generation_last_result"]["job_id"] == "job-1"


def test_generation_lock_can_be_cleared_explicitly(content_project) -> None:
    """Allow explicit stale/failed lock reset."""
    session_state = {VIDEO_GENERATION_LOCK_KEY: {"project_id": content_project.project_id}}

    clear_generation_lock(session_state)

    assert VIDEO_GENERATION_LOCK_KEY not in session_state
