"""Tests for OpenRouter video catalogue and provider workflow."""

import csv
import json
from pathlib import Path

from src.models.source import FrameRecord, FrameRole
from src.services.openrouter_video import (
    OpenRouterVideoProvider,
    build_openrouter_video_request_payload,
    estimate_openrouter_video_cost,
    fetch_openrouter_video_models,
    normalize_openrouter_video_model,
    openrouter_request_preview,
    openrouter_video_catalog_to_capabilities,
)
from src.services.video_generation import VideoGenerationRequest, generate_video_asset, validate_video_generation_request
from src.services.video_generation_providers import IMAGE_TO_VIDEO, TEXT_TO_VIDEO, VideoModelCapability
from src.services.video_model_advisor import recommend_video_model


class FakeResponse:
    """Minimal HTTP response fake."""

    def __init__(self, payload=None, content: bytes = b"", status_code: int = 200) -> None:
        """Initialise fake response."""
        self.payload = payload or {}
        self.content = content
        self.status_code = status_code

    def json(self):
        """Return fake JSON payload."""
        return self.payload

    def raise_for_status(self) -> None:
        """Raise no error for 2xx responses."""
        if self.status_code >= 400:
            raise RuntimeError("HTTP error")


class FakeOpenRouterHttp:
    """Fake OpenRouter HTTP client for submit, poll, and download."""

    def __init__(self, poll_payloads: list[dict[str, object]] | None = None) -> None:
        """Initialise fake HTTP client."""
        self.post_payloads: list[dict[str, object]] = []
        self.get_urls: list[str] = []
        self.poll_payloads = poll_payloads or [
            {
                "id": "job-1",
                "polling_url": "/api/v1/videos/job-1",
                "status": "completed",
                "generation_id": "gen-1",
                "usage": {"cost": 0.25},
            }
        ]

    def post(self, url: str, headers: dict[str, str], json: dict[str, object], timeout: float) -> FakeResponse:
        """Capture submit payload and return pending job."""
        self.post_payloads.append(json)
        return FakeResponse({"id": "job-1", "polling_url": "/api/v1/videos/job-1", "status": "pending"})

    def get(self, url: str, headers: dict[str, str] | None = None, timeout: float = 30.0) -> FakeResponse:
        """Return poll payloads then video bytes."""
        self.get_urls.append(url)
        if url.endswith("/content?index=0"):
            return FakeResponse(content=b"mp4 bytes")
        payload = self.poll_payloads.pop(0) if self.poll_payloads else {"id": "job-1", "status": "completed"}
        return FakeResponse(payload)


def video_catalog() -> dict[str, object]:
    """Return a normalized OpenRouter video catalogue."""
    models = [
        normalize_openrouter_video_model(
            {
                "id": "openrouter/auto",
                "name": "Auto Router",
                "supported_durations": [5],
                "supported_aspect_ratios": ["9:16"],
            }
        ),
        normalize_openrouter_video_model(
            {
                "id": "vendor/cheap-video",
                "name": "Cheap Video",
                "description": "Low-cost short video",
                "supported_durations": [5],
                "supported_resolutions": ["720p"],
                "supported_aspect_ratios": ["9:16"],
                "pricing_skus": {"per-video-second": "0.02"},
            }
        ),
        normalize_openrouter_video_model(
            {
                "id": "vendor/frame-video",
                "name": "Frame Video",
                "supported_durations": [5],
                "supported_resolutions": ["720p"],
                "supported_aspect_ratios": ["9:16"],
                "supported_frame_images": ["first_frame"],
                "pricing_skus": {"generate": "0.5"},
            }
        ),
    ]
    return {"fetch_status": "ok", "models": models, "model_count": len(models)}


def make_frame(tmp_path: Path) -> FrameRecord:
    """Return a selected frame."""
    path = tmp_path / "frame.jpg"
    path.write_bytes(b"image")
    return FrameRecord(
        frame_id="frame-1",
        source_id="source-1",
        file_name="frame.jpg",
        relative_path=Path("sources/frames/frame.jpg"),
        absolute_path=path,
        label="start",
        selected_role=FrameRole.HERO_FRAME,
    )


