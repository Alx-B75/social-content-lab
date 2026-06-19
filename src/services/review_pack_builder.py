"""Review state and final content-pack assembly services."""

import csv
import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field

from src.models.project import ContentProject
from src.services.file_utils import write_text_file


SECTION_NAMES = ["brief", "script", "storyboard", "prompts", "captions"]
SectionSource = Literal["deterministic", "llm", "custom"]
ReviewStatus = Literal["draft", "needs_review", "approved", "published"]


class ReviewState(BaseModel):
    """Persisted section selections and review status for a project."""

    project_id: str
    created_at: str
    updated_at: str
    selected_sections: dict[str, SectionSource]
    custom_section_text: dict[str, str] = Field(default_factory=dict)
    review_status: ReviewStatus = "draft"
    reviewer_notes: str = ""
    export_history: list[dict[str, object]] = Field(default_factory=list)


class UnsafeReviewContentError(ValueError):
    """Raised when selected review content contains unsafe local or secret data."""

    def __init__(self, warnings: list[str]) -> None:
        """Initialise the error with safe warning messages."""
        self.warnings = warnings
        super().__init__("Final pack contains content that must be reviewed before export.")


def discover_pack_versions(project_path: Path) -> dict[str, dict[str, bool]]:
    """Report deterministic and LLM file availability for each pack section."""
    return {
        section: {
            "deterministic": (project_path / f"{section}.md").exists(),
            "llm": (project_path / f"{section}.llm.md").exists(),
        }
        for section in SECTION_NAMES
    }


def load_pack_sections(project_path: Path) -> dict[str, dict[str, str]]:
    """Load deterministic and LLM section text from a project folder."""
    return {
        section: {
            "deterministic": _read_optional_text(project_path / f"{section}.md"),
            "llm": _read_optional_text(project_path / f"{section}.llm.md"),
        }
        for section in SECTION_NAMES
    }


def load_or_initialize_review_state(project: ContentProject) -> ReviewState:
    """Load review-state.json or create a backward-compatible default state."""
    review_path = project.project_path / "review-state.json"
    if review_path.exists():
        try:
            payload = json.loads(review_path.read_text(encoding="utf-8"))
            return ReviewState(**payload)
        except (OSError, json.JSONDecodeError, ValueError):
            pass
    timestamp = datetime.now(timezone.utc).isoformat()
    review_state = ReviewState(
        project_id=project.project_id,
        created_at=timestamp,
        updated_at=timestamp,
        selected_sections={section: "deterministic" for section in SECTION_NAMES},
        custom_section_text={section: "" for section in SECTION_NAMES},
    )
    write_text_file(review_path, json.dumps(review_state.model_dump(mode="json"), indent=2))
    return review_state


def save_review_state(project: ContentProject, review_state: ReviewState) -> ReviewState:
    """Persist review state without modifying deterministic or LLM files."""
    updated = review_state.model_copy(update={"updated_at": datetime.now(timezone.utc).isoformat()})
    write_text_file(project.project_path / "review-state.json", json.dumps(updated.model_dump(mode="json"), indent=2))
    return updated


def assemble_selected_sections(project: ContentProject, review_state: ReviewState) -> dict[str, dict[str, str]]:
    """Resolve selected deterministic, LLM, or custom text for every section."""
    versions = load_pack_sections(project.project_path)
    selected: dict[str, dict[str, str]] = {}
    for section in SECTION_NAMES:
        source = review_state.selected_sections.get(section, "deterministic")
        if source == "custom":
            text = review_state.custom_section_text.get(section, "")
        else:
            text = versions[section].get(source, "")
        selected[section] = {"source": source, "text": text}
    return selected


def detect_unsafe_review_content(selected_sections: dict[str, dict[str, str]]) -> list[str]:
    """Return safe warnings for secrets, paths, or local media references."""
    warnings: list[str] = []
    for section, selection in selected_sections.items():
        text = selection.get("text", "")
        if re.search(
            r"(?i)(?:OPENROUTER_API_KEY|OPENAI_API_KEY|FAL_KEY|REPLICATE_API_TOKEN|ELEVENLABS_API_KEY)\s*=|(?:sk-or-v1|sk)-[A-Za-z0-9_-]{8,}",
            text,
        ):
            warnings.append(f"{section.title()} contains secret-like API key text.")
        if re.search(r"[A-Za-z]:[\\/]", text):
            warnings.append(f"{section.title()} contains an absolute Windows path.")
        if re.search(r"(?i)(?:content|cache)[\\/].*(?:sources|frames|openrouter-model-catalog)", text):
            warnings.append(f"{section.title()} contains a local media or cache path.")
    return warnings


