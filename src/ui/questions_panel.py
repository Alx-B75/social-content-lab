"""Clarifying questions panel for Social Content Lab."""

from typing import Any

import streamlit as st

from src.models.planning import ClarifyingAnswers, CostBand, Question, QuestionGroup
from src.models.project import ContentProject
from src.models.source import SourceRecord, SourceType
from src.services.planning_defaults import infer_aspect_ratio, normalize_clarifying_answers, resolve_aspect_ratio, resolve_duration_seconds


def render_questions_panel(
    question_groups: list[QuestionGroup],
    current_answers: ClarifyingAnswers,
    project: ContentProject,
    sources: list[SourceRecord],
) -> ClarifyingAnswers:
    """Render grouped clarifying questions and return collected answers."""
    st.header("3. Clarifying questions")
    current_answers = normalize_clarifying_answers(current_answers, project)
    if st.session_state.get("answers_saved"):
        st.success("Clarifying answers loaded.")
    values = current_answers.model_dump()
    values["resolved_duration_seconds"] = resolve_duration_seconds(project, current_answers)
    values["inferred_aspect_ratio"] = infer_aspect_ratio(values.get("platform"), values.get("output_format"))
    values["resolved_aspect_ratio"] = resolve_aspect_ratio(current_answers)
    st.caption(f"Inferred aspect ratio: {values['inferred_aspect_ratio']}")
    with st.form("clarifying_questions_form"):
        for group in question_groups:
            with st.expander(group.title, expanded=True):
                for question in group.questions:
                    values[question.key] = _render_question(question, values.get(question.key))
                if group.title == "Platform and format":
                    inferred = infer_aspect_ratio(values.get("platform"), values.get("output_format"))
                    st.info(f"Current inferred aspect ratio: {inferred}")
        submitted = st.form_submit_button("Save answers")

    if submitted:
        values["aspect_ratio_override"] = None if values.get("aspect_ratio_override") == "Use inferred default" else values.get("aspect_ratio_override")
        values["inferred_aspect_ratio"] = infer_aspect_ratio(values.get("platform"), values.get("output_format"))
        try:
            candidate_answers = ClarifyingAnswers(**values)
            values["aspect_ratio"] = resolve_aspect_ratio(candidate_answers)
            values["resolved_aspect_ratio"] = values["aspect_ratio"]
            values["resolved_duration_seconds"] = resolve_duration_seconds(project, candidate_answers)
            answers = ClarifyingAnswers(**values)
        except ValueError as error:
            st.error(f"Could not save answers: {error}")
            return current_answers
        st.session_state["answers_saved"] = True
        st.success("Clarifying answers saved.")
        _render_saved_answer_warnings(project, sources, answers)
        return answers

    return current_answers


def _render_question(question: Question, current_value: Any) -> Any:
    """Render a single question based on its input type."""
    label, help_text = _label_and_help(question)
    if question.input_type == "text":
        return st.text_input(label, value=current_value or "", key=f"q_{question.key}", help=help_text)
    if question.input_type == "text_area":
        return st.text_area(label, value=current_value or "", key=f"q_{question.key}", height=100, help=help_text)
    if question.input_type == "select":
        options = [""] + question.options
        selected_value = current_value.value if isinstance(current_value, CostBand) else current_value
        if question.key == "aspect_ratio_override" and not selected_value:
            selected_value = "Use inferred default"
        index = options.index(selected_value) if selected_value in options else 0
        return st.selectbox(label, options, index=index, key=f"q_{question.key}", help=help_text) or None
    if question.input_type == "number":
        if question.key == "target_length_seconds":
            current_text = str(current_value) if current_value else ""
            value = st.text_input(label, value=current_text, placeholder="Not applicable", key=f"q_{question.key}", help=help_text)
            if not value.strip():
                return None
            try:
                return int(value)
            except ValueError:
                st.warning("Target length must be a whole number of seconds.")
                return current_value
        minimum = 1
        default_value = int(current_value or 1)
        value = st.number_input(label, min_value=minimum, value=default_value, step=1, key=f"q_{question.key}", help=help_text)
        return int(value) if value else None
    if question.input_type == "checkbox":
        return st.checkbox(label, value=bool(current_value), key=f"q_{question.key}", help=help_text)
    if question.input_type == "multiselect":
        current_list = current_value or []
        return st.multiselect(label, question.options, default=current_list, key=f"q_{question.key}", help=help_text)
    return st.text_input(label, value=current_value or "", key=f"q_{question.key}", help=help_text)


def _render_saved_answer_warnings(project: ContentProject, sources: list[SourceRecord], answers: ClarifyingAnswers) -> None:
    """Render validation warnings after answers are saved."""
    has_video_source = any(source.source_type == SourceType.VIDEO for source in sources)
    if answers.source_use == "copy closely" and has_video_source:
        st.warning("Copying a video source closely requires keyframe extraction and rights review before generation.")
    if answers.source_use == "copy closely" and not answers.rights_constraints:
        st.warning("Licensing status is unclear. Add rights constraints or use the source only as inspiration/reference context.")
    if not project.director_instructions.strip():
        st.warning("Director instructions are empty, so defaults may be generic.")


def _label_and_help(question: Question) -> tuple[str, str | None]:
    """Return a short field label and optional help text."""
    labels = {
        "main_point": "Main point",
        "intent": "Purpose",
        "call_to_action": "Call to action",
        "platform": "Platform",
        "output_format": "Format",
        "aspect_ratio_override": "Aspect ratio override",
        "target_length_seconds": "Target length",
        "include_voiceover": "Voiceover",
        "include_subtitles": "Subtitles",
        "include_on_screen_text": "On-screen text",
        "scene_structure": "Scene structure",
        "tone": "Tone",
        "brand_rules": "Brand rules",
        "avoid_aesthetics": "Avoid",
        "source_use": "Source use",
        "rights_constraints": "Rights constraints",
        "sensitive_materials": "Sensitive material",
        "video_source_treatment": "Video source treatment",
        "budget_priority": "Budget priority",
        "quality_level": "Quality level",
        "ai_video_acceptable": "AI video acceptable",
        "draft_variations": "Draft variations",
        "maximum_cost_band": "Maximum cost band",
        "needed_outputs": "Needed outputs",
        "include_captions_hashtags": "Captions and hashtags",
        "editing_destination": "Editing destination",
    }
    return labels.get(question.key, question.prompt), question.prompt
