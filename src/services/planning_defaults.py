"""Default inference and display helpers for Social Content Lab planning."""

import re

from typing import Any

from src.models.planning import ClarifyingAnswers, ProviderType, WorkflowRoute
from src.models.project import ContentProject


ROUTE_LABELS = {
    WorkflowRoute.TEXT_ONLY_PLANNING: "Text-only planning",
    WorkflowRoute.STATIC_IMAGE_POST: "Static image post",
    WorkflowRoute.CAROUSEL_POST: "Carousel post",
    WorkflowRoute.STILL_IMAGE_WITH_MOTION_VIDEO: "Still image with motion video",
    WorkflowRoute.AI_VIDEO_TEST_CLIP: "AI video test clip",
    WorkflowRoute.PREMIUM_AI_VIDEO_GENERATION: "Premium AI video generation",
    WorkflowRoute.MANUAL_EDIT_REQUIRED: "Manual edit required",
}

PROVIDER_LABELS = {
    ProviderType.MANUAL_ONLY: "Manual only",
    ProviderType.OPENROUTER_TEXT_PLANNING: "OpenRouter text planning",
    ProviderType.CANVA_OR_CAPCUT_MANUAL_EDIT: "Canva or CapCut manual edit",
    ProviderType.FAL_OR_REPLICATE_MEDIA_GENERATION: "fal.ai or Replicate media generation",
    ProviderType.PREMIUM_VIDEO_MODEL: "Premium video model",
    ProviderType.UNKNOWN: "Unknown",
}


def label_for_route(route: WorkflowRoute | str | None) -> str:
    """Return a human-readable route label."""
    if route is None:
        return "Not generated"
    try:
        route_value = route if isinstance(route, WorkflowRoute) else WorkflowRoute(route)
    except ValueError:
        return str(route).replace("_", " ").title()
    return ROUTE_LABELS.get(route_value, route_value.value.replace("_", " ").title())


def label_for_provider(provider: ProviderType | str | None) -> str:
    """Return a human-readable provider label."""
    if provider is None:
        return "Not generated"
    try:
        provider_value = provider if isinstance(provider, ProviderType) else ProviderType(provider)
    except ValueError:
        return str(provider).replace("_", " ").title()
    return PROVIDER_LABELS.get(provider_value, provider_value.value.replace("_", " ").title())


def normalize_clarifying_answers(value: Any, project: ContentProject | None = None) -> ClarifyingAnswers:
    """Upgrade dicts or stale answer model instances into the current schema."""
    if value is None:
        answers = ClarifyingAnswers()
    elif isinstance(value, ClarifyingAnswers):
        answers = ClarifyingAnswers(**value.model_dump())
    elif hasattr(value, "model_dump"):
        answers = ClarifyingAnswers(**value.model_dump())
    elif isinstance(value, dict):
        answers = ClarifyingAnswers(**value)
    else:
        answers = ClarifyingAnswers(**getattr(value, "__dict__", {}))
    platform = getattr(answers, "platform", None) or (infer_platform(project.director_instructions) if project else None)
    output_format = getattr(answers, "output_format", None) or (infer_output_format(project.director_instructions, platform) if project else None)
    extracted_duration = getattr(answers, "extracted_duration_seconds", None)
    if extracted_duration is None and project:
        extracted_duration = extract_duration_seconds(project.director_instructions)
    inferred_aspect_ratio = getattr(answers, "inferred_aspect_ratio", None) or infer_aspect_ratio(platform, output_format)
    normalized = answers.model_copy(
        update={
            "platform": platform,
            "output_format": output_format,
            "inferred_aspect_ratio": inferred_aspect_ratio,
            "extracted_duration_seconds": extracted_duration,
        }
    )
    return normalized.model_copy(
        update={
            "resolved_aspect_ratio": resolve_aspect_ratio(normalized),
            "resolved_duration_seconds": resolve_duration_seconds(project, normalized) if project else getattr(normalized, "resolved_duration_seconds", None),
        }
    )


