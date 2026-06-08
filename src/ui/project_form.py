"""Project setup panel for Social Content Lab."""

import streamlit as st

from src.models.project import ContentProject, ProjectCreate
from src.services.project_service import ProjectService


def render_project_form(project_service: ProjectService) -> ContentProject | None:
    """Render the project setup form and create a project when submitted."""
    st.header("1. Project setup")
    existing_project = st.session_state.get("project")
    if existing_project:
        st.success(f"Active project: {existing_project.project_id}")
        st.code(str(existing_project.project_path))
        return existing_project

    with st.form("project_setup_form"):
        project_name = st.text_input("Project name")
        working_title = st.text_input("Working title")
        brand_name = st.text_input("Brand name optional")
        topic = st.text_input("Topic optional")
        director_instructions = st.text_area("Director instructions", height=180)
        submitted = st.form_submit_button("Create project")

    if not submitted:
        return None

    if not project_name.strip() or not working_title.strip() or not director_instructions.strip():
        st.error("Project name, working title, and director instructions are required.")
        return None

    try:
        project = project_service.create_project(
            ProjectCreate(
                project_name=project_name.strip(),
                working_title=working_title.strip(),
                brand_name=brand_name.strip() or None,
                topic=topic.strip() or None,
                director_instructions=director_instructions.strip(),
            )
        )
    except OSError as error:
        st.error(f"Could not create project: {error}")
        return None

    st.success(f"Created project: {project.project_id}")
    return project
