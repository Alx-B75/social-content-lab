"""Planning models for questions, recommendations, and generated content packs."""

from enum import StrEnum

from pydantic import BaseModel, Field


class CostBand(StrEnum):
    """Supported rough cost bands."""

    FREE_MANUAL = "free/manual"
    VERY_LOW = "very low"
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    UNKNOWN = "unknown"


class WorkflowRoute(StrEnum):
    """Supported content-production workflow routes."""

    TEXT_ONLY_PLANNING = "text_only_planning"
    STATIC_IMAGE_POST = "static_image_post"
    CAROUSEL_POST = "carousel_post"
    STILL_IMAGE_WITH_MOTION_VIDEO = "still_image_with_motion_video"
    AI_VIDEO_TEST_CLIP = "ai_video_test_clip"
    PREMIUM_AI_VIDEO_GENERATION = "premium_ai_video_generation"
    MANUAL_EDIT_REQUIRED = "manual_edit_required"


class ProviderType(StrEnum):
    """Supported provider type recommendations."""

    MANUAL_ONLY = "manual_only"
    OPENROUTER_TEXT_PLANNING = "openrouter_text_planning"
    CANVA_OR_CAPCUT_MANUAL_EDIT = "canva_or_capcut_manual_edit"
    FAL_OR_REPLICATE_MEDIA_GENERATION = "fal_or_replicate_media_generation"
    PREMIUM_VIDEO_MODEL = "premium_video_model"
    UNKNOWN = "unknown"


class Question(BaseModel):
    """A clarifying question displayed to the director."""

    key: str
    prompt: str
    input_type: str
    options: list[str] = Field(default_factory=list)


class QuestionGroup(BaseModel):
    """A grouped set of clarifying questions."""

    title: str
    questions: list[Question]


class ClarifyingAnswers(BaseModel):
    """Answers gathered from the director before recommendation."""

    main_point: str | None = None
    intent: str | None = None
    call_to_action: str | None = None
    platform: str | None = None
    aspect_ratio: str | None = None
    inferred_aspect_ratio: str | None = None
    aspect_ratio_override: str | None = None
    resolved_aspect_ratio: str | None = None
    output_format: str | None = None
    extracted_duration_seconds: int | None = None
    target_length_seconds: int | None = None
    resolved_duration_seconds: int | None = None
    include_voiceover: bool = False
    include_subtitles: bool = True
    include_on_screen_text: bool = True
    scene_structure: str | None = None
    tone: str | None = None
    brand_rules: str | None = None
    avoid_aesthetics: str | None = None
    source_use: str | None = None
    rights_constraints: str | None = None
    sensitive_materials: str | None = None
    video_source_treatment: str | None = None
    budget_priority: str | None = None
    quality_level: str | None = None
    ai_video_acceptable: bool = False
    draft_variations: int | None = 2
    maximum_cost_band: CostBand | None = None
    needed_outputs: list[str] = Field(default_factory=list)
    include_captions_hashtags: bool = True
    editing_destination: str | None = None


class WorkflowRecommendation(BaseModel):
    """Recommendation for the most suitable production route."""

    recommended_workflow_route: WorkflowRoute
    recommended_model_category: str
    suggested_provider_type: ProviderType
    estimated_cost_band: CostBand
    rationale: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    suggested_next_step: str


class ContentPack(BaseModel):
    """Draft content pack generated for a project."""

    core_message: str
    target_platform: str
    recommended_format: str
    resolved_aspect_ratio: str | None = None
    resolved_duration_seconds: int | None = None
    resolved_call_to_action: str | None = None
    script_outline: list[str]
    shot_list: list[str]
    image_prompt: str
    video_prompts: list[str]
    caption_drafts: list[str]
    asset_checklist: list[str]
    risk_notes: list[str]
    next_actions: list[str]
