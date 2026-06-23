"""Content pack preview and export panel for Social Content Lab."""

import html

import streamlit as st

from src.models.planning import ClarifyingAnswers, ContentPack, WorkflowRecommendation
from src.models.project import ContentProject
from src.models.source import FrameRecord, FrameRole, SourceRecord
from src.services.content_pack_builder import ContentPackBuilder
from src.services.frame_summary import grouped_frame_references, load_frame_references
from src.services.planning_defaults import normalize_clarifying_answers
from src.ui.llm_planning_panel import render_llm_planning_panel
from src.ui.review_pack_panel import render_review_pack_panel


def render_content_pack_panel(
    content_pack_builder: ContentPackBuilder,
    project: ContentProject,
    sources: list[SourceRecord],
    answers: ClarifyingAnswers,
    recommendation: WorkflowRecommendation | None,
    current_pack: ContentPack | None,
) -> ContentPack | None:
    """Render content pack generation and preview controls."""
    st.header("5. Content pack preview")
    answers = normalize_clarifying_answers(answers, project)
    st.session_state.answers = answers
    if recommendation is None and current_pack is None:
        st.warning("Generate a recommendation before building the content pack, or load a saved project that already has one.")
        return current_pack

    if recommendation is not None and st.button("Generate and save content pack"):
        try:
            current_pack = content_pack_builder.build(project, sources, answers, recommendation)
        except OSError as error:
            st.error(f"Could not save content pack: {error}")
            return current_pack
        st.success("Content pack saved.")
        _render_output_location(project, ["brief.md", "script.md", "storyboard.md", "prompts.md", "captions.md"])

    if current_pack is None:
        st.info("Generate the content pack to preview and export files.")
        if recommendation is not None:
            render_llm_planning_panel(content_pack_builder.project_service.config, content_pack_builder.project_service, project, sources, answers, recommendation)
        return None

    current_pack = _render_amend_pack_form(content_pack_builder, project, sources, current_pack)
    _render_pack_preview(current_pack, sources)
    st.header("6. Save/export files")
    st.success("Files are saved locally.")
    _render_output_location(project, ["brief.md", "script.md", "storyboard.md", "prompts.md", "captions.md", "asset-log.csv", "project.json", "sources/source-index.json"])
    st.write("Created files: brief.md, script.md, storyboard.md, prompts.md, captions.md, asset-log.csv, project.json, sources/source-index.json")
    _render_file_previews(content_pack_builder, project)
    render_llm_planning_panel(content_pack_builder.project_service.config, content_pack_builder.project_service, project, sources, st.session_state.get("answers", answers), recommendation)
    render_review_pack_panel(project)
    return current_pack


def _render_output_location(project: ContentProject, filenames: list[str]) -> None:
    """Render copy-friendly local output path details."""
    st.markdown("**Project folder**")
    st.code(str(project.project_path))
    st.markdown("**Generated files**")
    for filename in filenames:
        st.write(f"- {filename}")


