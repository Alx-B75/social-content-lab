"""Side-by-side content pack review and final export panel."""

import streamlit as st

from src.models.project import ContentProject
from src.services.review_pack_builder import (
    SECTION_NAMES,
    ReviewState,
    UnsafeReviewContentError,
    discover_pack_versions,
    export_final_pack,
    load_or_initialize_review_state,
    load_pack_sections,
    save_review_state,
)


REVIEW_STATUSES = ["draft", "needs_review", "approved", "published"]


def render_review_pack_panel(project: ContentProject) -> None:
    """Render deterministic/LLM comparison and final-pack assembly controls."""
    st.header("Review and final pack")
    availability = discover_pack_versions(project.project_path)
    versions = load_pack_sections(project.project_path)
    review_state = load_or_initialize_review_state(project)
    _render_availability(availability)

    with st.form(f"review_pack_{project.project_id}"):
        selected_sections: dict[str, str] = {}
        custom_text: dict[str, str] = dict(review_state.custom_section_text)
        for section in SECTION_NAMES:
            with st.expander(section.title(), expanded=section == "brief"):
                columns = st.columns(2)
                columns[0].markdown("**Deterministic**")
                columns[0].text_area(
                    f"Deterministic {section}",
                    versions[section]["deterministic"] or "Not available",
                    height=220,
                    disabled=True,
                    key=f"review_det_{project.project_id}_{section}",
                    label_visibility="collapsed",
                )
                columns[1].markdown("**LLM-assisted**")
                columns[1].text_area(
                    f"LLM-assisted {section}",
                    versions[section]["llm"] or "Not available",
                    height=220,
                    disabled=True,
                    key=f"review_llm_{project.project_id}_{section}",
                    label_visibility="collapsed",
                )
                if not availability[section]["llm"]:
                    st.warning(f"No LLM-assisted {section} file is available.")
                options = ["deterministic"]
                if availability[section]["llm"]:
                    options.append("llm")
                options.append("custom")
                current_source = review_state.selected_sections.get(section, "deterministic")
                if current_source not in options:
                    current_source = "deterministic"
                selected_source = st.radio(
                    "Use for final pack",
                    options,
                    index=options.index(current_source),
                    horizontal=True,
                    key=f"review_source_{project.project_id}_{section}",
                )
                selected_sections[section] = selected_source
                if selected_source == "custom":
                    custom_text[section] = st.text_area(
                        "Custom section text",
                        value=review_state.custom_section_text.get(section, ""),
                        height=180,
                        key=f"review_custom_{project.project_id}_{section}",
                    )

        status = st.selectbox(
            "Review status",
            REVIEW_STATUSES,
            index=REVIEW_STATUSES.index(review_state.review_status),
        )
        reviewer_notes = st.text_area("Reviewer notes", value=review_state.reviewer_notes, height=100)
        action_columns = st.columns(2)
        save_clicked = action_columns[0].form_submit_button("Save review state")
        export_clicked = action_columns[1].form_submit_button("Export final pack")

    if save_clicked or export_clicked:
        updated_state = review_state.model_copy(
            update={
                "selected_sections": selected_sections,
                "custom_section_text": custom_text,
                "review_status": status,
                "reviewer_notes": reviewer_notes.strip(),
            }
        )
        updated_state = save_review_state(project, updated_state)
        if save_clicked:
            st.success("Review state saved.")
        if export_clicked:
            _export_reviewed_pack(project, updated_state)

    _render_export_history(load_or_initialize_review_state(project))


def _render_availability(availability: dict[str, dict[str, bool]]) -> None:
    """Render compact deterministic and LLM file availability."""
    st.subheader("Pack discovery")
    for section in SECTION_NAMES:
        deterministic = "Available" if availability[section]["deterministic"] else "Missing"
        llm = "Available" if availability[section]["llm"] else "Missing"
        st.write(f"**{section.title()}** - Deterministic: {deterministic} | LLM-assisted: {llm}")


def _export_reviewed_pack(project: ContentProject, review_state: ReviewState) -> None:
    """Export final files or display safe validation warnings."""
    try:
        exported_state = export_final_pack(project, review_state)
    except UnsafeReviewContentError as error:
        st.error("Final pack was not exported. Review these safety warnings:")
        for warning in error.warnings:
            st.warning(warning)
        return
    st.success(f"Final pack exported locally with status: {exported_state.review_status}.")
    st.write("Created: final-brief.md, final-script.md, final-storyboard.md, final-prompts.md, final-captions.md, final-pack.md")


def _render_export_history(review_state: ReviewState) -> None:
    """Render recent final-pack export history."""
    if not review_state.export_history:
        return
    with st.expander("Export history", expanded=False):
        for entry in reversed(review_state.export_history[-10:]):
            st.write(f"{entry.get('exported_at')} - {entry.get('review_status')}")
