"""Model advisor for OpenRouter-routed text planning jobs."""

from typing import Any, Literal

from pydantic import BaseModel, Field

from src.models.planning import ClarifyingAnswers
from src.models.project import ContentProject
from src.models.source import FrameRecord, SourceRecord
from src.services.frame_summary import frame_reference_summary
from src.services.openrouter_catalog import (
    estimate_model_cost_from_catalog,
    is_router_helper_model_id,
    select_candidate_models_for_job,
)


TaskType = Literal[
    "hooks_and_captions",
    "script_outline",
    "storyboard",
    "prompt_pack",
    "full_content_pack",
    "risk_review",
    "bulk_variants",
    "final_copy_polish",
]

RecommendationTier = Literal["cheapest_sensible", "balanced_recommended", "quality_first", "manual_override"]


class ModelAdvisorRecommendation(BaseModel):
    """Recommendation for one selected model routed through OpenRouter."""

    selected_model_id: str
    display_name: str
    tier: RecommendationTier
    why_this_model_fits: list[str] = Field(default_factory=list)
    estimated_cost_band: str = "unknown"
    estimated_token_use: dict[str, int] = Field(default_factory=dict)
    known_capability_strengths: list[str] = Field(default_factory=list)
    known_limitations: list[str] = Field(default_factory=list)
    confidence: Literal["low", "medium", "high"] = "low"
    catalogue_freshness_warning: str | None = None
    catalogue_fetched_at: str | None = None


class ModelAdvisorResult(BaseModel):
    """Model advisor result containing each recommendation tier."""

    task_type: TaskType
    cheapest_sensible: ModelAdvisorRecommendation | None = None
    balanced_recommended: ModelAdvisorRecommendation | None = None
    quality_first: ModelAdvisorRecommendation | None = None
    manual_override: ModelAdvisorRecommendation | None = None
    selected: ModelAdvisorRecommendation | None = None
    warnings: list[str] = Field(default_factory=list)


def advise_vision_model(catalog: dict[str, Any] | None) -> ModelAdvisorRecommendation | None:
    """Recommend a concrete vision-capable catalogue model for frame prefill."""
    if catalog is None:
        return None
    candidates = [
        model
        for model in catalog.get("models", [])
        if model.get("model_id")
        and model.get("vision_input_supported")
        and model.get("text_output_supported")
        and not is_router_helper_model_id(model.get("model_id"))
    ]
    if not candidates:
        return None
    ranked = sorted(candidates, key=_vision_model_rank)
    model = ranked[0]
    cost = estimate_model_cost_from_catalog(model, 1200, 600)
    reasons = ["Accepts image input and returns text through a concrete model ID."]
    if model.get("structured_output_supported"):
        reasons.append("Catalogue metadata indicates structured-output support.")
    if cost.get("pricing_available"):
        reasons.append("Its estimated small-frame-analysis cost is comparatively low among suitable candidates.")
    return ModelAdvisorRecommendation(
        selected_model_id=model["model_id"],
        display_name=model.get("name") or model["model_id"],
        tier="balanced_recommended",
        why_this_model_fits=reasons,
        estimated_cost_band=cost.get("cost_band") or "unknown",
        estimated_token_use={"input_tokens": 1200, "output_tokens": 600},
        known_capability_strengths=["vision input", "text output"],
        known_limitations=["Frame interpretation can be inaccurate and requires human review."],
        confidence="medium" if cost.get("pricing_available") else "low",
        catalogue_freshness_warning=_freshness_warning(catalog),
        catalogue_fetched_at=catalog.get("fetched_at"),
    )


def _vision_model_rank(model: dict[str, Any]) -> tuple[int, int, float, str]:
    """Return a stable rank favoring structured output and known low pricing."""
    cost = estimate_model_cost_from_catalog(model, 1200, 600)
    return (
        0 if model.get("structured_output_supported") else 1,
        0 if cost.get("pricing_available") else 1,
        float(cost.get("estimated_cost") or 999.0),
        str(model.get("model_id")),
    )


