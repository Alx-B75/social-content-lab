"""OpenRouter model catalogue fetching, caching, and filtering."""

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import httpx

from src.config import AppConfig
from src.services.file_utils import ensure_directory, write_text_file


FRESH_SECONDS = 24 * 60 * 60
VERY_STALE_SECONDS = 7 * 24 * 60 * 60


def fetch_openrouter_models(config: AppConfig, timeout_seconds: float = 20.0) -> dict[str, Any]:
    """Fetch and normalize the current OpenRouter model catalogue."""
    url = _catalogue_url(config)
    headers = _catalogue_headers(config)
    try:
        response = httpx.get(url, headers=headers, timeout=timeout_seconds)
        response.raise_for_status()
        payload = response.json()
    except (httpx.HTTPError, json.JSONDecodeError, OSError) as error:
        return _catalogue_payload([], "failed", type(error).__name__)
    raw_models = payload.get("data") if isinstance(payload, dict) else []
    normalized_models = [
        normalize_openrouter_model(model)
        for model in raw_models
        if isinstance(model, dict)
    ]
    return _catalogue_payload(normalized_models, "ok", None)


def load_cached_model_catalog(cache_path: Path) -> dict[str, Any] | None:
    """Load a cached OpenRouter model catalogue if it exists and parses."""
    if not cache_path.exists():
        return None
    try:
        payload = json.loads(cache_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return payload if isinstance(payload, dict) else None


def save_model_catalog_cache(cache_path: Path, catalog: dict[str, Any]) -> None:
    """Save a normalized model catalogue cache without secrets."""
    ensure_directory(cache_path.parent)
    write_text_file(cache_path, json.dumps(catalog, indent=2))


def get_model_catalog_status(cache_path: Path) -> dict[str, Any]:
    """Return catalogue cache status and freshness metadata."""
    catalog = load_cached_model_catalog(cache_path)
    if catalog is None:
        return {
            "availability": "unavailable",
            "freshness": "unavailable",
            "last_refreshed": None,
            "model_count": 0,
            "warning": "Model catalogue is unavailable. Manual model entry and deterministic mode remain available.",
            "catalog": None,
        }
    fetched_at = _parse_datetime(catalog.get("fetched_at"))
    freshness = _freshness_label(fetched_at)
    catalog["freshness"] = freshness
    warning = None
    if freshness == "stale":
        warning = "Model catalogue is stale; pricing and recommendations may be unreliable."
    if freshness == "very stale":
        warning = "Model catalogue is very stale; refresh before relying on pricing or model recommendations."
    if catalog.get("fetch_status") != "ok":
        warning = catalog.get("error_summary") or "Last model catalogue refresh failed."
    return {
        "availability": "available" if catalog.get("models") else "unavailable",
        "freshness": freshness,
        "last_refreshed": catalog.get("fetched_at"),
        "model_count": int(catalog.get("model_count") or 0),
        "warning": warning,
        "catalog": catalog,
    }


def normalize_openrouter_model(raw_model: dict[str, Any]) -> dict[str, Any]:
    """Normalize one OpenRouter model record with defensive field access."""
    architecture = raw_model.get("architecture") if isinstance(raw_model.get("architecture"), dict) else {}
    pricing = raw_model.get("pricing") if isinstance(raw_model.get("pricing"), dict) else {}
    supported_parameters = raw_model.get("supported_parameters") or raw_model.get("supported_parameters_json_schema") or []
    input_modalities = _as_string_list(architecture.get("input_modalities"))
    output_modalities = _as_string_list(architecture.get("output_modalities"))
    description = str(raw_model.get("description") or "")
    model_id = str(raw_model.get("id") or raw_model.get("canonical_slug") or "")
    return {
        "model_id": model_id,
        "name": str(raw_model.get("name") or model_id),
        "provider": _provider_from_model_id(model_id),
        "description": description,
        "context_length": _safe_int(raw_model.get("context_length")),
        "max_output_tokens": _safe_int(raw_model.get("max_completion_tokens") or raw_model.get("max_output_tokens")),
        "input_modalities": input_modalities,
        "output_modalities": output_modalities,
        "supported_parameters": _as_string_list(supported_parameters),
        "pricing_prompt": _safe_float(pricing.get("prompt")),
        "pricing_completion": _safe_float(pricing.get("completion")),
        "pricing_image": _safe_float(pricing.get("image")),
        "pricing_request": _safe_float(pricing.get("request")),
        "tokenizer": architecture.get("tokenizer"),
        "architecture": {
            "modality": architecture.get("modality"),
            "instruct_type": architecture.get("instruct_type"),
            "tokenizer": architecture.get("tokenizer"),
        },
        "text_output_supported": _supports_text_output(output_modalities, architecture),
        "structured_output_supported": _supports_structured_output(_as_string_list(supported_parameters), description),
        "vision_input_supported": _supports_vision_input(input_modalities, architecture),
        "tool_use_supported": _supports_tool_use(_as_string_list(supported_parameters), description),
        "raw_capability_notes": _capability_notes(raw_model),
    }


def filter_text_planning_models(models: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Return catalogue models that appear suitable for text planning."""
    return [
        model
        for model in models
        if model.get("model_id") and model.get("text_output_supported") and not _is_router_helper_model(model)
    ]


def estimate_model_cost_from_catalog(model: dict[str, Any], input_tokens: int, output_tokens: int) -> dict[str, Any]:
    """Estimate cost from normalized catalogue pricing when available."""
    prompt_price = model.get("pricing_prompt")
    completion_price = model.get("pricing_completion")
    request_price = model.get("pricing_request") or 0.0
    if prompt_price is None or completion_price is None:
        return {"estimated_cost": None, "cost_band": "unknown", "pricing_available": False}
    estimated_cost = (prompt_price * input_tokens) + (completion_price * output_tokens) + request_price
    return {
        "estimated_cost": estimated_cost,
        "cost_band": _cost_band(estimated_cost),
        "pricing_available": True,
    }


def select_candidate_models_for_job(models: list[dict[str, Any]], expected_input_tokens: int, need_json: bool) -> list[dict[str, Any]]:
    """Return viable model candidates for a text planning job."""
    candidates = []
    for model in filter_text_planning_models(models):
        context_length = model.get("context_length")
        if context_length and context_length < expected_input_tokens + 2000:
            continue
        if need_json and model.get("structured_output_supported") is False:
            continue
        candidates.append(model)
    return candidates


def _catalogue_url(config: AppConfig) -> str:
    """Return the OpenRouter models endpoint URL."""
    return f"{config.openrouter_base_url.rstrip('/')}/models"


def _catalogue_headers(config: AppConfig) -> dict[str, str]:
    """Return safe headers for the model catalogue request."""
    headers = {"Accept": "application/json"}
    if config.openrouter_api_key:
        headers["Authorization"] = f"Bearer {config.openrouter_api_key}"
    return headers


def _catalogue_payload(models: list[dict[str, Any]], fetch_status: str, error_summary: str | None) -> dict[str, Any]:
    """Build a cache-safe catalogue payload."""
    payload = {
        "fetched_at": datetime.now(timezone.utc).isoformat(),
        "source": "openrouter",
        "model_count": len(models),
        "fetch_status": fetch_status,
        "models": models,
    }
    if error_summary:
        payload["error_summary"] = error_summary
    return payload


def _parse_datetime(value: object) -> datetime | None:
    """Parse an ISO datetime value when possible."""
    if not value:
        return None
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None


def _freshness_label(fetched_at: datetime | None) -> str:
    """Return catalogue freshness label."""
    if fetched_at is None:
        return "unavailable"
    age_seconds = (datetime.now(timezone.utc) - fetched_at).total_seconds()
    if age_seconds < FRESH_SECONDS:
        return "fresh"
    if age_seconds <= VERY_STALE_SECONDS:
        return "stale"
    return "very stale"


def _supports_text_output(output_modalities: list[str], architecture: dict[str, Any]) -> bool:
    """Infer whether a model supports text output."""
    modality = str(architecture.get("modality") or "").lower()
    return "text" in output_modalities or "text" in modality


def _supports_structured_output(parameters: list[str], description: str) -> bool:
    """Infer whether JSON or structured output appears supported."""
    combined = " ".join(parameters + [description]).lower()
    return any(term in combined for term in ["response_format", "structured", "json"])


def _supports_vision_input(input_modalities: list[str], architecture: dict[str, Any]) -> bool:
    """Infer whether a model supports vision input."""
    modality = str(architecture.get("modality") or "").lower()
    return any(term in input_modalities for term in ["image", "vision"]) or "image" in modality


def _supports_tool_use(parameters: list[str], description: str) -> bool:
    """Infer whether a model supports tool or function calling."""
    combined = " ".join(parameters + [description]).lower()
    return any(term in combined for term in ["tools", "tool_choice", "function", "function calling"])


def _provider_from_model_id(model_id: str) -> str | None:
    """Return a provider-like grouping from a model slug."""
    if "/" not in model_id:
        return None
    return model_id.split("/", 1)[0]


def _is_router_helper_model(model: dict[str, Any]) -> bool:
    """Return whether a catalogue record is a router helper instead of an underlying model."""
    model_id = str(model.get("model_id") or "").lower()
    provider = str(model.get("provider") or "").lower()
    name = str(model.get("name") or "").lower()
    return provider == "openrouter" or model_id.startswith("openrouter/") or name in {"auto router"}


def _capability_notes(raw_model: dict[str, Any]) -> dict[str, Any]:
    """Return safe capability notes from a raw catalogue model."""
    return {
        "created": raw_model.get("created"),
        "canonical_slug": raw_model.get("canonical_slug"),
        "per_request_limits": raw_model.get("per_request_limits"),
    }


def _as_string_list(value: object) -> list[str]:
    """Convert a value into a list of strings."""
    if isinstance(value, list):
        return [str(item) for item in value if item is not None]
    if value is None:
        return []
    return [str(value)]


def _safe_int(value: object) -> int | None:
    """Convert a value to int when possible."""
    try:
        return int(value) if value is not None else None
    except (TypeError, ValueError):
        return None


def _safe_float(value: object) -> float | None:
    """Convert a value to float when possible."""
    try:
        return float(value) if value is not None else None
    except (TypeError, ValueError):
        return None


def _cost_band(estimated_cost: float) -> str:
    """Return a rough cost band for one request estimate."""
    if estimated_cost <= 0:
        return "free/manual"
    if estimated_cost < 0.002:
        return "very low"
    if estimated_cost < 0.02:
        return "low"
    if estimated_cost < 0.2:
        return "medium"
    return "high"
