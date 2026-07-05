"""Tests for video model/provider recommendations."""

from pathlib import Path

from src.models.planning import ClarifyingAnswers, ContentPack
from src.models.source import FrameRecord, FrameRole
from src.services.video_generation_providers import IMAGE_TO_VIDEO, TEXT_TO_VIDEO, VideoModelCapability
from src.services.video_model_advisor import compatibility_warnings, manual_override_warnings, recommend_video_model


def make_frame(tmp_path: Path) -> FrameRecord:
    """Return a selected frame reference."""
    path = tmp_path / "hero.jpg"
    path.write_bytes(b"image")
    return FrameRecord(
        frame_id="frame-1",
        source_id="video-1",
        file_name="hero.jpg",
        relative_path=Path("outputs/frames/hero.jpg"),
        absolute_path=path,
        label="start",
        selected_role=FrameRole.HERO_FRAME,
        description="Reviewed Shakespeare visual reference",
        needs_human_review=False,
    )


def capabilities() -> list[VideoModelCapability]:
    """Return test video capabilities."""
    return [
        VideoModelCapability(
            provider_name="openrouter",
            model_name="auto",
            display_name="OpenRouter auto helper",
            modes=[TEXT_TO_VIDEO, IMAGE_TO_VIDEO],
            supports_reference_image=True,
            configured=True,
            implemented=True,
        ),
        VideoModelCapability(
            provider_name="cheap",
            model_name="t2v",
            display_name="Cheap text model",
            modes=[TEXT_TO_VIDEO],
            supported_durations_seconds=[5],
            supported_aspect_ratios=["9:16"],
            pricing_known=True,
            estimated_cost_band="very low",
            configured=True,
            implemented=True,
            price_rank=1,
            quality_rank=1,
        ),
        VideoModelCapability(
            provider_name="quality",
            model_name="i2v",
            display_name="Quality image model",
            modes=[IMAGE_TO_VIDEO, TEXT_TO_VIDEO],
            supports_reference_image=True,
            supported_durations_seconds=[10],
            supported_aspect_ratios=["16:9"],
            pricing_known=True,
            estimated_cost_band="medium",
            configured=True,
            implemented=True,
            price_rank=4,
            quality_rank=5,
        ),
    ]


def make_pack() -> ContentPack:
    """Return a minimal pack with risk notes."""
    return ContentPack(
        core_message="Ask Shakespeare a question",
        target_platform="LinkedIn",
        recommended_format="short video",
        resolved_aspect_ratio="9:16",
        resolved_duration_seconds=10,
        script_outline=[],
        shot_list=[],
        image_prompt="",
        video_prompts=["A restrained teaser."],
        caption_drafts=[],
        asset_checklist=[],
        risk_notes=["Avoid fantasy Shakespeare and unreadable text."],
        next_actions=[],
    )


def test_recommends_image_to_video_when_selected_frame_exists(tmp_path, content_project) -> None:
    """Prefer image-to-video for selected reviewed frame references."""
    recommendation = recommend_video_model(
        content_project,
        ClarifyingAnswers(platform="LinkedIn"),
        make_pack(),
        "Create a Shakespeare teaser.",
        [make_frame(tmp_path)],
        capabilities=capabilities(),
        duration_seconds=10,
        aspect_ratio="16:9",
    )

    assert recommendation.recommended_mode == IMAGE_TO_VIDEO
    assert recommendation.provider_model_id == "quality/i2v"
    assert "one selected extracted frame image" in recommendation.inputs_that_would_be_sent
    assert any("human review" in note for note in recommendation.risk_notes)


def test_recommends_text_to_video_fallback_and_historical_drift_warning(content_project) -> None:
    """Use text-to-video fallback and warn about historical visual drift."""
    recommendation = recommend_video_model(
        content_project,
        ClarifyingAnswers(platform="LinkedIn"),
        make_pack(),
        "Create a Shakespeare teaser.",
        [],
        capabilities=capabilities(),
        duration_seconds=5,
        aspect_ratio="9:16",
    )

    assert recommendation.recommended_mode == TEXT_TO_VIDEO
    assert recommendation.provider_model_id == "cheap/t2v"
    assert not recommendation.provider_model_id.startswith("openrouter/")
    assert any("fantasy Shakespeare" in note for note in recommendation.risk_notes)


def test_preference_changes_model_ranking(content_project) -> None:
    """Respect cheapest and quality-first preference where models support the mode."""
    cheap = recommend_video_model(content_project, None, None, "Prompt", [], "cheapest sensible", TEXT_TO_VIDEO, 5, "9:16", capabilities())
    quality = recommend_video_model(content_project, None, None, "Prompt", [], "quality-first", TEXT_TO_VIDEO, 10, "16:9", capabilities())

    assert cheap.provider_model_id == "cheap/t2v"
    assert quality.provider_model_id == "quality/i2v"


def test_capability_and_manual_override_warnings() -> None:
    """Flag unsupported or unknown duration/aspect-ratio support."""
    unknown = VideoModelCapability(provider_name="unknown", model_name="model", display_name="Unknown model", modes=[TEXT_TO_VIDEO])
    mismatch = VideoModelCapability(
        provider_name="mismatch",
        model_name="model",
        display_name="Mismatch model",
        modes=[TEXT_TO_VIDEO],
        supported_durations_seconds=[5],
        supported_aspect_ratios=["1:1"],
        pricing_known=False,
    )

    assert any("unknown duration" in warning for warning in compatibility_warnings(unknown, TEXT_TO_VIDEO, 10, "9:16"))
    warnings = manual_override_warnings(mismatch, IMAGE_TO_VIDEO, 10, "9:16")
    assert any("does not advertise support" in warning for warning in warnings)
    assert any("unknown pricing" in warning for warning in warnings)