def advise_models_for_job(
    catalog: dict[str, Any] | None,
    project: ContentProject,
    sources: list[SourceRecord],
    answers: ClarifyingAnswers,
    frame_references: list[FrameRecord],
    task_type: TaskType,
    budget_preference: str,
    quality_preference: str,
    need_strict_json: bool,
    manual_model_id: str | None = None,
) -> ModelAdvisorResult:
    """Recommend candidate models for the current text-planning job."""
    if catalog is None or not catalog.get("models"):
        warnings = ["Model catalogue unavailable. Enter a manual selected model ID or use deterministic generation."]
        manual = _manual_recommendation(manual_model_id, warnings) if manual_model_id else None
        return ModelAdvisorResult(task_type=task_type, manual_override=manual, selected=manual, warnings=warnings)

    expected_input_tokens = estimate_expected_token_use(project, sources, answers, frame_references, task_type)["input_tokens"]
    expected_output_tokens = estimate_expected_token_use(project, sources, answers, frame_references, task_type)["output_tokens"]
    candidates = select_candidate_models_for_job(catalog.get("models", []), expected_input_tokens, need_strict_json)
    freshness_warning = _freshness_warning(catalog)
    warnings = [freshness_warning] if freshness_warning else []
    if not candidates:
        warnings.append("No catalogue models matched the job requirements. Use manual override or deterministic generation.")
    ranked = sorted(
        (
            _score_model(model, task_type, budget_preference, quality_preference, need_strict_json, expected_input_tokens, expected_output_tokens)
            for model in candidates
        ),
        key=lambda item: item["score"],
        reverse=True,
    )
    cheapest = _best_by_cost(candidates, task_type, need_strict_json, expected_input_tokens, expected_output_tokens, catalog)
    balanced = _recommendation_from_scored(ranked[0], "balanced_recommended", catalog, freshness_warning) if ranked else None
    quality = _best_by_quality(candidates, task_type, need_strict_json, expected_input_tokens, expected_output_tokens, catalog, freshness_warning)
    manual = _manual_recommendation(manual_model_id, warnings, catalog) if manual_model_id else None
    selected = manual or _select_by_preferences(cheapest, balanced, quality, budget_preference, quality_preference)
    return ModelAdvisorResult(
        task_type=task_type,
        cheapest_sensible=cheapest,
        balanced_recommended=balanced,
        quality_first=quality,
        manual_override=manual,
        selected=selected,
        warnings=warnings,
    )


def next_recommended_model(
    advisor_result: ModelAdvisorResult | None,
    unsuitable_model_ids: list[str],
    current_model_id: str | None = None,
) -> ModelAdvisorRecommendation | None:
    """Return the next recommended model that has not been marked unsuitable."""
    if advisor_result is None:
        return None
    blocked = set(unsuitable_model_ids)
    if current_model_id:
        blocked.add(current_model_id)
    for recommendation in [
        advisor_result.balanced_recommended,
        advisor_result.cheapest_sensible,
        advisor_result.quality_first,
        advisor_result.manual_override,
    ]:
        if recommendation is None:
            continue
        if recommendation.selected_model_id in blocked:
            continue
        return recommendation
    return None


def estimate_expected_token_use(
    project: ContentProject,
    sources: list[SourceRecord],
    answers: ClarifyingAnswers,
    frame_references: list[FrameRecord],
    task_type: TaskType,
) -> dict[str, int]:
    """Estimate input and output tokens for a local planning request."""
    text_chunks = [
        project.project_name,
        project.working_title,
        project.brand_name or "",
        project.topic or "",
        project.director_instructions,
        answers.main_point or "",
        answers.rights_constraints or "",
        answers.sensitive_materials or "",
        " ".join(frame_reference_summary(frame_references)),
        " ".join(source.original_filename or source.url or source.manual_description or source.source_id for source in sources),
    ]
    approximate_words = len(" ".join(text_chunks).split())
    input_tokens = max(800, int(approximate_words * 1.5) + 900)
    output_tokens = {
        "hooks_and_captions": 700,
        "script_outline": 900,
        "storyboard": 1000,
        "prompt_pack": 1200,
        "full_content_pack": 2200,
        "risk_review": 900,
        "bulk_variants": 1800,
        "final_copy_polish": 1000,
    }.get(task_type, 1400)
    return {"input_tokens": input_tokens, "output_tokens": output_tokens}


