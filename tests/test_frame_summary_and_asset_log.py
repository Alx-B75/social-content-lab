"""Tests for frame summaries and asset-log dedupe/update behaviour."""

import csv
from pathlib import Path

from src.models.source import FrameRecord, FrameRole
from src.services.frame_summary import (
    frame_asset_log_keep_reject,
    frame_prompt_detail,
    frame_reference_summary,
    frame_risk_notes,
    positive_frame_references,
    selected_frame_count,
)
from src.services.project_service import ProjectService


def make_frame(frame_id: str, role: FrameRole) -> FrameRecord:
    """Create a frame record for tests."""
    return FrameRecord(
        frame_id=frame_id,
        source_id="vid-1",
        file_name=f"{frame_id}.jpg",
        relative_path=Path("content/project/sources/frames/vid-1") / f"{frame_id}.jpg",
        absolute_path=Path("C:/ignored") / f"{frame_id}.jpg",
        timestamp_seconds=1.25,
        label="start",
        selected_role=role,
        description="Shakespeare figure in warm light",
        visible_subject="Shakespeare figure",
        setting="dark stage",
        mood="premium theatrical",
        visual_style="warm lighting",
        rights_notes="confirm rights",
        historical_or_brand_risk="needs review",
        recommended_use="opening visual reference",
        avoid_using_for="direct copy",
    )


def test_frame_summary_counts_risks_and_prompt_details() -> None:
    """Summarise positive, review, and rejected frame records."""
    hero = make_frame("hero", FrameRole.HERO_FRAME)
    background = make_frame("background", FrameRole.POSSIBLE_BACKGROUND)
    review = make_frame("review", FrameRole.NEEDS_REVIEW)
    rejected = make_frame("reject", FrameRole.DO_NOT_USE)
    frames = [hero, background, review, rejected]

    summary = frame_reference_summary(frames)
    risks = frame_risk_notes(frames)

    assert selected_frame_count(frames) == 2
    assert [frame.frame_id for frame in positive_frame_references(frames)] == ["hero", "background"]
    assert "Shakespeare figure" in frame_prompt_detail(hero)
    assert any("Do not use `reject.jpg`" in note for note in risks)
    assert any("require review" in note for note in risks)
    assert len(summary) == 4
    assert frame_asset_log_keep_reject(rejected) == "reject"
    assert frame_asset_log_keep_reject(hero) == "keep"


def test_frame_asset_log_dedupes_and_updates_role(app_config, content_project) -> None:
    """Append frame rows once and update keep/reject when role changes."""
    service = ProjectService(app_config)
    service.ensure_asset_log(content_project)
    frame = make_frame("hero", FrameRole.HERO_FRAME)

    service.append_frame_to_asset_log(content_project, frame)
    service.append_frame_to_asset_log(content_project, frame)
    rejected = frame.model_copy(update={"selected_role": FrameRole.DO_NOT_USE, "recommended_use": "do not use"})
    service.append_frame_to_asset_log(content_project, rejected)

    with (content_project.project_path / "asset-log.csv").open("r", encoding="utf-8", newline="") as handle:
        rows = list(csv.DictReader(handle))

    assert len(rows) == 1
    assert rows[0]["asset_id"] == "hero"
    assert rows[0]["keep_reject"] == "reject"
    assert "do not use" in rows[0]["notes"]
