"""Video generation workflow services."""

import csv
import hashlib
import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field

from src.models.project import ContentProject
from src.models.source import FrameRecord
from src.services.file_utils import ensure_directory, read_text_file, write_text_file
from src.services.frame_summary import positive_frame_references
from src.services.video_frame_extractor import load_frame_index
from src.services.video_generation_providers import (
    IMAGE_TO_VIDEO,
    TEXT_TO_VIDEO,
    VideoGenerationProvider,
    VideoModelCapability,
    VideoProviderGenerationRequest,
    VideoProviderGenerationResult,
    classify_provider_error,
    collect_video_model_capabilities,
    default_video_providers,
    provider_by_name,
)
from src.services.video_model_advisor import VideoModelRecommendation, compatibility_warnings


class PromptSource(BaseModel):
    """A prompt source discovered from project files or custom input."""

    label: str
    source_id: str
    path: Path | None = None
    text: str


class VideoGenerationRequest(BaseModel):
    """Validated app-level video generation request."""

    provider_name: str
    model_name: str
    mode: str
    prompt_source_label: str
    prompt_source_id: str
    prompt: str
    negative_prompt: str = ""
    reference_frame: FrameRecord | None = None
    duration_seconds: int = 5
    aspect_ratio: str = "9:16"
    seed: int | None = None
    settings: dict[str, Any] = Field(default_factory=dict)
    consent_checked: bool = False


class VideoGenerationResult(BaseModel):
    """Persisted app-level generation result."""

    provider: str
    model: str
    mode: str
    prompt_source: str
    status: str
    metadata_path: Path
    output_path: Path | None = None
    warnings: list[str] = Field(default_factory=list)
    error_type: str | None = None
    error_message: str | None = None
    provider_payload: dict[str, Any] = Field(default_factory=dict)


def discover_video_prompt_sources(project: ContentProject, custom_prompt: str = "") -> list[PromptSource]:
    """Discover available video prompt sources in priority order."""
    candidates = [
        ("Final reviewed prompts", "final-prompts.md"),
        ("LLM-assisted prompts", "prompts.llm.md"),
        ("Deterministic prompts", "prompts.md"),
    ]
    sources: list[PromptSource] = []
    for label, filename in candidates:
        path = project.project_path / filename
        if not path.exists():
            continue
        text = read_text_file(path).strip()
        if text:
            sources.append(PromptSource(label=label, source_id=filename, path=path, text=text))
    if custom_prompt.strip():
        sources.append(PromptSource(label="Custom prompt", source_id="custom", text=custom_prompt.strip()))
    return sources


def discover_selected_video_reference_frames(sources: list[Any]) -> list[FrameRecord]:
    """Return selected positive extracted frame references for image-to-video."""
    frames: list[FrameRecord] = []
    for source in sources:
        frame_index_path = getattr(source, "frame_index_path", None)
        if frame_index_path:
            frames.extend(load_frame_index(frame_index_path))
    return positive_frame_references(frames)


def default_video_generation_mode(frames: list[FrameRecord]) -> str:
    """Return the default generation mode for available inputs."""
    return IMAGE_TO_VIDEO if frames else TEXT_TO_VIDEO


def default_negative_prompt(risk_notes: list[str] | None = None, avoidances: str | None = None) -> str:
    """Build a practical negative prompt from avoidances and common risks."""
    defaults = [
        "fantasy Shakespeare",
        "exaggerated theatre masks",
        "fake parchment cliches",
        "modern actor likeness",
        "unreadable text",
        "cheap AI look",
    ]
    extras = []
    if avoidances:
        extras.append(avoidances)
    if risk_notes:
        extras.extend(note for note in risk_notes if "avoid" in note.lower() or "risk" in note.lower())
    return ", ".join(_dedupe([*defaults, *extras]))


