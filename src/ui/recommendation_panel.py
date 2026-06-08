"""Recommendation panel for Social Content Lab."""

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
    if not st.session_state.get("answers_saved"):
        st.warning("Save clarifying answers before generating a recommendation.")
    if st.button("Generate recommendation"):
        if not st.session_state.get("answers_saved"):
            st.warning("Recommendation skipped because clarifying answers have not been saved yet.")
            return st.session_state.get("recommendation")
        recommendation = model_router.recommend(project, sources, answers)
        st.session_state.recommendation = recommendation
    else:
        recommendation = st.session_state.get("recommendation")

    if recommendation is None:
        st.info("Save clarifying answers, then generate a recommendation.")
        return None

    columns = st.columns(4)
    columns[0].metric("Route", label_for_route(recommendation.recommended_workflow_route))
    columns[1].metric("Provider", label_for_provider(recommendation.suggested_provider_type))
    columns[2].metric("Cost band", recommendation.estimated_cost_band.value)
    columns[3].metric("Model category", recommendation.recommended_model_category)
    resolved_duration = resolve_duration_seconds(project, answers)
    resolved_aspect_ratio = resolve_aspect_ratio(answers)
    if is_video_format(recommendation.recommended_workflow_route) and (not resolved_duration or not resolved_aspect_ratio):
        st.warning("Video generation is recommended, but duration or aspect ratio is not fully resolved.")
    if answers.source_use == "copy closely" and not answers.rights_constraints:
        st.warning("Source use is set to copy closely, but licensing status is unclear.")

    st.subheader("Rationale")
    for item in recommendation.rationale:
        st.write(f"- {item}")

    st.subheader("Warnings")
    for warning in recommendation.warnings:
        st.warning(warning)

    st.subheader("Suggested next step")
    st.write(recommendation.suggested_next_step)
    return recommendation