def _render_amend_pack_form(
    content_pack_builder: ContentPackBuilder,
    project: ContentProject,
    sources: list[SourceRecord],
    content_pack: ContentPack,
) -> ContentPack:
    """Render an editable form for amending a loaded or generated content pack."""
    with st.expander("Amend content pack", expanded=False):
        with st.form("amend_content_pack_form"):
            core_message = st.text_area("Core message", content_pack.core_message, height=80)
            target_platform = st.text_input("Target platform", content_pack.target_platform)
            recommended_format = st.text_input("Recommended format", content_pack.recommended_format)
            resolved_aspect_ratio = st.text_input("Resolved aspect ratio", content_pack.resolved_aspect_ratio or "")
            resolved_duration_text = st.text_input(
                "Resolved duration seconds",
                str(content_pack.resolved_duration_seconds) if content_pack.resolved_duration_seconds else "",
                placeholder="Not applicable",
            )
            resolved_call_to_action = st.text_input("Resolved call to action", content_pack.resolved_call_to_action or "")
            script_outline = st.text_area("Script outline", _join_lines(content_pack.script_outline), height=180)
            shot_list = st.text_area("Shot list", _join_lines(content_pack.shot_list), height=180)
            image_prompt = st.text_area("Image prompt", content_pack.image_prompt, height=110)
            video_prompts = st.text_area("Video prompts", _join_lines(content_pack.video_prompts), height=150)
            caption_drafts = st.text_area("Caption drafts", _join_blocks(content_pack.caption_drafts), height=180)
            asset_checklist = st.text_area("Asset checklist", _join_lines(content_pack.asset_checklist), height=130)
            risk_notes = st.text_area("Risk notes", _join_lines(content_pack.risk_notes), height=130)
            next_actions = st.text_area("Next actions", _join_lines(content_pack.next_actions), height=130)
            submitted = st.form_submit_button("Save amended pack")
        if not submitted:
            return content_pack
        amended_pack = ContentPack(
            core_message=core_message.strip(),
            target_platform=target_platform.strip(),
            recommended_format=recommended_format.strip(),
            resolved_aspect_ratio=resolved_aspect_ratio.strip() or None,
            resolved_duration_seconds=_optional_int(resolved_duration_text),
            resolved_call_to_action=resolved_call_to_action.strip() or None,
            script_outline=_split_lines(script_outline),
            shot_list=_split_lines(shot_list),
            image_prompt=image_prompt.strip(),
            video_prompts=_split_lines(video_prompts),
            caption_drafts=_split_blocks(caption_drafts),
            asset_checklist=_split_lines(asset_checklist),
            risk_notes=_split_lines(risk_notes),
            next_actions=_split_lines(next_actions),
        )
        content_pack_builder.project_service.save_content_pack(project, sources, amended_pack, st.session_state.get("answers"))
        st.session_state["content_pack"] = amended_pack
        st.success("Amended content pack saved.")
        return amended_pack


def _render_pack_preview(content_pack: ContentPack, sources: list[SourceRecord]) -> None:
    """Render a readable preview of the generated content pack."""
    _render_overview_block(content_pack)
    _render_selected_frame_references(sources)
    _render_list_block("Script outline", content_pack.script_outline)
    _render_list_block("Shot list", content_pack.shot_list)
    with st.expander("Image prompt", expanded=True):
        _copy_box(content_pack.image_prompt)
    with st.expander("Video prompts", expanded=True):
        for index, prompt in enumerate(content_pack.video_prompts, 1):
            st.text_area(f"Video prompt {index}", prompt, height=95, key=f"video_prompt_preview_{index}")
    with st.expander("Caption drafts", expanded=True):
        for index, caption in enumerate(content_pack.caption_drafts, 1):
            st.text_area(f"Caption {index}", caption, height=105, key=f"caption_preview_{index}")
    _render_list_block("Asset checklist", content_pack.asset_checklist)
    with st.expander("Risk notes", expanded=False):
        _render_plain_list(content_pack.risk_notes)
    _render_list_block("Next actions", content_pack.next_actions)


def _render_file_previews(content_pack_builder: ContentPackBuilder, project: ContentProject) -> None:
    """Render copy-friendly file previews and download buttons."""
    with st.expander("Generated markdown files", expanded=False):
        for filename in ["brief.md", "script.md", "storyboard.md", "prompts.md", "captions.md"]:
            content = content_pack_builder.project_service.read_project_file(project, filename)
            st.markdown(f"**{filename}**")
            st.text_area(f"{filename} preview", content, height=240, key=f"file_preview_{filename}")
            st.download_button(
                f"Download {filename}",
                data=content,
                file_name=filename,
                mime="text/markdown",
                key=f"download_{filename}",
            )


def _render_overview_block(content_pack: ContentPack) -> None:
    """Render the high-level content pack summary."""
    duration = f"{content_pack.resolved_duration_seconds} seconds" if content_pack.resolved_duration_seconds else "Not applicable"
    values = [
        ("Core message", content_pack.core_message),
        ("Platform", content_pack.target_platform),
        ("Format", content_pack.recommended_format),
        ("Aspect ratio", content_pack.resolved_aspect_ratio or "Not applicable"),
        ("Duration", duration),
        ("CTA", content_pack.resolved_call_to_action or "Not specified"),
    ]
    st.subheader("Content pack summary")
    for label, value in values:
        st.markdown(
            "<div class='scl-card'>"
            f"<span class='scl-card-label'>{html.escape(label)}</span>"
            f"<span class='scl-card-value'>{html.escape(value)}</span>"
            "</div>",
            unsafe_allow_html=True,
        )


