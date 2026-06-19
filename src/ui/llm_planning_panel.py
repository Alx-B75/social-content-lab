"""Optional LLM-assisted text planning panel."""

import json
from typing import Any

import streamlit as st

from src.config import AppConfig
from src.models.planning import ClarifyingAnswers, WorkflowRecommendation
from src.models.project import ContentProject
from src.models.source import SourceRecord
from src.services.frame_summary import load_frame_references
from src.services.llm_planner import build_llm_planning_context, generate_llm_content_pack, save_llm_content_pack
from src.services.model_advisor import ModelAdvisorRecommendation, advise_models_for_job, next_recommended_model
from src.services.openrouter_catalog import (
    fetch_openrouter_models,
    get_model_catalog_status,
    save_model_catalog_cache,
)
from src.services.openrouter_client import is_openrouter_configured
from src.services.project_service import ProjectService


TASK_OPTIONS = [
    "hooks_and_captions",
    "script_outline",
    "storyboard",
    "prompt_pack",
    "full_content_pack",
    "risk_review",
    "bulk_variants",
    "final_copy_polish",
]


def render_llm_planning_panel(
    config: AppConfig,
    project_service: ProjectService,
    project: ContentProject,
    sources: list[SourceRecord],
    answers: ClarifyingAnswers,
    recommendation: WorkflowRecommendation | None,
) -> None:
    """Render optional LLM-assisted text planning controls."""
    st.header("Optional LLM-assisted text planning")
    st.caption("Router/provider: OpenRouter. The selected underlying model performs the writing/planning.")
    status = _render_catalogue_section(config)
    advisor_recommendation = _render_advisor_section(config, project, sources, answers, recommendation, status)
    _render_generation_section(config, project_service, project, sources, answers, recommendation, status, advisor_recommendation)


def _render_catalogue_section(config: AppConfig) -> dict[str, Any]:
    """Render catalogue status and refresh controls."""
    st.subheader("Model catalogue")
    status = get_model_catalog_status(config.openrouter_catalog_cache_path)
    columns = st.columns(4)
    columns[0].markdown("**Router/provider**  \nOpenRouter")
    columns[1].markdown(f"**Status**  \n{status['availability']}")
    columns[2].markdown(f"**Freshness**  \n{status['freshness']}")
    columns[3].markdown(f"**Models**  \n{status['model_count']}")
    st.write(f"Last refreshed: {status['last_refreshed'] or 'Never'}")
    if status["warning"]:
        st.warning(status["warning"])
    if st.button("Refresh OpenRouter model catalogue"):
        with st.spinner("Refreshing model catalogue from OpenRouter..."):
            catalog = fetch_openrouter_models(config)
            save_model_catalog_cache(config.openrouter_catalog_cache_path, catalog)
        if catalog.get("fetch_status") == "ok":
            st.success(f"Catalogue refreshed: {catalog.get('model_count', 0)} models cached locally.")
        else:
            st.warning(f"Catalogue refresh failed: {catalog.get('error_summary', 'unknown error')}.")
        status = get_model_catalog_status(config.openrouter_catalog_cache_path)
    return status


