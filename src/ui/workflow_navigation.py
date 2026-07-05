"""Workflow navigation helpers for the Streamlit app shell."""

from pathlib import Path
from typing import Any

from src.models.source import SourceRecord, SourceType


WORKFLOW_STAGES = [
    "Project",
    "Sources",
    "Frames",
    "Planning",
    "Review Pack",
    "Generate Video",
    "Diagnostics",
    "All Stages",
]


def default_workflow_stage(project: object | None, requested_stage: str | None = None) -> str:
    """Return a sensible workflow stage for the current state."""
    if requested_stage == "Generate Video" and project is not None:
        return "Generate Video"
    if requested_stage in WORKFLOW_STAGES and (project is not None or requested_stage == "Project"):
        return requested_stage
    return "Project" if project is None else "Project"


def previous_stage(stage: str) -> str | None:
    """Return the previous major workflow stage."""
    ordered = [stage for stage in WORKFLOW_STAGES if stage not in {"All Stages", "Diagnostics"}]
    if stage not in ordered:
        return None
    index = ordered.index(stage)
    return ordered[index - 1] if index > 0 else None


def next_stage(stage: str) -> str | None:
    """Return the next major workflow stage."""
    ordered = [stage for stage in WORKFLOW_STAGES if stage not in {"All Stages", "Diagnostics"}]
    if stage not in ordered:
        return None
    index = ordered.index(stage)
    return ordered[index + 1] if index < len(ordered) - 1 else None


def workflow_stage_statuses(
    project: object | None,
    sources: list[SourceRecord],
    recommendation: object | None,
    content_pack: object | None,
) -> dict[str, str]:
    """Return compact status text for each workflow stage."""
    project_path = getattr(project, "project_path", None)
    return {
        "Project": "loaded" if project is not None else "not loaded",
        "Sources": "present" if sources else "missing",
        "Frames": "extracted" if frames_are_extracted(sources) else "not extracted",
        "Planning": "present" if recommendation is not None or content_pack is not None else "missing",
        "Review Pack": "present" if final_pack_exists(project_path) else "missing",
        "Generate Video": "present" if video_outputs_exist(project_path) else "missing",
        "Diagnostics": "available",
        "All Stages": "debug view",
    }


def frames_are_extracted(sources: list[SourceRecord]) -> bool:
    """Return whether any video source has extracted frame evidence."""
    for source in sources:
        if source.source_type != SourceType.VIDEO:
            continue
        if source.frame_count > 0 or source.frame_extraction_status == "completed":
            return True
        if source.frame_index_path and Path(source.frame_index_path).exists():
            return True
    return False


def final_pack_exists(project_path: Any) -> bool:
    """Return whether a final pack exists for the project."""
    if not project_path:
        return False
    return (Path(project_path) / "final-pack.md").exists()


def video_outputs_exist(project_path: Any) -> bool:
    """Return whether generated video outputs exist for the project."""
    if not project_path:
        return False
    output_dir = Path(project_path) / "outputs" / "video"
    return output_dir.exists() and any(output_dir.glob("video-output-*.mp4"))


def missing_stage_guidance(stage: str) -> str:
    """Return a helpful message for missing prerequisites."""
    messages = {
        "Sources": "No sources yet. You can add uploads, URLs, pasted text, or manual descriptions here.",
        "Frames": "No extracted frames yet. Add a video source, then run frame extraction.",
        "Planning": "No recommendation or content pack yet. Answer planning questions and generate a recommendation when ready.",
        "Review Pack": "No final prompt found yet. Generate a content pack, use LLM planning if useful, or export a final pack.",
        "Generate Video": "No final prompt found yet. Use a custom prompt or go to Review Pack.",
    }
    return messages.get(stage, "Complete the earlier workflow steps or use custom inputs where available.")
