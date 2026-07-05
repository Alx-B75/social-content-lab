"""Streamlit panel for controlled video generation."""

import json

import streamlit as st

from src.models.planning import ClarifyingAnswers, ContentPack
from src.models.project import ContentProject
from src.models.source import FrameRecord, SourceRecord
from src.services.video_generation import (
    VideoGenerationRequest,
    default_negative_prompt,
    default_video_generation_mode,
    discover_selected_video_reference_frames,
    discover_video_prompt_sources,
    generate_video_asset,
    validate_video_generation_request,
)
from src.services.video_generation_providers import IMAGE_TO_VIDEO, TEXT_TO_VIDEO, collect_video_model_capabilities, default_video_providers
from src.services.video_model_advisor import manual_override_warnings, recommend_video_model


def render_video_generation_panel(
    project: ContentProject,
    sources: list[SourceRecord],
    answers: ClarifyingAnswers | None,
    content_pack: ContentPack | None,
) -> None:
    """Render the Generate Video workflow."""
    st.header("Generate Video")
    st.caption("Controlled MVP for reviewed prompts, selected frame references, model recommendation, explicit consent, and local output logging.")

    capabilities = collect_video_model_capabilities()
    if not any(capability.configured and capability.implemented and not capability.is_mock for capability in capabilities):
        st.info("Real video provider not configured yet.")

    custom_prompt = st.text_area("Custom prompt", "", height=120)
    prompt_sources = discover_video_prompt_sources(project, custom_prompt)
    if not prompt_sources:
        st.warning("No prompt source found yet. Export final prompts, generate a prompt pack, or enter a custom prompt.")
        return

    prompt_labels = [source.label for source in prompt_sources]
    selected_prompt_label = st.selectbox("Prompt source", prompt_labels)
    prompt_source = prompt_sources[prompt_labels.index(selected_prompt_label)]
    with st.expander("Selected prompt preview", expanded=True):
        st.text_area("Prompt preview", prompt_source.text, height=220, disabled=True)

    selected_frames = discover_selected_video_reference_frames(sources)
    default_mode = default_video_generation_mode(selected_frames)
    mode_labels = ["image-to-video", "text-to-video"]
    mode_values = [IMAGE_TO_VIDEO, TEXT_TO_VIDEO]
    mode_label = st.radio("Generation mode", mode_labels, index=mode_values.index(default_mode), horizontal=True)
    mode = mode_values[mode_labels.index(mode_label)]

    reference_frame = _render_reference_frame_selector(selected_frames) if mode == IMAGE_TO_VIDEO else None
    if mode == IMAGE_TO_VIDEO and reference_frame is None:
        st.warning("Image-to-video needs one selected frame reference. Switch to text-to-video or select/review frames first.")

    duration_default = _default_duration(content_pack, answers)
    duration_seconds = st.number_input("Duration seconds", min_value=1, max_value=30, value=duration_default, step=1)
    aspect_ratio = st.selectbox("Aspect ratio", ["9:16", "1:1", "16:9", "4:5"], index=_aspect_index(_default_aspect_ratio(content_pack, answers)))
    negative_prompt = st.text_area("Negative prompt", default_negative_prompt(content_pack.risk_notes if content_pack else [], answers.avoid_aesthetics if answers else None), height=100)

    preference = st.selectbox("User preference", ["cheapest sensible", "balanced", "quality-first"], index=1)
    recommendation_key = f"video_generation_recommendation_{project.project_id}"
    if st.button("Recommend video model"):
        st.session_state[recommendation_key] = recommend_video_model(
            project=project,
            answers=answers,
            content_pack=content_pack,
            prompt_text=prompt_source.text,
            selected_frames=selected_frames,
            user_preference=preference,
            requested_mode=mode,
            duration_seconds=int(duration_seconds),
            aspect_ratio=aspect_ratio,
            capabilities=capabilities,
        )
    recommendation = st.session_state.get(recommendation_key)
    if recommendation:
        _render_recommendation(recommendation)

    capability_labels = [f"{capability.display_name} ({capability.provider_name}/{capability.model_name})" for capability in capabilities]
    default_capability_index = _default_capability_index(capabilities, recommendation)
    selected_capability_label = st.selectbox("Provider/model", capability_labels, index=default_capability_index)
    selected_capability = capabilities[capability_labels.index(selected_capability_label)]
    override_warnings = manual_override_warnings(selected_capability, mode, int(duration_seconds), aspect_ratio)
    for warning in override_warnings:
        st.warning(warning)

    if selected_capability.is_mock:
        st.info("Mock provider selected. It does not create a real provider-generated video and does not spend money.")
    else:
        st.warning("This may send prompts and selected reference images to the selected video model/provider and may incur cost.")
    consent_checked = st.checkbox(
        "I understand this may incur cost and may send selected inputs to the provider.",
        disabled=selected_capability.is_mock,
        value=False,
    )

    request = VideoGenerationRequest(
        provider_name=selected_capability.provider_name,
        model_name=selected_capability.model_name,
        mode=mode,
        prompt_source_label=prompt_source.label,
        prompt_source_id=prompt_source.source_id,
        prompt=prompt_source.text,
        negative_prompt=negative_prompt,
        reference_frame=reference_frame,
        duration_seconds=int(duration_seconds),
        aspect_ratio=aspect_ratio,
        consent_checked=consent_checked,
    )
    blocking_errors = validate_video_generation_request(request, selected_capability)
    for error in blocking_errors:
        st.error(error)
    if st.button("Generate video", disabled=bool(blocking_errors)):
        result = generate_video_asset(
            project=project,
            request=request,
            advisor_recommendation=recommendation,
            providers=default_video_providers(),
            capabilities=capabilities,
        )
        if result.status == "failed":
            st.error(result.error_message or "Video generation failed.")
        else:
            st.success(f"Video generation status: {result.status}")
        if result.output_path:
            st.write(f"Output: `{result.output_path.relative_to(project.project_path).as_posix()}`")
        st.write(f"Metadata: `{result.metadata_path.relative_to(project.project_path).as_posix()}`")
        with st.expander("Debug metadata", expanded=False):
            st.json(json.loads(result.metadata_path.read_text(encoding="utf-8")))


