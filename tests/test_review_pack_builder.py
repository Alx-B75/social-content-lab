"""Tests for review-state persistence and final-pack assembly."""

import csv
import json

import pytest

from src.services.review_pack_builder import (
    SECTION_NAMES,
    UnsafeReviewContentError,
    assemble_selected_sections,
    detect_unsafe_review_content,
    export_final_pack,
    load_or_initialize_review_state,
    save_review_state,
)


def write_pack_versions(project_path, include_llm: bool = False) -> None:
    """Write deterministic and optional LLM fixtures into a project folder."""
    for section in SECTION_NAMES:
        (project_path / f"{section}.md").write_text(f"# Deterministic {section}\n", encoding="utf-8")
        if include_llm:
            (project_path / f"{section}.llm.md").write_text(f"# LLM {section}\n", encoding="utf-8")


def test_initializes_and_persists_review_state(content_project) -> None:
    """Create review-state.json with deterministic defaults."""
    state = load_or_initialize_review_state(content_project)
    payload = json.loads((content_project.project_path / "review-state.json").read_text(encoding="utf-8"))

    assert state.project_id == content_project.project_id
    assert state.review_status == "draft"
    assert all(source == "deterministic" for source in state.selected_sections.values())
    assert payload["selected_sections"] == state.selected_sections


def test_exports_final_pack_from_deterministic_sections(content_project) -> None:
    """Assemble and export a deterministic-only final pack."""
    write_pack_versions(content_project.project_path)
    state = load_or_initialize_review_state(content_project)

    exported = export_final_pack(content_project, state)
    final_pack = (content_project.project_path / "final-pack.md").read_text(encoding="utf-8")

    assert "Status: draft" in final_pack
    assert "Brief: deterministic" in final_pack
    assert "# Deterministic brief" in final_pack
    assert len(exported.export_history) == 1
    for section in SECTION_NAMES:
        assert (content_project.project_path / f"final-{section}.md").exists()


def test_assembles_mixed_deterministic_llm_and_custom_sections(content_project) -> None:
    """Resolve mixed section sources and retain attribution in final output."""
    write_pack_versions(content_project.project_path, include_llm=True)
    state = load_or_initialize_review_state(content_project).model_copy(
        update={
            "selected_sections": {
                "brief": "deterministic",
                "script": "llm",
                "storyboard": "custom",
                "prompts": "llm",
                "captions": "deterministic",
            },
            "custom_section_text": {"storyboard": "# Custom storyboard\n"},
            "review_status": "approved",
            "reviewer_notes": "Reviewed locally.",
        }
    )
    state = save_review_state(content_project, state)
    selected = assemble_selected_sections(content_project, state)

    export_final_pack(content_project, state)
    final_pack = (content_project.project_path / "final-pack.md").read_text(encoding="utf-8")

    assert selected["script"]["source"] == "llm"
    assert selected["storyboard"]["text"] == "# Custom storyboard\n"
    assert "> Section source: llm" in final_pack
    assert "> Section source: custom" in final_pack
    assert "Status: approved" in final_pack


def test_repeated_export_updates_one_asset_log_row(content_project) -> None:
    """Avoid duplicate final-pack rows across repeated exports."""
    write_pack_versions(content_project.project_path)
    state = load_or_initialize_review_state(content_project)

    state = export_final_pack(content_project, state)
    state = export_final_pack(content_project, state.model_copy(update={"review_status": "published"}))
    with (content_project.project_path / "asset-log.csv").open("r", encoding="utf-8", newline="") as handle:
        rows = list(csv.DictReader(handle))

    final_rows = [row for row in rows if row["source_or_generated"] == "final_pack"]
    assert len(final_rows) == 1
    assert final_rows[0]["tool_or_model"] == "mixed_manual_review"
    assert final_rows[0]["historical_or_brand_risk"] == "reviewed"
    assert len(state.export_history) == 2


def test_safety_detection_blocks_secret_and_absolute_path(content_project) -> None:
    """Detect and block secret-like text and absolute local paths."""
    write_pack_versions(content_project.project_path)
    state = load_or_initialize_review_state(content_project).model_copy(
        update={
            "selected_sections": {section: "deterministic" for section in SECTION_NAMES},
            "custom_section_text": {"brief": ""},
        }
    )
    (content_project.project_path / "brief.md").write_text(
        "OPENROUTER_API_KEY=sk-or-v1-secret\nC:\\private\\content\\project\\sources\\video.mp4",
        encoding="utf-8",
    )
    selected = assemble_selected_sections(content_project, state)
    warnings = detect_unsafe_review_content(selected)

    assert any("secret-like" in warning for warning in warnings)
    assert any("absolute Windows path" in warning for warning in warnings)
    with pytest.raises(UnsafeReviewContentError):
        export_final_pack(content_project, state)
    assert not (content_project.project_path / "final-pack.md").exists()
