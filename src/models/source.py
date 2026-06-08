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


class SourceRecord(BaseModel):
    """Metadata for a source saved in a local project."""

    source_id: str
    source_type: SourceType
    declared_purpose: str | None = None
    original_filename: str | None = None
    stored_path: Path | None = None
    mime_type: str | None = None
    file_size_bytes: int | None = None
    width: int | None = None
    height: int | None = None
    aspect_ratio: str | None = None
    url: str | None = None
    text_preview: str | None = None
    word_count: int | None = None
    likely_use_case: str | None = None
    manual_description: str | None = None
    strategy: SourceReferenceStrategy
    notes: list[str] = Field(default_factory=list)
    created_at: datetime = Field(default_factory=datetime.now)
    extra: dict[str, Any] = Field(default_factory=dict)