def _render_reference_frame_selector(frames: list[FrameRecord]) -> FrameRecord | None:
    """Render selected frame choices without exposing absolute paths."""
    if not frames:
        return None
    labels = [_frame_label(frame) for frame in frames]
    selected_label = st.selectbox("Reference frame", labels)
    frame = frames[labels.index(selected_label)]
    columns = st.columns([1, 2])
    if frame.absolute_path.exists():
        columns[0].image(str(frame.absolute_path), caption=frame.file_name, width="stretch")
    else:
        columns[0].write(frame.file_name)
    columns[1].write(f"Role: {frame.selected_role.value.replace('_', ' ')}")
    if frame.description:
        columns[1].write(f"Description: {frame.description}")
    columns[1].write(f"Human review required: {'yes' if frame.needs_human_review else 'no'}")
    return frame


def _render_recommendation(recommendation: object) -> None:
    """Render the recommendation card."""
    with st.expander("Video model recommendation", expanded=True):
        st.write(f"Route: `{recommendation.recommended_mode.replace('_', '-')}`")
        st.write(f"Provider/model: `{recommendation.provider_model_id}`")
        st.write(f"Cost estimate: {recommendation.cost_estimate}")
        _write_list("Why this route/model", recommendation.reason)
        _write_list("Known limitations", recommendation.known_limitations)
        _write_list("Inputs that would be sent", recommendation.inputs_that_would_be_sent)
        _write_list("Risk and review notes", recommendation.risk_notes)
        _write_list("Warnings", recommendation.warnings)


def _write_list(label: str, values: list[str]) -> None:
    """Render a compact list."""
    st.markdown(f"**{label}**")
    if not values:
        st.write("- None")
        return
    for value in values:
        st.write(f"- {value}")


def _frame_label(frame: FrameRecord) -> str:
    """Return a safe frame label."""
    return f"{frame.file_name} - {frame.selected_role.value.replace('_', ' ')} - {frame.frame_id}"


def _default_duration(content_pack: ContentPack | None, answers: ClarifyingAnswers | None) -> int:
    """Return a sensible default duration."""
    duration = None
    if content_pack and content_pack.resolved_duration_seconds:
        duration = content_pack.resolved_duration_seconds
    elif answers and answers.resolved_duration_seconds:
        duration = answers.resolved_duration_seconds
    elif answers and answers.target_length_seconds:
        duration = answers.target_length_seconds
    return int(duration) if duration else 10


def _default_aspect_ratio(content_pack: ContentPack | None, answers: ClarifyingAnswers | None) -> str:
    """Return a sensible default aspect ratio."""
    if content_pack and content_pack.resolved_aspect_ratio:
        return content_pack.resolved_aspect_ratio
    if answers and answers.resolved_aspect_ratio:
        return answers.resolved_aspect_ratio
    if answers and answers.aspect_ratio:
        return answers.aspect_ratio
    return "9:16"


def _aspect_index(aspect_ratio: str) -> int:
    """Return the aspect-ratio option index."""
    options = ["9:16", "1:1", "16:9", "4:5"]
    return options.index(aspect_ratio) if aspect_ratio in options else 0


def _default_capability_index(capabilities: list[object], recommendation: object | None) -> int:
    """Return the provider/model default index."""
    if recommendation is None:
        return 0
    for index, capability in enumerate(capabilities):
        if capability.provider_name == recommendation.provider_name and capability.model_name == recommendation.model_name:
            return index
    return 0