def _score_model(
    model: dict[str, Any],
    task_type: TaskType,
    budget_preference: str,
    quality_preference: str,
    need_strict_json: bool,
    input_tokens: int,
    output_tokens: int,
) -> dict[str, Any]:
    """Score a normalized catalogue model for a job."""
    cost = estimate_model_cost_from_catalog(model, input_tokens, output_tokens)
    score = 0.0
    score += 30 if model.get("text_output_supported") else -100
    score += 12 if model.get("structured_output_supported") else (-8 if need_strict_json else 0)
    score += 8 if model.get("tool_use_supported") else 0
    context_length = int(model.get("context_length") or 0)
    if context_length >= input_tokens + output_tokens:
        score += min(20, context_length / 20000)
    else:
        score -= 50
    if cost["pricing_available"]:
        score += _cost_score(cost["estimated_cost"] or 0.0, budget_preference)
    else:
        score -= 7
    if task_type in {"risk_review", "final_copy_polish", "full_content_pack"} or "quality" in quality_preference.lower():
        score += _quality_score(model)
    if task_type == "bulk_variants":
        score += _cost_score(cost["estimated_cost"] or 0.0, "cheapest")
    return {"model": model, "score": score, "cost": cost, "input_tokens": input_tokens, "output_tokens": output_tokens}


def _recommendation_from_scored(
    scored: dict[str, Any],
    tier: RecommendationTier,
    catalog: dict[str, Any],
    freshness_warning: str | None,
) -> ModelAdvisorRecommendation:
    """Build a recommendation object from a scored model."""
    model = scored["model"]
    cost = scored["cost"]
    limitations = _limitations(model, cost)
    confidence = _confidence(model, cost, freshness_warning)
    return ModelAdvisorRecommendation(
        selected_model_id=model["model_id"],
        display_name=model.get("name") or model["model_id"],
        tier=tier,
        why_this_model_fits=_fit_reasons(model, tier),
        estimated_cost_band=cost["cost_band"],
        estimated_token_use={"input_tokens": scored["input_tokens"], "output_tokens": scored["output_tokens"]},
        known_capability_strengths=_strengths(model),
        known_limitations=limitations,
        confidence=confidence,
        catalogue_freshness_warning=freshness_warning,
        catalogue_fetched_at=catalog.get("fetched_at"),
    )


def _best_by_cost(
    candidates: list[dict[str, Any]],
    task_type: TaskType,
    need_strict_json: bool,
    input_tokens: int,
    output_tokens: int,
    catalog: dict[str, Any],
) -> ModelAdvisorRecommendation | None:
    """Return the cheapest sensible candidate."""
    scored = [
        _score_model(model, task_type, "cheapest", "good enough draft", need_strict_json, input_tokens, output_tokens)
        for model in candidates
    ]
    priced = [item for item in scored if item["cost"]["pricing_available"]]
    pool = priced or scored
    if not pool:
        return None
    best = sorted(pool, key=lambda item: (item["cost"]["estimated_cost"] is None, item["cost"]["estimated_cost"] or 999, -item["score"]))[0]
    return _recommendation_from_scored(best, "cheapest_sensible", catalog, _freshness_warning(catalog))


def _best_by_quality(
    candidates: list[dict[str, Any]],
    task_type: TaskType,
    need_strict_json: bool,
    input_tokens: int,
    output_tokens: int,
    catalog: dict[str, Any],
    freshness_warning: str | None,
) -> ModelAdvisorRecommendation | None:
    """Return the strongest quality-first candidate."""
    scored = [
        _score_model(model, task_type, "balanced", "quality first", need_strict_json, input_tokens, output_tokens)
        for model in candidates
    ]
    if not scored:
        return None
    best = sorted(scored, key=lambda item: item["score"] + _quality_score(item["model"]), reverse=True)[0]
    return _recommendation_from_scored(best, "quality_first", catalog, freshness_warning)


def _manual_recommendation(
    manual_model_id: str | None,
    warnings: list[str],
    catalog: dict[str, Any] | None = None,
) -> ModelAdvisorRecommendation | None:
    """Return a manual override recommendation."""
    if not manual_model_id:
        return None
    model = _find_model(catalog, manual_model_id) if catalog else None
    limitations = ["Manual override: verify model capability and cost before use."]
    if model is None:
        limitations.append("Manual model ID was not found in the current catalogue.")
    return ModelAdvisorRecommendation(
        selected_model_id=manual_model_id.strip(),
        display_name=(model.get("name") if model else manual_model_id.strip()),
        tier="manual_override",
        why_this_model_fits=["Chosen manually by the user."],
        estimated_cost_band="unknown",
        estimated_token_use={"input_tokens": 0, "output_tokens": 0},
        known_capability_strengths=_strengths(model) if model else [],
        known_limitations=limitations,
        confidence="medium" if model else "low",
        catalogue_freshness_warning=warnings[0] if warnings else None,
        catalogue_fetched_at=catalog.get("fetched_at") if catalog else None,
    )


