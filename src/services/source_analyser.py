"""Local source analysis service for Social Content Lab."""

import mimetypes
import uuid
from pathlib import Path

from PIL import Image, UnidentifiedImageError

from src.models.project import ContentProject
from src.models.source import SourceRecord, SourceReferenceStrategy, SourceType
from src.services.project_service import ProjectService


class SourceAnalyser:
    """Analyse and persist source references without external model calls."""

    def __init__(self, project_service: ProjectService) -> None:
        """Initialise the source analyser with project persistence."""
        self.project_service = project_service

    def add_image_source(
        self,
        project: ContentProject,
        filename: str,
        data: bytes,
        mime_type: str | None,
        declared_purpose: str | None,
    ) -> SourceRecord:
        """Save and analyse an uploaded image source with Pillow metadata."""
        stored_path = self.project_service.save_uploaded_file(project, filename, data)
        width = None
        height = None
        aspect_ratio = None
        notes: list[str] = []
        try:
            with Image.open(stored_path) as image:
                width, height = image.size
                aspect_ratio = self._format_aspect_ratio(width, height)
        except (UnidentifiedImageError, OSError) as error:
            notes.append(f"Image metadata could not be read: {error}")

        return SourceRecord(
            source_id=self._source_id("img"),
            source_type=SourceType.IMAGE,
            declared_purpose=declared_purpose,
            original_filename=Path(filename).name,
            stored_path=stored_path,
            mime_type=mime_type or mimetypes.guess_type(filename)[0],
            file_size_bytes=len(data),
            width=width,
            height=height,
            aspect_ratio=aspect_ratio,
            strategy=SourceReferenceStrategy.DIRECT_VISUAL_REFERENCE,
            notes=notes,
        )

    def add_video_source(
        self,
        project: ContentProject,
        filename: str,
        data: bytes,
        mime_type: str | None,
        declared_purpose: str | None,
    ) -> SourceRecord:
        """Save an uploaded video source and record future extraction needs."""
        stored_path = self.project_service.save_uploaded_file(project, filename, data)
        return SourceRecord(
            source_id=self._source_id("vid"),
            source_type=SourceType.VIDEO,
            declared_purpose=declared_purpose,
            original_filename=Path(filename).name,
            stored_path=stored_path,
            mime_type=mime_type or mimetypes.guess_type(filename)[0],
            file_size_bytes=len(data),
            strategy=SourceReferenceStrategy.KEYFRAME_EXTRACTION_NEEDED,
            notes=[
                "Future extraction recommended: first frame.",
                "Future extraction recommended: 3-5 representative keyframes.",
                "Future extraction recommended: duration.",
                "Future extraction recommended: aspect ratio.",
                "Future extraction recommended: available audio transcript.",
                "Future extraction recommended: visible text if OCR is later added.",
            ],
        )

    def add_url_source(
        self,
        url: str,
        declared_purpose: str | None,
    ) -> SourceRecord:
        """Record a URL source without scraping it."""
        return SourceRecord(
            source_id=self._source_id("url"),
            source_type=SourceType.URL,
            declared_purpose=declared_purpose,
            url=url,
            strategy=SourceReferenceStrategy.URL_EXTRACTION_NEEDED,
            notes=["URL scraping is not implemented in the MVP."],
        )

    def add_pasted_text_source(
        self,
        project: ContentProject,
        text: str,
        declared_purpose: str | None,
    ) -> SourceRecord:
        """Save pasted text and summarise it with a local heuristic."""
        source_id = self._source_id("txt")
        stored_path = self.project_service.save_source_text(project, f"{source_id}.txt", text)
        word_count = len(text.split())
        return SourceRecord(
            source_id=source_id,
            source_type=SourceType.PASTED_TEXT,
            declared_purpose=declared_purpose,
            stored_path=stored_path,
            text_preview=text[:500],
            word_count=word_count,
            likely_use_case=self._guess_text_use_case(text),
            strategy=SourceReferenceStrategy.TEXT_SUMMARY_REFERENCE,
        )

    def add_manual_description_source(
        self,
        description: str,
        declared_purpose: str | None,
    ) -> SourceRecord:
        """Record a manual description source."""
        return SourceRecord(
            source_id=self._source_id("desc"),
            source_type=SourceType.MANUAL_DESCRIPTION,
            declared_purpose=declared_purpose,
            manual_description=description,
            strategy=SourceReferenceStrategy.MANUAL_DESCRIPTION_REFERENCE,
        )

    def _format_aspect_ratio(self, width: int, height: int) -> str:
        """Format an image aspect ratio as width:height."""
        if width <= 0 or height <= 0:
            return "unknown"
        divisor = self._greatest_common_divisor(width, height)
        return f"{width // divisor}:{height // divisor}"

    def _greatest_common_divisor(self, first_value: int, second_value: int) -> int:
        """Calculate the greatest common divisor for two integers."""
        while second_value:
            first_value, second_value = second_value, first_value % second_value
        return max(first_value, 1)

    def _guess_text_use_case(self, text: str) -> str:
        """Guess how pasted text may be used in the content pack."""
        lower_text = text.lower()
        if any(term in lower_text for term in ["quote", "interview", "transcript"]):
            return "message and script reference"
        if any(term in lower_text for term in ["spec", "feature", "price", "launch"]):
            return "product or announcement reference"
        if any(term in lower_text for term in ["brand", "tone", "style", "guideline"]):
            return "brand guidance reference"
        return "general context reference"

    def _source_id(self, prefix: str) -> str:
        """Create a compact source identifier."""
        return f"{prefix}-{uuid.uuid4().hex[:8]}"