def validate_video_generation_request(
    request: VideoGenerationRequest,
    capability: VideoModelCapability | None,
) -> list[str]:
    """Return validation errors that block generation."""
    errors: list[str] = []
    if not request.prompt.strip():
        errors.append("Prompt text is required.")
    if request.mode not in {TEXT_TO_VIDEO, IMAGE_TO_VIDEO}:
        errors.append("Generation mode is unsupported.")
    if request.mode == IMAGE_TO_VIDEO:
        if request.reference_frame is None:
            errors.append("Image-to-video requires a selected frame reference.")
        elif not request.reference_frame.absolute_path.exists():
            errors.append("Selected reference frame image is missing locally.")
    if capability is None:
        errors.append("Selected provider/model capability is unknown.")
    else:
        if request.mode not in capability.modes:
            errors.append("Selected provider/model does not support the requested generation mode.")
        if request.mode == IMAGE_TO_VIDEO and not capability.supports_reference_image:
            errors.append("Selected provider/model does not support reference images.")
        if not capability.is_mock and not request.consent_checked:
            errors.append("Explicit paid/remote provider consent is required.")
        if not capability.is_mock and (not capability.configured or not capability.implemented):
            errors.append("Real video provider not configured yet.")
    return errors


def build_provider_payload(request: VideoGenerationRequest) -> dict[str, Any]:
    """Build a provider payload that excludes local paths and secrets."""
    payload: dict[str, Any] = {
        "mode": request.mode,
        "prompt": _sanitize_provider_text(request.prompt),
        "negative_prompt": _sanitize_provider_text(request.negative_prompt),
        "duration_seconds": request.duration_seconds,
        "aspect_ratio": request.aspect_ratio,
        "seed": request.seed,
        "settings": request.settings,
    }
    if request.reference_frame is not None:
        payload["reference_frame"] = {
            "source_id": request.reference_frame.source_id,
            "frame_id": request.reference_frame.frame_id,
            "file_name": request.reference_frame.file_name,
            "role": request.reference_frame.selected_role.value,
        }
    return payload


def generate_video_asset(
    project: ContentProject,
    request: VideoGenerationRequest,
    advisor_recommendation: VideoModelRecommendation | None = None,
    providers: list[VideoGenerationProvider] | None = None,
    capabilities: list[VideoModelCapability] | None = None,
) -> VideoGenerationResult:
    """Generate or mock-generate a video asset and save metadata."""
    registry = providers or default_video_providers()
    capability = _capability_for(capabilities or collect_video_model_capabilities(registry), request.provider_name, request.model_name)
    output_path, metadata_path = _next_video_output_paths(project)
    provider_payload = build_provider_payload(request)
    validation_errors = validate_video_generation_request(request, capability)
    if validation_errors:
        result = VideoProviderGenerationResult(
            status="failed",
            error_type="validation_failed",
            error_message=" ".join(validation_errors),
            warnings=validation_errors,
        )
        metadata = _metadata(project, request, provider_payload, result, output_path if output_path.exists() else None, metadata_path, advisor_recommendation, capability)
        write_text_file(metadata_path, json.dumps(metadata, indent=2))
        return _app_result(request, result, metadata_path, provider_payload)

    provider = provider_by_name(registry, request.provider_name)
    if provider is None:
        result = VideoProviderGenerationResult(
            status="failed",
            error_type="provider_not_found",
            error_message="Selected provider was not found.",
        )
        metadata = _metadata(project, request, provider_payload, result, None, metadata_path, advisor_recommendation, capability)
        write_text_file(metadata_path, json.dumps(metadata, indent=2))
        return _app_result(request, result, metadata_path, provider_payload)

    provider_request = VideoProviderGenerationRequest(
        mode=request.mode,
        prompt=request.prompt,
        negative_prompt=request.negative_prompt,
        duration_seconds=request.duration_seconds,
        aspect_ratio=request.aspect_ratio,
        seed=request.seed,
        settings=request.settings,
        reference_image_path=request.reference_frame.absolute_path if request.reference_frame else None,
        provider_payload=provider_payload,
    )
    try:
        provider_result = provider.generate(request.model_name, provider_request, output_path)
    except Exception as error:
        error_type, error_message = classify_provider_error(error)
        provider_result = VideoProviderGenerationResult(status="failed", error_type=error_type, error_message=error_message)

    actual_output_path = provider_result.output_path if provider_result.output_path and provider_result.output_path.exists() else None
    metadata = _metadata(project, request, provider_payload, provider_result, actual_output_path, metadata_path, advisor_recommendation, capability)
    write_text_file(metadata_path, json.dumps(metadata, indent=2))
    if provider_result.status != "failed":
        _upsert_generated_video_asset_log(project, metadata)
    return _app_result(request, provider_result, metadata_path, provider_payload)


