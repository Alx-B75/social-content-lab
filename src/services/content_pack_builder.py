"""Content pack builder for Social Content Lab."""

from src.models.planning import ClarifyingAnswers, ContentPack, WorkflowRecommendation
from src.models.project import ContentProject
from src.models.source import FrameRecord, FrameRole, SourceRecord, SourceReferenceStrategy, SourceType
from src.services.frame_summary import frame_prompt_detail, frame_risk_notes, load_frame_references, positive_frame_references
from src.services.planning_defaults import label_for_route, resolve_aspect_ratio, resolve_call_to_action, resolve_duration_seconds
from src.services.project_service import ProjectService


class ContentPackBuilder:
    """Generate and persist draft content packs from planning inputs."""

    def __init__(self, project_service: ProjectService) -> None:
        """Initialise the content pack builder with project persistence."""
        self.project_service = project_service

    def build(
        self,
        project: ContentProject,
        sources: list[SourceRecord],
        answers: ClarifyingAnswers,
        recommendation: WorkflowRecommendation,
    ) -> ContentPack:
        """Build a draft content pack from project context and answers."""
        core_message = answers.main_point or project.topic or project.working_title
        target_platform = answers.platform or "multi-platform"
        recommended_format = answers.output_format or label_for_route(recommendation.recommended_workflow_route)
        source_summary = self._source_summary(sources)
        tone = answers.tone or "clear and useful"
        call_to_action = resolve_call_to_action(project, answers)
        resolved_duration = resolve_duration_seconds(project, answers)
        resolved_aspect_ratio = resolve_aspect_ratio(answers)
        frame_references = load_frame_references(sources)
        selected_frames = positive_frame_references(frame_references)
        extracted_frame_warning = self._extracted_frame_warning(sources, selected_frames)
        risk_notes = list(recommendation.warnings)
        if extracted_frame_warning:
            risk_notes.append(extracted_frame_warning)
        risk_notes.extend(frame_risk_notes(frame_references))

        content_pack = ContentPack(
            core_message=core_message,
            target_platform=target_platform,
            recommended_format=recommended_format,
            resolved_aspect_ratio=resolved_aspect_ratio,
            resolved_duration_seconds=resolved_duration,
            resolved_call_to_action=call_to_action,
            script_outline=self._build_script_outline(project, answers, core_message, call_to_action, resolved_duration, selected_frames),
            shot_list=self._build_shot_list(sources, answers, core_message, call_to_action, resolved_duration, selected_frames),
            image_prompt=self._build_image_prompt(project, answers, core_message, source_summary, resolved_aspect_ratio, selected_frames),
            video_prompts=self._build_video_prompts(project, answers, core_message, recommendation, resolved_duration, resolved_aspect_ratio, selected_frames),
            caption_drafts=self._build_captions(project, answers, core_message, call_to_action),
            asset_checklist=self._build_asset_checklist(sources, answers, selected_frames),
            risk_notes=risk_notes,
            next_actions=[
                recommendation.suggested_next_step,
                "Review rights and source-use constraints before generating or publishing assets.",
                "Update asset-log.csv as source and generated assets are selected.",
                *self._frame_next_actions(sources, selected_frames, frame_references),
            ],
        )
        self.project_service.save_content_pack(project, sources, content_pack, answers)
        return content_pack

    def _source_summary(self, sources: list[SourceRecord]) -> str:
        """Summarise sources for generated planning copy."""
        if not sources:
            return "no external sources yet"
        parts = []
        for source in sources:
            label = source.original_filename or source.url or source.manual_description or source.source_id
            detail = f"{source.source_type.value} source {label} via {source.strategy.value}"
            if source.source_type == SourceType.VIDEO and source.duration_seconds:
                detail = f"{detail}, {source.duration_seconds:.1f}s"
            if source.aspect_ratio:
                detail = f"{detail}, {source.aspect_ratio}"
            parts.append(detail)
        return "; ".join(parts)

    def _build_script_outline(
        self,
        project: ContentProject,
        answers: ClarifyingAnswers,
        core_message: str,
        call_to_action: str,
        resolved_duration: int | None,
        selected_frames: list[FrameRecord],
    ) -> list[str]:
        """Build a specific script outline from known project details."""
        topic_line = f"Topic: {project.topic}." if project.topic else f"Working title: {project.working_title}."
        frame_context = self._selected_frame_context(selected_frames)
        if resolved_duration:
            segments = self._timeline_segments(resolved_duration)
            return [
                f"{segments[0]}: Lead with the strongest approved visual from '{project.working_title}' and make the promise clear: {core_message}.{frame_context}",
                f"{segments[1]}: Deliver the core value for {answers.platform or 'the chosen platform'} in a {answers.tone or 'clear'} tone. {topic_line}",
                f"{segments[2]}: Build on the selected visual references or confirmed source details without inventing unsupported claims.",
                f"{segments[3]}: End with the CTA: {call_to_action}",
            ]
        return [
            f"Headline: connect '{project.working_title}' to the message '{core_message}'.",
            f"Body: explain why this matters for {answers.platform or 'the target platform'} using the director instructions as the source of truth.",
            f"Support: include brand/topic context. {topic_line}",
            f"CTA: {call_to_action}",
        ]

    def _build_image_prompt(
        self,
        project: ContentProject,
        answers: ClarifyingAnswers,
        core_message: str,
        source_summary: str,
        resolved_aspect_ratio: str,
        selected_frames: list[FrameRecord],
    ) -> str:
        """Build a draft image prompt."""
        brand = f" for {project.brand_name}" if project.brand_name else ""
        source_use_instruction = self._source_use_instruction(answers)
        avoid = f" Avoid: {self._clean_sentence_fragment(answers.avoid_aesthetics)}." if answers.avoid_aesthetics else ""
        frame_instruction = f" {self._selected_frame_prompt(selected_frames)}" if selected_frames else ""
        return (
            f"Create a {answers.tone or 'clear'} social media visual{brand} about {core_message}. "
            f"{source_use_instruction}: {source_summary}. "
            f"Aspect ratio: {resolved_aspect_ratio}.{frame_instruction}{avoid}"
        )

    def _build_video_prompts(
        self,
        project: ContentProject,
        answers: ClarifyingAnswers,
        core_message: str,
        recommendation: WorkflowRecommendation,
        resolved_duration: int | None,
        resolved_aspect_ratio: str,
        selected_frames: list[FrameRecord],
    ) -> list[str]:
        """Build draft video prompts."""
        length = resolved_duration or 15
        structure = answers.scene_structure or "multiple shots"
        frame_prompt = self._selected_frame_prompt(selected_frames)
        return [
            f"{length}-second {structure} social video for {answers.platform or 'multi-platform'} about '{project.working_title}': {core_message}.",
            f"Use the route {label_for_route(recommendation.recommended_workflow_route)} at {resolved_aspect_ratio}; include subtitles: {answers.include_subtitles}; include on-screen text: {answers.include_on_screen_text}.",
            frame_prompt if frame_prompt else "Use extracted frames only after keyframes are selected and rights are reviewed.",
            f"Keep brand fit for {project.brand_name or 'the project'} and avoid rights-sensitive direct copying unless explicitly cleared.",
        ]

    def _build_captions(
        self,
        project: ContentProject,
        answers: ClarifyingAnswers,
        core_message: str,
        call_to_action: str,
    ) -> list[str]:
        """Build draft caption options."""
        hashtag_tail = " #contentplanning #aivideo #creativeworkflow" if answers.include_captions_hashtags else ""
        brand_intro = f"{project.brand_name}: " if project.brand_name else ""
        hook = self._caption_hook(project, core_message, call_to_action)
        return [
            f"{brand_intro}{hook}\n\n{call_to_action}{hashtag_tail}",
            f"What would you ask next? {core_message}\n\n{call_to_action}{hashtag_tail}",
            f"A short teaser for {project.working_title}: {core_message}\n\n{call_to_action}{hashtag_tail}",
        ]

    def _build_asset_checklist(self, sources: list[SourceRecord], answers: ClarifyingAnswers, selected_frames: list[FrameRecord]) -> list[str]:
        """Build a practical asset checklist."""
        checklist = [
            "Approved project brief",
            "Final script outline",
            "Storyboard or shot list",
            "Brand colours, fonts, and logo files if required",
            "Rights notes for all reference sources",
        ]
        if any(source.source_type.value == "video" for source in sources):
            checklist.extend(["Video keyframes", "Duration and aspect ratio", "Transcript or captions if available"])
        if selected_frames:
            checklist.extend([f"Selected frame: {frame.file_name} ({frame.selected_role.value}) - {frame.recommended_use or 'manual reference'}" for frame in selected_frames])
        if answers.include_voiceover:
            checklist.append("Voiceover script and preferred voice direction")
        if answers.editing_destination and answers.editing_destination != "not needed":
            checklist.append(f"Editing handoff notes for {answers.editing_destination}")
        return checklist

    def _build_shot_list(
        self,
        sources: list[SourceRecord],
        answers: ClarifyingAnswers,
        core_message: str,
        call_to_action: str,
        resolved_duration: int | None,
        selected_frames: list[FrameRecord],
    ) -> list[str]:
        """Build a shot list that respects available source analysis."""
        keyframe_needed = any(source.strategy == SourceReferenceStrategy.KEYFRAME_EXTRACTION_NEEDED for source in sources)
        strongest_visual = self._opening_visual_instruction(selected_frames, keyframe_needed)
        if resolved_duration:
            segments = self._timeline_segments(resolved_duration)
            return [
                f"{segments[0]}: {strongest_visual}; introduce {core_message}.",
                f"{segments[1]}: {self._middle_visual_instruction(selected_frames)} with concise on-screen text for {answers.platform or 'the target platform'}.",
                f"{segments[2]}: use confirmed source details and selected reference descriptions to support the message.",
                f"{segments[3]}: end card with CTA: {call_to_action}",
            ]
        return [
            f"Frame 1: {strongest_visual}; headline the message '{core_message}'.",
            f"Frame 2: {self._middle_visual_instruction(selected_frames)} using only confirmed source details.",
            "Frame 3: add source-backed supporting copy that can be manually checked.",
            f"Frame 4: CTA/end card: {call_to_action}",
        ]

    def _timeline_segments(self, duration_seconds: int) -> list[str]:
        """Create four practical timeline segments for a duration."""
        if duration_seconds <= 4:
            return ["0-1s", "1-2s", f"2-{max(duration_seconds - 1, 2)}s", f"{max(duration_seconds - 1, 2)}-{duration_seconds}s"]
        if duration_seconds == 10:
            return ["0-2s", "2-6s", "6-9s", "9-10s"]
        first_end = max(2, round(duration_seconds * 0.2))
        second_end = max(first_end + 1, round(duration_seconds * 0.6))
        third_end = max(second_end + 1, round(duration_seconds * 0.9))
        if third_end >= duration_seconds:
            third_end = max(second_end + 1, duration_seconds - 1)
        return ["0-" + str(first_end) + "s", f"{first_end}-{second_end}s", f"{second_end}-{third_end}s", f"{third_end}-{duration_seconds}s"]

    def _source_use_instruction(self, answers: ClarifyingAnswers) -> str:
        """Return clear source-use wording for prompts."""
        source_use = (answers.source_use or "inspiration/reference context").lower()
        if "copy" in source_use or "close" in source_use:
            return "Use the uploaded source as a close visual reference only where rights are cleared"
        if "factual" in source_use:
            return "Use the uploaded source for factual and reference context only"
        return "Use the uploaded source as inspiration/reference context"

    def _caption_hook(self, project: ContentProject, core_message: str, call_to_action: str) -> str:
        """Build a deterministic social hook for caption drafts."""
        combined_text = f"{project.working_title} {project.topic or ''} {core_message} {call_to_action}".lower()
        if "shakespeare" in combined_text and "question" in combined_text:
            return "What if Shakespeare could answer back?"
        if "question" in combined_text or "ask" in combined_text:
            return "What would you ask if the story could answer back?"
        if "teaser" in combined_text or "curious" in combined_text:
            return f"What if {project.working_title} was only the beginning?"
        return f"What changes when {core_message} becomes the first thing people see?"

    def _clean_sentence_fragment(self, value: str) -> str:
        """Clean punctuation from a sentence fragment before appending punctuation."""
        return value.strip().rstrip(".!?")

    def _extracted_frame_warning(self, sources: list[SourceRecord], selected_frames: list[FrameRecord]) -> str | None:
        """Return a warning when frames exist but none are selected."""
        if selected_frames:
            return None
        if any(source.frame_count > 0 for source in sources if source.source_type == SourceType.VIDEO):
            return "Frames have been extracted, but no hero/reference frames have been selected."
        return None

    def _selected_frame_context(self, selected_frames: list[FrameRecord]) -> str:
        """Return a short script context sentence for selected frames."""
        hero_frame = next((frame for frame in selected_frames if frame.selected_role == FrameRole.HERO_FRAME), None)
        if hero_frame:
            return f" Open with `{hero_frame.file_name}` ({hero_frame.label}), described as: {frame_prompt_detail(hero_frame)}."
        if selected_frames:
            frame = selected_frames[0]
            return f" Use `{frame.file_name}` as a {frame.selected_role.value.replace('_', ' ')}: {frame_prompt_detail(frame)}."
        return ""

    def _selected_frame_prompt(self, selected_frames: list[FrameRecord]) -> str:
        """Return prompt guidance for selected frames."""
        if not selected_frames:
            return ""
        hero_frames = [frame for frame in selected_frames if frame.selected_role == FrameRole.HERO_FRAME]
        visual_frames = [frame for frame in selected_frames if frame.selected_role == FrameRole.VISUAL_REFERENCE]
        background_frames = [frame for frame in selected_frames if frame.selected_role == FrameRole.POSSIBLE_BACKGROUND]
        lines = []
        for frame in hero_frames:
            lines.append(f"Open with `{frame.file_name}` ({frame.label}), described as: {frame_prompt_detail(frame)}. Use this as an opening visual reference, not as a direct copy unless rights are cleared.")
        for frame in visual_frames:
            lines.append(f"Use `{frame.file_name}` ({frame.label}) as a middle visual reference: {frame_prompt_detail(frame)}.")
        for frame in background_frames:
            lines.append(f"Use `{frame.file_name}` ({frame.label}) only as background or atmosphere reference: {frame_prompt_detail(frame)}.")
        return " ".join(lines)

    def _middle_visual_instruction(self, selected_frames: list[FrameRecord]) -> str:
        """Return middle-shot guidance based on selected visual reference frames."""
        visual_frame = next((frame for frame in selected_frames if frame.selected_role == FrameRole.VISUAL_REFERENCE), None)
        if visual_frame:
            return f"use `{visual_frame.file_name}` as the mid-sequence visual reference: {frame_prompt_detail(visual_frame)}"
        background_frame = next((frame for frame in selected_frames if frame.selected_role == FrameRole.POSSIBLE_BACKGROUND), None)
        if background_frame:
            return f"use `{background_frame.file_name}` for background atmosphere, not primary composition"
        return "show the core value/message"

    def _opening_visual_instruction(self, selected_frames: list[FrameRecord], keyframe_needed: bool) -> str:
        """Return opening visual guidance using selected frames when available."""
        hero_frame = next((frame for frame in selected_frames if frame.selected_role == FrameRole.HERO_FRAME), None)
        if hero_frame:
            return f"use selected hero frame `{hero_frame.file_name}` as the opening visual reference: {frame_prompt_detail(hero_frame)}"
        if selected_frames:
            return f"use selected frame `{selected_frames[0].file_name}` as the first approved visual reference: {frame_prompt_detail(selected_frames[0])}"
        if keyframe_needed:
            return "choose strongest extracted keyframe"
        return "use the strongest approved visual reference or title frame"

    def _frame_next_actions(self, sources: list[SourceRecord], selected_frames: list[FrameRecord], frame_references: list[FrameRecord]) -> list[str]:
        """Return frame-related next actions."""
        if selected_frames:
            return ["Confirm selected frame rights before using them as direct visual references."]
        if any(frame.selected_role == FrameRole.NEEDS_REVIEW for frame in frame_references):
            return ["Review selected frame descriptions before using them in generation prompts."]
        if any(source.frame_count > 0 for source in sources if source.source_type == SourceType.VIDEO):
            return ["Select hero/reference frames from the extracted frame grid."]
        if any(source.source_type == SourceType.VIDEO for source in sources):
            return ["Extract reference frames from the uploaded video source."]
        return []
