"""Rough cost estimation service for Social Content Lab."""

from src.models.planning import CostBand, WorkflowRoute


class CostEstimator:
    """Estimate rough cost bands without claiming live pricing."""

    def estimate_for_route(self, route: WorkflowRoute) -> CostBand:
        """Return a rough cost band for a workflow route."""
        mapping = {
            WorkflowRoute.TEXT_ONLY_PLANNING: CostBand.FREE_MANUAL,
            WorkflowRoute.STATIC_IMAGE_POST: CostBand.VERY_LOW,
            WorkflowRoute.CAROUSEL_POST: CostBand.VERY_LOW,
            WorkflowRoute.STILL_IMAGE_WITH_MOTION_VIDEO: CostBand.LOW,
            WorkflowRoute.AI_VIDEO_TEST_CLIP: CostBand.MEDIUM,
            WorkflowRoute.PREMIUM_AI_VIDEO_GENERATION: CostBand.HIGH,
            WorkflowRoute.MANUAL_EDIT_REQUIRED: CostBand.UNKNOWN,
        }
        return mapping.get(route, CostBand.UNKNOWN)
