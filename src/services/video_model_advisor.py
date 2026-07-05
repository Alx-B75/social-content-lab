"""Advisor for video generation route and provider/model selection."""

from pydantic import BaseModel, Field

from src.models.planning import ClarifyingAnswers, ContentPack
from src.models.project import ContentProject
from src.models.source import FrameRecord
from src.services.video_generation_providers import (
    IMAGE_TO_VIDEO,
    TEXT_TO_VIDEO,
    VideoModelCapability,
    collect_video_model_capabilities,
)


class VideoModelRecommendation(BaseModel):
    """Recommendation for one video generation job."""

    recommended_mode: str
    provider_name: str
    model_name: str
    display_name: str
    reason: list[str] = Field(default_factory=list)
    cost_estimate: str = "unknown"
    known_limitations: list[str] = Field(default_factory=list)
    inputs_that_would_be_sent: list[str] = Field(default_factory=list)
    risk_notes: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    human_review_required: bool = True
    capability_confidence: str = "unknown"

    @property
    def provider_model_id(self) -> str:
        """Return the selected provider/model identifier."""
        return f"{self.provider_name}/{self.model_name}"


def recommend_video_model(
    project: ContentProject,
    answers: ClarifyingAnswers | None,
    content_pack: ContentPack | None,
    prompt_text: str,
    selected_frames: list[FrameRecord],
    user_preference: str = "balanced",
    requested_mode: str | None = None,
    duration_seconds: int | None = None,
    aspect_ratio: str | None = None,
    capabilities: list[VideoModelCapability] | None = None,
) -> VideoModelRecommendation:
    """Recommend a video generation route and provider/model."""
    available = _eligible_capabilities(capabilities or collect_video_model_capabilities())
    positive_frames = _usable_frame_references(selected_frames)
    mode = requested_mode or (IMAGE_TO_VIDEO if positive_frames else TEXT_TO_VIDEO)
    candidates = [capability for capability in available if mode in capability.modes]
    if mode == IMAGE_TO_VIDEO:
        candidates = [capability for capability in candidates if capability.supports_reference_image]
    selected = _rank_capabilities(candidates, user_preference, duration_seconds, aspect_ratio)[0] if candidates else _fallback_capability(mode)

    reason = _reason_for_selection(mode, selected, positive_frames, user_preference)
    warnings = compatibility_warnings(selected, mode, duration_seconds, aspect_ratio)
    if not selected.configured or not selected.implemented:
        warnings.append("Real video provider not configured yet.")
    risk_notes = _risk_notes(project, answers, content_pack, prompt_text, mode, positive_frames)
    inputs = ["reviewed prompt text"]
    if mode == IMAGE_TO_VIDEO and positive_frames:
        inputs.append("one selected extracted frame image")
        inputs.append("selected frame source_id/frame_id metadata")
    if mode == IMAGE_TO_VIDEO and not positive_frames:
        warnings.append("Image-to-video was requested but no suitable selected frame reference is available.")
    return VideoModelRecommendation(
        recommended_mode=mode,
        provider_name=selected.provider_name,
        model_name=selected.model_name,
        display_name=selected.display_name,
        reason=reason,
        cost_estimate=selected.estimated_cost_band if selected.pricing_known else "unknown",
        known_limitations=selected.known_limitations,
        inputs_that_would_be_sent=inputs,
        risk_notes=risk_notes,
        warnings=_dedupe(warnings),
        capability_confidence=selected.reliability,
    )


def compatibility_warnings(
    capability: VideoModelCapability | None,
    requested_mode: str,
    duration_seconds: int | None,
    aspect_ratio: str | None,
) -> list[str]:
    """Return warnings for unsupported or unknown provider/model capability."""
    if capability is None:
        return ["Selected provider/model capability is unknown."]
    warnings: list[str] = []
    if requested_mode not in capability.modes:
        warnings.append(f"{capability.display_name} does not advertise support for {requested_mode.replace('_', '-')}.")
    if requested_mode == IMAGE_TO_VIDEO and not capability.supports_reference_image:
        warnings.append(f"{capability.display_name} does not advertise reference image support.")
    if duration_seconds is not None:
        if not capability.supported_durations_seconds:
            warnings.append(f"{capability.display_name} has unknown duration support.")
        elif duration_seconds not in capability.supported_durations_seconds:
            warnings.append(f"{capability.display_name} may not support {duration_seconds} second outputs.")
    if aspect_ratio:
        if not capability.supported_aspect_ratios:
            warnings.append(f"{capability.display_name} has unknown aspect-ratio support.")
        elif aspect_ratio not in capability.supported_aspect_ratios:
            warnings.append(f"{capability.display_name} may not support {aspect_ratio} outputs.")
    if not capability.output_download_supported:
        warnings.append(f"{capability.display_name} does not advertise downloadable output support.")
    return warnings


def manual_override_warnings(
    capability: VideoModelCapability | None,
    requested_mode: str,
    duration_seconds: int | None,
    aspect_ratio: str | None,
) -> list[str]:
    """Return warnings when a user manually overrides the advisor selection."""
    warnings = compatibility_warnings(capability, requested_mode, duration_seconds, aspect_ratio)
    if capability and not capability.pricing_known:
        warnings.append(f"{capability.display_name} has unknown pricing.")
    if capability and (not capability.configured or not capability.implemented):
        warnings.append("Real video provider not configured yet.")
    return _dedupe(warnings)