def _select_by_preferences(
    cheapest: ModelAdvisorRecommendation | None,
    balanced: ModelAdvisorRecommendation | None,
    quality: ModelAdvisorRecommendation | None,
    budget_preference: str,
    quality_preference: str,
) -> ModelAdvisorRecommendation | None:
    """Select a default recommendation from preference labels."""
    if "cheapest" in budget_preference.lower() and cheapest:
        return cheapest
    if "quality" in quality_preference.lower() and quality:
        return quality
    return balanced or cheapest or quality


def _find_model(catalog: dict[str, Any] | None, model_id: str) -> dict[str, Any] | None:
    """Find a normalized model in a catalogue."""
    if catalog is None:
        return None
    return next((model for model in catalog.get("models", []) if model.get("model_id") == model_id), None)


def _fit_reasons(model: dict[str, Any], tier: RecommendationTier) -> list[str]:
    """Return human-readable reasons for a recommendation."""
    reasons = [f"Text output is supported by selected model `{model.get('model_id')}`."]
    if tier == "cheapest_sensible":
        reasons.append("Chosen from viable candidates with the lowest catalogue-estimated request cost.")
    if tier == "balanced_recommended":
        reasons.append("Balances context window, capability metadata, and current catalogue pricing.")
    if tier == "quality_first":
        reasons.append("Prioritises stronger capability signals over lowest cost.")
    if model.get("structured_output_supported"):
        reasons.append("Catalogue metadata suggests structured or JSON-style output support.")
    return reasons


def _strengths(model: dict[str, Any] | None) -> list[str]:
    """Return known capability strengths from model metadata."""
    if model is None:
        return []
    strengths = []
    if model.get("context_length"):
        strengths.append(f"Context window: {model['context_length']} tokens.")
    if model.get("structured_output_supported"):
        strengths.append("Structured output appears supported.")
    if model.get("tool_use_supported"):
        strengths.append("Tool/function use appears supported.")
    if model.get("vision_input_supported"):
        strengths.append("Vision input appears supported, though this app sends text only.")
    return strengths


def _limitations(model: dict[str, Any], cost: dict[str, Any]) -> list[str]:
    """Return known limitations from model metadata."""
    limitations = []
    if not cost["pricing_available"]:
        limitations.append("Pricing metadata is missing; cost estimate is unknown.")
    if not model.get("structured_output_supported"):
        limitations.append("JSON support is unknown; strict JSON may still fail.")
    if not model.get("context_length"):
        limitations.append("Context window metadata is missing.")
    return limitations


def _confidence(model: dict[str, Any], cost: dict[str, Any], freshness_warning: str | None) -> Literal["low", "medium", "high"]:
    """Return confidence based on metadata completeness and catalogue freshness."""
    if freshness_warning:
        return "low"
    if cost["pricing_available"] and model.get("context_length") and model.get("structured_output_supported"):
        return "high"
    if model.get("context_length"):
        return "medium"
    return "low"


def _cost_score(estimated_cost: float, budget_preference: str) -> float:
    """Score a model by estimated cost."""
    if "cheapest" in budget_preference.lower():
        return max(0.0, 20.0 - estimated_cost * 1000)
    return max(0.0, 12.0 - estimated_cost * 300)


def _quality_score(model: dict[str, Any]) -> float:
    """Score quality from conservative metadata signals."""
    score = 0.0
    context_length = int(model.get("context_length") or 0)
    if context_length >= 100000:
        score += 8
    if model.get("structured_output_supported"):
        score += 4
    description = str(model.get("description") or "").lower()
    if any(term in description for term in ["reasoning", "frontier", "advanced", "flagship", "best"]):
        score += 6
    return score


def _freshness_warning(catalog: dict[str, Any]) -> str | None:
    """Return a catalogue freshness warning if present in cache metadata."""
    status = str(catalog.get("freshness") or "")
    if status in {"stale", "very stale"}:
        return "Catalogue freshness is stale; pricing and model recommendations may be unreliable."
    if catalog.get("fetch_status") != "ok":
        return "Last catalogue refresh failed; recommendations may be incomplete."
    return None
