"""Project setup panel for Social Content Lab."""

from typing import Any

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
        first_column, second_column, third_column = st.columns(3)
        if first_column.button("Reiterate this project"):
            _store_project_seed(existing_project)
            _clear_current_project_for_new_start()
            st.session_state["project_start_mode"] = "Reiterate last project"
            st.rerun()
        if second_column.button("Start fresh project"):
            _store_project_seed(existing_project)
            _clear_current_project_for_new_start()
            st.session_state["project_start_mode"] = "Start new project"
            st.rerun()
        if third_column.button("Load saved project"):
            _store_project_seed(existing_project)
            _clear_current_project_for_new_start()
            st.session_state["project_start_mode"] = "Load saved project"
            st.rerun()
        return existing_project

    seed = st.session_state.get("last_project_seed")
    default_mode = st.session_state.get("project_start_mode") or ("Reiterate last project" if seed else "Start new project")
    mode_options = _project_start_options(project_service, seed)
    mode_index = mode_options.index(default_mode) if default_mode in mode_options else 0
    selected_mode = st.radio(
        "Project start",
        mode_options,
        index=mode_index,
        horizontal=True,
        help="Reiterate last project copies prior settings and answers into a new local project folder.",
    )
    if selected_mode == "Load saved project":
        return _render_project_loader(project_service)
    _render_project_manager(project_service)
    inherited_project = _project_seed(seed) if selected_mode == "Reiterate last project" else {}

    with st.form("project_setup_form"):
        project_name = st.text_input("Project name", value=_default_project_name(inherited_project))
        working_title = st.text_input("Working title", value=_string_value(inherited_project, "working_title"))
        brand_name = st.text_input("Brand name optional", value=_string_value(inherited_project, "brand_name"))
        topic = st.text_input("Topic optional", value=_string_value(inherited_project, "topic"))
        director_instructions = st.text_area("Director instructions", value=_string_value(inherited_project, "director_instructions"), height=180)
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

    if selected_mode == "Reiterate last project" and seed:
        st.session_state["pending_inherited_answers"] = seed.get("answers")
    else:
        st.session_state["pending_inherited_answers"] = None
    st.session_state["project_start_mode"] = selected_mode
    st.success(f"Created project: {project.project_id}")
    return project


def _store_project_seed(project: ContentProject) -> None:
    """Store current project and answers as a seed for a new project."""
    answers = st.session_state.get("answers")
    st.session_state["last_project_seed"] = {
        "project": project.model_dump(mode="json"),
        "answers": answers.model_dump(mode="json") if hasattr(answers, "model_dump") else answers,
    }


def _clear_current_project_for_new_start() -> None:
    """Clear only active project state while preserving reusable seed data."""
    st.session_state["project"] = None
    st.session_state["sources"] = []
    st.session_state["recommendation"] = None
    st.session_state["content_pack"] = None
    st.session_state["answers_saved"] = False


def _project_seed(seed: dict[str, Any] | None) -> dict[str, Any]:
    """Return project seed data from session state."""
    if not seed:
        return {}
    project = seed.get("project")
    return project if isinstance(project, dict) else {}


def _string_value(project_seed: dict[str, Any], key: str) -> str:
    """Return a string value from project seed data."""
    value = project_seed.get(key)
    return str(value) if value else ""


def _default_project_name(project_seed: dict[str, Any]) -> str:
    """Return an inherited project name default."""
    project_name = _string_value(project_seed, "project_name")
    if not project_name:
        return ""
    return f"{project_name} iteration"


def _project_start_options(project_service: ProjectService, seed: dict[str, Any] | None) -> list[str]:
    """Return available project start options."""
    options = ["Start new project"]
    if seed:
        options.append("Reiterate last project")
    if project_service.list_projects():
        options.append("Load saved project")
    return options


