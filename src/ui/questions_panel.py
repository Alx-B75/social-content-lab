"""Clarifying questions panel for Social Content Lab."""

from typing import Any

import streamlit as st

from src.models.planning import ClarifyingAnswers, CostBand, Question, QuestionGroup


def render_questions_panel(question_groups: list[QuestionGroup], current_answers: ClarifyingAnswers) -> ClarifyingAnswers:
    """Render grouped clarifying questions and return collected answers."""
    st.header("3. Clarifying questions")
    values = current_answers.model_dump()
    with st.form("clarifying_questions_form"):
        for group in question_groups:
            st.subheader(group.title)
            for question in group.questions:
                values[question.key] = _render_question(question, values.get(question.key))
        submitted = st.form_submit_button("Save answers")

    if submitted:
        try:
            answers = ClarifyingAnswers(**values)
        except ValueError as error:
            st.error(f"Could not save answers: {error}")
            return current_answers
        st.success("Clarifying answers saved.")
        return answers

    return current_answers


def _render_question(question: Question, current_value: Any) -> Any:
    """Render a single question based on its input type."""
    if question.input_type == "text":
        return st.text_input(question.prompt, value=current_value or "", key=f"q_{question.key}")
    if question.input_type == "text_area":
        return st.text_area(question.prompt, value=current_value or "", key=f"q_{question.key}", height=100)
    if question.input_type == "select":
        options = [""] + question.options
        selected_value = current_value.value if isinstance(current_value, CostBand) else current_value
        index = options.index(selected_value) if selected_value in options else 0
        return st.selectbox(question.prompt, options, index=index, key=f"q_{question.key}") or None
    if question.input_type == "number":
        minimum = 0
        default_value = int(current_value or 0)
        value = st.number_input(question.prompt, min_value=minimum, value=default_value, step=1, key=f"q_{question.key}")
        return int(value) if value else None
    if question.input_type == "checkbox":
        return st.checkbox(question.prompt, value=bool(current_value), key=f"q_{question.key}")
    if question.input_type == "multiselect":
        current_list = current_value or []
        return st.multiselect(question.prompt, question.options, default=current_list, key=f"q_{question.key}")
    return st.text_input(question.prompt, value=current_value or "", key=f"q_{question.key}")
