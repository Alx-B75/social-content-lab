"""Content pack preview and export panel for Social Content Lab."""

import streamlit as st

from src.models.planning import ClarifyingAnswers, ContentPack, WorkflowRecommendation
from src.models.project import ContentProject
from src.models.source import SourceRecord
from src.services.content_pack_builder import ContentPackBuilder


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
    if recommendation is None:
        st.info("Generate a recommendation before building the content pack.")
        return current_pack

    if st.button("Generate and save content pack"):
        try:
            current_pack = content_pack_builder.build(project, sources, answers, recommendation)
        except OSError as error:
            st.error(f"Could not save content pack: {error}")
            return current_pack
        st.success("Content pack saved to the project folder.")

    if current_pack is None:
        st.info("Generate the content pack to preview and export files.")
        return None

    _render_pack_preview(current_pack)
    st.header("6. Save/export files")
    st.success("Files are saved locally in the project folder.")
    st.code(str(project.project_path))
    st.write("Created files: brief.md, script.md, storyboard.md, prompts.md, captions.md, asset-log.csv, project.json, sources/source-index.json")
    return current_pack


def _render_pack_preview(content_pack: ContentPack) -> None:
    """Render a readable preview of the generated content pack."""
    st.subheader("Core message")
    st.write(content_pack.core_message)
    st.subheader("Target platform and format")
    st.write(f"{content_pack.target_platform} · {content_pack.recommended_format}")
    st.subheader("Script outline")
    for line in content_pack.script_outline:
        st.write(f"- {line}")
    st.subheader("Shot list")
    for shot in content_pack.shot_list:
        st.write(f"- {shot}")
    st.subheader("Image prompt")
    st.write(content_pack.image_prompt)
    st.subheader("Video prompts")
    for prompt in content_pack.video_prompts:
        st.write(f"- {prompt}")
    st.subheader("Caption drafts")
    for caption in content_pack.caption_drafts:
        st.text_area("Caption", caption, height=90)
    st.subheader("Asset checklist")
    for item in content_pack.asset_checklist:
        st.write(f"- {item}")
    st.subheader("Risk notes")
    for note in content_pack.risk_notes:
        st.write(f"- {note}")
    st.subheader("Next actions")
    for action in content_pack.next_actions:
        st.write(f"- {action}")