def _render_project_loader(project_service: ProjectService) -> ContentProject | None:
    """Render controls for loading a saved project from local storage."""
    projects = project_service.list_projects()
    if not projects:
        st.info("No saved local projects found yet.")
        return None
    labels = [project["label"] for project in projects]
    selected_label = st.selectbox("Saved project", labels)
    selected_project = projects[labels.index(selected_label)]
    st.caption(selected_project["path"])
    if not st.button("Load selected project"):
        return None
    try:
        project, sources, content_pack, answers = project_service.load_project(selected_project["project_id"])
    except (OSError, ValueError) as error:
        st.error(f"Could not load project: {error}")
        return None
    st.session_state["project"] = project
    st.session_state["sources"] = sources
    st.session_state["content_pack"] = content_pack
    st.session_state["answers"] = answers
    st.session_state["recommendation"] = None
    st.session_state["answers_saved"] = answers is not None
    st.session_state["pending_inherited_answers"] = None
    st.success(f"Loaded project: {project.project_id}")
    return project


def _render_project_manager(project_service: ProjectService) -> None:
    """Render lightweight local project CRUD controls."""
    projects = project_service.list_projects()
    if not projects:
        return
    with st.expander("Manage saved projects", expanded=False):
        labels = [project["label"] for project in projects]
        selected_label = st.selectbox("Project", labels, key="manage_project_select")
        selected_project = projects[labels.index(selected_label)]
        st.caption(selected_project["path"])
        first_column, second_column, third_column = st.columns(3)
        if first_column.button("Load", key="manage_load_project"):
            _load_project_into_session(project_service, selected_project["project_id"])
            st.rerun()
        if second_column.button("Duplicate", key="manage_duplicate_project"):
            try:
                duplicate = project_service.duplicate_project(selected_project["project_id"])
            except (OSError, ValueError) as error:
                st.error(f"Could not duplicate project: {error}")
            else:
                st.success(f"Duplicated project: {duplicate.project_id}")
        delete_confirmation = st.text_input("Type DELETE to remove selected project", key="manage_delete_confirmation")
        if third_column.button("Delete", key="manage_delete_project"):
            if delete_confirmation != "DELETE":
                st.warning("Type DELETE before removing a project.")
            else:
                try:
                    project_service.delete_project(selected_project["project_id"])
                except (OSError, ValueError) as error:
                    st.error(f"Could not delete project: {error}")
                else:
                    if st.session_state.get("project") and st.session_state.project.project_id == selected_project["project_id"]:
                        _clear_current_project_for_new_start()
                    st.success(f"Deleted project: {selected_project['project_id']}")
                    st.rerun()
        _render_metadata_editor(project_service, selected_project["project_id"])


def _render_metadata_editor(project_service: ProjectService, project_id: str) -> None:
    """Render controls for updating saved project metadata."""
    try:
        project, _sources, _content_pack, _answers = project_service.load_project(project_id)
    except (OSError, ValueError):
        return
    with st.form(f"metadata_editor_{project_id}"):
        project_name = st.text_input("Project name", project.project_name)
        working_title = st.text_input("Working title", project.working_title)
        brand_name = st.text_input("Brand name optional", project.brand_name or "")
        topic = st.text_input("Topic optional", project.topic or "")
        director_instructions = st.text_area("Director instructions", project.director_instructions, height=120)
        submitted = st.form_submit_button("Update metadata")
    if not submitted:
        return
    updated_project = project_service.update_project_metadata(
        project,
        {
            "project_name": project_name.strip(),
            "working_title": working_title.strip(),
            "brand_name": brand_name.strip() or None,
            "topic": topic.strip() or None,
            "director_instructions": director_instructions.strip(),
        },
    )
    if st.session_state.get("project") and st.session_state.project.project_id == updated_project.project_id:
        st.session_state["project"] = updated_project
    st.success("Project metadata updated.")


def _load_project_into_session(project_service: ProjectService, project_id: str) -> None:
    """Load a project into Streamlit session state."""
    project, sources, content_pack, answers = project_service.load_project(project_id)
    st.session_state["project"] = project
    st.session_state["sources"] = sources
    st.session_state["content_pack"] = content_pack
    st.session_state["answers"] = answers
    st.session_state["recommendation"] = None
    st.session_state["answers_saved"] = answers is not None
    st.session_state["pending_inherited_answers"] = None
    st.session_state["project_start_mode"] = "Load saved project"
