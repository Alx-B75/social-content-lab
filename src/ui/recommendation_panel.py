"""Recommendation panel for Social Content Lab."""

import html

import streamlit as st

from src.models.planning import ClarifyingAnswers, WorkflowRecommendation
from src.models.project import ContentProject
from src.models.source import SourceRecord
from src.services.model_router import ModelRouter
from src.services.planning_defaults import is_video_format, label_for_provider, label_for_route, normalize_clarifying_answers, resolve_aspect_ratio, resolve_duration_seconds


def render_recommendation_panel(
    model_router: ModelRouter,
    project: ContentProject,
    sources: list[SourceRecord],
    answers: ClarifyingAnswers,
) -> WorkflowRecommendation | None:
    """Render workflow recommendation controls and output."""
    st.header("4. Model/workflow recommendation")
    answers = normalize_clarifying_answers(answers, project)
    st.session_state.answers = answers
    answers_ready = clarifying_answers_ready(answers, st.session_state.get("answers_saved"))
    if answers_ready:
        st.success("Clarifying answers loaded.")
    else:
        st.warning("Save clarifying answers before generating a recommendation.")
    if st.button("Generate recommendation"):
        if not answers_ready:
            st.warning("Recommendation skipped because clarifying answers have not been saved yet.")
            return st.session_state.get("recommendation")
        recommendation = model_router.recommend(project, sources, answers)
        st.session_state.recommendation = recommendation
    else:
        recommendation = st.session_state.get("recommendation")

    if recommendation is None:
        if answers_ready:
            st.info("Clarifying answers loaded. Generate a recommendation to continue.")
        else:
            st.info("Save clarifying answers, then generate a recommendation.")
        return None

    resolved_duration = resolve_duration_seconds(project, answers)
    resolved_aspect_ratio = resolve_aspect_ratio(answers)
    st.subheader("Recommendation summary")
    summary_items = [
        ("Route", label_for_route(recommendation.recommended_workflow_route)),
        ("Provider", label_for_provider(recommendation.suggested_provider_type)),
        ("Cost band", recommendation.estimated_cost_band.value),
        ("Model category", recommendation.recommended_model_category),
        ("Resolved platform", answers.platform or "Not resolved yet"),
        ("Resolved aspect ratio", resolved_aspect_ratio or "Not resolved yet"),
        ("Resolved duration", f"{resolved_duration} seconds" if resolved_duration else "Not applicable"),
    ]
    _render_summary_grid(summary_items)
    display_warnings = list(recommendation.warnings)
    if is_video_format(recommendation.recommended_workflow_route) and (not resolved_duration or not resolved_aspect_ratio):
        display_warnings.append("Video generation is recommended, but duration or aspect ratio is not fully resolved.")
    if answers.source_use == "copy closely" and not answers.rights_constraints:
        display_warnings.append("Source use is set to copy closely, but licensing status is unclear.")

    st.subheader("Rationale")
    for item in recommendation.rationale:
        st.write(f"- {item}")

    _render_warning_cards(display_warnings)

    st.subheader("Suggested next step")
    st.write(recommendation.suggested_next_step)
    return recommendation


def clarifying_answers_ready(answers: ClarifyingAnswers | None, answers_saved: object) -> bool:
    """Return whether clarifying answers can be used for recommendation."""
    return bool(answers_saved and answers is not None)


def _render_summary_grid(items: list[tuple[str, str]]) -> None:
    """Render recommendation values in wrapping cards."""
    columns = st.columns(2)
    for index, item in enumerate(items):
        label, value = item
        columns[index % 2].markdown(_summary_card(label, value), unsafe_allow_html=True)


def _summary_card(label: str, value: str) -> str:
    """Build a small HTML recommendation card."""
    return (
        "<div class='scl-card'>"
        f"<span class='scl-card-label'>{html.escape(label)}</span>"
        f"<span class='scl-card-value'>{html.escape(value)}</span>"
        "</div>"
    )


def _render_warning_cards(warnings: list[str]) -> None:
    """Render warnings as compact readable cards."""
    if not warnings:
        return
    st.subheader("Warnings")
    for warning in warnings:
        st.markdown(f"<div class='scl-card'><span class='scl-card-value'>{html.escape(warning)}</span></div>", unsafe_allow_html=True)
