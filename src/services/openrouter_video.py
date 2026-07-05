"""OpenRouter video catalogue and generation helpers."""

import base64
import json
import mimetypes
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import httpx

from src.config import AppConfig
from src.services.file_utils import ensure_directory, write_text_file
from src.services.openrouter_client import build_openrouter_headers, is_openrouter_configured, safe_openrouter_error_message
from src.services.openrouter_catalog import FRESH_SECONDS, VERY_STALE_SECONDS, is_router_helper_model_id
from src.services.video_generation_providers import IMAGE_TO_VIDEO, TEXT_TO_VIDEO, VideoModelCapability


OPENROUTER_VIDEO_PROVIDER_NAME = "openrouter"
TERMINAL_FAILURE_STATUSES = {"failed", "cancelled", "expired"}
COMPLETED_STATUS = "completed"


def fetch_openrouter_video_models(config: AppConfig, timeout_seconds: float = 20.0) -> dict[str, Any]:
    """Fetch and normalize OpenRouter video generation models."""
    if not is_openrouter_configured(config):
        return _catalogue_payload([], "failed", "missing_api_key")
    try:
        response = httpx.get(_video_models_url(config), headers=build_openrouter_headers(config), timeout=timeout_seconds)
        response.raise_for_status()
        payload = response.json()
    except (httpx.HTTPError, json.JSONDecodeError, OSError) as error:
        return _catalogue_payload([], "failed", safe_openrouter_error_message(error) if isinstance(error, httpx.HTTPStatusError) else type(error).__name__)
    raw_models = payload.get("data") if isinstance(payload, dict) else []
    normalized = [normalize_openrouter_video_model(model) for model in raw_models if isinstance(model, dict)]
    return _catalogue_payload(normalized, "ok", None)