def build_initial_answers(project: ContentProject) -> ClarifyingAnswers:
    """Build sensible initial clarifying answers from director instructions."""
    platform = infer_platform(project.director_instructions)
    output_format = infer_output_format(project.director_instructions, platform)
    inferred_aspect_ratio = infer_aspect_ratio(platform, output_format)
    extracted_duration = extract_duration_seconds(project.director_instructions)
    duration = resolve_duration_seconds(project, ClarifyingAnswers(platform=platform, output_format=output_format, extracted_duration_seconds=extracted_duration))
    return ClarifyingAnswers(
        platform=platform,
        output_format=output_format,
        inferred_aspect_ratio=inferred_aspect_ratio,
        resolved_aspect_ratio=inferred_aspect_ratio,
        extracted_duration_seconds=extracted_duration,
        target_length_seconds=duration,
        resolved_duration_seconds=duration,
        source_use=infer_source_use(project.director_instructions),
        budget_priority="best balance",
        quality_level="good enough draft",
        draft_variations=2,
        include_subtitles=True,
        include_on_screen_text=True,
        include_captions_hashtags=True,
        video_source_treatment="not applicable",
    )


def infer_platform(text: str) -> str:
    """Infer a platform from plain director instructions."""
    lower_text = text.lower()
    if "tiktok" in lower_text:
        return "TikTok"
    if "youtube shorts" in lower_text or "shorts" in lower_text:
        return "YouTube Shorts"
    if "youtube" in lower_text:
        return "YouTube standard"
    if "reel" in lower_text:
        return "Instagram Reels"
    if "instagram" in lower_text and "square" in lower_text:
        return "Instagram square"
    if "instagram" in lower_text:
        return "Instagram feed"
    if "story" in lower_text or "stories" in lower_text:
        return "Stories"
    if "website" in lower_text or "hero" in lower_text:
        return "Website hero"
    if "multi-platform" in lower_text or "multi platform" in lower_text:
        return "multi-platform"
    return "LinkedIn"


def infer_output_format(text: str, platform: str | None) -> str:
    """Infer an output format from instructions and platform."""
    lower_text = text.lower()
    platform_lower = (platform or "").lower()
    if "carousel" in lower_text:
        return "carousel"
    if "reel" in lower_text or "shorts" in platform_lower:
        return "reel"
    if "story" in lower_text or "stories" in lower_text:
        return "story"
    if "clip" in lower_text or "short video" in lower_text:
        return "short video"
    if "video" in lower_text:
        return "standard video"
    if "hero" in lower_text:
        return "website hero"
    return "static post"


def infer_aspect_ratio(platform: str | None, output_format: str | None) -> str:
    """Infer a default aspect ratio from platform and format."""
    platform_lower = (platform or "").lower()
    format_lower = (output_format or "").lower()
    if "multi" in platform_lower:
        return "variants_required"
    if "tiktok" in platform_lower or "reels" in platform_lower or "shorts" in platform_lower or "story" in platform_lower or "stories" in format_lower or "reel" in format_lower:
        return "9:16"
    if "instagram" in platform_lower and "square" in platform_lower:
        return "1:1"
    if "instagram" in platform_lower and "feed" in platform_lower:
        return "4:5"
    if "linkedin" in platform_lower and any(term in format_lower for term in ["short video", "reel"]):
        return "4:5"
    if "linkedin" in platform_lower and any(term in format_lower for term in ["landscape", "standard video", "video post"]):
        return "16:9"
    if "linkedin" in platform_lower and any(term in format_lower for term in ["static", "image", "carousel", "post"]):
        return "1:1"
    if "youtube standard" in platform_lower or "website hero" in platform_lower or "hero" in format_lower:
        return "16:9"
    return "1:1"


def extract_duration_seconds(text: str) -> int | None:
    """Extract a requested duration from director instructions."""
    pattern = re.compile(r"\b(\d{1,3})(?:\.\d+)?\s*(seconds?|secs?|s|minutes?|mins?)\b", re.IGNORECASE)
    match = pattern.search(text)
    if not match:
        return None
    value = int(match.group(1))
    unit = match.group(2).lower()
    if unit.startswith("min"):
        return value * 60
    return value


