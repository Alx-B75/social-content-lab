"""Selected frame summary helpers for deterministic content planning."""

from collections import defaultdict

from src.models.source import FrameRecord, FrameRole, SourceRecord, SourceType
from src.services.video_frame_extractor import load_frame_index


POSITIVE_REFERENCE_ROLES = {
    FrameRole.HERO_FRAME,
    FrameRole.VISUAL_REFERENCE,
    FrameRole.POSSIBLE_BACKGROUND,
}


def load_frame_references(sources: list[SourceRecord]) -> list[FrameRecord]:
    """Load all selected, review, and avoid frame references from video sources."""
    frames: list[FrameRecord] = []
    for source in sources:
        if source.source_type != SourceType.VIDEO:
            continue
        for frame in load_frame_index(source.frame_index_path):
            if frame.selected_role != FrameRole.UNSELECTED:
                frames.append(frame)
    return frames


def selected_frame_count(frames: list[FrameRecord]) -> int:
    """Count frames selected as positive production references."""
    return sum(1 for frame in frames if frame.selected_role in POSITIVE_REFERENCE_ROLES)


def positive_frame_references(frames: list[FrameRecord]) -> list[FrameRecord]:
    """Return frames that can be used as positive prompt references."""
    return [frame for frame in frames if frame.selected_role in POSITIVE_REFERENCE_ROLES]


def grouped_frame_references(frames: list[FrameRecord]) -> dict[FrameRole, list[FrameRecord]]:
    """Group frame references by selected role."""
    grouped: dict[FrameRole, list[FrameRecord]] = defaultdict(list)
    for frame in frames:
        grouped[frame.selected_role].append(frame)
    return dict(grouped)


def frame_reference_summary(frames: list[FrameRecord]) -> list[str]:
    """Return compact selected-frame summaries for prompt and preview use."""
    return [_frame_summary_line(frame) for frame in frames]


def frame_risk_notes(frames: list[FrameRecord]) -> list[str]:
    """Return risk and avoid notes from selected frame metadata."""
    notes: list[str] = []
    if any(frame.selected_role == FrameRole.NEEDS_REVIEW for frame in frames):
        notes.append("Some selected frames require review before generation or publication.")
    for frame in frames:
        if frame.selected_role == FrameRole.DO_NOT_USE:
            avoid = frame.avoid_using_for or "generation or publication"
            notes.append(f"Do not use `{frame.file_name}` for {avoid}.")
        if frame.rights_notes:
            notes.append(f"Rights note for `{frame.file_name}`: {frame.rights_notes}.")
        if frame.historical_or_brand_risk and frame.selected_role != FrameRole.DO_NOT_USE:
            notes.append(f"Risk note for `{frame.file_name}`: {frame.historical_or_brand_risk}.")
    return _dedupe(notes)


def frame_prompt_detail(frame: FrameRecord) -> str:
    """Return a compact prompt-ready description for one frame."""
    details = [
        frame.description,
        f"subject: {frame.visible_subject}" if frame.visible_subject else "",
        f"setting: {frame.setting}" if frame.setting else "",
        f"mood: {frame.mood}" if frame.mood else "",
        f"visual style: {frame.visual_style}" if frame.visual_style else "",
        f"on-screen text: {frame.on_screen_text}" if frame.on_screen_text else "",
        f"recommended use: {frame.recommended_use}" if frame.recommended_use else "",
    ]
    cleaned = [detail for detail in details if detail]
    if cleaned:
        return "; ".join(cleaned)
    return frame.notes or "no manual description added"


def frame_asset_log_keep_reject(frame: FrameRecord) -> str:
    """Return the asset-log keep/reject value for a frame role."""
    if frame.selected_role == FrameRole.DO_NOT_USE:
        return "reject"
    if frame.selected_role in POSITIVE_REFERENCE_ROLES:
        return "keep"
    return "undecided"


def frame_asset_log_notes(frame: FrameRecord) -> str:
    """Return asset-log notes for a frame using structured metadata."""
    parts = []
    if frame.recommended_use:
        parts.append(f"use: {frame.recommended_use}")
    if frame.historical_or_brand_risk:
        parts.append(f"risk: {frame.historical_or_brand_risk}")
    if frame.rights_notes:
        parts.append(f"rights: {frame.rights_notes}")
    if frame.avoid_using_for:
        parts.append(f"avoid: {frame.avoid_using_for}")
    if frame.notes:
        parts.append(f"notes: {frame.notes}")
    return "; ".join(parts)


def _frame_summary_line(frame: FrameRecord) -> str:
    """Return one compact frame summary line."""
    fields = [
        f"`{frame.file_name}`",
        f"role: {frame.selected_role.value}",
        f"time: {_frame_time_label(frame)}",
        f"description: {frame.description}" if frame.description else "",
        f"subject: {frame.visible_subject}" if frame.visible_subject else "",
        f"setting: {frame.setting}" if frame.setting else "",
        f"mood: {frame.mood}" if frame.mood else "",
        f"style: {frame.visual_style}" if frame.visual_style else "",
        f"text: {frame.on_screen_text}" if frame.on_screen_text else "",
        f"use: {frame.recommended_use}" if frame.recommended_use else "",
        f"rights: {frame.rights_notes}" if frame.rights_notes else "",
        f"risk: {frame.historical_or_brand_risk}" if frame.historical_or_brand_risk else "",
        f"avoid: {frame.avoid_using_for}" if frame.avoid_using_for else "",
    ]
    return "; ".join(field for field in fields if field)


def _frame_time_label(frame: FrameRecord) -> str:
    """Return a readable frame timestamp and label."""
    timestamp = f"{frame.timestamp_seconds:.2f}s" if frame.timestamp_seconds is not None else "unknown"
    return f"{frame.label} at {timestamp}"


def _dedupe(values: list[str]) -> list[str]:
    """Return values without duplicates while preserving order."""
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        if value in seen:
            continue
        seen.add(value)
        result.append(value)
    return result
