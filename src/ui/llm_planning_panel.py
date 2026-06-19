"""Optional LLM-assisted text planning panel."""

from typing import Any

import streamlit as st

from src.config import AppConfig
from src.models.planning import ClarifyingAnswers, WorkflowRecommendation
from src.models.project import ContentProject
from src.models.source import SourceRecord
from src.services.frame_summary import load_frame_references
from src.services.llm_planner import (
    build_llm_planning_context,
    can_save_structured_llm_result,
    generate_llm_content_pack,
    generate_tiny_llm_test,
    llm_result_status,
    repair_llm_content_pack_response,
    requires_high_token_warning,
    save_failed_llm_output,
    save_llm_content_pack,
)
from src.services.model_advisor import ModelAdvisorRecommendation, advise_models_for_job, next_recommended_model
from src.services.openrouter_catalog import (
    estimate_model_cost_from_catalog,
    fetch_openrouter_models,
    get_model_catalog_status,
    is_router_helper_model_id,
    save_model_catalog_cache,
    validate_writing_model_id,
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
    manual_model_valid, manual_model_warning = validate_writing_model_id(manual_model_id)
    manual_is_router_helper = bool(manual_model_id.strip()) and not manual_model_valid
    if manual_model_warning and manual_model_id.strip():
        st.warning(manual_model_warning)
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
            None if manual_is_router_helper else manual_model_id.strip() or None,
        )
        st.session_state["openrouter_advisor_result"] = advisor_result
        if advisor_result.selected and not is_router_helper_model_id(advisor_result.selected.selected_model_id):
            st.session_state["openrouter_pending_model_id"] = advisor_result.selected.selected_model_id
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
    if is_router_helper_model_id(selected_default):
        selected_default = ""
    selected_model_key = "openrouter_selected_model_input"
    pending_model = st.session_state.pop("openrouter_pending_model_id", None)
    if pending_model:
        st.session_state[selected_model_key] = pending_model
    elif selected_model_key not in st.session_state:
        st.session_state[selected_model_key] = selected_default
    selected_model = st.text_input("Selected model", placeholder="Choose from advisor or enter a model ID", key=selected_model_key)
    selected_model_valid, selected_model_warning = validate_writing_model_id(selected_model)
    if selected_model_warning:
        if selected_model.strip():
            st.warning(selected_model_warning)
        else:
            st.info(selected_model_warning)
    generation_mode = st.radio("Generation mode", ["Tiny test", "Full content pack"], horizontal=True)
    columns = st.columns(2)
    temperature = columns[0].slider("Temperature", min_value=0.0, max_value=1.5, value=0.5, step=0.05)
    if generation_mode == "Tiny test":
        max_tokens = 400
        columns[1].write("Max tokens: 400")
    else:
        max_tokens = int(columns[1].number_input("Max tokens", min_value=300, max_value=8000, value=1000, step=100))
    if requires_high_token_warning(max_tokens):
        st.warning("Max tokens above 1000 may materially increase cost. Increase deliberately and review the estimate before continuing.")
    _render_cost_estimate(status.get("catalog"), selected_model.strip(), max_tokens, generation_mode)
    cost_acknowledged = st.checkbox("I understand this call may incur cost")
    st.warning("LLM-assisted text may incur cost. Review all output before publication.")
    generate_label = "Run tiny test generation" if generation_mode == "Tiny test" else "Generate LLM-assisted content pack"
    generation_disabled = not selected_model_valid or not cost_acknowledged or not configured
    if st.button(generate_label, disabled=generation_disabled):
        context = build_llm_planning_context(project, sources, answers, recommendation, load_frame_references(sources), advisor_recommendation)
        with st.spinner("Generating LLM-assisted draft via OpenRouter..."):
            if generation_mode == "Tiny test":
                result = generate_tiny_llm_test(config, selected_model.strip(), context, temperature, max_tokens)
                result["generation_mode"] = "tiny_test"
            else:
                result = generate_llm_content_pack(config, selected_model.strip(), context, temperature, max_tokens)
                result["generation_mode"] = "full_content_pack"
        st.session_state["openrouter_llm_result"] = result
        st.session_state.pop("openrouter_alternate_recommendation", None)
    result = st.session_state.get("openrouter_llm_result")
    if not result:
        return
    _render_llm_result(result)
    _render_empty_response_recovery(result)
    _render_result_actions(project_service, project, result, advisor_recommendation, status.get("last_refreshed"))


