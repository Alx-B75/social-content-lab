"""Content pack builder for Social Content Lab."""

from src.models.planning import ClarifyingAnswers, ContentPack, WorkflowRecommendation
from src.models.project import ContentProject
from src.models.source import SourceRecord
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
        recommended_format = answers.output_format or recommendation.recommended_workflow_route.value
        source_summary = self._source_summary(sources)
        tone = answers.tone or "clear and useful"
        call_to_action = answers.call_to_action or "Invite the audience to take the next practical step."

        content_pack = ContentPack(
            core_message=core_message,
            target_platform=target_platform,
            recommended_format=recommended_format,
            script_outline=[
                f"Open with a specific hook around: {core_message}.",
                f"Establish context using the director instructions: {project.director_instructions[:220]}",
                f"Develop the message in a {tone} tone with source context: {source_summary}.",
                f"Close with this action: {call_to_action}",
            ],
            shot_list=[
                "Opening frame: strong visual or title card that makes the topic immediately clear.",
                "Context frame: show the problem, opportunity, or reference material.",
                "Development frame: present the main proof points or sequence of ideas.",
                "Closing frame: display the call to action and brand-safe end state.",
            ],
            image_prompt=self._build_image_prompt(project, answers, core_message, source_summary),
            video_prompts=self._build_video_prompts(project, answers, core_message, recommendation),
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
            parts.append(f"{source.source_type.value} source {label} via {source.strategy.value}")
        return "; ".join(parts)

    def _build_image_prompt(
        self,
        project: ContentProject,
        answers: ClarifyingAnswers,
        core_message: str,
        source_summary: str,
    ) -> str:
        """Build a draft image prompt."""
        brand = f" for {project.brand_name}" if project.brand_name else ""
        avoid = f" Avoid: {answers.avoid_aesthetics}." if answers.avoid_aesthetics else ""
        return (
            f"Create a {answers.tone or 'clear'} social media visual{brand} about {core_message}. "
            f"Use references as {answers.source_use or 'planning context'}: {source_summary}. "
            f"Aspect ratio: {answers.aspect_ratio or 'platform appropriate'}.{avoid}"
        )

    def _build_video_prompts(
        self,
        project: ContentProject,
        answers: ClarifyingAnswers,
        core_message: str,
        recommendation: WorkflowRecommendation,
    ) -> list[str]:
        """Build draft video prompts."""
        length = answers.target_length_seconds or 15
        structure = answers.scene_structure or "multiple shots"
        return [
            f"{length}-second {structure} social video about {core_message}, in a {answers.tone or 'clear'} tone, designed for {answers.platform or 'multi-platform'}.",
            f"Use the route {recommendation.recommended_workflow_route.value}; include subtitles: {answers.include_subtitles}; include on-screen text: {answers.include_on_screen_text}.",
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
