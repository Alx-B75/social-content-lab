"""Consent-gated OpenRouter vision analysis for selected extracted frames."""

import base64
import json
import mimetypes
import re
from pathlib import Path
from typing import Any

from src.config import AppConfig
from src.models.project import ContentProject
from src.models.source import FrameRecord, FrameRole
from src.services.frame_prefill import apply_prefill_to_frame
from src.services.openrouter_catalog import is_router_helper_model_id
from src.services.openrouter_client import call_openrouter_chat


VISION_FIELDS = {
    "selected_role",
    "notes",
    "description",
    "visible_subject",
    "setting",
    "mood",
    "visual_style",
    "on_screen_text",
    "rights_notes",
    "historical_or_brand_risk",
    "recommended_use",
    "avoid_using_for",
    "confidence",
}


def analyse_frame_with_vision_model(
    config: AppConfig,
    model_id: str,
    frame_path: Path,
    project: ContentProject,
    frame: FrameRecord,
    max_tokens: int = 600,
) -> dict[str, Any]:
    """Send one extracted frame and safe text context to a concrete vision model."""
    if is_router_helper_model_id(model_id) or not model_id.strip():
        return _failure("invalid_model", "Choose a concrete vision-capable model.")
    try:
        image_url = _frame_data_url(frame_path)
    except (OSError, ValueError) as error:
        return _failure("frame_read_failed", f"Frame analysis could not start: {type(error).__name__}.")
    result = call_openrouter_chat(
        config,
        model_id,
        build_frame_analysis_messages(project, frame, image_url),
        temperature=0.2,
        max_tokens=max_tokens,
    )
    if not result.get("ok"):
        return {**result, "parsed_successfully": False, "analysis": None}
    parsed = parse_frame_analysis_response(str(result.get("text") or ""))
    return {**result, **parsed}


def build_frame_analysis_messages(project: ContentProject, frame: FrameRecord, image_data_url: str) -> list[dict[str, Any]]:
    """Build a path-free multimodal request for one selected extracted frame."""
    prompt = "\n".join(
        [
            "Analyse only the attached extracted video frame for local content planning.",
            f"Project: {_safe_context_text(project.project_name)}",
            f"Working title: {_safe_context_text(project.working_title)}",
            f"Brand: {_safe_context_text(project.brand_name or 'Not specified')}",
            f"Topic: {_safe_context_text(project.topic or 'Not specified')}",
            f"Frame label: {frame.label}",
            f"Timestamp seconds: {frame.timestamp_seconds if frame.timestamp_seconds is not None else 'unknown'}",
            "Return strict JSON with keys: selected_role, notes, description, visible_subject, setting, mood, visual_style, on_screen_text, rights_notes, historical_or_brand_risk, recommended_use, avoid_using_for, confidence.",
            "selected_role must be one of unselected, hero_frame, visual_reference, do_not_use, possible_background, needs_review.",
            "Do not infer identity, rights ownership, sensitive traits, or historical facts. Flag uncertainty and require human review.",
        ]
    )
    return [
        {"role": "system", "content": "You are a cautious visual pre-production assistant. Return JSON only."},
        {
            "role": "user",
            "content": [
                {"type": "text", "text": prompt},
                {"type": "image_url", "image_url": {"url": image_data_url}},
            ],
        },
    ]


def parse_frame_analysis_response(raw_text: str) -> dict[str, Any]:
    """Parse strict or fenced JSON from a vision response without another API call."""
    cleaned = raw_text.strip()
    if cleaned.startswith("```"):
        lines = cleaned.splitlines()
        cleaned = "\n".join(lines[1:-1]).strip() if len(lines) >= 3 else cleaned
    candidates = [cleaned]
    start = cleaned.find("{")
    end = cleaned.rfind("}")
    if start >= 0 and end > start:
        candidates.append(cleaned[start : end + 1])
    for candidate in candidates:
        try:
            payload = json.loads(candidate)
        except json.JSONDecodeError:
            continue
        if not isinstance(payload, dict):
            continue
        analysis = {key: payload.get(key, "") for key in VISION_FIELDS}
        try:
            analysis["selected_role"] = FrameRole(str(analysis.get("selected_role") or "needs_review"))
        except ValueError:
            analysis["selected_role"] = FrameRole.NEEDS_REVIEW
        return {"parsed_successfully": True, "analysis": analysis, "error_type": None, "error": None}
    return _failure("json_parse_failed", "The frame analysis response could not be parsed as JSON.")


def apply_ai_frame_prefill(
    frame: FrameRecord,
    analysis: dict[str, Any] | None,
    model_id: str,
    replace_existing: bool = False,
) -> FrameRecord:
    """Apply a parsed AI analysis without overwriting manual/local values by default."""
    if not analysis:
        return frame
    confidence = str(analysis.get("confidence") or "").strip()
    return apply_prefill_to_frame(
        frame,
        analysis,
        replace_existing=replace_existing,
        prefill_source="ai_vision",
        model_id=model_id,
        confidence=confidence,
    )


def _frame_data_url(frame_path: Path) -> str:
    """Encode one local extracted image as an in-request data URL."""
    mime_type = mimetypes.guess_type(frame_path.name)[0] or "image/jpeg"
    if mime_type not in {"image/jpeg", "image/png", "image/webp"}:
        raise ValueError("Unsupported extracted frame type.")
    encoded = base64.b64encode(frame_path.read_bytes()).decode("ascii")
    return f"data:{mime_type};base64,{encoded}"


def _safe_context_text(value: str) -> str:
    """Remove path- and secret-like fragments from user-entered prompt context."""
    cleaned = re.sub(r"(?i)\b[a-z]:\\[^\s]+", "[local path removed]", str(value))
    cleaned = re.sub(r"(?i)\b(?:sk-or-v1-|sk-)[a-z0-9_-]{16,}\b", "[secret removed]", cleaned)
    return cleaned[:500]


def _failure(error_type: str, message: str) -> dict[str, Any]:
    """Return a stable failed-analysis result."""
    return {"ok": False, "parsed_successfully": False, "analysis": None, "error_type": error_type, "error": message, "usage": {}}
