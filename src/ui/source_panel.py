"""Source upload and reference panel for Social Content Lab."""

import streamlit as st

from src.models.project import ContentProject
from src.models.source import SourceRecord
from src.services.source_analyser import SourceAnalyser


def render_source_panel(
    source_analyser: SourceAnalyser,
    project: ContentProject,
    current_sources: list[SourceRecord],
) -> list[SourceRecord]:
    """Render source collection controls and persist source metadata."""
    st.header("2. Source upload/reference")
    if project is None:
        st.warning("Create a project before adding sources.")
        return current_sources
    sources = list(current_sources)
    source_type = st.selectbox("Source type", ["image upload", "video upload", "URL", "pasted text", "manual description"])
    declared_purpose = st.text_input("Declared purpose for this source", placeholder="Example: visual style reference, factual context, quote source")

    if source_type == "image upload":
        uploaded_file = st.file_uploader("Upload image", type=["png", "jpg", "jpeg", "webp"], key="image_upload")
        if st.button("Add image source", disabled=uploaded_file is None):
            if uploaded_file is not None:
                record = source_analyser.add_image_source(project, uploaded_file.name, uploaded_file.getvalue(), uploaded_file.type, declared_purpose or None)
                _persist_source(source_analyser, project, sources, record)
                st.success(f"Added image source: {record.source_id}. Asset log updated.")

    if source_type == "video upload":
        uploaded_file = st.file_uploader("Upload video", type=["mp4", "mov", "webm", "m4v"], key="video_upload")
        if st.button("Add video source", disabled=uploaded_file is None):
            if uploaded_file is not None:
                record = source_analyser.add_video_source(project, uploaded_file.name, uploaded_file.getvalue(), uploaded_file.type, declared_purpose or None)
                _persist_source(source_analyser, project, sources, record)
                if record.duration_seconds and record.aspect_ratio:
                    st.success(f"Added video source: {record.source_id}. Detected {record.duration_seconds:.1f}s at {record.aspect_ratio}. Asset log updated.")
                else:
                    st.warning(f"Added video source: {record.source_id}. Video metadata extraction unavailable. Asset log updated.")

    if source_type == "URL":
        url = st.text_input("URL")
        if st.button("Add URL source"):
            if not url.strip():
                st.error("Enter a URL before adding it.")
            else:
                record = source_analyser.add_url_source(url.strip(), declared_purpose or None)
                _persist_source(source_analyser, project, sources, record)
                st.success(f"Added URL source: {record.source_id}. Asset log updated.")

    if source_type == "pasted text":
        pasted_text = st.text_area("Pasted text", height=180)
        if st.button("Add pasted text source"):
            if not pasted_text.strip():
                st.error("Paste text before adding it.")
            else:
                record = source_analyser.add_pasted_text_source(project, pasted_text.strip(), declared_purpose or None)
                _persist_source(source_analyser, project, sources, record)
                st.success(f"Added pasted text source: {record.source_id}. Asset log updated.")

    if source_type == "manual description":
        description = st.text_area("Manual description", height=140)
        if st.button("Add manual description source"):
            if not description.strip():
                st.error("Enter a manual description before adding it.")
            else:
                record = source_analyser.add_manual_description_source(description.strip(), declared_purpose or None)
                _persist_source(source_analyser, project, sources, record)
                st.success(f"Added manual description source: {record.source_id}. Asset log updated.")

    _render_source_summary(sources)
    return sources


def _persist_source(
    source_analyser: SourceAnalyser,
    project: ContentProject,
    sources: list[SourceRecord],
    record: SourceRecord,
) -> None:
    """Persist a newly added source across all local project files."""
    sources.append(record)
    source_analyser.project_service.save_source_index(project, sources)
    source_analyser.project_service.append_source_to_asset_log(project, record)
    source_analyser.project_service.save_project(project, sources, st.session_state.get("content_pack"))


def _render_source_summary(sources: list[SourceRecord]) -> None:
    """Render a compact source metadata summary."""
    if not sources:
        st.info("No sources added yet. You can continue with director instructions only.")
        return

    st.subheader("Source index")
    for source in sources:
        with st.expander(f"{source.source_id} - {source.source_type.value} - {source.strategy.value}", expanded=False):
            st.json(source.model_dump(mode="json"))