def _render_selected_frame_references(sources: list[SourceRecord]) -> None:
    """Render selected frame references grouped by role."""
    frames = load_frame_references(sources)
    if not frames:
        return
    st.subheader("Selected frame references")
    grouped = grouped_frame_references(frames)
    role_order = [
        (FrameRole.HERO_FRAME, "Hero frame"),
        (FrameRole.VISUAL_REFERENCE, "Visual references"),
        (FrameRole.POSSIBLE_BACKGROUND, "Backgrounds"),
        (FrameRole.NEEDS_REVIEW, "Needs review"),
        (FrameRole.DO_NOT_USE, "Do not use"),
    ]
    for role, label in role_order:
        role_frames = grouped.get(role, [])
        if not role_frames:
            continue
        st.markdown(f"**{label}**")
        for frame in role_frames:
            _render_frame_reference(frame)


def _render_frame_reference(frame: FrameRecord) -> None:
    """Render one selected frame reference with available description metadata."""
    columns = st.columns([1, 2])
    if frame.absolute_path.exists():
        columns[0].image(str(frame.absolute_path), caption=frame.file_name, width="stretch")
    else:
        columns[0].write(frame.file_name)
    details = [
        ("Role", frame.selected_role.value.replace("_", " ")),
        ("Timestamp", _frame_timestamp(frame)),
        ("Description", frame.description),
        ("Subject", frame.visible_subject),
        ("Setting", frame.setting),
        ("Mood", frame.mood),
        ("Style", frame.visual_style),
        ("On-screen text", frame.on_screen_text),
        ("Recommended use", frame.recommended_use),
        ("Rights", frame.rights_notes),
        ("Risk", frame.historical_or_brand_risk),
        ("Avoid", frame.avoid_using_for),
    ]
    for label, value in details:
        if value:
            columns[1].markdown(f"**{label}:** {value}")
    with st.expander(f"Debug metadata for {frame.file_name}", expanded=False):
        st.json(frame.model_dump(mode="json"))


def _frame_timestamp(frame: FrameRecord) -> str:
    """Return a display timestamp for a selected frame."""
    timestamp = f"{frame.timestamp_seconds:.2f}s" if frame.timestamp_seconds is not None else "unknown"
    return f"{frame.label} at {timestamp}"


def _render_list_block(title: str, items: list[str]) -> None:
    """Render a list section in a readable block."""
    st.subheader(title)
    st.markdown("<div class='scl-section'>", unsafe_allow_html=True)
    _render_plain_list(items)
    st.markdown("</div>", unsafe_allow_html=True)


def _render_plain_list(items: list[str]) -> None:
    """Render list items with standard markdown bullets."""
    if not items:
        st.write("No items generated.")
        return
    for item in items:
        st.write(f"- {item}")


def _copy_box(value: str) -> None:
    """Render copy-friendly generated text."""
    st.markdown(f"<div class='scl-copy-box'>{html.escape(value)}</div>", unsafe_allow_html=True)


def _join_lines(items: list[str]) -> str:
    """Join list items into one editable line per item."""
    return "\n".join(items)


def _join_blocks(items: list[str]) -> str:
    """Join text blocks with blank lines for editing."""
    return "\n\n".join(items)


def _split_lines(value: str) -> list[str]:
    """Split text into non-empty stripped lines."""
    return [line.strip() for line in value.splitlines() if line.strip()]


def _split_blocks(value: str) -> list[str]:
    """Split text into non-empty blocks separated by blank lines."""
    return [block.strip() for block in value.split("\n\n") if block.strip()]


def _optional_int(value: str) -> int | None:
    """Parse an optional integer value."""
    if not value.strip():
        return None
    try:
        return int(value)
    except ValueError:
        st.warning("Resolved duration must be a whole number. Keeping it blank.")
        return None