def default_duration_seconds(platform: str | None, output_format: str | None) -> int | None:
    """Return a sensible duration default for a platform and format."""
    platform_lower = (platform or "").lower()
    format_lower = (output_format or "").lower()
    if any(term in format_lower for term in ["static", "image", "carousel"]):
        return None
    if "short video" in format_lower:
        return 10
    if any(term in platform_lower for term in ["reels", "shorts", "tiktok", "stories"]) or any(term in format_lower for term in ["reel", "story", "shorts"]):
        return 15
    if "video" in format_lower:
        return 30
    return None


def resolve_duration_seconds(project: ContentProject | None, answers: ClarifyingAnswers) -> int | None:
    """Resolve final duration from answers, director instructions, and defaults."""
    target_length = getattr(answers, "target_length_seconds", None)
    if target_length:
        return target_length
    extracted_duration = getattr(answers, "extracted_duration_seconds", None)
    if extracted_duration:
        return extracted_duration
    director_instructions = getattr(project, "director_instructions", "") if project else ""
    extracted_duration = extract_duration_seconds(director_instructions)
    if extracted_duration:
        return extracted_duration
    resolved_duration = getattr(answers, "resolved_duration_seconds", None)
    if resolved_duration:
        return resolved_duration
    return default_duration_seconds(getattr(answers, "platform", None), getattr(answers, "output_format", None))


def resolve_aspect_ratio(answers: ClarifyingAnswers) -> str:
    """Resolve final aspect ratio from override, stored inference, and live inference."""
    aspect_ratio_override = getattr(answers, "aspect_ratio_override", None)
    if aspect_ratio_override:
        return aspect_ratio_override
    aspect_ratio = getattr(answers, "aspect_ratio", None)
    if aspect_ratio:
        return aspect_ratio
    resolved_aspect_ratio = getattr(answers, "resolved_aspect_ratio", None)
    if resolved_aspect_ratio:
        return resolved_aspect_ratio
    inferred_aspect_ratio = getattr(answers, "inferred_aspect_ratio", None)
    if inferred_aspect_ratio:
        return inferred_aspect_ratio
    return infer_aspect_ratio(getattr(answers, "platform", None), getattr(answers, "output_format", None))


def resolve_call_to_action(project: ContentProject, answers: ClarifyingAnswers) -> str:
    """Resolve a deterministic call to action from answers or director instructions."""
    answer_cta = getattr(answers, "call_to_action", None)
    if answer_cta:
        return normalize_call_to_action(answer_cta)
    director_instructions = getattr(project, "director_instructions", "")
    patterns = [
        r"(?:call to action|cta)\s*(?:is|:)\s*([^.!?\n]+)",
        r"curious enough to\s+([^.!?\n]+)",
        r"(?:make|encourage|get|invite)\s+(?:people|viewers|the audience|users)\s+(?:curious enough\s+)?to\s+([^.!?\n]+)",
    ]
    for pattern in patterns:
        match = re.search(pattern, director_instructions, flags=re.IGNORECASE)
        if match:
            return normalize_call_to_action(match.group(1))
    return "Ask for the next step."


def normalize_call_to_action(value: str) -> str:
    """Normalize a call to action into a short imperative sentence."""
    cleaned = re.sub(r"\s+", " ", value.strip().strip("\"'` "))
    cleaned = re.sub(r"^(to|that they|they should|people should|viewers should)\s+", "", cleaned, flags=re.IGNORECASE)
    if not cleaned:
        return "Ask for the next step."
    cleaned = cleaned[0].upper() + cleaned[1:]
    if cleaned[-1] not in ".!?":
        cleaned = f"{cleaned}."
    return cleaned


def infer_source_use(text: str) -> str:
    """Infer conservative source-use intent from director instructions."""
    lower_text = text.lower()
    if any(term in lower_text for term in ["match", "copy closely", "replicate", "polish existing", "polish the existing"]):
        return "copy closely"
    return "inspiration/reference context"


def is_video_format(route_or_format: str | WorkflowRoute | None) -> bool:
    """Return whether a route or format implies video output."""
    if route_or_format is None:
        return False
    value = route_or_format.value if isinstance(route_or_format, WorkflowRoute) else str(route_or_format)
    return any(term in value.lower() for term in ["video", "reel", "story", "clip"])
