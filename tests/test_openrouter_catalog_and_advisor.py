"""Tests for OpenRouter catalogue normalization and model advisor logic."""

from datetime import datetime, timedelta, timezone

from src.models.planning import ClarifyingAnswers
from src.services.model_advisor import advise_models_for_job, next_recommended_model
from src.services.openrouter_catalog import (
    estimate_model_cost_from_catalog,
    filter_text_planning_models,
    get_model_catalog_status,
    normalize_openrouter_model,
    save_model_catalog_cache,
)


def test_catalog_normalizes_filters_and_estimates_cost() -> None:
    """Normalize catalogue records, exclude router helpers, and estimate price."""
    router = {
        "id": "openrouter/auto",
        "name": "Auto Router",
        "architecture": {"modality": "text->text", "input_modalities": ["text"], "output_modalities": ["text"]},
        "supported_parameters": ["response_format"],
        "pricing": {"prompt": "0", "completion": "0"},
    }
    model = {
        "id": "sample/quality",
        "name": "Sample Quality",
        "description": "advanced JSON text model with tool support",
        "context_length": 128000,
        "architecture": {"modality": "text->text", "input_modalities": ["text"], "output_modalities": ["text"]},
        "supported_parameters": ["response_format", "tools"],
        "pricing": {"prompt": "0.000001", "completion": "0.000002"},
    }

    normalized_router = normalize_openrouter_model(router)
    normalized_model = normalize_openrouter_model(model)
    filtered = filter_text_planning_models([normalized_router, normalized_model])
    estimate = estimate_model_cost_from_catalog(normalized_model, input_tokens=1000, output_tokens=500)

    assert [item["model_id"] for item in filtered] == ["sample/quality"]
    assert normalized_model["structured_output_supported"] is True
    assert normalized_model["tool_use_supported"] is True
    assert estimate["pricing_available"] is True
    assert estimate["cost_band"] == "low"


def test_catalog_status_reports_fresh_and_very_stale(app_config) -> None:
    """Report catalogue freshness from cached timestamps."""
    fresh_catalog = {
        "fetched_at": datetime.now(timezone.utc).isoformat(),
        "source": "openrouter",
        "model_count": 1,
        "fetch_status": "ok",
        "models": [{"model_id": "sample/model"}],
    }
    save_model_catalog_cache(app_config.openrouter_catalog_cache_path, fresh_catalog)
    fresh_status = get_model_catalog_status(app_config.openrouter_catalog_cache_path)

    stale_catalog = dict(fresh_catalog)
    stale_catalog["fetched_at"] = (datetime.now(timezone.utc) - timedelta(days=8)).isoformat()
    save_model_catalog_cache(app_config.openrouter_catalog_cache_path, stale_catalog)
    stale_status = get_model_catalog_status(app_config.openrouter_catalog_cache_path)

    assert fresh_status["freshness"] == "fresh"
    assert stale_status["freshness"] == "very stale"
    assert "very stale" in stale_status["warning"]


def test_model_advisor_recommends_concrete_models_and_alternates(content_project) -> None:
    """Recommend non-router models and return an alternate after one is blocked."""
    catalog = {
        "fetched_at": datetime.now(timezone.utc).isoformat(),
        "fetch_status": "ok",
        "models": [
            {
                "model_id": "openrouter/auto",
                "name": "Auto Router",
                "provider": "openrouter",
                "context_length": 2000000,
                "pricing_prompt": 0.0,
                "pricing_completion": 0.0,
                "text_output_supported": True,
                "structured_output_supported": True,
            },
            {
                "model_id": "sample/cheap",
                "name": "Sample Cheap",
                "provider": "sample",
                "context_length": 64000,
                "pricing_prompt": 0.0000001,
                "pricing_completion": 0.0000002,
                "text_output_supported": True,
                "structured_output_supported": True,
            },
            {
                "model_id": "sample/quality",
                "name": "Sample Quality",
                "provider": "sample",
                "description": "advanced reasoning flagship",
                "context_length": 128000,
                "pricing_prompt": 0.000001,
                "pricing_completion": 0.000002,
                "text_output_supported": True,
                "structured_output_supported": True,
                "tool_use_supported": True,
            },
        ],
    }

    result = advise_models_for_job(
        catalog,
        content_project,
        [],
        ClarifyingAnswers(platform="LinkedIn", output_format="short video", target_length_seconds=10),
        [],
        "full_content_pack",
        "balanced",
        "polished draft",
        True,
    )
    alternate = next_recommended_model(result, [result.selected.selected_model_id], result.selected.selected_model_id)

    assert result.selected is not None
    assert not result.selected.selected_model_id.startswith("openrouter/")
    assert alternate is not None
    assert alternate.selected_model_id != result.selected.selected_model_id
