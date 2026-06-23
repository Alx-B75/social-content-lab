"""Source upload and reference panel for Social Content Lab."""

import html

import streamlit as st

from src.models.project import ContentProject
from src.models.source import FrameRecord, FrameRole, SourceRecord, SourceType
from src.services.frame_prefill import apply_prefill_to_frame, build_local_frame_prefill, prefill_missing_frame_fields
from src.services.frame_summary import selected_frame_count
from src.services.model_advisor import advise_vision_model
from src.services.openrouter_catalog import (
    estimate_model_cost_from_catalog,
    fetch_openrouter_models,
    get_model_catalog_status,
    is_router_helper_model_id,
    save_model_catalog_cache,
)
from src.services.source_analyser import SourceAnalyser
from src.services.vision_frame_analyser import analyse_frame_with_vision_model, apply_ai_frame_prefill
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
    _render_source_summary(source_analyser, project, sources)
    _render_add_source_controls(source_analyser, project, sources)
    return sources


def _render_add_source_controls(
    source_analyser: SourceAnalyser,
    project: ContentProject,
    sources: list[SourceRecord],
) -> None:
    """Render controls for adding a new source without confusing existing source metadata."""
    with st.expander("Add new source", expanded=not sources):
        source_options = ["image upload", "video upload", "URL", "pasted text", "manual description"]
        source_type = st.selectbox(
            "New source type",
            source_options,
            index=_default_source_type_index(sources, source_options),
            key="source_type_input",
        )
        declared_purpose = st.text_input(
            "Purpose for this new source",
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


def _default_source_type_index(sources: list[SourceRecord], source_options: list[str]) -> int:
    """Return the default source-type index based on saved context."""
    if any(source.source_type == SourceType.VIDEO for source in sources):
        return source_options.index("video upload")
    return source_options.index("image upload")


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

    st.subheader("Existing sources")
    duplicate_filenames = duplicate_source_filenames(sources)
    if duplicate_filenames:
        st.warning("Duplicate filename detected. Use source ID/timestamp to distinguish.")
    for source in sources:
        st.markdown(_source_row(source), unsafe_allow_html=True)
        if source.source_type == SourceType.VIDEO:
            _render_video_frame_tools(source_analyser, project, sources, source)
        with st.expander(f"Debug metadata for {source.source_id}", expanded=False):
            st.json(source.model_dump(mode="json"))


def _source_row(source: SourceRecord) -> str:
    """Render a readable source summary row."""
    source_name = source.original_filename or source.url or source.manual_description or source.source_id
    details = [
        f"Source ID: {source.source_id}",
        f"Filename: {source.original_filename or 'Not applicable'}",
        f"Type: {source.source_type.value}",
        f"Strategy: {source.strategy.value}",
        f"Size: {_format_file_size(source.file_size_bytes)}",
        f"Purpose: {source.declared_purpose or 'Not specified'}",
        f"Created: {source.created_at.isoformat(timespec='seconds')}",
    ]
    if source.aspect_ratio:
        details.append(f"Aspect: {source.aspect_ratio}")
    if source.duration_seconds:
        details.append(f"Duration: {source.duration_seconds:.1f}s")
    if source.frame_rate:
        details.append(f"Frame rate: {source.frame_rate:.2f} fps")
    if source.source_type == SourceType.VIDEO:
        details.append(f"Extraction: {source.frame_extraction_status} ({source.frame_count} frames)")
        if source.selected_frame_count:
            details.append(f"Selected: {source.selected_frame_count}")
    return (
        "<div class='scl-source-row'>"
        f"<strong>{html.escape(str(source_name))}</strong><br>"
        f"<span class='scl-muted'>{html.escape(' | '.join(details))}</span>"
        "</div>"
    )


def duplicate_source_filenames(sources: list[SourceRecord]) -> set[str]:
    """Return uploaded filenames that occur more than once."""
    counts: dict[str, int] = {}
    for source in sources:
        if source.original_filename:
            counts[source.original_filename] = counts.get(source.original_filename, 0) + 1
    return {filename for filename, count in counts.items() if count > 1}


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
    frames = load_frame_index(source.frame_index_path)
    _render_ffmpeg_diagnostics(show_warning=not frame_extraction_is_complete(source))
    if frame_extraction_is_complete(source):
        st.success(f"Frames extracted: {source.frame_count}.")
        st.info("View/edit extracted frames below.")
        with st.expander("Re-extract frames", expanded=False):
            st.warning("Re-extracting frames may overwrite or update frame-index.json for this source.")
            if st.button("Re-extract frames", key=f"reextract_frames_{source.source_id}"):
                _extract_frames_for_source(source_analyser, project, sources, source)
    else:
        if st.button(frame_extraction_action_label(source), key=f"extract_frames_{source.source_id}"):
            _extract_frames_for_source(source_analyser, project, sources, source)
    if frames:
        _render_frame_prefill_controls(source_analyser, project, sources, source, frames)
        _render_frame_selection(source_analyser, project, sources, source, frames)
    elif source.frame_extraction_status == "completed":
        st.info("Frame extraction completed, but no frame index was found.")


def frame_extraction_is_complete(source: SourceRecord) -> bool:
    """Return whether a video source has extracted frames ready for review."""
    return source.frame_extraction_status == "completed" and source.frame_count > 0


def frame_extraction_action_label(source: SourceRecord) -> str:
    """Return the primary frame extraction action label for a source."""
    if frame_extraction_is_complete(source):
        return "View/edit extracted frames"
    if source.frame_extraction_status in {"failed", "unavailable"}:
        return "Try frame extraction again"
    return "Extract reference frames"


def _render_ffmpeg_diagnostics(show_warning: bool = True) -> None:
    """Render compact FFmpeg visibility diagnostics for the current process."""
    ffmpeg_visible = is_ffmpeg_available()
    ffprobe_visible = is_ffprobe_available()
    if show_warning and (not ffmpeg_visible or not ffprobe_visible):
        st.warning("FFmpeg is not visible to this Streamlit process. Restart terminal/VS Code after installing FFmpeg or check PATH.")
    with st.expander("Video tool diagnostics", expanded=False):
        st.write(f"ffmpeg visible to this process: {'yes' if ffmpeg_visible else 'no'}")
        st.write(f"ffprobe visible to this process: {'yes' if ffprobe_visible else 'no'}")


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
    preset_options = ["No fast fill", "Use as opening hero", "Use as background", "Needs review", "Do not use"]
    st.markdown(f"**Select and describe frames for {source.source_id}**")
    with st.form(f"frame_selection_{source.source_id}"):
        updated_frames: list[FrameRecord] = []
        for index, frame in enumerate(frames):
            with st.expander(_frame_caption(frame), expanded=index == 0):
                st.caption(_frame_prefill_status(frame))
                columns = st.columns([1, 2])
                if frame.absolute_path.exists():
                    columns[0].image(str(frame.absolute_path), caption=_frame_caption(frame), width="stretch")
                else:
                    columns[0].warning("Frame file missing.")
                selected_index = role_options.index(frame.selected_role.value) if frame.selected_role.value in role_options else 0
                columns[1].markdown("**Quick setup**")
                preset = columns[1].selectbox(
                    "Quick preset",
                    preset_options,
                    key=f"preset_{source.source_id}_{frame.frame_id}",
                    help="Applies a preset role/use when you save this frame.",
                )
                role_value = columns[1].selectbox("Role", role_options, index=selected_index, key=f"role_{source.source_id}_{frame.frame_id}")
                recommended_use = columns[1].text_input("Recommended use", value=frame.recommended_use, key=f"use_{source.source_id}_{frame.frame_id}")
                st.markdown("**Description**")
                description = st.text_area("What is visible?", value=frame.description, height=85, key=f"description_{source.source_id}_{frame.frame_id}")
                detail_columns = st.columns(2)
                visible_subject = detail_columns[0].text_input("Main subject", value=frame.visible_subject, key=f"subject_{source.source_id}_{frame.frame_id}")
                setting = detail_columns[1].text_input("Setting/background", value=frame.setting, key=f"setting_{source.source_id}_{frame.frame_id}")
                with st.expander("Rights and risk", expanded=False):
                    on_screen_text = st.text_input("On-screen text, if any", value=frame.on_screen_text, key=f"text_{source.source_id}_{frame.frame_id}")
                    rights_notes = st.text_input("Rights/licensing note", value=frame.rights_notes, key=f"rights_{source.source_id}_{frame.frame_id}")
                    historical_or_brand_risk = st.text_input("Historical or brand risk", value=frame.historical_or_brand_risk, key=f"risk_{source.source_id}_{frame.frame_id}")
                    avoid_using_for = st.text_input("Avoid using this frame for", value=frame.avoid_using_for, key=f"avoid_{source.source_id}_{frame.frame_id}")
                with st.expander("Advanced notes", expanded=False):
                    notes = st.text_input("Notes", value=frame.notes, key=f"notes_{source.source_id}_{frame.frame_id}")
                    mood = st.text_input("Mood/tone", value=frame.mood, key=f"mood_{source.source_id}_{frame.frame_id}")
                    visual_style = st.text_input("Visual style", value=frame.visual_style, key=f"style_{source.source_id}_{frame.frame_id}")
                updated_frame = frame.model_copy(
                    update={
                        "selected_role": FrameRole(role_value),
                        "notes": notes,
                        "description": description,
                        "visible_subject": visible_subject,
                        "setting": setting,
                        "mood": mood,
                        "visual_style": visual_style,
                        "on_screen_text": on_screen_text,
                        "rights_notes": rights_notes,
                        "historical_or_brand_risk": historical_or_brand_risk,
                        "recommended_use": recommended_use,
                        "avoid_using_for": avoid_using_for,
                    }
                )
                updated_frames.append(_apply_frame_preset(updated_frame, preset))
        submitted = st.form_submit_button("Save frame selections")
    if submitted:
        save_frame_index(source.source_id, source.frame_index_path, updated_frames)
        for frame in updated_frames:
            source_analyser.project_service.append_frame_to_asset_log(project, frame)
        source.selected_frame_count = selected_frame_count(updated_frames)
        _persist_video_frame_state(source_analyser, project, sources)
        st.success("Frame selections saved.")


def _render_frame_prefill_controls(
    source_analyser: SourceAnalyser,
    project: ContentProject,
    sources: list[SourceRecord],
    source: SourceRecord,
    frames: list[FrameRecord],
) -> None:
    """Render local and optional consent-gated AI frame prefill controls."""
    st.markdown("**Frame interpretation prefill**")
    st.caption("Prefill suggestions are starting points. Review every field before using it in generated content.")
    replace_local = st.checkbox(
        "Replace existing values with local suggestions",
        value=False,
        key=f"replace_local_prefill_{source.source_id}",
    )
    frame_options = {f"{_frame_caption(frame)} ({frame.file_name})": frame.frame_id for frame in frames}
    selected_local_label = st.selectbox(
        "Current frame",
        list(frame_options),
        key=f"local_prefill_frame_{source.source_id}",
    )
    local_columns = st.columns(2)
    if local_columns[0].button("Prefill and save current frame", key=f"prefill_current_{source.source_id}"):
        frame_id = frame_options[selected_local_label]
        updated = [
            apply_prefill_to_frame(
                frame,
                build_local_frame_prefill(frame, source, project, st.session_state.get("answers")),
                replace_existing=replace_local,
            )
            if frame.frame_id == frame_id
            else frame
            for frame in frames
        ]
        _save_prefilled_frames(source_analyser, project, sources, source, updated)
        st.success("Prefill saved to frame-index.json. Review the suggestions before publication.")
        st.rerun()
    if local_columns[1].button("Prefill and save all empty frame fields", key=f"prefill_all_{source.source_id}"):
        updated = prefill_missing_frame_fields(
            frames,
            source,
            project,
            st.session_state.get("answers"),
            replace_existing=replace_local,
        )
        _save_prefilled_frames(source_analyser, project, sources, source, updated)
        st.success("Prefill saved to frame-index.json. Review the suggestions before publication.")
        st.rerun()
    _render_ai_frame_prefill(source_analyser, project, sources, source, frames, frame_options)


def _render_ai_frame_prefill(
    source_analyser: SourceAnalyser,
    project: ContentProject,
    sources: list[SourceRecord],
    source: SourceRecord,
    frames: list[FrameRecord],
    frame_options: dict[str, str],
) -> None:
    """Render an explicit-consent OpenRouter vision prefill workflow."""
    config = source_analyser.project_service.config
    with st.expander("Optional AI frame prefill", expanded=False):
        st.warning("This sends only the selected extracted frame images and safe project text to OpenRouter. It never sends the original video or local file paths.")
        status = get_model_catalog_status(config.openrouter_catalog_cache_path)
        st.caption(
            f"OpenRouter key detected: {'yes' if config.openrouter_api_key else 'no'} | "
            f"Catalogue: {status['availability']} | Freshness: {status['freshness']} | Models: {status['model_count']}"
        )
        if status.get("warning"):
            st.info(status["warning"])
        if st.button("Refresh model catalogue", key=f"refresh_vision_catalog_{source.source_id}"):
            catalog = fetch_openrouter_models(config)
            if catalog.get("fetch_status") == "ok":
                save_model_catalog_cache(config.openrouter_catalog_cache_path, catalog)
                st.success(f"Catalogue refreshed with {catalog.get('model_count', 0)} models.")
                st.rerun()
            else:
                st.error("The OpenRouter model catalogue could not be refreshed.")
        catalog = status.get("catalog")
        recommendation = advise_vision_model(catalog)
        recommended_id = recommendation.selected_model_id if recommendation else ""
        model_id = st.text_input(
            "Concrete vision model ID",
            value=recommended_id,
            placeholder="provider/vision-model",
            key=f"vision_model_{source.source_id}",
        ).strip()
        if recommendation:
            st.caption(
                f"Recommended: {recommendation.display_name} | Cost band: {recommendation.estimated_cost_band} | "
                f"Confidence: {recommendation.confidence}"
            )
        if is_router_helper_model_id(model_id):
            st.warning("Choose a concrete vision-capable model. OpenRouter helper/router entries are not suitable here.")
        catalog_models = catalog.get("models", []) if isinstance(catalog, dict) else []
        matched_model = next((model for model in catalog_models if model.get("model_id") == model_id), None)
        vision_capability_confirmed = not catalog_models or bool(matched_model and matched_model.get("vision_input_supported"))
        if model_id and catalog_models and matched_model is None:
            st.warning("This model ID is not in the cached catalogue, so vision capability cannot be confirmed. Refresh the catalogue or choose the recommendation.")
        elif matched_model and not matched_model.get("vision_input_supported"):
            st.warning("The cached catalogue does not identify this model as vision-capable.")
        selected_labels = st.multiselect(
            "Extracted frames to analyse",
            list(frame_options),
            key=f"vision_frames_{source.source_id}",
        )
        max_tokens = st.number_input(
            "Maximum output tokens per frame",
            min_value=300,
            max_value=1000,
            value=600,
            step=100,
            key=f"vision_tokens_{source.source_id}",
        )
        cost_message, cost_is_warning = vision_cost_notice(status, matched_model, len(selected_labels), int(max_tokens))
        if cost_is_warning:
            st.warning(cost_message)
        else:
            st.info(cost_message)
        replace_ai = st.checkbox(
            "Replace existing values with AI suggestions",
            value=False,
            key=f"replace_ai_prefill_{source.source_id}",
        )
        st.warning("Each selected frame makes a separate paid API call. Review the model and frame count before continuing.")
        consent = st.checkbox(
            "I consent to sending the selected extracted frame images to OpenRouter and understand this may incur cost",
            value=False,
            key=f"vision_consent_{source.source_id}",
        )
        can_run = bool(
            config.openrouter_api_key
            and consent
            and selected_labels
            and model_id
            and not is_router_helper_model_id(model_id)
            and vision_capability_confirmed
        )
        if st.button("Run AI frame prefill", disabled=not can_run, key=f"run_vision_prefill_{source.source_id}"):
            selected_ids = {frame_options[label] for label in selected_labels}
            updated_frames: list[FrameRecord] = []
            successes = 0
            failures: list[str] = []
            for frame in frames:
                if frame.frame_id not in selected_ids:
                    updated_frames.append(frame)
                    continue
                result = analyse_frame_with_vision_model(config, model_id, frame.absolute_path, project, frame, int(max_tokens))
                if not result.get("parsed_successfully"):
                    updated_frames.append(frame)
                    failures.append(f"{frame.file_name}: {result.get('error') or 'analysis failed'}")
                    continue
                updated = apply_ai_frame_prefill(frame, result.get("analysis"), model_id, replace_existing=replace_ai)
                updated_frames.append(updated)
                source_analyser.project_service.upsert_frame_analysis_asset_log(
                    project,
                    updated,
                    model_id,
                    recommendation.estimated_cost_band if recommendation and recommendation.selected_model_id == model_id else "unknown",
                )
                successes += 1
            _save_prefilled_frames(source_analyser, project, sources, source, updated_frames)
            if successes:
                st.success(f"AI prefill saved for {successes} frame(s). Human review is required.")
            for failure in failures:
                st.error(failure)
            if successes:
                st.rerun()


def vision_cost_notice(status: dict[str, object], model: dict[str, object] | None, frame_count: int, max_tokens: int) -> tuple[str, bool]:
    """Return a pre-consent AI vision cost notice and whether it is a warning."""
    if status.get("freshness") != "fresh" or status.get("availability") != "available":
        return "Cost estimate unavailable or stale. Refresh model catalogue before using paid analysis.", True
    if model is None:
        return "Cost estimate unavailable for this selected model. Refresh model catalogue before using paid analysis.", True
    if frame_count <= 0:
        return "Select extracted frames to see a rough paid-analysis estimate.", False
    estimate = estimate_model_cost_from_catalog(model, input_tokens=800 * frame_count, output_tokens=max_tokens * frame_count)
    image_price = model.get("pricing_image")
    image_cost = float(image_price or 0.0) * frame_count if image_price is not None else 0.0
    if not estimate["pricing_available"] and image_price is None:
        return "Cost estimate unavailable for this selected model. Refresh model catalogue before using paid analysis.", True
    token_cost = float(estimate["estimated_cost"] or 0.0)
    total_cost = token_cost + image_cost
    cost_band = estimate["cost_band"] if estimate["pricing_available"] else "unknown"
    return f"Rough estimate for {frame_count} frame(s): ${total_cost:.6f} ({cost_band}).", False


def _save_prefilled_frames(
    source_analyser: SourceAnalyser,
    project: ContentProject,
    sources: list[SourceRecord],
    source: SourceRecord,
    frames: list[FrameRecord],
) -> None:
    """Persist frame prefills and related project/source metadata."""
    if source.frame_index_path is None:
        return
    save_frame_index(source.source_id, source.frame_index_path, frames)
    source.selected_frame_count = selected_frame_count(frames)
    _persist_video_frame_state(source_analyser, project, sources)


def _frame_prefill_status(frame: FrameRecord) -> str:
    """Return a compact provenance and review status for one frame."""
    source = frame.prefill_source.replace("_", " ") if frame.prefill_source else "none"
    model = f" | Model: {frame.prefill_model}" if frame.prefill_model else ""
    confidence = f" | Confidence: {frame.prefill_confidence}" if frame.prefill_confidence else ""
    review = " | Human review required" if frame.needs_human_review else ""
    return f"Prefill: {source}{model}{confidence}{review}"


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


def _apply_frame_preset(frame: FrameRecord, preset: str) -> FrameRecord:
    """Apply a local frame-description preset selected by the user."""
    if preset == "Use as opening hero":
        return frame.model_copy(update={"selected_role": FrameRole.HERO_FRAME, "recommended_use": "opening visual reference"})
    if preset == "Use as background":
        return frame.model_copy(update={"selected_role": FrameRole.POSSIBLE_BACKGROUND, "recommended_use": "background texture or atmosphere"})
    if preset == "Needs review":
        return frame.model_copy(update={"selected_role": FrameRole.NEEDS_REVIEW, "historical_or_brand_risk": "needs review before generation"})
    if preset == "Do not use":
        return frame.model_copy(
            update={
                "selected_role": FrameRole.DO_NOT_USE,
                "recommended_use": "do not use",
                "avoid_using_for": "generation or publication",
            }
        )
    return frame


def _persist_video_frame_state(source_analyser: SourceAnalyser, project: ContentProject, sources: list[SourceRecord]) -> None:
    """Persist source metadata after frame extraction or selection."""
    source_analyser.project_service.save_source_index(project, sources)
    source_analyser.project_service.save_project(project, sources, st.session_state.get("content_pack"), st.session_state.get("answers"))
