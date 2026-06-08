"""Streamlit entrypoint for Social Content Lab."""

from pathlib import Path

import streamlit as st
from dotenv import load_dotenv

from src.config import AppConfig
from src.models.planning import ClarifyingAnswers
from src.services.content_pack_builder import ContentPackBuilder
from src.services.cost_estimator import CostEstimator
from src.services.model_router import ModelRouter
from src.services.planning_defaults import build_initial_answers, label_for_route, normalize_clarifying_answers, resolve_aspect_ratio, resolve_duration_seconds
from src.services.project_service import ProjectService
from src.services.question_builder import QuestionBuilder
from src.services.source_analyser import SourceAnalyser
from src.ui.content_pack_panel import render_content_pack_panel
from src.ui.project_form import render_project_form
from src.ui.questions_panel import render_questions_panel
from src.ui.recommendation_panel import render_recommendation_panel
from src.ui.source_panel import render_source_panel


def initialise_session_state() -> None:
    """Initialise Streamlit session state keys used by the app."""
    defaults = {
        "project": None,
        "sources": [],
        "answers": ClarifyingAnswers(),
        "answers_saved": False,
        "recommendation": None,
        "content_pack": None,
    }
    for key, value in defaults.items():
        if key not in st.session_state:
            st.session_state[key] = value
    st.session_state.answers = normalize_clarifying_answers(st.session_state.get("answers"))


def render_sidebar() -> None:
    """Render sidebar project and planning status."""
    project = st.session_state.get("project")
    sources = st.session_state.get("sources", [])
    answers = normalize_clarifying_answers(st.session_state.get("answers", ClarifyingAnswers()), project)
    st.session_state.answers = answers
    recommendation = st.session_state.get("recommendation")
    content_pack = st.session_state.get("content_pack")
    st.sidebar.title("Planning status")
    if project is None:
        st.sidebar.info("No project yet")
        st.sidebar.write("Current workflow stage: Project setup")
    else:
        st.sidebar.write(f"Current project: {getattr(project, 'project_id', 'Not resolved yet')}")
        st.sidebar.write(f"Resolved platform: {answers.platform or 'Not resolved yet'}")
        resolved_aspect_ratio = resolve_aspect_ratio(answers) or "Not resolved yet"
        st.sidebar.write(f"Resolved aspect ratio: {resolved_aspect_ratio}")
        duration = resolve_duration_seconds(project, answers)
        st.sidebar.write(f"Resolved duration: {f'{duration} seconds' if duration else 'Not resolved yet'}")
        st.sidebar.write(f"Source count: {len(sources)}")
        st.sidebar.write(f"Current workflow stage: {_current_stage(project, sources, st.session_state.get('answers_saved'), recommendation, content_pack)}")
        if recommendation:
            st.sidebar.write(f"Route: {label_for_route(recommendation.recommended_workflow_route)}")
    if st.sidebar.button("Reset current session only"):
        st.session_state.clear()
        st.rerun()


def _current_stage(project: object, sources: list[object], answers_saved: bool, recommendation: object, content_pack: object) -> str:
    """Return a compact workflow stage label."""
    if project is None:
        return "Project setup"
    if not sources:
        return "Source upload/reference"
    if not answers_saved:
        return "Clarifying questions"
    if recommendation is None:
        return "Model/workflow recommendation"
    if content_pack is None:
        return "Content pack preview"
    return "Save/export files"


def main() -> None:
    """Render the Social Content Lab application."""
    load_dotenv()
    config = AppConfig.from_environment(Path.cwd())
    project_service = ProjectService(config)
    source_analyser = SourceAnalyser(project_service)
    question_builder = QuestionBuilder()
    cost_estimator = CostEstimator()
    model_router = ModelRouter(cost_estimator)
    content_pack_builder = ContentPackBuilder(project_service)

    st.set_page_config(page_title="Social Content Lab", layout="wide")
    initialise_session_state()
    render_sidebar()

    st.title("Social Content Lab")
    st.caption("A local-first pre-production tool for planning AI-assisted social media content.")

    project = render_project_form(project_service)
    if project is None:
        st.info("Create a project to unlock source collection, recommendations, and export.")
        return

    if st.session_state.project is None or st.session_state.project.project_id != project.project_id:
        st.session_state.answers = build_initial_answers(project)
        st.session_state.answers_saved = False
        st.session_state.recommendation = None
        st.session_state.content_pack = None
        st.session_state.sources = []
    else:
        st.session_state.answers = normalize_clarifying_answers(st.session_state.answers, project)
    st.session_state.project = project
    st.divider()

    sources = render_source_panel(source_analyser, project, st.session_state.sources)
    st.session_state.sources = sources
    st.divider()

    question_groups = question_builder.build_questions(project, sources)
    answers = render_questions_panel(question_groups, st.session_state.answers, project, sources)
    st.session_state.answers = answers
    st.divider()

    recommendation = render_recommendation_panel(model_router, project, sources, answers)
    st.session_state.recommendation = recommendation
    st.divider()

    content_pack = render_content_pack_panel(
        content_pack_builder,
        project,
        sources,
        answers,
        recommendation,
        st.session_state.content_pack,
    )
    st.session_state.content_pack = content_pack


if __name__ == "__main__":
    main()
