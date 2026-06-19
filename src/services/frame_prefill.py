"""Local deterministic helpers for prefilling extracted frame records."""

from datetime import datetime, timezone
from typing import Any

from src.models.project import ContentProject
from src.models.source import FrameRecord, FrameRole, SourceRecord


PREFILL_FIELDS = (
    "notes",
    "description",
    "visible_subject",
    "setting",
    "mood",
    "visual_style",
    "on_screen_text",
    "rights_notes",
    "historical_or_brand_risk",
    "recommended_use",
    "avoid_using_for",
)


def suggest_frame_role(frame: FrameRecord, source: SourceRecord, project: ContentProject) -> FrameRole:
    """Suggest a conservative role from frame position and project context."""
    if frame.selected_role != FrameRole.UNSELECTED:
        return frame.selected_role
    if frame.label == "start":
        return FrameRole.HERO_FRAME
    if frame.label == "end":
        return FrameRole.POSSIBLE_BACKGROUND
    return FrameRole.VISUAL_REFERENCE


def build_local_frame_prefill(
    frame: FrameRecord,
    source: SourceRecord,
    project: ContentProject,
    answers: Any = None,
) -> dict[str, str | FrameRole]:
    """Build honest position-based suggestions without claiming visual inspection."""
    purpose = source.declared_purpose or "visual reference"
    topic = project.topic or project.working_title
    position = _position_label(frame)
    platform = getattr(answers, "platform", None) if answers is not None else None
    platform_detail = f" for {platform}" if platform else ""
    role = suggest_frame_role(frame, source, project)
    return {
        "selected_role": role,
        "notes": f"Deterministic prefill based on the {position} frame position; visual details require human review.",
        "description": f"Extracted {position} reference frame from the source video for the {topic} project. Confirm visible details manually.",
        "visible_subject": "Confirm the main visible subject.",
        "setting": "Confirm the visible setting and background.",
        "mood": "Confirm the intended mood from the frame.",
        "visual_style": "Use as source-reference context only after visual review.",
        "on_screen_text": "Check the frame for readable on-screen text.",
        "rights_notes": "Confirm rights and permissions before reuse.",
        "historical_or_brand_risk": "Human review required for visual accuracy, brand fit, and sensitive details.",
        "recommended_use": f"Consider as a {role.value.replace('_', ' ')}{platform_detail}; declared source purpose: {purpose}.",
        "avoid_using_for": "Direct publication or factual visual claims before human review.",
    }


def apply_prefill_to_frame(
    frame: FrameRecord,
    prefill: dict[str, Any],
    replace_existing: bool = False,
    prefill_source: str = "local_deterministic",
    model_id: str | None = None,
    confidence: str = "",
) -> FrameRecord:
    """Apply prefill values while preserving user-entered values by default."""
    updates: dict[str, Any] = {}
    field_sources = dict(frame.field_sources)
    for field in PREFILL_FIELDS:
        value = str(prefill.get(field) or "").strip()
        if not value or (getattr(frame, field) and not replace_existing):
            continue
        updates[field] = value
        field_sources[field] = prefill_source
    suggested_role = prefill.get("selected_role")
    if suggested_role is not None and (frame.selected_role == FrameRole.UNSELECTED or replace_existing):
        updates["selected_role"] = FrameRole(suggested_role)
        field_sources["selected_role"] = prefill_source
    if not updates:
        return frame
    updates.update(
        {
            "prefill_source": _combined_prefill_source(frame.prefill_source, prefill_source),
            "prefill_model": model_id or frame.prefill_model,
            "prefill_timestamp": datetime.now(timezone.utc).isoformat(),
            "prefill_confidence": confidence,
            "needs_human_review": True,
            "field_sources": field_sources,
        }
    )
    return frame.model_copy(update=updates)


def prefill_missing_frame_fields(
    frames: list[FrameRecord],
    source: SourceRecord,
    project: ContentProject,
    answers: Any = None,
    replace_existing: bool = False,
) -> list[FrameRecord]:
    """Apply deterministic prefill suggestions to a list of frames."""
    return [
        apply_prefill_to_frame(
            frame,
            build_local_frame_prefill(frame, source, project, answers),
            replace_existing=replace_existing,
        )
        for frame in frames
    ]


def _position_label(frame: FrameRecord) -> str:
    """Return a readable frame-position label."""
    if frame.label == "start":
        return "opening"
    if frame.label == "end":
        return "closing"
    return "mid-video"


def _combined_prefill_source(existing: str, incoming: str) -> str:
    """Return an aggregate provenance label for mixed prefill sources."""
    if existing in {"none", "", incoming}:
        return incoming
    return "mixed"