def export_final_pack(project: ContentProject, review_state: ReviewState) -> ReviewState:
    """Validate, write final pack files, update history, and upsert the asset log."""
    selected = assemble_selected_sections(project, review_state)
    warnings = detect_unsafe_review_content(selected)
    if warnings:
        raise UnsafeReviewContentError(warnings)

    output_files: list[str] = []
    for section in SECTION_NAMES:
        filename = f"final-{section}.md"
        write_text_file(project.project_path / filename, _render_final_section(section, selected[section]))
        output_files.append(filename)
    write_text_file(project.project_path / "final-pack.md", _render_final_pack(project, review_state, selected))
    output_files.append("final-pack.md")

    exported_at = datetime.now(timezone.utc).isoformat()
    history_entry = {
        "exported_at": exported_at,
        "review_status": review_state.review_status,
        "selected_sections": dict(review_state.selected_sections),
        "files": output_files,
    }
    updated = review_state.model_copy(update={"export_history": [*review_state.export_history, history_entry]})
    updated = save_review_state(project, updated)
    _upsert_final_pack_asset_log(project, updated)
    return updated


def _render_final_section(section: str, selection: dict[str, str]) -> str:
    """Render one final section with its source attribution."""
    return "\n".join(
        [
            f"# Final {section.title()}",
            "",
            f"> Section source: {selection['source']}",
            "",
            selection["text"].strip(),
            "",
        ]
    )


def _render_final_pack(
    project: ContentProject,
    review_state: ReviewState,
    selected_sections: dict[str, dict[str, str]],
) -> str:
    """Render the combined final pack with a concise review summary."""
    source_lines = [f"- {section.title()}: {selected_sections[section]['source']}" for section in SECTION_NAMES]
    parts = [
        f"# Final Pack: {project.working_title}",
        "",
        "## Review Summary",
        f"Status: {review_state.review_status}",
        f"Reviewer notes: {review_state.reviewer_notes or 'None'}",
        "",
        "### Section Sources",
        *source_lines,
    ]
    for section in SECTION_NAMES:
        parts.extend(
            [
                "",
                f"## {section.title()}",
                f"> Section source: {selected_sections[section]['source']}",
                "",
                selected_sections[section]["text"].strip(),
            ]
        )
    return "\n".join(parts).rstrip() + "\n"


def _upsert_final_pack_asset_log(project: ContentProject, review_state: ReviewState) -> None:
    """Append or update one stable final-pack asset-log row."""
    asset_log_path = project.project_path / "asset-log.csv"
    columns = [
        "asset_id",
        "project_id",
        "source_or_generated",
        "file_name",
        "tool_or_model",
        "estimated_cost_band",
        "time_spent_minutes",
        "rating",
        "historical_or_brand_risk",
        "keep_reject",
        "notes",
    ]
    rows = _read_csv_rows(asset_log_path)
    asset_id = f"final-pack-{project.project_id}"
    row = {
        "asset_id": asset_id,
        "project_id": project.project_id,
        "source_or_generated": "final_pack",
        "file_name": "final-pack.md",
        "tool_or_model": "mixed_manual_review",
        "estimated_cost_band": "free/manual",
        "time_spent_minutes": "",
        "rating": "unrated",
        "historical_or_brand_risk": "reviewed" if review_state.review_status in {"approved", "published"} else "needs_review",
        "keep_reject": "keep",
        "notes": "final pack assembled from deterministic/LLM/custom sections",
    }
    existing = next((item for item in rows if item.get("asset_id") == asset_id), None)
    if existing is None:
        rows.append(row)
    else:
        existing.update(row)
    with asset_log_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=columns)
        writer.writeheader()
        writer.writerows(rows)


def _read_csv_rows(path: Path) -> list[dict[str, str]]:
    """Read CSV rows when an asset log exists."""
    if not path.exists():
        return []
    with path.open("r", encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


def _read_optional_text(path: Path) -> str:
    """Read optional UTF-8 text or return an empty string."""
    if not path.exists():
        return ""
    try:
        return path.read_text(encoding="utf-8")
    except OSError:
        return ""