def _render_result_actions(
    project_service: ProjectService,
    project: ContentProject,
    result: dict[str, Any],
    advisor_recommendation: ModelAdvisorRecommendation | None,
    catalogue_fetched_at: str | None,
) -> None:
    """Render save, repair, and deterministic fallback actions for a result."""
    if result.get("generation_mode") == "tiny_test" and can_save_structured_llm_result(result):
        st.info("Tiny test succeeded. Run Full content pack mode to create savable `.llm.md` files.")
    elif can_save_structured_llm_result(result):
        save_columns = st.columns(2)
        if save_columns[0].button("Save LLM version to project"):
            metadata = save_llm_content_pack(project_service, project, result, advisor_recommendation, catalogue_fetched_at)
            st.success(f"Saved LLM-assisted files. Output hash: {metadata['output_hash']}")
    elif result.get("error_type") == "json_parse_failed" and result.get("text"):
        action_columns = st.columns(2)
        if action_columns[0].button("Try local JSON extraction/repair"):
            repaired = repair_llm_content_pack_response(result["text"])
            if repaired["parsed_successfully"]:
                updated = dict(result)
                updated.update({"ok": True, "error": None, "error_type": None, "parsed_successfully": True, "parsed": repaired["content"], "parse_error": None})
                st.session_state["openrouter_llm_result"] = updated
                st.success("Local JSON extraction succeeded. No additional model call was made.")
                st.rerun()
            else:
                st.warning(repaired["error"])
        if action_columns[1].button("Save raw failed output for inspection"):
            path = save_failed_llm_output(project, result)
            st.success(f"Saved failed raw output locally as {path.name}.")
    elif result.get("text"):
        if st.button("Save raw failed output for inspection"):
            path = save_failed_llm_output(project, result)
            st.success(f"Saved failed raw output locally as {path.name}.")
    if st.button("Keep deterministic version"):
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
    usage = result.get("usage") or {}
    st.write(f"Status: **{llm_result_status(result)}**")
    st.write(f"Parsed successfully: **{'Yes' if result.get('parsed_successfully') else 'No'}**")
    st.write(f"Model used: `{result.get('selected_model')}`")
    token_parts = []
    if usage.get("prompt_tokens") is not None:
        token_parts.append(f"input {usage['prompt_tokens']}")
    if usage.get("completion_tokens") is not None:
        token_parts.append(f"output {usage['completion_tokens']}")
    if usage.get("total_tokens") is not None:
        token_parts.append(f"total {usage['total_tokens']}")
    if token_parts:
        st.write("Tokens: " + ", ".join(token_parts))
    if usage.get("cost") is not None:
        st.write(f"Reported cost: ${float(usage['cost']):.6f}")
    with st.expander("Detailed usage metadata", expanded=False):
        st.json(usage)
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


def _render_cost_estimate(catalog: dict[str, Any] | None, model_id: str, max_tokens: int, generation_mode: str) -> None:
    """Render a rough catalogue-based estimate before a live call."""
    if not catalog or not model_id:
        st.write("Rough cost estimate: unavailable")
        return
    model = next((item for item in catalog.get("models", []) if item.get("model_id") == model_id), None)
    if model is None:
        st.write("Rough cost estimate: unavailable for this selected model")
        return
    expected_input_tokens = 400 if generation_mode == "Tiny test" else 1400
    estimate = estimate_model_cost_from_catalog(model, expected_input_tokens, max_tokens)
    if not estimate["pricing_available"]:
        st.write("Rough cost estimate: unknown (catalogue pricing incomplete)")
        return
    st.write(f"Rough maximum estimate: ${estimate['estimated_cost']:.6f} ({estimate['cost_band']})")


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
        st.session_state["openrouter_pending_model_id"] = alternate.selected_model_id
        st.rerun()


def _write_list(label: str, items: object) -> None:
    """Render a compact list."""
    st.markdown(f"**{label}**")
    if not items:
        st.write("No items.")
        return
    values = items if isinstance(items, list) else [items]
    for item in values:
        st.write(f"- {item}")
