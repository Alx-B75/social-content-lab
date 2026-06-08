"""Content pack builder for Social Content Lab."""

from src.models.planning import ClarifyingAnswers, ContentPack, WorkflowRecommendation
from src.models.project import ContentProject
from src.models.source import SourceRecord, SourceReferenceStrategy, SourceType
from src.services.planning_defaults import label_for_route, resolve_aspect_ratio, resolve_duration_seconds
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
        call_to_action = answers.call_to_action or "Invite the audience to take the next practical step."
        resolved_duration = resolve_duration_seconds(project, answers)
        resolved_aspect_ratio = resolve_aspect_ratio(answers)

        content_pack = ContentPack(
            core_message=core_message,
            target_platform=target_platform,
            recommended_format=recommended_format,
            resolved_aspect_ratio=resolved_aspect_ratio,
            resolved_duration_seconds=resolved_duration,
            script_outline=self._build_script_outline(project, answers, core_message, call_to_action, resolved_duration),
            shot_list=self._build_shot_list(sources, answers, core_message, call_to_action, resolved_duration),
            image_prompt=self._build_image_prompt(project, answers, core_message, source_summary, resolved_aspect_ratio),
            video_prompts=self._build_video_prompts(project, answers, core_message, recommendation, resolved_duration, resolved_aspect_ratio),
            caption_drafts=self._build_captions(project, answers, core_message, call_to_action),
            asset_checklist=self._build_asset_checklist(sources, answers),
            risk_notes=recommendation.warnings,
            next_actions=[
                recommendation.suggested_next_step,
                "Review rights and source-use constraints before generating or publishing assets.",
                "Update asset-log.csv as source and generated assets are selected.",
            ],
        )
        self.project_service.save_content_pack(project, sources, content_pack)
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
    ) -> list[str]:
        """Build a specific script outline from known project details."""
        topic_line = f"Topic: {project.topic}." if project.topic else f"Working title: {project.working_title}."
        if resolved_duration:
            segments = self._timeline_segments(resolved_duration)
            return [
                f"{segments[0]}: Lead with the strongest moment from '{project.working_title}' and make the promise clear: {core_message}.",
                f"{segments[1]}: Deliver the core value for {answers.platform or 'the chosen platform'} in a {answers.tone or 'clear'} tone. {topic_line}",
                f"{segments[2]}: Show proof, a teaser, or the most useful feature moment without inventing unsupported source details.",
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
    ) -> str:
        """Build a draft image prompt."""
        brand = f" for {project.brand_name}" if project.brand_name else ""
        avoid = f" Avoid: {answers.avoid_aesthetics}." if answers.avoid_aesthetics else ""
        return (
            f"Create a {answers.tone or 'clear'} social media visual{brand} about {core_message}. "
            f"Use references as {answers.source_use or 'planning context'}: {source_summary}. "
            f"Aspect ratio: {resolved_aspect_ratio}.{avoid}"
        )

    def _build_video_prompts(
        self,
        project: ContentProject,
        answers: ClarifyingAnswers,
        core_message: str,
        recommendation: WorkflowRecommendation,
        resolved_duration: int | None,
        resolved_aspect_ratio: str,
    ) -> list[str]:
        """Build draft video prompts."""
        length = resolved_duration or 15
        structure = answers.scene_structure or "multiple shots"
        return [
            f"{length}-second {structure} social video for {answers.platform or 'multi-platform'} about '{project.working_title}': {core_message}.",
            f"Use the route {label_for_route(recommendation.recommended_workflow_route)} at {resolved_aspect_ratio}; include subtitles: {answers.include_subtitles}; include on-screen text: {answers.include_on_screen_text}.",
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
        return [
            f"{brand_intro}{core_message}\n\n{call_to_action}{hashtag_tail}",
            f"A practical look at {core_message}. Save this before your next production sprint.{hashtag_tail}",
            f"Before generating anything expensive, get the concept, source use, and route right. {call_to_action}{hashtag_tail}",
        ]

    def _build_asset_checklist(self, sources: list[SourceRecord], answers: ClarifyingAnswers) -> list[str]:
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
    ) -> list[str]:
        """Build a shot list that respects available source analysis."""
        keyframe_needed = any(source.strategy == SourceReferenceStrategy.KEYFRAME_EXTRACTION_NEEDED for source in sources)
        strongest_visual = "choose strongest extracted keyframe" if keyframe_needed else "use the strongest approved visual reference or title frame"
        if resolved_duration:
            segments = self._timeline_segments(resolved_duration)
            return [
                f"{segments[0]}: {strongest_visual}; introduce {core_message}.",
                f"{segments[1]}: show the core value/message with concise on-screen text for {answers.platform or 'the target platform'}.",
                f"{segments[2]}: show proof, teaser, feature, or source-backed supporting moment.",
                f"{segments[3]}: end card with CTA: {call_to_action}",
            ]
        return [
            f"Frame 1: {strongest_visual}; headline the message '{core_message}'.",
            "Frame 2: show the key context or benefit using only confirmed source details.",
            "Frame 3: add proof, feature, or teaser copy that can be manually checked.",
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
