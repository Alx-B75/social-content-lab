"""Tests for controlled video generation workflow."""

import csv
import json
from pathlib import Path

from src.models.source import FrameRecord, FrameRole, SourceRecord, SourceReferenceStrategy, SourceType
from src.services.video_frame_extractor import save_frame_index
from src.services.video_generation import (
    VideoGenerationRequest,
    build_provider_payload,
    discover_selected_video_reference_frames,
    discover_video_prompt_sources,
    generate_video_asset,
    validate_video_generation_request,
)
from src.services.video_generation_providers import (
    IMAGE_TO_VIDEO,
    TEXT_TO_VIDEO,
    VideoModelCapability,
    VideoProviderGenerationRequest,
    VideoProviderGenerationResult,
)


class FakeMockProvider:
    """Test provider that writes a deterministic output file."""

    provider_name = "fake"

    def list_models(self) -> list[VideoModelCapability]:
        """Return fake model capabilities."""
        return [fake_capability()]

    def generate(
        self,
        model_name: str,
        request: VideoProviderGenerationRequest,
        target_output_path: Path,
    ) -> VideoProviderGenerationResult:
        """Write fake MP4 bytes."""
        target_output_path.parent.mkdir(parents=True, exist_ok=True)
        target_output_path.write_bytes(b"fake mp4")
        return VideoProviderGenerationResult(status="mock_completed", output_path=target_output_path, cost="free/manual")


def fake_capability() -> VideoModelCapability:
    """Return fake mock capability."""
    return VideoModelCapability(
        provider_name="fake",
        model_name="mock-video",
        display_name="Fake mock video",
        modes=[TEXT_TO_VIDEO, IMAGE_TO_VIDEO],
        supports_reference_image=True,
        supported_durations_seconds=[5, 10],
        supported_aspect_ratios=["9:16"],
        pricing_known=True,
        estimated_cost_band="free/manual",
        configured=True,
        implemented=True,
        is_mock=True,
    )


def real_capability() -> VideoModelCapability:
    """Return fake real capability."""
    return VideoModelCapability(
        provider_name="real",
        model_name="paid-video",
        display_name="Paid video",
        modes=[TEXT_TO_VIDEO],
        pricing_known=False,
        configured=True,
        implemented=True,
        is_mock=False,
    )


def make_frame(tmp_path: Path) -> FrameRecord:
    """Return a selected frame reference."""
    frame_path = tmp_path / "frame.jpg"
    frame_path.write_bytes(b"frame")
    return FrameRecord(
        frame_id="frame-1",
        source_id="video-1",
        file_name="frame.jpg",
        relative_path=Path("sources/frames/frame.jpg"),
        absolute_path=frame_path,
        label="start",
        selected_role=FrameRole.HERO_FRAME,
        description="Reviewed frame",
        needs_human_review=False,
    )


def test_prompt_source_discovery_priority(content_project) -> None:
    """Discover final, LLM, deterministic, and custom prompts in priority order."""
    (content_project.project_path / "prompts.md").write_text("deterministic", encoding="utf-8")
    (content_project.project_path / "prompts.llm.md").write_text("llm", encoding="utf-8")
    (content_project.project_path / "final-prompts.md").write_text("final", encoding="utf-8")

    sources = discover_video_prompt_sources(content_project, "custom")

    assert [source.source_id for source in sources] == ["final-prompts.md", "prompts.llm.md", "prompts.md", "custom"]
    assert sources[0].text == "final"


def test_selected_frame_reference_discovery(tmp_path, content_project) -> None:
    """Load selected positive frame references from source frame indexes."""
    frame = make_frame(tmp_path)
    index_path = tmp_path / "frame-index.json"
    save_frame_index("video-1", index_path, [frame])
    source = SourceRecord(
        source_id="video-1",
        source_type=SourceType.VIDEO,
        strategy=SourceReferenceStrategy.KEYFRAME_EXTRACTION_NEEDED,
        stored_path=tmp_path / "full-uploaded-video.mp4",
        frame_index_path=index_path,
    )

    frames = discover_selected_video_reference_frames([source])

    assert [item.frame_id for item in frames] == ["frame-1"]


