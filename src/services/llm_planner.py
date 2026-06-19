"""Optional LLM-assisted text planning through OpenRouter."""

import csv
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from src.config import AppConfig
from src.models.planning import ClarifyingAnswers, WorkflowRecommendation
from src.models.project import ContentProject
from src.models.source import FrameRecord, SourceRecord, SourceType
from src.services.file_utils import write_text_file
from src.services.frame_summary import frame_reference_summary, frame_risk_notes
from src.services.model_advisor import ModelAdvisorRecommendation
from src.services.openrouter_client import call_openrouter_chat
from src.services.planning_defaults import resolve_aspect_ratio, resolve_call_to_action, resolve_duration_seconds
from src.services.project_service import ProjectService


LLM_JSON_KEYS = {
    "core_message",
    "hook_options",
    "script_outline",
    "shot_list",
    "image_prompt",
    "video_prompts",
    "caption_drafts",
    "risk_notes",
    "next_actions",
    "rationale",
}


def build_llm_planning_context(
    project: ContentProject,
    sources: list[SourceRecord],
    answers: ClarifyingAnswers,
    recommendation: WorkflowRecommendation | None,
    frame_references: list[FrameRecord],
    advisor_recommendation: ModelAdvisorRecommendation | None,
) -> dict[str, Any]:
    """Build a text-only planning context safe to send to a selected model."""
    return {
        "project_name": project.project_name,
        "working_title": project.working_title,
        "brand_name": project.brand_name,
        "topic": project.topic,
        "director_instructions": project.director_instructions,
        "resolved_platform": answers.platform,
        "resolved_format": answers.output_format,
        "resolved_aspect_ratio": resolve_aspect_ratio(answers),
        "resolved_duration": resolve_duration_seconds(project, answers),
        "resolved_cta": resolve_call_to_action(project, answers),
        "source_summaries": [_source_summary(source) for source in sources],
        "selected_frame_summaries": frame_reference_summary(frame_references),
        "risk_notes": frame_risk_notes(frame_references) + list(recommendation.warnings if recommendation else []),
        "budget_preference": answers.budget_priority,
        "quality_preference": answers.quality_level,
        "source_use_constraints": {
            "source_use": answers.source_use,
            "rights_constraints": answers.rights_constraints,
            "sensitive_materials": answers.sensitive_materials,
            "video_source_treatment": answers.video_source_treatment,
        },
        "model_advisor_recommendation": advisor_recommendation.model_dump(mode="json") if advisor_recommendation else None,
    }


def build_llm_prompt(context: dict[str, Any]) -> list[dict[str, str]]:
    """Build OpenAI-compatible messages for LLM-assisted text planning."""
    system_prompt = (
        "You are a social media planning assistant. Return strict JSON only. "
        "Use British English. Make copy social-media-ready and practical. "
        "Do not invent unsupported factual claims. Respect source-use and licensing constraints. "
        "Do not imply direct likeness of living people. Avoid fantasy styling unless explicitly requested. "
        "Preserve resolved duration, aspect ratio, and concrete CTA. "
        "If evidence is insufficient, say what needs review rather than inventing it."
    )
    user_prompt = (
        "Create an LLM-assisted draft via OpenRouter using the selected model routed through OpenRouter. "
        "Use only this text context; no uploaded media or local file paths are available.\n\n"
        f"{json.dumps(context, indent=2)}\n\n"
        "Return JSON with exactly these keys: "
        "core_message, hook_options, script_outline, shot_list, image_prompt, video_prompts, "
        "caption_drafts, risk_notes, next_actions, rationale."
    )
    return [{"role": "system", "content": system_prompt}, {"role": "user", "content": user_prompt}]