def _next_video_output_paths(project: ContentProject) -> tuple[Path, Path]:
    """Return versioned video and metadata paths without overwriting outputs."""
    output_dir = ensure_directory(project.project_path / "outputs" / "video")
    counter = 1
    while True:
        stem = f"video-output-v{counter:03d}"
        output_path = output_dir / f"{stem}.mp4"
        metadata_path = output_dir / f"{stem}.json"
        if not output_path.exists() and not metadata_path.exists():
            return output_path, metadata_path
        counter += 1


def _metadata(
    project: ContentProject,
    request: VideoGenerationRequest,
    provider_payload: dict[str, Any],
    provider_result: VideoProviderGenerationResult,
    output_path: Path | None,
    metadata_path: Path,
    advisor_recommendation: VideoModelRecommendation | None,
    capability: VideoModelCapability | None,
) -> dict[str, Any]:
    """Build safe generation metadata."""
    reference = None
    if request.reference_frame is not None:
        reference = {
            "source_id": request.reference_frame.source_id,
            "frame_id": request.reference_frame.frame_id,
            "file_name": request.reference_frame.file_name,
            "role": request.reference_frame.selected_role.value,
            "needs_human_review": request.reference_frame.needs_human_review,
        }
    output_relative = _relative_to_project(project, output_path) if output_path else None
    warnings = list(provider_result.warnings)
    if capability is not None:
        warnings.extend(compatibility_warnings(capability, request.mode, request.duration_seconds, request.aspect_ratio))
    if advisor_recommendation:
        warnings.extend(advisor_recommendation.warnings)
    return {
        "provider": request.provider_name,
        "model": request.model_name,
        "mode": request.mode,
        "prompt_source": request.prompt_source_label,
        "prompt_source_id": request.prompt_source_id,
        "prompt_hash": hashlib.sha256(request.prompt.encode("utf-8")).hexdigest(),
        "prompt_summary": _summarize(request.prompt),
        "negative_prompt": _sanitize_provider_text(request.negative_prompt),
        "reference_frame": reference,
        "duration_seconds": request.duration_seconds,
        "aspect_ratio": request.aspect_ratio,
        "created_timestamp": datetime.now(timezone.utc).isoformat(),
        "status": provider_result.status,
        "cost": provider_result.cost or (capability.estimated_cost_band if capability and capability.pricing_known else None),
        "local_output_relative_path": output_relative,
        "metadata_relative_path": _relative_to_project(project, metadata_path),
        "warnings": _dedupe(warnings),
        "advisor_recommendation_summary": advisor_recommendation.model_dump(mode="json") if advisor_recommendation else None,
        "provider_payload": provider_payload,
        "provider_job_id": provider_result.provider_job_id,
        "error_type": provider_result.error_type,
        "error_message": provider_result.error_message,
        "human_review_required": True,
    }