def openrouter_config(app_config):
    """Return app config with a fake OpenRouter key."""
    return app_config.model_copy(update={"openrouter_api_key": "sk-test-key"})


def test_video_catalog_normalizes_pricing_and_capabilities() -> None:
    """Parse model metadata and keep ambiguous video pricing low confidence."""
    model = normalize_openrouter_video_model(
        {
            "id": "google/veo-3.1-lite",
            "name": "Veo Lite",
            "supported_durations": [5, 8],
            "supported_resolutions": ["720p"],
            "supported_aspect_ratios": ["16:9", "9:16"],
            "supported_frame_images": ["first_frame"],
            "pricing_skus": {"per-video-second": "0.10"},
        }
    )
    estimate = estimate_openrouter_video_cost(model, 5, "720p")
    capabilities = openrouter_video_catalog_to_capabilities({"fetch_status": "ok", "models": [model]}, configured=True)

    assert model["supports_frame_images"] is True
    assert estimate["estimated_cost"] is None
    assert estimate["pricing_hint"] == 0.5
    assert estimate["confidence"] == "low"
    assert capabilities[0].provider_name == "openrouter"
    assert capabilities[0].supports_reference_image is True
    assert capabilities[0].estimated_cost is None
    assert capabilities[0].cost_estimate_confidence == "low"


def test_fetch_video_models_uses_mocked_http_without_live_call(monkeypatch, app_config) -> None:
    """Fetch and normalize catalogue data from a mocked OpenRouter response."""
    class FakeHttp:
        @staticmethod
        def get(url, headers, timeout):
            return FakeResponse({"data": [{"id": "vendor/video", "name": "Video", "pricing_skus": {"generate": "0.1"}}]})

    monkeypatch.setattr("src.services.openrouter_video.httpx", FakeHttp)
    catalog = fetch_openrouter_video_models(openrouter_config(app_config))

    assert catalog["fetch_status"] == "ok"
    assert catalog["models"][0]["model_id"] == "vendor/video"


def test_advisor_recommends_cheapest_openrouter_text_to_video_for_smoke(content_project) -> None:
    """Recommend low-cost OpenRouter text-to-video when available."""
    capabilities = openrouter_video_catalog_to_capabilities(video_catalog(), configured=True)
    recommendation = recommend_video_model(
        content_project,
        None,
        None,
        "A calm five-second cinematic shot of a dark teal background.",
        [],
        "cheapest sensible",
        TEXT_TO_VIDEO,
        5,
        "9:16",
        capabilities,
    )

    assert recommendation.provider_model_id == "openrouter/vendor/cheap-video"
    assert recommendation.recommended_mode == TEXT_TO_VIDEO
    assert "prompt" in recommendation.inputs_that_would_be_sent
    assert "low confidence" in recommendation.cost_estimate


def test_advisor_uses_image_to_video_only_when_frame_images_supported(tmp_path, content_project) -> None:
    """Recommend image-to-video only for models with frame-image support."""
    text_only = openrouter_video_catalog_to_capabilities({"fetch_status": "ok", "models": [video_catalog()["models"][1]]}, configured=True)
    frame_capable = openrouter_video_catalog_to_capabilities(video_catalog(), configured=True)

    fallback = recommend_video_model(content_project, None, None, "Prompt", [make_frame(tmp_path)], "balanced", IMAGE_TO_VIDEO, 5, "9:16", text_only)
    image = recommend_video_model(content_project, None, None, "Prompt", [make_frame(tmp_path)], "balanced", IMAGE_TO_VIDEO, 5, "9:16", frame_capable)

    assert fallback.recommended_mode == TEXT_TO_VIDEO
    assert image.recommended_mode == IMAGE_TO_VIDEO
    assert image.provider_model_id == "openrouter/vendor/frame-video"