def generate_llm_content_pack(
    config: AppConfig,
    selected_model: str,
    context: dict[str, Any],
    temperature: float,
    max_tokens: int,
) -> dict[str, Any]:
    """Generate a content pack draft with the selected model routed through OpenRouter."""
    messages = build_llm_prompt(context)
    response = call_openrouter_chat(config, selected_model, messages, temperature, max_tokens)
    parsed = parse_llm_content_pack_response(response.get("text", ""))
    return {
        "ok": bool(response.get("ok")),
        "selected_model": selected_model,
        "text": response.get("text", ""),
        "usage": response.get("usage", {}),
        "error": response.get("error"),
        "error_type": response.get("error_type"),
        "parsed_successfully": parsed["parsed_successfully"],
        "parsed": parsed["content"],
        "parse_error": parsed["error"],
    }


def parse_llm_content_pack_response(raw_text: str) -> dict[str, Any]:
    """Parse strict JSON returned by the selected model."""
    cleaned = _strip_json_fence(raw_text.strip())
    try:
        payload = json.loads(cleaned)
    except json.JSONDecodeError as error:
        return {"parsed_successfully": False, "content": None, "error": f"JSON parse failed: {type(error).__name__}"}
    if not isinstance(payload, dict):
        return {"parsed_successfully": False, "content": None, "error": "JSON root was not an object."}
    normalized = {key: payload.get(key, [] if key.endswith("s") or key in {"hook_options"} else "") for key in LLM_JSON_KEYS}
    return {"parsed_successfully": True, "content": normalized, "error": None}


def save_llm_content_pack(
    project_service: ProjectService,
    project: ContentProject,
    llm_result: dict[str, Any],
    advisor_recommendation: ModelAdvisorRecommendation | None,
    catalogue_fetched_at: str | None,
) -> dict[str, Any]:
    """Save LLM-assisted output separately from deterministic project files."""
    parsed = llm_result.get("parsed") if isinstance(llm_result.get("parsed"), dict) else None
    selected_model = str(llm_result.get("selected_model") or "unknown")
    raw_text = str(llm_result.get("text") or "")
    output_hash = hashlib.sha256(f"{selected_model}\n{raw_text}".encode("utf-8")).hexdigest()[:12]
    metadata = {
        "router_provider": "openrouter",
        "selected_model": selected_model,
        "model_advisor_tier": advisor_recommendation.tier if advisor_recommendation else None,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "parsed_successfully": bool(llm_result.get("parsed_successfully")),
        "usage": llm_result.get("usage") or {},
        "catalogue_fetched_at": catalogue_fetched_at,
        "output_hash": output_hash,
    }
    if parsed:
        _write_llm_markdown_files(project.project_path, parsed)
        write_text_file(project.project_path / "llm-output.json", json.dumps({"metadata": metadata, "content": parsed}, indent=2))
    raw_output_path = project.project_path / "llm-raw-output.txt"
    if raw_text and not metadata["parsed_successfully"]:
        write_text_file(raw_output_path, raw_text)
    elif metadata["parsed_successfully"] and raw_output_path.exists():
        raw_output_path.unlink()
    _update_project_llm_metadata(project.project_path / "project.json", metadata)
    _append_llm_asset_log(project.project_path / "asset-log.csv", project.project_id, selected_model, advisor_recommendation, output_hash)
    return metadata


def _source_summary(source: SourceRecord) -> dict[str, Any]:
    """Return a safe source summary without local absolute paths."""
    return {
        "source_id": source.source_id,
        "type": source.source_type.value,
        "name": source.original_filename or source.url or source.manual_description or source.source_id,
        "declared_purpose": source.declared_purpose,
        "strategy": source.strategy.value,
        "duration_seconds": source.duration_seconds if source.source_type == SourceType.VIDEO else None,
        "aspect_ratio": source.aspect_ratio,
        "selected_frame_count": source.selected_frame_count,
        "notes": source.notes[:5],
    }


def _write_llm_markdown_files(project_path: Path, parsed: dict[str, Any]) -> None:
    """Write parsed LLM output to separate markdown files."""
    write_text_file(project_path / "brief.llm.md", _render_llm_brief(parsed))
    write_text_file(project_path / "script.llm.md", _render_llm_list("Script Outline", parsed.get("script_outline", [])))
    write_text_file(project_path / "storyboard.llm.md", _render_llm_list("Storyboard", parsed.get("shot_list", [])))
    write_text_file(project_path / "prompts.llm.md", _render_llm_prompts(parsed))
    write_text_file(project_path / "captions.llm.md", _render_llm_list("Caption Drafts", parsed.get("caption_drafts", [])))


