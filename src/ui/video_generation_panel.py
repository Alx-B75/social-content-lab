"""Streamlit panel for controlled video generation."""

import json
from datetime import datetime, timezone

import streamlit as st

from src.config import AppConfig
from src.models.planning import ClarifyingAnswers, ContentPack
from src.models.project import ContentProject
from src.models.source import FrameRecord, SourceRecord
from src.services.openrouter_video import (
    fetch_openrouter_video_models,
    get_video_model_catalog_status,
    openrouter_request_preview,
    save_video_model_catalog_cache,
)
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

LOW_RISK_OPENROUTER_VIDEO_SMOKE_TEST = {
    "title": "Low-risk OpenRouter video smoke test",
    "prompt": "A calm five-second cinematic shot of a dark teal background with soft moving light, subtle dust particles, premium educational brand atmosphere, no people, no readable text.",
    "negative_prompt": "people, faces, readable text, logos, copyrighted characters, violent imagery, fantasy style, cheap AI look",
    "duration_seconds": 5,
    "mode": TEXT_TO_VIDEO,
    "preference": "cheapest sensible",
}
VIDEO_GENERATION_LOCK_KEY = "video_generation_in_progress"
VIDEO_GENERATION_LAST_RESULT_KEY = "video_generation_last_result"
DUPLICATE_GENERATION_WARNING = "A generation job is already running. Wait for it to finish before submitting another paid request."


def render_video_generation_panel(
    config: AppConfig,
    project: ContentProject,
    sources: list[SourceRecord],
    answers: ClarifyingAnswers | None,
    content_pack: ContentPack | None,
) -> None:
    """Render the Generate Video workflow."""
    st.header("Generate Video")
    st.caption("Controlled MVP for reviewed prompts, selected frame references, model recommendation, explicit consent, and local output logging.")

    video_catalog_status = _render_openrouter_catalog_controls(config)
    video_catalog = video_catalog_status.get("catalog") if video_catalog_status else None
    providers = default_video_providers(config, video_catalog)
    capabilities = collect_video_model_capabilities(providers)
    if not any(capability.configured and capability.implemented and not capability.is_mock for capability in capabilities):
        st.info("Real video provider not configured yet.")

    _render_smoke_test_preset()
    custom_prompt = st.text_area("Custom prompt", key="video_custom_prompt", height=120)
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
    preferred_mode = st.session_state.get("video_generation_mode", default_mode)
    mode_label = st.radio("Generation mode", mode_labels, index=mode_values.index(preferred_mode if preferred_mode in mode_values else default_mode), horizontal=True)
    mode = mode_values[mode_labels.index(mode_label)]

    reference_frame = _render_reference_frame_selector(selected_frames) if mode == IMAGE_TO_VIDEO else None
    if mode == IMAGE_TO_VIDEO and reference_frame is None:
        st.warning("Image-to-video needs one selected frame reference. Switch to text-to-video or select/review frames first.")

    duration_default = int(st.session_state.get("video_duration_seconds", _default_duration(content_pack, answers)))
    duration_seconds = st.number_input("Duration seconds", min_value=1, max_value=30, value=duration_default, step=1)
    aspect_ratio = st.selectbox("Aspect ratio", ["9:16", "1:1", "16:9", "4:5"], index=_aspect_index(_default_aspect_ratio(content_pack, answers)))
    if "video_negative_prompt" not in st.session_state:
        st.session_state["video_negative_prompt"] = default_negative_prompt(content_pack.risk_notes if content_pack else [], answers.avoid_aesthetics if answers else None)
    negative_prompt = st.text_area("Negative prompt", key="video_negative_prompt", height=100)

    preference_options = ["cheapest sensible", "balanced", "quality-first"]
    preferred_preference = st.session_state.get("video_user_preference", "balanced")
    preference = st.selectbox("User preference", preference_options, index=preference_options.index(preferred_preference if preferred_preference in preference_options else "balanced"))
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
    active_lock = active_generation_lock(st.session_state, project.project_id)
    if active_lock:
        st.warning(DUPLICATE_GENERATION_WARNING)
        _render_active_generation(active_lock)
        if st.button("Clear active generation state"):
            clear_generation_lock(st.session_state)
            st.rerun()

    if selected_capability.is_mock:
        st.info("Mock provider selected. It does not create a real provider-generated video and does not spend money.")
    else:
        st.warning("This may send prompts and selected reference images to the selected video model/provider and may incur cost.")
    max_spend_usd = st.number_input("Max test spend USD", min_value=0.01, max_value=25.0, value=1.0, step=0.25, disabled=selected_capability.is_mock)
    preview_request = VideoGenerationRequest(
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
        max_spend_usd=float(max_spend_usd),
    )
    preview = openrouter_request_preview(preview_request, selected_capability, float(max_spend_usd))
    _render_request_preview(preview)
    unknown_cost_acknowledged = st.checkbox(
        "I understand the cost estimate is unavailable.",
        disabled=selected_capability.is_mock or preview["cost_estimate_confidence"] == "known",
        value=False,
    )
    consent_label = "I understand this will submit a real video generation request through OpenRouter and may spend credits."
    if selected_capability.provider_name != "openrouter":
        consent_label = "I understand this may incur cost and may send selected inputs to the provider."
    consent_checked = st.checkbox(consent_label, disabled=selected_capability.is_mock, value=False)

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
        max_spend_usd=float(max_spend_usd),
        unknown_cost_acknowledged=unknown_cost_acknowledged,
    )
    blocking_errors = validate_video_generation_request(request, selected_capability)
    for error in blocking_errors:
        st.error(error)
    button_label = "Generate real video via OpenRouter" if selected_capability.provider_name == "openrouter" else "Generate video"
    button_disabled = bool(blocking_errors) or bool(active_lock and not selected_capability.is_mock)
    if st.button(button_label, disabled=button_disabled):
        if active_generation_lock(st.session_state, project.project_id) and not selected_capability.is_mock:
            st.warning(DUPLICATE_GENERATION_WARNING)
            return
        if not selected_capability.is_mock:
            start_generation_lock(st.session_state, project.project_id, request, selected_capability.display_name)
        with st.status("Generation request submitted.", expanded=True) as status:
            status.write("Validating request.")
            status.write(
                f"Waiting for OpenRouter job status... Model: {selected_capability.provider_name}/{selected_capability.model_name}; "
                f"mode: {mode.replace('_', '-')}; duration: {int(duration_seconds)}s; max spend: ${float(max_spend_usd):.2f}."
            )
            status.write("Submitting job.")
            result = generate_video_asset(
                project=project,
                request=request,
                advisor_recommendation=recommendation,
                providers=providers,
                capabilities=capabilities,
            )
            if result.provider_job_id:
                status.write(f"Job submitted: `{result.provider_job_id}`.")
            status.write("Polling.")
            if result.status == "completed":
                status.write("Completed.")
            if result.output_path:
                status.write("Downloading.")
                status.write(f"Saved: `{result.output_path.relative_to(project.project_path).as_posix()}`.")
            if result.status == "failed":
                status.update(label="Generation failed or timed out.", state="error")
            else:
                status.update(label="Generation completed and saved.", state="complete")
        finish_generation_lock(st.session_state, project.project_id, result)
        if result.status == "failed":
            st.error(result.error_message or "Video generation failed.")
        else:
            st.success(f"Video generation status: {result.status}")
        if result.output_path:
            st.write(f"Output: `{result.output_path.relative_to(project.project_path).as_posix()}`")
        st.write(f"Job/status: `{result.provider_job_id or result.status}`")
        st.write(f"Metadata: `{result.metadata_path.relative_to(project.project_path).as_posix()}`")
        metadata = json.loads(result.metadata_path.read_text(encoding="utf-8"))
        actual_cost = metadata.get("actual_cost")
        if actual_cost is not None and result.provider == "openrouter":
            st.write(f"Actual OpenRouter usage cost: ${float(actual_cost):.6f}")
        with st.expander("Debug metadata", expanded=False):
            st.json(metadata)


