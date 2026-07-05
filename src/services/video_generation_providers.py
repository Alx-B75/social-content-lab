"""Provider abstractions for video generation workflows."""

import shutil
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Protocol

from pydantic import BaseModel, Field

from src.config import AppConfig


VideoGenerationMode = str
TEXT_TO_VIDEO = "text_to_video"
IMAGE_TO_VIDEO = "image_to_video"


class VideoModelCapability(BaseModel):
    """Describes one video provider/model option."""

    provider_name: str
    model_name: str
    display_name: str
    modes: list[str]
    supports_reference_image: bool = False
    supported_durations_seconds: list[int] = Field(default_factory=list)
    supported_aspect_ratios: list[str] = Field(default_factory=list)
    supported_resolutions: list[str] = Field(default_factory=list)
    supported_sizes: list[str] = Field(default_factory=list)
    supported_frame_images: list[str] = Field(default_factory=list)
    output_download_supported: bool = True
    pricing_known: bool = False
    estimated_cost: float | None = None
    estimated_cost_band: str = "unknown"
    cost_estimate_confidence: str = "unavailable"
    cost_estimate_note: str = "Cost estimate unavailable."
    configured: bool = False
    implemented: bool = False
    is_mock: bool = False
    quality_rank: int = 1
    price_rank: int = 3
    reliability: str = "unknown"
    known_limitations: list[str] = Field(default_factory=list)
    capability_metadata: dict[str, Any] = Field(default_factory=dict)

    @property
    def provider_model_id(self) -> str:
        """Return the stable provider/model identifier."""
        return f"{self.provider_name}/{self.model_name}"


@dataclass
class VideoProviderGenerationRequest:
    """Provider-facing video generation request."""

    mode: str
    prompt: str
    negative_prompt: str = ""
    duration_seconds: int = 5
    aspect_ratio: str = "9:16"
    seed: int | None = None
    settings: dict[str, Any] = field(default_factory=dict)
    reference_image_path: Path | None = None
    provider_payload: dict[str, Any] = field(default_factory=dict)


@dataclass
class VideoProviderGenerationResult:
    """Result returned by a video provider."""

    status: str
    output_path: Path | None = None
    cost: str | None = None
    warnings: list[str] = field(default_factory=list)
    provider_job_id: str | None = None
    error_type: str | None = None
    error_message: str | None = None
    raw_metadata: dict[str, Any] = field(default_factory=dict)


class VideoGenerationProvider(Protocol):
    """Protocol implemented by video generation providers."""

    provider_name: str

    def list_models(self) -> list[VideoModelCapability]:
        """Return available models for this provider."""

    def generate(
        self,
        model_name: str,
        request: VideoProviderGenerationRequest,
        target_output_path: Path,
    ) -> VideoProviderGenerationResult:
        """Generate a video or safe placeholder artifact."""


class MockLocalVideoProvider:
    """Local mock provider that can exercise the workflow without paid calls."""

    provider_name = "mock"
    model_name = "local-placeholder"

    def list_models(self) -> list[VideoModelCapability]:
        """Return the local placeholder model capability."""
        return [
            VideoModelCapability(
                provider_name=self.provider_name,
                model_name=self.model_name,
                display_name="Mock local placeholder",
                modes=[TEXT_TO_VIDEO, IMAGE_TO_VIDEO],
                supports_reference_image=True,
                supported_durations_seconds=[5, 10],
                supported_aspect_ratios=["9:16", "1:1", "16:9"],
                output_download_supported=True,
                pricing_known=True,
                estimated_cost_band="free/manual",
                configured=True,
                implemented=True,
                is_mock=True,
                quality_rank=1,
                price_rank=1,
                reliability="local deterministic placeholder",
                known_limitations=["Creates a placeholder artifact only; it is not provider-generated video."],
            )
        ]

    def generate(
        self,
        model_name: str,
        request: VideoProviderGenerationRequest,
        target_output_path: Path,
    ) -> VideoProviderGenerationResult:
        """Create a local placeholder MP4 when FFmpeg is available."""
        if model_name != self.model_name:
            return VideoProviderGenerationResult(
                status="failed",
                error_type="unsupported_model",
                error_message=f"Mock provider does not support model `{model_name}`.",
            )

        ffmpeg_path = shutil.which("ffmpeg")
        if not ffmpeg_path:
            return VideoProviderGenerationResult(
                status="mock_completed_no_video",
                warnings=["FFmpeg is unavailable, so the mock provider saved metadata only."],
            )

        target_output_path.parent.mkdir(parents=True, exist_ok=True)
        width, height = _dimensions_for_aspect_ratio(request.aspect_ratio)
        command = [
            ffmpeg_path,
            "-y",
            "-f",
            "lavfi",
            "-i",
            f"color=c=black:s={width}x{height}:d={max(request.duration_seconds, 1)}",
            "-vf",
            "drawtext=text='Mock video generation placeholder':fontcolor=white:fontsize=36:x=(w-text_w)/2:y=(h-text_h)/2",
            "-pix_fmt",
            "yuv420p",
            str(target_output_path),
        ]
        completed = subprocess.run(command, capture_output=True, text=True, check=False)
        if completed.returncode != 0 or not target_output_path.exists():
            return VideoProviderGenerationResult(
                status="mock_completed_no_video",
                warnings=["FFmpeg placeholder MP4 creation failed, so the mock provider saved metadata only."],
                raw_metadata={"ffmpeg_error": completed.stderr[-1000:]},
            )

        return VideoProviderGenerationResult(
            status="mock_completed",
            output_path=target_output_path,
            cost="free/manual",
            warnings=["Mock provider output is a local placeholder and requires human review."],
        )


