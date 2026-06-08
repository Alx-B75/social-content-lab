"""Streamlit entrypoint for Social Content Lab."""

from pathlib import Path

import streamlit as st
from dotenv import load_dotenv

from src.config import AppConfig
from src.models.planning import ClarifyingAnswers
from src.services.content_pack_builder import ContentPackBuilder
from src.services.cost_estimator import CostEstimator
from src.services.model_router import ModelRouter
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
        "recommendation": None,
        "content_pack": None,
    }
    for key, value in defaults.items():
        if key not in st.session_state:
            st.session_state[key] = value


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

    st.title("Social Content Lab")
    st.caption("A local-first pre-production tool for planning AI-assisted social media content.")

    project = render_project_form(project_service)
    if project is None:
        st.info("Create a project to unlock source collection, recommendations, and export.")
        return

    st.session_state.project = project
    st.divider()

    sources = render_source_panel(source_analyser, project, st.session_state.sources)
    st.session_state.sources = sources
    st.divider()

    question_groups = question_builder.build_questions(project, sources)
    answers = render_questions_panel(question_groups, st.session_state.answers)
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
