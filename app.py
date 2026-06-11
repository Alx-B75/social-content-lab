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
from src.ui.style import apply_app_style


def initialise_session_state() -> None:
    """Initialise Streamlit session state keys used by the app."""
    defaults = {
        "project": None,
        "sources": [],
        "answers": ClarifyingAnswers(),
        "answers_saved": False,
        "recommendation": None,
        "content_pack": None,
        "last_project_seed": None,
        "pending_inherited_answers": None,
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
        st.sidebar.markdown(_sidebar_item("Current project", getattr(project, "project_id", "Not resolved yet")), unsafe_allow_html=True)
        st.sidebar.markdown(_sidebar_item("Project path", _short_path(str(getattr(project, "project_path", "")))), unsafe_allow_html=True)
        st.sidebar.markdown(_sidebar_item("Workflow stage", _current_stage(project, sources, st.session_state.get("answers_saved"), recommendation, content_pack)), unsafe_allow_html=True)
        st.sidebar.markdown(_sidebar_item("Platform", answers.platform or "Not resolved yet"), unsafe_allow_html=True)
        resolved_aspect_ratio = resolve_aspect_ratio(answers) or "Not resolved yet"
        st.sidebar.markdown(_sidebar_item("Aspect ratio", resolved_aspect_ratio), unsafe_allow_html=True)
        duration = resolve_duration_seconds(project, answers)
        st.sidebar.markdown(_sidebar_item("Duration", f"{duration} seconds" if duration else "Not resolved yet"), unsafe_allow_html=True)
        st.sidebar.markdown(_sidebar_item("Source count", str(len(sources))), unsafe_allow_html=True)
        if recommendation:
            st.sidebar.markdown(_sidebar_item("Route", label_for_route(recommendation.recommended_workflow_route)), unsafe_allow_html=True)
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


def _sidebar_item(label: str, value: str) -> str:
    """Render a compact sidebar status item."""
    return f"<div class='scl-sidebar-item'><strong>{label}</strong><br><span>{value}</span></div>"


def _short_path(path: str) -> str:
    """Shorten a local path for sidebar display."""
    if len(path) <= 54:
        return path
    return f"...{path[-51:]}"


def remember_current_project_seed() -> None:
    """Store current project and answer settings for quick iteration."""
    project = st.session_state.get("project")
    if project is None:
        return
    answers = normalize_clarifying_answers(st.session_state.get("answers"), project)
    st.session_state.last_project_seed = {
        "project": project.model_dump(mode="json"),
        "answers": answers.model_dump(mode="json"),
    }


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
    apply_app_style()
    initialise_session_state()
    render_sidebar()

    st.title("Social Content Lab")
    st.caption("A local-first pre-production tool for planning AI-assisted social media content.")

    project = render_project_form(project_service)
    if project is None:
        st.info("Create a project to unlock source collection, recommendations, and export.")
        return

    if st.session_state.project is None or st.session_state.project.project_id != project.project_id:
        if st.session_state.project is not None and st.session_state.project.project_id == project.project_id:
            st.session_state.answers = normalize_clarifying_answers(st.session_state.answers, project)
        else:
            inherited_answers = st.session_state.get("pending_inherited_answers")
            st.session_state.answers = normalize_clarifying_answers(inherited_answers, project) if inherited_answers else build_initial_answers(project)
            st.session_state.pending_inherited_answers = None
            if st.session_state.get("project_start_mode") != "Load saved project":
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
    if st.session_state.get("answers_saved"):
        project_service.save_project(project, sources, st.session_state.get("content_pack"), answers)
    remember_current_project_seed()
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