def _render_openrouter_catalog_controls(config: AppConfig) -> dict[str, object]:
    """Render OpenRouter video catalogue status and refresh control."""
    with st.expander("OpenRouter video models", expanded=False):
        if not config.openrouter_api_key:
            st.info("Set OPENROUTER_API_KEY to enable OpenRouter video model discovery and real video tests.")
        status = get_video_model_catalog_status(config.openrouter_video_catalog_cache_path)
        st.write(f"Catalogue: {status['availability']} / {status['freshness']} / {status['model_count']} model(s)")
        if status.get("warning"):
            st.warning(str(status["warning"]))
        if st.button("Refresh OpenRouter video models", disabled=not bool(config.openrouter_api_key)):
            catalog = fetch_openrouter_video_models(config)
            save_video_model_catalog_cache(config.openrouter_video_catalog_cache_path, catalog)
            if catalog.get("fetch_status") == "ok":
                st.success(f"Refreshed {catalog.get('model_count', 0)} OpenRouter video model(s).")
            else:
                st.error(f"OpenRouter video catalogue refresh failed: {catalog.get('error_summary', 'unknown error')}")
            st.rerun()
    return status


def _render_smoke_test_preset() -> None:
    """Render the low-risk OpenRouter smoke-test preset."""
    if st.button("Use low-risk OpenRouter video smoke test"):
        st.session_state["video_custom_prompt"] = LOW_RISK_OPENROUTER_VIDEO_SMOKE_TEST["prompt"]
        st.session_state["video_negative_prompt"] = LOW_RISK_OPENROUTER_VIDEO_SMOKE_TEST["negative_prompt"]
        st.session_state["video_duration_seconds"] = LOW_RISK_OPENROUTER_VIDEO_SMOKE_TEST["duration_seconds"]
        st.session_state["video_generation_mode"] = LOW_RISK_OPENROUTER_VIDEO_SMOKE_TEST["mode"]
        st.session_state["video_user_preference"] = LOW_RISK_OPENROUTER_VIDEO_SMOKE_TEST["preference"]
        st.rerun()