def test_request_preview_and_spend_guard(tmp_path) -> None:
    """Preview request inputs and report low-confidence cost clearly."""
    capability = openrouter_video_catalog_to_capabilities(video_catalog(), configured=True)[1]
    request = VideoGenerationRequest(
        provider_name="openrouter",
        model_name=capability.model_name,
        mode=IMAGE_TO_VIDEO,
        prompt_source_label="Custom",
        prompt_source_id="custom",
        prompt=r"Prompt from C:\private\source.mp4 sk-or-v1-1234567890abcdefghijklmnop",
        negative_prompt="no text",
        reference_frame=make_frame(tmp_path),
        duration_seconds=5,
        aspect_ratio="9:16",
    )

    preview = openrouter_request_preview(request, capability, max_spend_usd=0.1)

    assert preview["reference_frame_will_be_sent"] is True
    assert preview["estimated_cost"] is None
    assert preview["pricing_hint"] == 0.5
    assert preview["cost_estimate_confidence"] == "low"
    assert "low-confidence" in preview["cost_estimate_note"]
    assert preview["spend_guard_passed"] is True


def test_real_generation_validation_requires_consent_spend_and_unknown_cost_ack() -> None:
    """Block real calls without consent, spend guard, or unknown-cost acknowledgement."""
    known = VideoModelCapability(
        provider_name="openrouter",
        model_name="vendor/video",
        display_name="Video",
        modes=[TEXT_TO_VIDEO],
        configured=True,
        implemented=True,
        estimated_cost=2.0,
        pricing_known=True,
        cost_estimate_confidence="known",
    )
    unknown = known.model_copy(update={"estimated_cost": None, "pricing_known": False, "cost_estimate_confidence": "unavailable"})
    low = known.model_copy(update={"estimated_cost": None, "pricing_known": False, "cost_estimate_confidence": "low"})
    request = VideoGenerationRequest(
        provider_name="openrouter",
        model_name="vendor/video",
        mode=TEXT_TO_VIDEO,
        prompt_source_label="Custom",
        prompt_source_id="custom",
        prompt="Prompt",
        consent_checked=False,
        max_spend_usd=1.0,
    )

    assert any("consent" in error for error in validate_video_generation_request(request, known))
    assert any("exceeds" in error for error in validate_video_generation_request(request.model_copy(update={"consent_checked": True}), known))
    assert any("Cost estimate is unavailable" in error for error in validate_video_generation_request(request.model_copy(update={"consent_checked": True}), unknown))
    assert any("low-confidence" in error for error in validate_video_generation_request(request.model_copy(update={"consent_checked": True}), low))
    assert validate_video_generation_request(request.model_copy(update={"consent_checked": True, "unknown_cost_acknowledged": True}), unknown) == []


def test_openrouter_payload_excludes_paths_keys_and_full_videos(tmp_path) -> None:
    """Build remote payload with no local paths, API keys, or full uploaded videos in logged preview."""
    capability = openrouter_video_catalog_to_capabilities(video_catalog(), configured=True)[1]
    frame = make_frame(tmp_path)
    request = VideoGenerationRequest(
        provider_name="openrouter",
        model_name=capability.model_name,
        mode=IMAGE_TO_VIDEO,
        prompt_source_label="Custom",
        prompt_source_id="custom",
        prompt=r"Prompt from C:\private\video.mp4 sk-or-v1-1234567890abcdefghijklmnop",
        reference_frame=frame,
        duration_seconds=5,
        aspect_ratio="9:16",
        settings={"source": r"C:\private\full-uploaded-video.mp4"},
    )

    payload = build_openrouter_video_request_payload(
        request.model_copy(update={"prompt": "Prompt"}),
        capability,
        include_reference_image=True,
    )
    preview_result = generate_video_asset(
        tmp_project(tmp_path),
        request.model_copy(update={"consent_checked": True, "unknown_cost_acknowledged": True}),
        providers=[],
        capabilities=[capability],
    )
    serialized_payload = json.dumps(payload)
    serialized_preview = json.dumps(preview_result.provider_payload)

    assert str(frame.absolute_path) not in serialized_payload
    assert "data:image" in serialized_payload
    assert "C:\\private" not in serialized_preview
    assert "sk-or-v1" not in serialized_preview
    assert "full-uploaded-video.mp4" not in serialized_preview


