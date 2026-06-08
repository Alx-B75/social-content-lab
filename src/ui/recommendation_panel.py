"""Recommendation panel for Social Content Lab."""

import streamlit as st

from src.models.planning import ClarifyingAnswers, WorkflowRecommendation
from src.models.project import ContentProject
from src.models.source import SourceRecord
from src.services.model_router import ModelRouter


def render_recommendation_panel(
    model_router: ModelRouter,
    project: ContentProject,
    sources: list[SourceRecord],
    answers: ClarifyingAnswers,
) -> WorkflowRecommendation | None:
    """Render workflow recommendation controls and output."""
    st.header("4. Model/workflow recommendation")
    if st.button("Generate recommendation"):
        recommendation = model_router.recommend(project, sources, answers)
        st.session_state.recommendation = recommendation
    else:
        recommendation = st.session_state.get("recommendation")

    if recommendation is None:
        st.info("Save clarifying answers, then generate a recommendation.")
        return None

    columns = st.columns(4)
    columns[0].metric("Route", recommendation.recommended_workflow_route.value)
    columns[1].metric("Provider", recommendation.suggested_provider_type.value)
    columns[2].metric("Cost band", recommendation.estimated_cost_band.value)
    columns[3].metric("Model category", recommendation.recommended_model_category)

    st.subheader("Rationale")
    for item in recommendation.rationale:
        st.write(f"- {item}")

    st.subheader("Warnings")
    for warning in recommendation.warnings:
        st.warning(warning)

    st.subheader("Suggested next step")
    st.write(recommendation.suggested_next_step)
    return recommendation