def _app_result(
    request: VideoGenerationRequest,
    result: VideoProviderGenerationResult,
    metadata_path: Path,
    provider_payload: dict[str, Any],
) -> VideoGenerationResult:
    """Convert a provider result to an app-level result."""
    return VideoGenerationResult(
        provider=request.provider_name,
        model=request.model_name,
        mode=request.mode,
        prompt_source=request.prompt_source_label,
        status=result.status,
        metadata_path=metadata_path,
        output_path=result.output_path if result.output_path and result.output_path.exists() else None,
        warnings=result.warnings,
        error_type=result.error_type,
        error_message=result.error_message,
        provider_payload=provider_payload,
    )


def _upsert_generated_video_asset_log(project: ContentProject, metadata: dict[str, Any]) -> None:
    """Append or update an asset-log row for generated video metadata."""
    asset_log_path = project.project_path / "asset-log.csv"
    columns = [
        "asset_id",
        "project_id",
        "source_or_generated",
        "file_name",
        "tool_or_model",
        "estimated_cost_band",
        "time_spent_minutes",
        "rating",
        "historical_or_brand_risk",
        "keep_reject",
        "notes",
    ]
    rows = _read_csv_rows(asset_log_path)
    metadata_path = Path(str(metadata.get("metadata_relative_path") or "outputs/video/video-output.json"))
    asset_id = f"generated-video-{metadata_path.stem}"
    row = {
        "asset_id": asset_id,
        "project_id": project.project_id,
        "source_or_generated": "generated_video",
        "file_name": str(metadata.get("local_output_relative_path") or metadata.get("metadata_relative_path") or ""),
        "tool_or_model": f"{metadata['provider']}/{metadata['model']}",
        "estimated_cost_band": str(metadata.get("cost") or "unknown"),
        "time_spent_minutes": "",
        "rating": "unrated",
        "historical_or_brand_risk": "needs_review",
        "keep_reject": "needs_review",
        "notes": "Generated video asset requires human review before publication",
    }
    existing = next((item for item in rows if item.get("asset_id") == asset_id), None)
    if existing is None:
        rows.append(row)
    else:
        existing.update(row)
    with asset_log_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=columns)
        writer.writeheader()
        writer.writerows(rows)


def _capability_for(capabilities: list[VideoModelCapability], provider_name: str, model_name: str) -> VideoModelCapability | None:
    """Return a capability for a provider/model pair."""
    return next((capability for capability in capabilities if capability.provider_name == provider_name and capability.model_name == model_name), None)


def _read_csv_rows(path: Path) -> list[dict[str, str]]:
    """Read CSV rows when the file exists."""
    if not path.exists():
        return []
    with path.open("r", encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


def _relative_to_project(project: ContentProject, path: Path | None) -> str | None:
    """Return a project-relative path string."""
    if path is None:
        return None
    try:
        return path.relative_to(project.project_path).as_posix()
    except ValueError:
        return path.name


def _summarize(text: str, limit: int = 360) -> str:
    """Return a compact one-line text summary."""
    cleaned = " ".join(text.split())
    if len(cleaned) <= limit:
        return _sanitize_provider_text(cleaned)
    return _sanitize_provider_text(f"{cleaned[: limit - 3]}...")


def _sanitize_provider_text(text: str) -> str:
    """Redact secrets and local paths from provider payloads and metadata."""
    redacted = re.sub(
        r"(?i)(?:OPENROUTER_API_KEY|OPENAI_API_KEY|FAL_KEY|REPLICATE_API_TOKEN|ELEVENLABS_API_KEY)\s*=\s*\S+|(?:sk-or-v1|sk)-[A-Za-z0-9_-]{8,}",
        "[redacted]",
        text,
    )
    redacted = re.sub(r"[A-Za-z]:[\\/][^\s`'\"<>]+", "[local-path-redacted]", redacted)
    redacted = re.sub(r"(?i)(?:content|cache)[\\/][^\s`'\"<>]+", "[local-path-redacted]", redacted)
    return redacted


def _dedupe(values: list[str]) -> list[str]:
    """Return unique values while preserving order."""
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        if value and value not in seen:
            seen.add(value)
            result.append(value)
    return result