def load_cached_video_model_catalog(cache_path: Path) -> dict[str, Any] | None:
    """Load a cached OpenRouter video model catalogue."""
    if not cache_path.exists():
        return None
    try:
        payload = json.loads(cache_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return payload if isinstance(payload, dict) else None


def save_video_model_catalog_cache(cache_path: Path, catalog: dict[str, Any]) -> None:
    """Save a normalized OpenRouter video catalogue cache without secrets."""
    ensure_directory(cache_path.parent)
    write_text_file(cache_path, json.dumps(catalog, indent=2))


def get_video_model_catalog_status(cache_path: Path) -> dict[str, Any]:
    """Return video catalogue cache status and freshness metadata."""
    catalog = load_cached_video_model_catalog(cache_path)
    if catalog is None:
        return {
            "availability": "unavailable",
            "freshness": "unavailable",
            "last_refreshed": None,
            "model_count": 0,
            "warning": "OpenRouter video model catalogue is unavailable. Mock provider remains available.",
            "catalog": None,
        }
    fetched_at = _parse_datetime(catalog.get("fetched_at"))
    freshness = _freshness_label(fetched_at)
    catalog["freshness"] = freshness
    warning = None
    if freshness == "stale":
        warning = "OpenRouter video model catalogue is stale; pricing and recommendations may be unreliable."
    if freshness == "very stale":
        warning = "OpenRouter video model catalogue is very stale; refresh before paid video tests."
    if catalog.get("fetch_status") != "ok":
        warning = catalog.get("error_summary") or "Last OpenRouter video catalogue refresh failed."
    return {
        "availability": "available" if catalog.get("models") else "unavailable",
        "freshness": freshness,
        "last_refreshed": catalog.get("fetched_at"),
        "model_count": int(catalog.get("model_count") or 0),
        "warning": warning,
        "catalog": catalog,
    }


def normalize_openrouter_video_model(raw_model: dict[str, Any]) -> dict[str, Any]:
    """Normalize one OpenRouter video model record."""
    model_id = str(raw_model.get("id") or raw_model.get("canonical_slug") or "")
    pricing_skus = raw_model.get("pricing_skus") if isinstance(raw_model.get("pricing_skus"), dict) else {}
    supported_frame_images = _as_string_list(raw_model.get("supported_frame_images"))
    return {
        "model_id": model_id,
        "name": str(raw_model.get("name") or model_id),
        "provider": _provider_from_model_id(model_id),
        "description": str(raw_model.get("description") or ""),
        "canonical_slug": str(raw_model.get("canonical_slug") or model_id),
        "supported_durations": _as_int_list(raw_model.get("supported_durations")),
        "supported_resolutions": _as_string_list(raw_model.get("supported_resolutions")),
        "supported_aspect_ratios": _as_string_list(raw_model.get("supported_aspect_ratios")),
        "supported_sizes": _as_string_list(raw_model.get("supported_sizes")),
        "supported_frame_images": supported_frame_images,
        "supports_frame_images": bool(supported_frame_images),
        "allowed_passthrough_parameters": _as_string_list(raw_model.get("allowed_passthrough_parameters")),
        "pricing_skus": {str(key): _safe_float(value) for key, value in pricing_skus.items()},
        "generate_audio": raw_model.get("generate_audio"),
        "seed": raw_model.get("seed"),
        "raw_capability_notes": {
            "created": raw_model.get("created"),
            "capability_confidence": "catalogue",
        },
    }


def openrouter_video_catalog_to_capabilities(catalog: dict[str, Any] | None, configured: bool) -> list[VideoModelCapability]:
    """Convert a normalized video catalogue to provider capabilities."""
    if not catalog or catalog.get("fetch_status") != "ok":
        return []
    capabilities: list[VideoModelCapability] = []
    for model in catalog.get("models", []):
        if not isinstance(model, dict):
            continue
        model_id = str(model.get("model_id") or "")
        if not model_id or is_router_helper_model_id(model_id):
            continue
        supports_frame = bool(model.get("supports_frame_images"))
        modes = [TEXT_TO_VIDEO]
        if supports_frame:
            modes.append(IMAGE_TO_VIDEO)
        estimate = estimate_openrouter_video_cost(model, _first_duration(model), _first_resolution(model))
        capabilities.append(
            VideoModelCapability(
                provider_name=OPENROUTER_VIDEO_PROVIDER_NAME,
                model_name=model_id,
                display_name=str(model.get("name") or model_id),
                modes=modes,
                supports_reference_image=supports_frame,
                supported_durations_seconds=list(model.get("supported_durations") or []),
                supported_aspect_ratios=list(model.get("supported_aspect_ratios") or []),
                supported_resolutions=list(model.get("supported_resolutions") or []),
                supported_sizes=list(model.get("supported_sizes") or []),
                supported_frame_images=list(model.get("supported_frame_images") or []),
                output_download_supported=True,
                pricing_known=estimate["confidence"] == "known",
                estimated_cost=estimate["estimated_cost"] if estimate["confidence"] == "known" else None,
                estimated_cost_band=estimate["cost_band"],
                cost_estimate_confidence=estimate["confidence"],
                cost_estimate_note=estimate["note"],
                configured=configured,
                implemented=True,
                is_mock=False,
                quality_rank=_quality_rank(model),
                price_rank=_price_rank(estimate["estimated_cost"] if estimate["confidence"] == "known" else estimate["pricing_hint"]),
                reliability="OpenRouter video catalogue",
                known_limitations=_known_limitations(model),
                capability_metadata={
                    "pricing_skus": model.get("pricing_skus") or {},
                    "pricing_hint": estimate["pricing_hint"],
                    "allowed_passthrough_parameters": model.get("allowed_passthrough_parameters") or [],
                    "generate_audio": model.get("generate_audio"),
                },
            )
        )
    return capabilities


def estimate_openrouter_video_cost(
    model: dict[str, Any],
    duration_seconds: int | None,
    resolution: str | None = None,
) -> dict[str, Any]:
    """Return a conservative OpenRouter video cost estimate or pricing hint."""
    prices = model.get("pricing_skus") if isinstance(model.get("pricing_skus"), dict) else {}
    numeric_prices = {str(key): value for key, value in prices.items() if isinstance(value, int | float)}
    if not numeric_prices:
        return {
            "estimated_cost": None,
            "pricing_hint": None,
            "cost_band": "unknown",
            "pricing_available": False,
            "confidence": "unavailable",
            "note": "Cost estimate unavailable. OpenRouter may return actual usage cost after generation.",
        }
    duration = max(int(duration_seconds or _first_duration(model) or 1), 1)
    resolution_key = str(resolution or "").lower()
    candidates: list[float] = []
    for sku, price in numeric_prices.items():
        sku_lower = sku.lower()
        if resolution_key and resolution_key in sku_lower:
            candidates.append(_price_for_sku(sku_lower, float(price), duration))
        elif not resolution_key:
            candidates.append(_price_for_sku(sku_lower, float(price), duration))
    if not candidates:
        candidates = [_price_for_sku(sku.lower(), float(price), duration) for sku, price in numeric_prices.items()]
    estimated = min(candidates) if candidates else None
    return {
        "estimated_cost": None,
        "pricing_hint": estimated,
        "cost_band": _cost_band(estimated),
        "pricing_available": False,
        "confidence": "low",
        "note": "Cost estimate unavailable or low-confidence. OpenRouter may return actual usage cost after generation.",
    }


def build_openrouter_video_request_payload(
    request: Any,
    capability: VideoModelCapability,
    include_reference_image: bool,
) -> dict[str, Any]:
    """Build the OpenRouter video request payload in one isolated place."""
    payload: dict[str, Any] = {
        "model": capability.model_name,
        "prompt": _sanitize_outbound_text(request.prompt),
        "generate_audio": False,
    }
    if _supports_duration(capability, request.duration_seconds):
        payload["duration"] = request.duration_seconds
    if _supports_aspect_ratio(capability, request.aspect_ratio):
        payload["aspect_ratio"] = request.aspect_ratio
    resolution = request.settings.get("resolution") or _default_resolution(capability)
    if resolution and _supports_resolution(capability, resolution):
        payload["resolution"] = resolution
    size = request.settings.get("size")
    if size and _supports_size(capability, size):
        payload["size"] = size
    if request.seed is not None:
        payload["seed"] = request.seed
    allowed = set(capability.capability_metadata.get("allowed_passthrough_parameters") or [])
    if request.negative_prompt and "negative_prompt" in allowed:
        payload["provider"] = {"negative_prompt": _sanitize_outbound_text(request.negative_prompt)}
    reference_image_path = getattr(request, "reference_image_path", None)
    reference_frame = getattr(request, "reference_frame", None)
    if reference_image_path is None and reference_frame is not None:
        reference_image_path = reference_frame.absolute_path
    if include_reference_image and reference_image_path is not None:
        payload["frame_images"] = [
            {
                "type": "image_url",
                "image_url": {"url": _image_data_url(reference_image_path)},
                "frame_type": "first_frame",
            }
        ]
    return payload


def openrouter_request_preview(
    request: Any,
    capability: VideoModelCapability,
    max_spend_usd: float,
) -> dict[str, Any]:
    """Return a safe request preview and spend guard result."""
    include_reference = request.mode == IMAGE_TO_VIDEO and bool(request.reference_frame) and capability.supports_reference_image
    resolution = request.settings.get("resolution") or _default_resolution(capability)
    confidence = capability.cost_estimate_confidence
    return {
        "provider": capability.provider_name,
        "model": capability.model_name,
        "mode": request.mode,
        "prompt_source": request.prompt_source_label,
        "duration_seconds": request.duration_seconds,
        "aspect_ratio": request.aspect_ratio,
        "resolution": resolution,
        "reference_frame_will_be_sent": include_reference,
        "negative_prompt_will_be_sent": _negative_prompt_will_be_sent(request, capability),
        "estimated_cost": capability.estimated_cost if confidence == "known" else None,
        "pricing_hint": capability.capability_metadata.get("pricing_hint"),
        "cost_band": capability.estimated_cost_band,
        "cost_known": confidence == "known" and capability.estimated_cost is not None,
        "cost_estimate_confidence": confidence,
        "cost_estimate_note": capability.cost_estimate_note,
        "max_spend_usd": max_spend_usd,
        "spend_guard_passed": confidence != "known" or capability.estimated_cost is None or capability.estimated_cost <= max_spend_usd,
        "inputs_sent": _inputs_sent(request, include_reference),
    }


class OpenRouterVideoProvider:
    """OpenRouter-routed video generation provider."""

    provider_name = OPENROUTER_VIDEO_PROVIDER_NAME

    def __init__(
        self,
        config: AppConfig,
        catalog: dict[str, Any] | None = None,
        http_client: Any = httpx,
        poll_interval_seconds: float = 5.0,
        max_poll_attempts: int = 60,
    ) -> None:
        """Initialise the provider with config, catalogue, and HTTP client."""
        self.config = config
        self.catalog = catalog
        self.http_client = http_client
        self.poll_interval_seconds = poll_interval_seconds
        self.max_poll_attempts = max_poll_attempts

    def list_models(self) -> list[VideoModelCapability]:
        """Return OpenRouter video model capabilities from cache."""
        return openrouter_video_catalog_to_capabilities(self.catalog, is_openrouter_configured(self.config))

    def generate(self, model_name: str, request: Any, target_output_path: Path) -> Any:
        """Submit, poll, download, and save one OpenRouter video job."""
        from src.services.video_generation_providers import VideoProviderGenerationResult

        if not is_openrouter_configured(self.config):
            return VideoProviderGenerationResult(status="failed", error_type="missing_api_key", error_message="OpenRouter API key is not configured.")
        capability = next((item for item in self.list_models() if item.model_name == model_name), None)
        if capability is None:
            return VideoProviderGenerationResult(status="failed", error_type="unknown_model", error_message="Selected OpenRouter video model is unavailable in the current catalogue.")
        include_reference = request.mode == IMAGE_TO_VIDEO and bool(request.reference_image_path) and capability.supports_reference_image
        try:
            payload = build_openrouter_video_request_payload(request, capability, include_reference)
            submitted = self._submit(payload)
            completed = self._poll_until_complete(submitted)
            content = self._download(completed)
        except httpx.HTTPStatusError as error:
            return VideoProviderGenerationResult(status="failed", error_type="http_error", error_message=safe_openrouter_error_message(error))
        except (httpx.HTTPError, json.JSONDecodeError, OSError, ValueError) as error:
            return VideoProviderGenerationResult(status="failed", error_type=_safe_error_type(error), error_message=_safe_error_message(error))
        target_output_path.parent.mkdir(parents=True, exist_ok=True)
        target_output_path.write_bytes(content)
        usage = completed.get("usage") if isinstance(completed.get("usage"), dict) else {}
        cost = usage.get("cost") if isinstance(usage, dict) else None
        return VideoProviderGenerationResult(
            status=str(completed.get("status") or COMPLETED_STATUS),
            output_path=target_output_path,
            cost=str(cost) if cost is not None else None,
            provider_job_id=str(completed.get("id") or submitted.get("id") or ""),
            raw_metadata={
                "polling_url": completed.get("polling_url") or submitted.get("polling_url"),
                "generation_id": completed.get("generation_id") or submitted.get("generation_id"),
                "usage": usage,
                "unsigned_urls_present": bool(completed.get("unsigned_urls")),
            },
        )

    def _submit(self, payload: dict[str, Any]) -> dict[str, Any]:
        """Submit a video generation job."""
        response = self.http_client.post(_videos_url(self.config), headers=build_openrouter_headers(self.config), json=payload, timeout=60.0)
        response.raise_for_status()
        return response.json()

    def _poll_until_complete(self, submitted: dict[str, Any]) -> dict[str, Any]:
        """Poll a video job until completion or terminal failure."""
        current = submitted
        for attempt in range(self.max_poll_attempts):
            status = str(current.get("status") or "").lower()
            if status == COMPLETED_STATUS:
                return current
            if status in TERMINAL_FAILURE_STATUSES:
                raise ValueError(str(current.get("error") or f"OpenRouter video generation {status}."))
            polling_url = current.get("polling_url")
            job_id = current.get("id")
            if not polling_url and not job_id:
                raise ValueError("OpenRouter video job did not include a polling URL or job ID.")
            if attempt > 0 or status:
                time.sleep(self.poll_interval_seconds)
            poll_url = _absolute_openrouter_url(self.config, str(polling_url or f"/videos/{job_id}"))
            response = self.http_client.get(poll_url, headers=build_openrouter_headers(self.config), timeout=30.0)
            response.raise_for_status()
            current = response.json()
        raise TimeoutError("OpenRouter video generation did not complete before the polling timeout.")

    def _download(self, completed: dict[str, Any]) -> bytes:
        """Download completed video content."""
        unsigned_urls = completed.get("unsigned_urls") if isinstance(completed.get("unsigned_urls"), list) else []
        url = str(unsigned_urls[0]) if unsigned_urls else _absolute_openrouter_url(self.config, f"/videos/{completed.get('id')}/content?index=0")
        headers = build_openrouter_headers(self.config) if url.startswith(self.config.openrouter_base_url.rstrip("/")) else {}
        response = self.http_client.get(url, headers=headers, timeout=120.0)
        response.raise_for_status()
        return response.content


def _video_models_url(config: AppConfig) -> str:
    """Return OpenRouter video models endpoint URL."""
    return f"{config.openrouter_base_url.rstrip('/')}/videos/models"


def _videos_url(config: AppConfig) -> str:
    """Return OpenRouter video generation endpoint URL."""
    return f"{config.openrouter_base_url.rstrip('/')}/videos"


def _absolute_openrouter_url(config: AppConfig, value: str) -> str:
    """Return an absolute OpenRouter URL for relative polling/content paths."""
    if value.startswith("http://") or value.startswith("https://"):
        return value
    base = config.openrouter_base_url.rstrip("/")
    path = value if value.startswith("/") else f"/{value}"
    if path.startswith("/api/v1/"):
        return f"https://openrouter.ai{path}"
    return f"{base}{path}"


def _catalogue_payload(models: list[dict[str, Any]], fetch_status: str, error_summary: str | None) -> dict[str, Any]:
    """Build a cache-safe video catalogue payload."""
    payload = {
        "fetched_at": datetime.now(timezone.utc).isoformat(),
        "source": "openrouter_video",
        "model_count": len(models),
        "fetch_status": fetch_status,
        "models": models,
    }
    if error_summary:
        payload["error_summary"] = error_summary
    return payload


def _parse_datetime(value: object) -> datetime | None:
    """Parse an ISO datetime value."""
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


def _provider_from_model_id(model_id: str) -> str | None:
    """Return provider prefix from model ID."""
    if "/" not in model_id:
        return None
    return model_id.split("/", 1)[0]


def _first_duration(model: dict[str, Any]) -> int | None:
    """Return the first supported duration."""
    durations = model.get("supported_durations") or []
    return int(durations[0]) if durations else None


def _first_resolution(model: dict[str, Any] | VideoModelCapability) -> str | None:
    """Return a low-cost default resolution when available."""
    resolutions = model.get("supported_resolutions") if isinstance(model, dict) else model.supported_resolutions
    if not resolutions:
        return None
    if "720p" in resolutions:
        return "720p"
    return str(resolutions[0])


def _default_resolution(capability: VideoModelCapability) -> str | None:
    """Return a safe default resolution for a capability."""
    return _first_resolution(capability)


def _price_for_sku(sku: str, price: float, duration: int) -> float:
    """Return estimated request cost from a video pricing SKU."""
    if "second" in sku:
        return price * duration
    return price


def _cost_band(estimated_cost: float | None) -> str:
    """Return a rough cost band for one video request."""
    if estimated_cost is None:
        return "unknown"
    if estimated_cost <= 0:
        return "free/manual"
    if estimated_cost < 0.05:
        return "very low"
    if estimated_cost < 0.25:
        return "low"
    if estimated_cost < 1.0:
        return "medium"
    return "high"


def _price_rank(estimated_cost: float | None) -> int:
    """Return a low-is-better price rank."""
    if estimated_cost is None:
        return 5
    if estimated_cost < 0.05:
        return 1
    if estimated_cost < 0.25:
        return 2
    if estimated_cost < 1.0:
        return 3
    return 4


def _quality_rank(model: dict[str, Any]) -> int:
    """Infer a simple quality rank from model naming."""
    combined = f"{model.get('model_id')} {model.get('name')}".lower()
    if any(term in combined for term in ["pro", "sora", "veo-3.1"]):
        return 5
    if any(term in combined for term in ["lite", "fast", "std"]):
        return 2
    return 3


def _known_limitations(model: dict[str, Any]) -> list[str]:
    """Return known limitation notes from model metadata."""
    limitations = ["OpenRouter video generation may spend credits and requires human review."]
    if not model.get("supports_frame_images"):
        limitations.append("This model does not advertise frame-image support.")
    if not model.get("pricing_skus"):
        limitations.append("Pricing metadata is unavailable; cost is unknown.")
    return limitations


def _supports_duration(capability: VideoModelCapability, duration: int) -> bool:
    """Return whether a duration can be sent for this capability."""
    return not capability.supported_durations_seconds or duration in capability.supported_durations_seconds


def _supports_aspect_ratio(capability: VideoModelCapability, aspect_ratio: str) -> bool:
    """Return whether an aspect ratio can be sent for this capability."""
    return not capability.supported_aspect_ratios or aspect_ratio in capability.supported_aspect_ratios


def _supports_resolution(capability: VideoModelCapability, resolution: str) -> bool:
    """Return whether a resolution can be sent for this capability."""
    return not capability.supported_resolutions or resolution in capability.supported_resolutions


def _supports_size(capability: VideoModelCapability, size: str) -> bool:
    """Return whether a size can be sent for this capability."""
    return not capability.supported_sizes or size in capability.supported_sizes


def _negative_prompt_will_be_sent(request: Any, capability: VideoModelCapability) -> bool:
    """Return whether negative prompt will be included in provider passthrough."""
    allowed = set(capability.capability_metadata.get("allowed_passthrough_parameters") or [])
    return bool(request.negative_prompt and "negative_prompt" in allowed)


def _inputs_sent(request: Any, include_reference: bool) -> list[str]:
    """Return safe input labels sent to OpenRouter."""
    inputs = ["prompt"]
    if request.negative_prompt:
        inputs.append("negative prompt if model/provider supports it")
    if include_reference:
        inputs.append("selected extracted frame image as first_frame")
    return inputs


def _image_data_url(path: Path) -> str:
    """Return a base64 data URL for a selected frame image."""
    mime_type = mimetypes.guess_type(path.name)[0] or "image/jpeg"
    encoded = base64.b64encode(path.read_bytes()).decode("ascii")
    return f"data:{mime_type};base64,{encoded}"


def _safe_error_type(error: Exception) -> str:
    """Return a safe error type for OpenRouter video failures."""
    if isinstance(error, TimeoutError):
        return "timeout"
    if isinstance(error, ValueError):
        return "video_job_failed"
    return "request_error"


def _safe_error_message(error: Exception) -> str:
    """Return a safe OpenRouter video error message."""
    if isinstance(error, TimeoutError):
        return "OpenRouter video generation did not complete before the polling timeout."
    if isinstance(error, ValueError):
        return str(error)
    return f"OpenRouter video request failed: {type(error).__name__}."


def _sanitize_outbound_text(value: str) -> str:
    """Redact secrets and local paths before sending text to OpenRouter."""
    import re

    redacted = re.sub(
        r"(?i)(?:OPENROUTER_API_KEY|OPENAI_API_KEY|FAL_KEY|REPLICATE_API_TOKEN|ELEVENLABS_API_KEY)\s*=\s*\S+|(?:sk-or-v1|sk)-[A-Za-z0-9_-]{8,}",
        "[redacted]",
        value,
    )
    redacted = re.sub(r"[A-Za-z]:[\\/][^\s`'\"<>]+", "[local-path-redacted]", redacted)
    redacted = re.sub(r"(?i)(?:content|cache)[\\/][^\s`'\"<>]+", "[local-path-redacted]", redacted)
    return redacted


def _as_string_list(value: object) -> list[str]:
    """Convert a value to a string list."""
    if isinstance(value, list):
        return [str(item) for item in value if item is not None]
    if value is None:
        return []
    return [str(value)]


def _as_int_list(value: object) -> list[int]:
    """Convert a value to an int list."""
    if not isinstance(value, list):
        return []
    result: list[int] = []
    for item in value:
        try:
            result.append(int(item))
        except (TypeError, ValueError):
            continue
    return result


def _safe_float(value: object) -> float | None:
    """Convert a value to float when possible."""
    try:
        return float(value) if value is not None else None
    except (TypeError, ValueError):
        return None