def _render_llm_brief(parsed: dict[str, Any]) -> str:
    """Render LLM brief markdown."""
    return "\n".join(
        [
            "# LLM-Assisted Brief",
            "",
            f"Core message: {parsed.get('core_message') or ''}",
            "",
            "## Hook Options",
            _bullet_lines(parsed.get("hook_options", [])),
            "",
            "## Rationale",
            str(parsed.get("rationale") or ""),
            "",
            "## Risk Notes",
            _bullet_lines(parsed.get("risk_notes", [])),
            "",
            "## Next Actions",
            _bullet_lines(parsed.get("next_actions", [])),
        ]
    )


def _render_llm_prompts(parsed: dict[str, Any]) -> str:
    """Render LLM prompt markdown."""
    return "\n".join(
        [
            "# LLM-Assisted Prompt Pack",
            "",
            "## Image Prompt",
            str(parsed.get("image_prompt") or ""),
            "",
            "## Video Prompts",
            _numbered_lines(parsed.get("video_prompts", [])),
        ]
    )


def _render_llm_list(title: str, items: object) -> str:
    """Render an LLM list markdown file."""
    return f"# LLM-Assisted {title}\n\n{_numbered_lines(items)}"


def _update_project_llm_metadata(project_json_path: Path, metadata: dict[str, Any]) -> None:
    """Update project.json with LLM metadata without secrets."""
    try:
        payload = json.loads(project_json_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        payload = {}
    payload["llm_content_pack"] = metadata
    write_text_file(project_json_path, json.dumps(payload, indent=2))


def _append_llm_asset_log(
    asset_log_path: Path,
    project_id: str,
    selected_model: str,
    advisor_recommendation: ModelAdvisorRecommendation | None,
    output_hash: str,
) -> None:
    """Append a generated text row without duplicating the saved output hash."""
    asset_id = f"llm-text-{output_hash}"
    rows = _read_asset_rows(asset_log_path)
    if any(row.get("asset_id") == asset_id for row in rows):
        return
    rows.append(
        {
            "asset_id": asset_id,
            "project_id": project_id,
            "source_or_generated": "generated_text",
            "file_name": "llm-output.json",
            "tool_or_model": selected_model,
            "estimated_cost_band": advisor_recommendation.estimated_cost_band if advisor_recommendation else "unknown",
            "time_spent_minutes": "",
            "rating": "unrated",
            "historical_or_brand_risk": "needs_review",
            "keep_reject": "undecided",
            "notes": "LLM-assisted content pack generated via OpenRouter router/provider",
        }
    )
    _write_asset_rows(asset_log_path, rows)


def _read_asset_rows(asset_log_path: Path) -> list[dict[str, str]]:
    """Read asset-log rows or return an empty list."""
    if not asset_log_path.exists():
        return []
    with asset_log_path.open("r", encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


def _write_asset_rows(asset_log_path: Path, rows: list[dict[str, str]]) -> None:
    """Write asset-log rows."""
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
    with asset_log_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=columns)
        writer.writeheader()
        writer.writerows(rows)


def _strip_json_fence(value: str) -> str:
    """Remove a simple Markdown JSON fence when present."""
    if value.startswith("```"):
        lines = value.splitlines()
        if lines and lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        return "\n".join(lines).strip()
    return value


def _bullet_lines(items: object) -> str:
    """Render a bullet list from a value."""
    values = items if isinstance(items, list) else [items] if items else []
    return "\n".join(f"- {item}" for item in values)


def _numbered_lines(items: object) -> str:
    """Render a numbered list from a value."""
    values = items if isinstance(items, list) else [items] if items else []
    return "\n".join(f"{index}. {item}" for index, item in enumerate(values, 1))
