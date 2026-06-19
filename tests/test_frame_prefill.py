"""Tests for deterministic frame interpretation prefill."""

import json
from pathlib import Path

from src.models.source import FrameRecord, FrameRole, SourceRecord, SourceReferenceStrategy, SourceType
from src.services.frame_prefill import apply_prefill_to_frame, build_local_frame_prefill, prefill_missing_frame_fields
from src.services.frame_summary import frame_reference_summary
from src.services.video_frame_extractor import load_frame_index, save_frame_index


def make_source() -> SourceRecord:
    """Return a minimal video source for prefill tests."""
    return SourceRecord(
        source_id="video-1",
        source_type=SourceType.VIDEO,
        declared_purpose="visual style reference",
        strategy=SourceReferenceStrategy.KEYFRAME_EXTRACTION_NEEDED,
    )


def make_frame(tmp_path: Path, frame_id: str, label: str) -> FrameRecord:
    """Return a minimal extracted frame record."""
    path = tmp_path / f"{frame_id}.jpg"
    path.write_bytes(b"test")
    return FrameRecord(
        frame_id=frame_id,
        source_id="video-1",
        file_name=path.name,
        relative_path=Path("content/project/frames") / path.name,
        absolute_path=path,
        timestamp_seconds=1.0,
        label=label,
    )


def test_local_prefill_preserves_existing_values_and_assigns_stable_roles(tmp_path, content_project) -> None:
    """Keep manual values while assigning deterministic position-based roles."""
    source = make_source()
    opening = make_frame(tmp_path, "opening", "start").model_copy(update={"description": "Manual description"})
    middle = make_frame(tmp_path, "middle", "50pct")
    closing = make_frame(tmp_path, "closing", "end")

    updated = prefill_missing_frame_fields([opening, middle, closing], source, content_project)

    assert updated[0].description == "Manual description"
    assert updated[0].selected_role == FrameRole.HERO_FRAME
    assert updated[1].selected_role == FrameRole.VISUAL_REFERENCE
    assert updated[2].selected_role == FrameRole.POSSIBLE_BACKGROUND
    assert all(frame.needs_human_review for frame in updated)
    assert all(frame.prefill_source == "local_deterministic" for frame in updated)


def test_local_prefill_replaces_only_when_explicit(tmp_path, content_project) -> None:
    """Replace existing frame fields only when the caller explicitly opts in."""
    frame = make_frame(tmp_path, "opening", "start").model_copy(update={"description": "Manual description"})
    prefill = build_local_frame_prefill(frame, make_source(), content_project)

    preserved = apply_prefill_to_frame(frame, prefill)
    replaced = apply_prefill_to_frame(frame, prefill, replace_existing=True)

    assert preserved.description == "Manual description"
    assert replaced.description != "Manual description"


def test_old_frame_index_normalizes_prefill_defaults_and_round_trips(tmp_path, content_project) -> None:
    """Load an older frame index and persist new metadata without migration steps."""
    frame = make_frame(tmp_path, "legacy", "50pct")
    legacy_payload = frame.model_dump(mode="json", exclude={"prefill_source", "prefill_model", "prefill_timestamp", "prefill_confidence", "needs_human_review", "field_sources"})
    index_path = tmp_path / "frame-index.json"
    index_path.write_text(json.dumps({"source_id": "video-1", "frames": [legacy_payload]}), encoding="utf-8")

    loaded = load_frame_index(index_path)
    updated = prefill_missing_frame_fields(loaded, make_source(), content_project)
    save_frame_index("video-1", index_path, updated)
    reloaded = load_frame_index(index_path)

    assert loaded[0].prefill_source == "none"
    assert reloaded[0].prefill_source == "local_deterministic"
    assert "Confirm visible details manually" in frame_reference_summary(reloaded)[0]