def test_generation_validation_consent_and_mock_rules(tmp_path) -> None:
    """Require consent for real providers but not mock providers."""
    request = VideoGenerationRequest(
        provider_name="real",
        model_name="paid-video",
        mode=TEXT_TO_VIDEO,
        prompt_source_label="Custom",
        prompt_source_id="custom",
        prompt="Prompt",
        consent_checked=False,
    )
    mock_request = request.model_copy(update={"provider_name": "fake", "model_name": "mock-video"})

    assert any("consent" in error for error in validate_video_generation_request(request, real_capability()))
    assert validate_video_generation_request(mock_request, fake_capability()) == []


def test_mock_generation_saves_versioned_output_metadata_and_asset_log(tmp_path, content_project) -> None:
    """Mock generation writes versioned outputs, metadata, and generated asset-log rows."""
    request = VideoGenerationRequest(
        provider_name="fake",
        model_name="mock-video",
        mode=TEXT_TO_VIDEO,
        prompt_source_label="Custom prompt",
        prompt_source_id="custom",
        prompt=r"Create teaser sk-or-v1-1234567890abcdefghijklmnop from C:\private\source.mp4",
        negative_prompt="OPENROUTER_API_KEY=secret",
        duration_seconds=5,
        aspect_ratio="9:16",
    )

    first = generate_video_asset(content_project, request, providers=[FakeMockProvider()], capabilities=[fake_capability()])
    second = generate_video_asset(content_project, request, providers=[FakeMockProvider()], capabilities=[fake_capability()])
    metadata = json.loads(first.metadata_path.read_text(encoding="utf-8"))
    rows = list(csv.DictReader((content_project.project_path / "asset-log.csv").open("r", encoding="utf-8", newline="")))

    assert first.output_path and first.output_path.name == "video-output-v001.mp4"
    assert second.output_path and second.output_path.name == "video-output-v002.mp4"
    assert first.metadata_path.name == "video-output-v001.json"
    assert metadata["status"] == "mock_completed"
    assert metadata["human_review_required"] is True
    assert "[redacted]" in json.dumps(metadata["provider_payload"])
    assert "C:\\private" not in json.dumps(metadata["provider_payload"])
    assert rows[0]["source_or_generated"] == "generated_video"
    assert rows[0]["keep_reject"] == "needs_review"


def test_provider_payload_excludes_absolute_paths_and_full_uploaded_videos(tmp_path) -> None:
    """Provider payload keeps local paths and full uploaded videos out of remote-bound data."""
    frame = make_frame(tmp_path)
    request = VideoGenerationRequest(
        provider_name="fake",
        model_name="mock-video",
        mode=IMAGE_TO_VIDEO,
        prompt_source_label="Custom prompt",
        prompt_source_id="custom",
        prompt="Prompt",
        reference_frame=frame,
        duration_seconds=5,
        aspect_ratio="9:16",
    )

    payload = build_provider_payload(request)
    serialized = json.dumps(payload)

    assert str(frame.absolute_path) not in serialized
    assert "full-uploaded-video.mp4" not in serialized
    assert payload["reference_frame"]["frame_id"] == "frame-1"


def test_unsupported_provider_mode_returns_safe_error_metadata(content_project) -> None:
    """Unsupported provider/mode fails safely and saves error metadata."""
    capability = VideoModelCapability(
        provider_name="fake",
        model_name="text-only",
        display_name="Text only",
        modes=[TEXT_TO_VIDEO],
        configured=True,
        implemented=True,
        is_mock=True,
    )
    request = VideoGenerationRequest(
        provider_name="fake",
        model_name="text-only",
        mode=IMAGE_TO_VIDEO,
        prompt_source_label="Custom prompt",
        prompt_source_id="custom",
        prompt="Prompt",
        duration_seconds=5,
        aspect_ratio="9:16",
    )

    result = generate_video_asset(content_project, request, providers=[FakeMockProvider()], capabilities=[capability])
    metadata = json.loads(result.metadata_path.read_text(encoding="utf-8"))

    assert result.status == "failed"
    assert result.error_type == "validation_failed"
    assert metadata["status"] == "failed"
    assert "does not support" in metadata["error_message"]
