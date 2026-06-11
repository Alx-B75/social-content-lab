"""Source upload and reference panel for Social Content Lab."""

import html

import streamlit as st

from src.models.project import ContentProject
from src.models.source import FrameRecord, FrameRole, SourceRecord, SourceType
from src.services.source_analyser import SourceAnalyser
from src.services.video_frame_extractor import (
    build_frame_index,
    extract_reference_frames,
    is_ffmpeg_available,
    is_ffprobe_available,
    load_frame_index,
    save_frame_index,
)


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
    declared_purpose = st.text_input(
        "Declared purpose for this source",
        placeholder="Example: visual style reference, factual context, quote source",
        key="source_declared_purpose",
    )

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

    _render_source_summary(source_analyser, project, sources)
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
    source_analyser.project_service.save_project(project, sources, st.session_state.get("content_pack"), st.session_state.get("answers"))


def _render_source_summary(
    source_analyser: SourceAnalyser,
    project: ContentProject,
    sources: list[SourceRecord],
) -> None:
    """Render a compact source metadata summary."""
    if not sources:
        st.info("No sources added yet. You can continue with director instructions only.")
        return

    st.subheader("Source index")
    for source in sources:
        st.markdown(_source_row(source), unsafe_allow_html=True)
        if source.source_type == SourceType.VIDEO:
            _render_video_frame_tools(source_analyser, project, sources, source)
        with st.expander(f"Raw metadata for {source.source_id}", expanded=False):
            st.json(source.model_dump(mode="json"))


def _source_row(source: SourceRecord) -> str:
    """Render a readable source summary row."""
    source_name = source.original_filename or source.url or source.manual_description or source.source_id
    details = [
        f"Type: {source.source_type.value}",
        f"Strategy: {source.strategy.value}",
        f"Size: {_format_file_size(source.file_size_bytes)}",
    ]
    if source.aspect_ratio:
        details.append(f"Aspect: {source.aspect_ratio}")
    if source.duration_seconds:
        details.append(f"Duration: {source.duration_seconds:.1f}s")
    if source.frame_rate:
        details.append(f"Frame rate: {source.frame_rate:.2f} fps")
    if source.source_type == SourceType.VIDEO:
        details.append(f"Frames: {source.frame_extraction_status} ({source.frame_count})")
        if source.selected_frame_count:
            details.append(f"Selected: {source.selected_frame_count}")
    details.append(f"Purpose: {source.declared_purpose or 'Not specified'}")
    return (
        "<div class='scl-source-row'>"
        f"<strong>{html.escape(str(source_name))}</strong><br>"
        f"<span class='scl-muted'>{html.escape(' | '.join(details))}</span>"
        "</div>"
    )


def _format_file_size(file_size_bytes: int | None) -> str:
    """Format a file size for source summaries."""
    if file_size_bytes is None:
        return "Not applicable"
    if file_size_bytes < 1024:
        return f"{file_size_bytes} B"
    if file_size_bytes < 1024 * 1024:
        return f"{file_size_bytes / 1024:.1f} KB"
    return f"{file_size_bytes / (1024 * 1024):.1f} MB"


def _render_video_frame_tools(
    source_analyser: SourceAnalyser,
    project: ContentProject,
    sources: list[SourceRecord],
    source: SourceRecord,
) -> None:
    """Render extraction and frame-selection controls for a video source."""
    metadata_text = _video_metadata_text(source)
    st.caption(metadata_text)
    if not is_ffmpeg_available() or not is_ffprobe_available():
        st.warning("Install FFmpeg and make sure ffmpeg/ffprobe are on PATH to enable frame extraction.")
    if st.button("Extract reference frames", key=f"extract_frames_{source.source_id}"):
        _extract_frames_for_source(source_analyser, project, sources, source)
    frames = load_frame_index(source.frame_index_path)
    if frames:
        _render_frame_selection(source_analyser, project, sources, source, frames)
    elif source.frame_extraction_status == "completed":
        st.info("Frame extraction completed, but no frame index was found.")