def _render_advisor_section(
    config: AppConfig,
    project: ContentProject,
    sources: list[SourceRecord],
    answers: ClarifyingAnswers,
    recommendation: WorkflowRecommendation | None,
    status: dict[str, Any],
) -> ModelAdvisorRecommendation | None:
    """Render model advisor controls and recommendation cards."""
    st.subheader("Model advisor")
    catalog = status.get("catalog")
    frame_references = load_frame_references(sources)
    with st.form("model_advisor_form"):
        columns = st.columns(2)
        task_type = columns[0].selectbox("Task type", TASK_OPTIONS, index=TASK_OPTIONS.index("full_content_pack"))
        budget_preference = columns[1].selectbox("Budget preference", ["cheapest", "balanced", "quality acceptable", "unknown"], index=1)
        quality_preference = columns[0].selectbox("Quality preference", ["good enough draft", "polished draft", "client-ready", "quality first"], index=1)
        need_strict_json = columns[1].checkbox("Need strict JSON", value=True)
        manual_model_id = st.text_input("Manual selected model ID", value=config.openrouter_default_model or "", placeholder="Example: anthropic/claude-3.5-sonnet")
        submitted = st.form_submit_button("Recommend model for this job")
    if submitted:
        advisor_result = advise_models_for_job(
            catalog,
            project,
            sources,
            answers,
            frame_references,
            task_type,
            budget_preference,
            quality_preference,
            need_strict_json,
            manual_model_id.strip() or None,
        )
        st.session_state["openrouter_advisor_result"] = advisor_result
    advisor_result = st.session_state.get("openrouter_advisor_result")
    if advisor_result is None:
        st.info("Refresh or load a catalogue, then ask the model advisor for a recommendation. Manual selected model IDs are also supported.")
        return None
    if advisor_result.warnings:
        for warning in advisor_result.warnings:
            st.warning(warning)
    _render_recommendation_card("Cheapest sensible", advisor_result.cheapest_sensible)
    _render_recommendation_card("Balanced recommended", advisor_result.balanced_recommended)
    _render_recommendation_card("Quality first", advisor_result.quality_first)
    _render_recommendation_card("Manual override", advisor_result.manual_override)
    if advisor_result.selected:
        st.success(f"Selected model routed through OpenRouter: {advisor_result.selected.selected_model_id}")
    return advisor_result.selected


def _render_generation_section(
    config: AppConfig,
    project_service: ProjectService,
    project: ContentProject,
    sources: list[SourceRecord],
    answers: ClarifyingAnswers,
    recommendation: WorkflowRecommendation | None,
    status: dict[str, Any],
    advisor_recommendation: ModelAdvisorRecommendation | None,
) -> None:
    """Render optional LLM-assisted generation controls."""
    st.subheader("Generate LLM-assisted draft")
    configured = is_openrouter_configured(config)
    st.write(f"OpenRouter API key configured: {'Yes' if configured else 'No'}")
    if not configured:
        st.info("Add OPENROUTER_API_KEY to `.env` to enable live LLM-assisted drafts. Deterministic generation remains available.")
    alternate_recommendation = st.session_state.get("openrouter_alternate_recommendation")
    selected_default = (
        alternate_recommendation.selected_model_id
        if alternate_recommendation
        else advisor_recommendation.selected_model_id
        if advisor_recommendation
        else (config.openrouter_default_model or "")
    )
    selected_model = st.text_input("Selected model", value=selected_default, placeholder="Choose from advisor or enter a model ID")
    columns = st.columns(2)
    temperature = columns[0].slider("Temperature", min_value=0.0, max_value=1.5, value=0.5, step=0.05)
    max_tokens = columns[1].number_input("Max tokens", min_value=500, max_value=8000, value=2200, step=100)
    st.warning("LLM-assisted text may incur cost. Review all output before publication.")
    if st.button("Generate LLM-assisted content pack", disabled=not selected_model.strip()):
        context = build_llm_planning_context(project, sources, answers, recommendation, load_frame_references(sources), advisor_recommendation)
        with st.spinner("Generating LLM-assisted draft via OpenRouter..."):
            result = generate_llm_content_pack(config, selected_model.strip(), context, temperature, int(max_tokens))
        st.session_state["openrouter_llm_result"] = result
        st.session_state.pop("openrouter_alternate_recommendation", None)
    result = st.session_state.get("openrouter_llm_result")
    if not result:
        return
    _render_llm_result(result)
    _render_empty_response_recovery(result)
    save_columns = st.columns(2)
    if save_columns[0].button("Save LLM version to project", disabled=not result.get("text") or result.get("error_type") == "empty_model_response"):
        metadata = save_llm_content_pack(project_service, project, result, advisor_recommendation, status.get("last_refreshed"))
        st.success(f"Saved LLM-assisted files. Output hash: {metadata['output_hash']}")
    if save_columns[1].button("Keep deterministic version"):
        st.session_state.pop("openrouter_llm_result", None)
        st.info("Kept the deterministic content pack as the active version.")


