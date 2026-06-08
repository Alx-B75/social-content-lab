"""Workflow recommendation service for Social Content Lab."""

from src.models.planning import ClarifyingAnswers, ProviderType, WorkflowRecommendation, WorkflowRoute
from src.models.project import ContentProject
from src.models.source import SourceRecord, SourceReferenceStrategy, SourceType
from src.services.cost_estimator import CostEstimator
from src.services.planning_defaults import resolve_aspect_ratio, resolve_duration_seconds


class ModelRouter:
    """Recommend content-production routes from answers and source metadata."""

    def __init__(self, cost_estimator: CostEstimator) -> None:
        """Initialise the router with a rough cost estimator."""
        self.cost_estimator = cost_estimator

    def recommend(
        self,
        project: ContentProject,
        sources: list[SourceRecord],
        answers: ClarifyingAnswers,
    ) -> WorkflowRecommendation:
        """Generate a workflow recommendation for the project."""
        platform = answers.platform or "multi-platform"
        budget_priority = answers.budget_priority or "best balance"
        output_format = answers.output_format or ""
        route = self._select_route(platform, budget_priority, output_format, answers)
        provider_type = self._provider_for_route(route)
        warnings = self._build_warnings(sources, answers, project)
        rationale = self._build_rationale(project, platform, budget_priority, output_format, sources, answers, route)
        return WorkflowRecommendation(
            recommended_workflow_route=route,
            recommended_model_category=self._model_category_for_route(route),
            suggested_provider_type=provider_type,
            estimated_cost_band=self.cost_estimator.estimate_for_route(route),
            rationale=rationale,
            warnings=warnings,
            suggested_next_step=self._next_step_for_route(route, sources),
        )

    def _select_route(
        self,
        platform: str,
        budget_priority: str,
        output_format: str,
        answers: ClarifyingAnswers,
    ) -> WorkflowRoute:
        """Select the most appropriate workflow route."""
        platform_lower = platform.lower()
        format_lower = output_format.lower()
        if "linkedin" in platform_lower and budget_priority == "cheapest":
            if "carousel" in format_lower:
                return WorkflowRoute.CAROUSEL_POST
            return WorkflowRoute.STATIC_IMAGE_POST
        if any(term in platform_lower for term in ["tiktok", "reels", "shorts", "instagram", "youtube shorts"]) and budget_priority == "cheapest":
            return WorkflowRoute.STILL_IMAGE_WITH_MOTION_VIDEO
        if budget_priority == "fastest":
            return WorkflowRoute.MANUAL_EDIT_REQUIRED
        if budget_priority == "highest quality" and answers.ai_video_acceptable:
            return WorkflowRoute.PREMIUM_AI_VIDEO_GENERATION
        if "carousel" in format_lower:
            return WorkflowRoute.CAROUSEL_POST
        if "video" in format_lower or "reel" in format_lower or "story" in format_lower:
            if answers.ai_video_acceptable:
                return WorkflowRoute.AI_VIDEO_TEST_CLIP
            return WorkflowRoute.STILL_IMAGE_WITH_MOTION_VIDEO
        if not answers.ai_video_acceptable:
            return WorkflowRoute.STATIC_IMAGE_POST
        return WorkflowRoute.TEXT_ONLY_PLANNING

    def _provider_for_route(self, route: WorkflowRoute) -> ProviderType:
        """Map a workflow route to a suggested provider type."""
        mapping = {
            WorkflowRoute.TEXT_ONLY_PLANNING: ProviderType.OPENROUTER_TEXT_PLANNING,
            WorkflowRoute.STATIC_IMAGE_POST: ProviderType.CANVA_OR_CAPCUT_MANUAL_EDIT,
            WorkflowRoute.CAROUSEL_POST: ProviderType.CANVA_OR_CAPCUT_MANUAL_EDIT,
            WorkflowRoute.STILL_IMAGE_WITH_MOTION_VIDEO: ProviderType.CANVA_OR_CAPCUT_MANUAL_EDIT,
            WorkflowRoute.AI_VIDEO_TEST_CLIP: ProviderType.FAL_OR_REPLICATE_MEDIA_GENERATION,
            WorkflowRoute.PREMIUM_AI_VIDEO_GENERATION: ProviderType.PREMIUM_VIDEO_MODEL,
            WorkflowRoute.MANUAL_EDIT_REQUIRED: ProviderType.CANVA_OR_CAPCUT_MANUAL_EDIT,
        }
        return mapping.get(route, ProviderType.UNKNOWN)

    def _model_category_for_route(self, route: WorkflowRoute) -> str:
        """Return a human-readable model category for a route."""
        mapping = {
            WorkflowRoute.TEXT_ONLY_PLANNING: "text planning and prompt drafting",
            WorkflowRoute.STATIC_IMAGE_POST: "image planning with manual layout",
            WorkflowRoute.CAROUSEL_POST: "carousel scripting and layout planning",
            WorkflowRoute.STILL_IMAGE_WITH_MOTION_VIDEO: "image-to-motion or template video assembly",
            WorkflowRoute.AI_VIDEO_TEST_CLIP: "short AI video test generation",
            WorkflowRoute.PREMIUM_AI_VIDEO_GENERATION: "premium AI video generation with iteration budget",
            WorkflowRoute.MANUAL_EDIT_REQUIRED: "manual editing and template assembly",
        }
        return mapping.get(route, "unknown")

    def _build_warnings(
        self,
        sources: list[SourceRecord],
        answers: ClarifyingAnswers,
        project: ContentProject,
    ) -> list[str]:
        """Build warnings for production risk and source constraints."""
        warnings: list[str] = []
        if any(source.source_type == SourceType.VIDEO and answers.video_source_treatment == "match visually" for source in sources):
            warnings.append("Video sources that must be closely matched should go through keyframe extraction before generation.")
        if any(source.source_type == SourceType.VIDEO for source in sources) and answers.source_use == "copy closely":
            warnings.append("Copying a video source closely requires keyframe extraction and rights review before generation.")
        if any(source.strategy == SourceReferenceStrategy.URL_EXTRACTION_NEEDED for source in sources):
            warnings.append("URL sources are stored but not scraped in this MVP, so important facts should be pasted manually.")
        combined_text = " ".join(
            [
                project.director_instructions,
                answers.main_point or "",
                answers.brand_rules or "",
                answers.sensitive_materials or "",
            ]
        ).lower()
        if any(term in combined_text for term in ["face", "person", "people", "historical", "readable text", "continuity"]):
            warnings.append("Human faces, historical accuracy, readable text, and complex continuity can require multiple AI video retries.")
        if answers.rights_constraints or answers.source_use == "copy closely":
            warnings.append("If licensing is uncertain, use sources as inspiration or factual context instead of direct reproduction.")
        if answers.source_use == "copy closely" and not answers.rights_constraints:
            warnings.append("Licensing status is unclear for close copying. Add rights notes before generation.")
        route_text = f"{answers.output_format or ''} {answers.platform or ''}".lower()
        if any(term in route_text for term in ["video", "reel", "story", "shorts", "tiktok"]):
            if not resolve_duration_seconds(project, answers):
                warnings.append("Video planning needs a resolved duration before generation.")
            if not resolve_aspect_ratio(answers):
                warnings.append("Video planning needs a resolved aspect ratio before generation.")
        if answers.maximum_cost_band and answers.maximum_cost_band in {"free/manual", "very low"} and answers.ai_video_acceptable:
            warnings.append("AI video may exceed a very low budget once retries are included.")
        return warnings or ["No major warnings identified for the planning stage."]

    def _build_rationale(
        self,
        project: ContentProject,
        platform: str,
        budget_priority: str,
        output_format: str,
        sources: list[SourceRecord],
        answers: ClarifyingAnswers,
        route: WorkflowRoute,
    ) -> list[str]:
        """Build rationale for the selected route."""
        resolved_duration = resolve_duration_seconds(project, answers)
        resolved_aspect_ratio = resolve_aspect_ratio(answers)
        rationale = [f"Platform is {platform}, format is {output_format or 'not specified'}, aspect ratio is {resolved_aspect_ratio}, and budget priority is {budget_priority}."]
        if resolved_duration:
            rationale.append(f"Resolved duration is {resolved_duration} seconds.")
        if route in {WorkflowRoute.STATIC_IMAGE_POST, WorkflowRoute.CAROUSEL_POST}:
            rationale.append("Static or carousel planning keeps production cost and iteration risk low.")
        if route == WorkflowRoute.STILL_IMAGE_WITH_MOTION_VIDEO:
            rationale.append("Still images with motion are a practical bridge before expensive full video generation.")
        if route == WorkflowRoute.PREMIUM_AI_VIDEO_GENERATION:
            rationale.append("The answers prioritise quality and accept AI video generation.")
        if route == WorkflowRoute.MANUAL_EDIT_REQUIRED:
            rationale.append("Speed favours assembling the result in a familiar manual editing tool.")
        if sources:
            rationale.append(f"{len(sources)} source reference(s) are available for planning.")
        if answers.include_captions_hashtags:
            rationale.append("Captions and hashtags are included in the deliverable scope.")
        if answers.quality_level:
            rationale.append(f"Quality target is {answers.quality_level}.")
        return rationale

    def _next_step_for_route(self, route: WorkflowRoute, sources: list[SourceRecord]) -> str:
        """Return the suggested next action for a route."""
        if any(source.strategy == SourceReferenceStrategy.KEYFRAME_EXTRACTION_NEEDED for source in sources):
            return "Extract keyframes and confirm which frames are allowed as direct visual references."
        if route == WorkflowRoute.MANUAL_EDIT_REQUIRED:
            return "Assemble the first draft in Canva, CapCut, Premiere, or DaVinci Resolve using the exported pack."
        if route in {WorkflowRoute.AI_VIDEO_TEST_CLIP, WorkflowRoute.PREMIUM_AI_VIDEO_GENERATION}:
            return "Generate a short low-stakes test clip before committing to final production."
        return "Review the content pack, tighten the brief, and prepare manual layout or prompt drafting."
