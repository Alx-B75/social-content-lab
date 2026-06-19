"""Source reference models for uploaded and manually entered material."""

from datetime import datetime
from enum import StrEnum
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field


class SourceType(StrEnum):
    """Supported kinds of reference source."""

    IMAGE = "image"
    VIDEO = "video"
    URL = "url"
    PASTED_TEXT = "pasted_text"
    MANUAL_DESCRIPTION = "manual_description"


class SourceReferenceStrategy(StrEnum):
    """Supported strategies for using a source during planning."""

    DIRECT_VISUAL_REFERENCE = "direct_visual_reference"
    KEYFRAME_EXTRACTION_NEEDED = "keyframe_extraction_needed"
    TRANSCRIPT_OR_CAPTION_NEEDED = "transcript_or_caption_needed"
    URL_EXTRACTION_NEEDED = "url_extraction_needed"
    TEXT_SUMMARY_REFERENCE = "text_summary_reference"
    MANUAL_DESCRIPTION_REFERENCE = "manual_description_reference"
    MANUAL_DESCRIPTION_NEEDED = "manual_description_needed"


class FrameRole(StrEnum):
    """Supported roles for extracted video frames."""

    UNSELECTED = "unselected"
    HERO_FRAME = "hero_frame"
    VISUAL_REFERENCE = "visual_reference"
    DO_NOT_USE = "do_not_use"
    POSSIBLE_BACKGROUND = "possible_background"
    NEEDS_REVIEW = "needs_review"


class FrameRecord(BaseModel):
    """Metadata for an extracted video frame."""

    frame_id: str
    source_id: str
    file_name: str
    relative_path: Path
    absolute_path: Path
    timestamp_seconds: float | None = None
    label: str
    selected_role: FrameRole = FrameRole.UNSELECTED
    notes: str = ""
    description: str = ""
    visible_subject: str = ""
    setting: str = ""
    mood: str = ""
    visual_style: str = ""
    on_screen_text: str = ""
    rights_notes: str = ""
    historical_or_brand_risk: str = ""
    recommended_use: str = ""
    avoid_using_for: str = ""
    prefill_source: str = "none"
    prefill_model: str | None = None
    prefill_timestamp: str | None = None
    prefill_confidence: str = ""
    needs_human_review: bool = False
    field_sources: dict[str, str] = Field(default_factory=dict)


class SourceRecord(BaseModel):
    """Metadata for a source saved in a local project."""

    source_id: str
    source_type: SourceType
    declared_purpose: str | None = None
    original_filename: str | None = None
    stored_path: Path | None = None
    mime_type: str | None = None
    file_size_bytes: int | None = None
    duration_seconds: float | None = None
    frame_rate: float | None = None
    width: int | None = None
    height: int | None = None
    aspect_ratio: str | None = None
    url: str | None = None
    text_preview: str | None = None
    word_count: int | None = None
    likely_use_case: str | None = None
    manual_description: str | None = None
    strategy: SourceReferenceStrategy
    frame_extraction_status: str = "not_started"
    frame_count: int = 0
    frame_index_path: Path | None = None
    selected_frame_count: int = 0
    notes: list[str] = Field(default_factory=list)
    created_at: datetime = Field(default_factory=datetime.now)
    extra: dict[str, Any] = Field(default_factory=dict)