def test_openrouter_poll_download_saves_output_metadata_and_asset_log(app_config, content_project) -> None:
    """Mock successful OpenRouter submit, poll, download, metadata, and asset-log update."""
    config = openrouter_config(app_config)
    http = FakeOpenRouterHttp()
    provider = OpenRouterVideoProvider(config, video_catalog(), http_client=http, poll_interval_seconds=0, max_poll_attempts=2)
    capability = provider.list_models()[0]
    request = VideoGenerationRequest(
        provider_name="openrouter",
        model_name=capability.model_name,
        mode=TEXT_TO_VIDEO,
        prompt_source_label="Custom",
        prompt_source_id="custom",
        prompt="Prompt",
        duration_seconds=5,
        aspect_ratio="9:16",
        consent_checked=True,
        max_spend_usd=1.0,
        unknown_cost_acknowledged=True,
    )

    result = generate_video_asset(content_project, request, providers=[provider], capabilities=provider.list_models())
    metadata = json.loads(result.metadata_path.read_text(encoding="utf-8"))
    rows = list(csv.DictReader((content_project.project_path / "asset-log.csv").open("r", encoding="utf-8", newline="")))

    assert result.status == "completed"
    assert result.output_path and result.output_path.read_bytes() == b"mp4 bytes"
    assert metadata["provider"] == "openrouter"
    assert metadata["openrouter_job_id"] == "job-1"
    assert metadata["usage"]["cost"] == 0.25
    assert metadata["estimated_cost"] is None
    assert metadata["actual_cost"] == 0.25
    assert metadata["cost_estimate_confidence"] == "low"
    assert "low-confidence" in metadata["cost_estimate_note"]
    assert "C:\\private" not in json.dumps(http.post_payloads[0])
    assert "sk-or-v1" not in json.dumps(http.post_payloads[0])
    assert rows[0]["source_or_generated"] == "generated_video"


def test_openrouter_poll_timeout_returns_safe_error(app_config, content_project) -> None:
    """Return a safe failure when OpenRouter polling times out."""
    config = openrouter_config(app_config)
    http = FakeOpenRouterHttp(poll_payloads=[{"id": "job-1", "polling_url": "/api/v1/videos/job-1", "status": "in_progress"}])
    provider = OpenRouterVideoProvider(config, video_catalog(), http_client=http, poll_interval_seconds=0, max_poll_attempts=1)
    capability = provider.list_models()[0]
    request = VideoGenerationRequest(
        provider_name="openrouter",
        model_name=capability.model_name,
        mode=TEXT_TO_VIDEO,
        prompt_source_label="Custom",
        prompt_source_id="custom",
        prompt="Prompt",
        duration_seconds=5,
        aspect_ratio="9:16",
        consent_checked=True,
        max_spend_usd=1.0,
        unknown_cost_acknowledged=True,
    )

    result = generate_video_asset(content_project, request, providers=[provider], capabilities=provider.list_models())

    assert result.status == "failed"
    assert result.error_type == "timeout"
    assert result.provider_job_id == "job-1"


def tmp_project(tmp_path: Path):
    """Return a minimal project for payload safety tests."""
    from src.models.project import ContentProject

    project_path = tmp_path / "content" / "project"
    project_path.mkdir(parents=True, exist_ok=True)
    return ContentProject(
        project_id="project",
        project_name="Project",
        working_title="Project",
        director_instructions="Instructions",
        project_path=project_path,
    )