def _extract_frames_for_source(
    source_analyser: SourceAnalyser,
    project: ContentProject,
    sources: list[SourceRecord],
    source: SourceRecord,
) -> None:
    """Extract frames for one video source and persist metadata."""
    if source.stored_path is None:
        st.error("This video source has no saved file path.")
        return
    frame_dir = project.project_path / "sources" / "frames" / source.source_id
    frame_index_path = frame_dir / "frame-index.json"
    try:
        frames = extract_reference_frames(source.stored_path, frame_dir, source.duration_seconds, max_frames=5, source_id=source.source_id)
        build_frame_index(source.source_id, frames, frame_index_path)
    except RuntimeError as error:
        _update_source_frame_status(source, "unavailable", 0, None, str(error))
        _persist_video_frame_state(source_analyser, project, sources)
        st.warning(str(error))
        return
    except Exception as error:
        _update_source_frame_status(source, "failed", 0, None, f"Frame extraction failed: {type(error).__name__}")
        _persist_video_frame_state(source_analyser, project, sources)
        st.error(f"Frame extraction failed: {type(error).__name__}")
        return
    _update_source_frame_status(source, "completed", len(frames), frame_index_path, "Reference frames extracted with ffmpeg.")
    for frame in frames:
        source_analyser.project_service.append_frame_to_asset_log(project, frame)
    _persist_video_frame_state(source_analyser, project, sources)
    st.success(f"Extracted {len(frames)} reference frame(s).")


def _render_frame_selection(
    source_analyser: SourceAnalyser,
    project: ContentProject,
    sources: list[SourceRecord],
    source: SourceRecord,
    frames: list[FrameRecord],
) -> None:
    """Render frame thumbnails and selection controls."""
    role_options = [role.value for role in FrameRole]
    with st.expander(f"Select frames for {source.source_id}", expanded=True):
        with st.form(f"frame_selection_{source.source_id}"):
            updated_frames: list[FrameRecord] = []
            for index, frame in enumerate(frames):
                columns = st.columns([1, 2])
                if frame.absolute_path.exists():
                    columns[0].image(str(frame.absolute_path), caption=_frame_caption(frame), use_container_width=True)
                else:
                    columns[0].warning("Frame file missing.")
                selected_index = role_options.index(frame.selected_role.value) if frame.selected_role.value in role_options else 0
                role_value = columns[1].selectbox("Role", role_options, index=selected_index, key=f"role_{source.source_id}_{frame.frame_id}")
                notes = columns[1].text_input("Notes", value=frame.notes, key=f"notes_{source.source_id}_{frame.frame_id}")
                updated_frames.append(frame.model_copy(update={"selected_role": FrameRole(role_value), "notes": notes}))
            submitted = st.form_submit_button("Save frame selections")
        if submitted:
            save_frame_index(source.source_id, source.frame_index_path, updated_frames)
            source.selected_frame_count = _selected_frame_count(updated_frames)
            _persist_video_frame_state(source_analyser, project, sources)
            st.success("Frame selections saved.")


def _video_metadata_text(source: SourceRecord) -> str:
    """Return compact video metadata text for the source panel."""
    parts = [f"Extraction status: {source.frame_extraction_status}"]
    if source.duration_seconds:
        parts.append(f"Duration: {source.duration_seconds:.1f}s")
    if source.aspect_ratio:
        parts.append(f"Aspect: {source.aspect_ratio}")
    if source.width and source.height:
        parts.append(f"Size: {source.width}x{source.height}")
    if source.frame_rate:
        parts.append(f"Frame rate: {source.frame_rate:.2f} fps")
    extractor = source.extra.get("metadata_extractor") if isinstance(source.extra, dict) else None
    if extractor:
        parts.append(f"Metadata: {extractor}")
    return " | ".join(parts)


def _frame_caption(frame: FrameRecord) -> str:
    """Return a readable frame caption."""
    timestamp = f"{frame.timestamp_seconds:.2f}s" if frame.timestamp_seconds is not None else "unknown"
    return f"{frame.label} at {timestamp}"


def _update_source_frame_status(
    source: SourceRecord,
    status: str,
    frame_count: int,
    frame_index_path: object,
    note: str,
) -> None:
    """Update frame extraction metadata on a source record."""
    source.frame_extraction_status = status
    source.frame_count = frame_count
    source.frame_index_path = frame_index_path
    if note and note not in source.notes:
        source.notes.append(note)


def _persist_video_frame_state(source_analyser: SourceAnalyser, project: ContentProject, sources: list[SourceRecord]) -> None:
    """Persist source metadata after frame extraction or selection."""
    source_analyser.project_service.save_source_index(project, sources)
    source_analyser.project_service.save_project(project, sources, st.session_state.get("content_pack"), st.session_state.get("answers"))


def _selected_frame_count(frames: list[FrameRecord]) -> int:
    """Count frames selected for production use."""
    return sum(1 for frame in frames if frame.selected_role not in {FrameRole.UNSELECTED, FrameRole.DO_NOT_USE})