def _render_request_preview(preview: dict[str, object]) -> None:
    """Render a safe request preview before generation."""
    with st.expander("Request preview", expanded=True):
        st.write(f"Provider/model: `{preview['provider']}/{preview['model']}`")
        st.write(f"Mode: `{str(preview['mode']).replace('_', '-')}`")
        st.write(f"Prompt source: {preview['prompt_source']}")
        st.write(f"Duration: {preview['duration_seconds']} seconds")
        st.write(f"Aspect/resolution: {preview['aspect_ratio']} / {preview.get('resolution') or 'default'}")
        st.write(f"Reference frame will be sent: {'yes' if preview['reference_frame_will_be_sent'] else 'no'}")
        st.write(f"Negative prompt will be sent: {'yes' if preview['negative_prompt_will_be_sent'] else 'no'}")
        if preview["cost_estimate_confidence"] == "known":
            st.write(f"Estimated cost: ${float(preview['estimated_cost']):.4f} ({preview['cost_band']})")
        else:
            st.warning(str(preview["cost_estimate_note"]))
            if preview.get("pricing_hint") is not None:
                st.write(f"Catalogue pricing hint: {preview['pricing_hint']} ({preview['cost_band']})")
        st.write(f"Max test spend: ${float(preview['max_spend_usd']):.2f}")
        if not preview["spend_guard_passed"]:
            st.error("Estimated cost exceeds max test spend.")
        _write_list("Inputs that would be sent", list(preview.get("inputs_sent") or []))


def start_generation_lock(session_state: object, project_id: str, request: VideoGenerationRequest, model_label: str) -> dict[str, object]:
    """Store an active paid-generation lock in session state."""
    lock = {
        "project_id": project_id,
        "provider": request.provider_name,
        "model": request.model_name,
        "model_label": model_label,
        "mode": request.mode,
        "duration_seconds": request.duration_seconds,
        "max_spend_usd": request.max_spend_usd,
        "prompt_source": request.prompt_source_label,
        "started_at": datetime.now(timezone.utc).isoformat(),
        "status": "submitting",
        "job_id": None,
    }
    session_state[VIDEO_GENERATION_LOCK_KEY] = lock
    return lock


def active_generation_lock(session_state: object, project_id: str | None = None) -> dict[str, object] | None:
    """Return active generation lock metadata when present."""
    lock = session_state.get(VIDEO_GENERATION_LOCK_KEY)
    if not isinstance(lock, dict):
        return None
    if project_id and lock.get("project_id") != project_id:
        return None
    return lock


def finish_generation_lock(session_state: object, project_id: str, result: object) -> None:
    """Persist terminal generation result metadata and clear active lock."""
    last_result = {
        "project_id": project_id,
        "provider": getattr(result, "provider", None),
        "model": getattr(result, "model", None),
        "status": getattr(result, "status", None),
        "job_id": getattr(result, "provider_job_id", None),
        "polling_url": getattr(result, "polling_url", None),
        "error_type": getattr(result, "error_type", None),
        "error_message": getattr(result, "error_message", None),
        "metadata_path": str(getattr(result, "metadata_path", "")),
        "output_path": str(getattr(result, "output_path", "")) if getattr(result, "output_path", None) else None,
        "finished_at": datetime.now(timezone.utc).isoformat(),
    }
    session_state[VIDEO_GENERATION_LAST_RESULT_KEY] = last_result
    clear_generation_lock(session_state)


def clear_generation_lock(session_state: object) -> None:
    """Clear the active paid-generation lock."""
    if VIDEO_GENERATION_LOCK_KEY in session_state:
        del session_state[VIDEO_GENERATION_LOCK_KEY]


def duplicate_generation_warning() -> str:
    """Return the duplicate paid-generation warning copy."""
    return DUPLICATE_GENERATION_WARNING


def _render_active_generation(lock: dict[str, object]) -> None:
    """Render active generation metadata without exposing secrets."""
    started_at = lock.get("started_at")
    elapsed = ""
    if started_at:
        try:
            elapsed_seconds = int((datetime.now(timezone.utc) - datetime.fromisoformat(str(started_at))).total_seconds())
            elapsed = f"Elapsed: {elapsed_seconds}s"
        except ValueError:
            elapsed = ""
    st.write(f"Model: `{lock.get('provider')}/{lock.get('model')}`")
    st.write(f"Mode: `{str(lock.get('mode')).replace('_', '-')}`")
    st.write(f"Duration: {lock.get('duration_seconds')} seconds")
    st.write(f"Max spend: ${float(lock.get('max_spend_usd') or 0):.2f}")
    if lock.get("job_id"):
        st.write(f"Job ID: `{lock.get('job_id')}`")
    if elapsed:
        st.write(elapsed)


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