def is_helper_video_model(capability: VideoModelCapability) -> bool:
    """Return whether a capability describes a helper/router pseudo-model."""
    combined = f"{capability.provider_name}/{capability.model_name}/{capability.display_name}".lower()
    helper_terms = ["openrouter/auto", "router", "helper", "auto"]
    return any(term in combined for term in helper_terms)


def _eligible_capabilities(capabilities: list[VideoModelCapability]) -> list[VideoModelCapability]:
    """Return capabilities eligible for recommendation."""
    return [capability for capability in capabilities if not is_helper_video_model(capability)]


def _rank_capabilities(
    capabilities: list[VideoModelCapability],
    user_preference: str,
    duration_seconds: int | None,
    aspect_ratio: str | None,
) -> list[VideoModelCapability]:
    """Rank capabilities according to preference and compatibility."""
    preference = user_preference.lower()

    def score(capability: VideoModelCapability) -> tuple[int, int, int, int, int]:
        duration_penalty = 0 if duration_seconds is None or not capability.supported_durations_seconds or duration_seconds in capability.supported_durations_seconds else 1
        ratio_penalty = 0 if not aspect_ratio or not capability.supported_aspect_ratios or aspect_ratio in capability.supported_aspect_ratios else 1
        readiness_penalty = 0 if capability.configured and capability.implemented else 1
        if preference == "quality-first":
            return (readiness_penalty, duration_penalty + ratio_penalty, -capability.quality_rank, capability.price_rank, 0 if capability.pricing_known else 1)
        if preference == "cheapest sensible":
            return (readiness_penalty, capability.price_rank, duration_penalty + ratio_penalty, -capability.quality_rank, 0 if capability.pricing_known else 1)
        return (readiness_penalty, duration_penalty + ratio_penalty, capability.price_rank, -capability.quality_rank, 0 if capability.pricing_known else 1)

    return sorted(capabilities, key=score)


def _fallback_capability(mode: str) -> VideoModelCapability:
    """Return a safe fallback capability when no candidate exists."""
    return VideoModelCapability(
        provider_name="none",
        model_name="unavailable",
        display_name="No compatible video model",
        modes=[mode],
        configured=False,
        implemented=False,
        known_limitations=["No compatible provider/model capability was found."],
    )


def _usable_frame_references(frames: list[FrameRecord]) -> list[FrameRecord]:
    """Return frames that can act as positive image-to-video references."""
    return [frame for frame in frames if frame.selected_role.value in {"hero_frame", "visual_reference", "possible_background"}]


def _reason_for_selection(
    mode: str,
    selected: VideoModelCapability,
    positive_frames: list[FrameRecord],
    user_preference: str,
) -> list[str]:
    """Return plain-language selection reasons."""
    reasons = []
    if mode == IMAGE_TO_VIDEO:
        reasons.append("Selected frame references are available, so image-to-video should preserve visual and brand consistency better than text-only generation.")
    else:
        reasons.append("No suitable selected frame reference is available, so text-to-video is the safest fallback route.")
    if selected.is_mock:
        reasons.append("The mock local provider is recommended for this MVP because it exercises the workflow without spending money.")
    reasons.append(f"Preference considered: {user_preference}.")
    if positive_frames:
        reasons.append(f"{len(positive_frames)} selected frame reference(s) can inform the job.")
    return reasons


def _risk_notes(
    project: ContentProject,
    answers: ClarifyingAnswers | None,
    content_pack: ContentPack | None,
    prompt_text: str,
    mode: str,
    positive_frames: list[FrameRecord],
) -> list[str]:
    """Return risk notes for the requested video generation job."""
    combined = " ".join(
        [
            project.working_title,
            project.topic or "",
            project.director_instructions,
            prompt_text,
            answers.tone or "" if answers else "",
            answers.avoid_aesthetics or "" if answers else "",
            " ".join(content_pack.risk_notes) if content_pack else "",
        ]
    ).lower()
    notes = ["Generated video requires human review before publication."]
    if "shakespeare" in combined or "historical" in combined:
        notes.append("Historical or likeness-sensitive content can drift into generic costume drama or inaccurate fantasy imagery.")
        if mode == TEXT_TO_VIDEO:
            notes.append("Pure text-to-video may drift toward fantasy Shakespeare or generic historical imagery without a reference frame.")
    if "brand" in combined or positive_frames:
        notes.append("Check visual consistency against selected frame references and brand expectations.")
    if "text" in combined or "caption" in combined or "subtitle" in combined:
        notes.append("Generated on-screen text may be unreadable and should be reviewed manually.")
    for frame in positive_frames:
        if frame.rights_notes:
            notes.append(f"Frame rights note for {frame.frame_id}: {frame.rights_notes}.")
        if frame.historical_or_brand_risk:
            notes.append(f"Frame risk note for {frame.frame_id}: {frame.historical_or_brand_risk}.")
    return _dedupe(notes)


def _dedupe(values: list[str]) -> list[str]:
    """Return unique values while preserving order."""
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        if value and value not in seen:
            seen.add(value)
            result.append(value)
    return result