class UnconfiguredVideoProvider:
    """Future-provider placeholder that never performs paid or remote calls."""

    def __init__(self, capability: VideoModelCapability) -> None:
        """Initialise the unconfigured provider with its capability metadata."""
        self.capability = capability
        self.provider_name = capability.provider_name

    def list_models(self) -> list[VideoModelCapability]:
        """Return the future provider capability."""
        return [self.capability]

    def generate(
        self,
        model_name: str,
        request: VideoProviderGenerationRequest,
        target_output_path: Path,
    ) -> VideoProviderGenerationResult:
        """Return a safe not-configured error."""
        return VideoProviderGenerationResult(
            status="failed",
            error_type="provider_not_configured",
            error_message="Real video provider not configured yet.",
        )


def default_video_providers(config: AppConfig | None = None, openrouter_video_catalog: dict[str, Any] | None = None) -> list[VideoGenerationProvider]:
    """Return the MVP provider registry."""
    providers: list[VideoGenerationProvider] = [
        MockLocalVideoProvider(),
        UnconfiguredVideoProvider(
            VideoModelCapability(
                provider_name="future-fal",
                model_name="image-to-video",
                display_name="Future fal.ai image-to-video",
                modes=[IMAGE_TO_VIDEO],
                supports_reference_image=True,
                supported_durations_seconds=[5, 10],
                supported_aspect_ratios=["9:16", "16:9"],
                output_download_supported=True,
                pricing_known=False,
                configured=False,
                implemented=False,
                quality_rank=3,
                price_rank=3,
                reliability="not configured",
                known_limitations=["Integration placeholder only. No remote calls are implemented."],
            )
        ),
        UnconfiguredVideoProvider(
            VideoModelCapability(
                provider_name="future-replicate",
                model_name="text-to-video",
                display_name="Future Replicate text-to-video",
                modes=[TEXT_TO_VIDEO],
                supports_reference_image=False,
                supported_durations_seconds=[5],
                supported_aspect_ratios=["9:16", "1:1", "16:9"],
                output_download_supported=True,
                pricing_known=False,
                configured=False,
                implemented=False,
                quality_rank=2,
                price_rank=3,
                reliability="not configured",
                known_limitations=["Integration placeholder only. No remote calls are implemented."],
            )
        ),
    ]
    if config and config.openrouter_api_key:
        from src.services.openrouter_video import OpenRouterVideoProvider

        providers.append(OpenRouterVideoProvider(config, openrouter_video_catalog))
    return providers


def collect_video_model_capabilities(providers: list[VideoGenerationProvider] | None = None) -> list[VideoModelCapability]:
    """Return all capability records from the provider registry."""
    registry = providers or default_video_providers()
    capabilities: list[VideoModelCapability] = []
    for provider in registry:
        capabilities.extend(provider.list_models())
    return capabilities


def provider_by_name(providers: list[VideoGenerationProvider], provider_name: str) -> VideoGenerationProvider | None:
    """Return a provider from a registry by name."""
    return next((provider for provider in providers if provider.provider_name == provider_name), None)


def classify_provider_error(error: Exception) -> tuple[str, str]:
    """Classify provider errors without leaking local details."""
    message = str(error)
    lower_message = message.lower()
    if "timeout" in lower_message:
        return "timeout", "Provider request timed out."
    if "401" in lower_message or "403" in lower_message or "auth" in lower_message:
        return "authentication_failed", "Provider authentication failed."
    if "rate" in lower_message:
        return "rate_limited", "Provider rate limit was reached."
    return "provider_error", "Video provider call failed."


def _dimensions_for_aspect_ratio(aspect_ratio: str) -> tuple[int, int]:
    """Return conservative placeholder dimensions for a requested aspect ratio."""
    mapping = {
        "9:16": (720, 1280),
        "16:9": (1280, 720),
        "1:1": (1024, 1024),
    }
    return mapping.get(aspect_ratio, (720, 1280))