def _render_recommendation_card(label: str, recommendation: ModelAdvisorRecommendation | None) -> None:
    """Render one model advisor recommendation card."""
    if recommendation is None:
        return
    with st.expander(label, expanded=label == "Balanced recommended"):
        st.markdown(f"**Selected model:** `{recommendation.selected_model_id}`")
        st.write(f"Estimated cost band: {recommendation.estimated_cost_band}")
        st.write(f"Confidence: {recommendation.confidence}")
        st.write(f"Estimated token use: {recommendation.estimated_token_use}")
        if recommendation.catalogue_freshness_warning:
            st.warning(recommendation.catalogue_freshness_warning)
        _write_list("Why this model fits", recommendation.why_this_model_fits)
        _write_list("Known capability strengths", recommendation.known_capability_strengths)
        _write_list("Known limitations", recommendation.known_limitations)


def _render_llm_result(result: dict[str, Any]) -> None:
    """Render generated LLM result and raw output."""
    if result.get("error"):
        st.warning(result["error"])
    st.write(f"Model used: `{result.get('selected_model')}`")
    st.write(f"Usage metadata: `{json.dumps(result.get('usage') or {})}`")
    if result.get("parsed_successfully"):
        st.success("Structured JSON parsed successfully.")
        parsed = result.get("parsed") or {}
        with st.expander("Structured LLM preview", expanded=True):
            st.markdown(f"**Core message:** {parsed.get('core_message') or ''}")
            _write_list("Hooks", parsed.get("hook_options", []))
            _write_list("Script outline", parsed.get("script_outline", []))
            _write_list("Shot list", parsed.get("shot_list", []))
            st.text_area("Image prompt", parsed.get("image_prompt") or "", height=120)
            _write_list("Video prompts", parsed.get("video_prompts", []))
            _write_list("Caption drafts", parsed.get("caption_drafts", []))
            _write_list("Risk notes", parsed.get("risk_notes", []))
            _write_list("Next actions", parsed.get("next_actions", []))
    else:
        st.warning(result.get("parse_error") or "JSON parsing did not succeed. Deterministic files were not overwritten.")
    with st.expander("Raw selected model output", expanded=False):
        st.text_area("Raw output", result.get("text") or "", height=240)


def _render_empty_response_recovery(result: dict[str, Any]) -> None:
    """Render explicit recovery controls for empty selected-model responses."""
    if result.get("error_type") != "empty_model_response":
        return
    failed_model = str(result.get("selected_model") or "")
    advisor_result = st.session_state.get("openrouter_advisor_result")
    unsuitable_models = st.session_state.setdefault("openrouter_unsuitable_models", [])
    st.warning(f"Failed selected model: `{failed_model}`")
    if failed_model and failed_model not in unsuitable_models:
        if st.button("Mark this model unsuitable for this session/job"):
            unsuitable_models.append(failed_model)
            st.session_state["openrouter_unsuitable_models"] = unsuitable_models
            st.success("Marked model as unsuitable for this session/job.")
            st.rerun()
    alternate = next_recommended_model(advisor_result, unsuitable_models, failed_model)
    if alternate is None:
        st.info("No alternate recommended model is available. Run the model advisor again or enter a manual selected model ID.")
        return
    st.write(f"Next recommended model: `{alternate.selected_model_id}`")
    st.warning("Trying another selected model may incur additional cost. Click only if you want to make another live call.")
    if st.button("Try alternate recommended model"):
        st.session_state["openrouter_alternate_recommendation"] = alternate
        st.info("Alternate selected model loaded. Review settings, then click Generate LLM-assisted content pack.")


def _write_list(label: str, items: object) -> None:
    """Render a compact list."""
    st.markdown(f"**{label}**")
    if not items:
        st.write("No items.")
        return
    values = items if isinstance(items, list) else [items]
    for item in values:
        st.write(f"- {item}")
