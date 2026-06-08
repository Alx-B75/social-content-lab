"""Clarifying question builder for Social Content Lab."""

from src.models.planning import Question, QuestionGroup
from src.models.project import ContentProject
from src.models.source import SourceRecord, SourceType


class QuestionBuilder:
    """Build grouped clarifying questions from project and source context."""

    def build_questions(self, project: ContentProject, sources: list[SourceRecord]) -> list[QuestionGroup]:
        """Build the standard question groups for a content project."""
        return [
            self._goal_and_message_group(project),
            self._platform_and_format_group(),
            self._length_and_structure_group(),
            self._brand_and_style_group(project),
            self._source_use_group(sources),
            self._budget_and_quality_group(),
            self._production_constraints_group(),
        ]

    def _goal_and_message_group(self, project: ContentProject) -> QuestionGroup:
        """Build goal and message questions."""
        default_point = project.topic or project.working_title
        return QuestionGroup(
            title="Goal and message",
            questions=[
                Question(key="main_point", prompt=f"What is the single main point this content should make? Suggested: {default_point}", input_type="text_area"),
                Question(key="intent", prompt="Is this meant to educate, entertain, sell, announce, or build brand authority?", input_type="select", options=["educate", "entertain", "sell", "announce", "build brand authority"]),
                Question(key="call_to_action", prompt="Is there a call to action?", input_type="text"),
            ],
        )

    def _platform_and_format_group(self) -> QuestionGroup:
        """Build platform and format questions."""
        return QuestionGroup(
            title="Platform and format",
            questions=[
                Question(key="platform", prompt="Which platform is this for?", input_type="select", options=["LinkedIn", "Instagram feed", "Instagram Reels", "Instagram square", "TikTok", "YouTube Shorts", "YouTube standard", "Facebook", "X", "Website hero", "Stories", "multi-platform"]),
                Question(key="output_format", prompt="What format should this be?", input_type="select", options=["static post", "carousel", "short video", "standard video", "ad", "story", "reel", "website hero", "long-form video"]),
                Question(key="aspect_ratio_override", prompt="Optional aspect ratio override", input_type="select", options=["Use inferred default", "16:9", "9:16", "1:1", "4:5", "variants_required"]),
            ],
        )

    def _length_and_structure_group(self) -> QuestionGroup:
        """Build length and structure questions."""
        return QuestionGroup(
            title="Length and structure",
            questions=[
                Question(key="target_length_seconds", prompt="Target length in seconds?", input_type="number"),
                Question(key="include_voiceover", prompt="Should it include voiceover?", input_type="checkbox"),
                Question(key="include_subtitles", prompt="Should it include subtitles?", input_type="checkbox"),
                Question(key="include_on_screen_text", prompt="Should it include on-screen text?", input_type="checkbox"),
                Question(key="scene_structure", prompt="Should it be one continuous scene or multiple shots?", input_type="select", options=["one continuous scene", "multiple shots", "either"]),
            ],
        )

    def _brand_and_style_group(self, project: ContentProject) -> QuestionGroup:
        """Build brand and style questions."""
        brand_prompt = f"Are there brand colours, fonts, logos, or visual rules for {project.brand_name}?" if project.brand_name else "Are there brand colours, fonts, logos, or visual rules?"
        return QuestionGroup(
            title="Brand and style",
            questions=[
                Question(key="tone", prompt="What tone should it use?", input_type="select", options=["serious", "witty", "cinematic", "documentary", "educational", "premium", "playful"]),
                Question(key="brand_rules", prompt=brand_prompt, input_type="text_area"),
                Question(key="avoid_aesthetics", prompt="Should it avoid fantasy, exaggerated, comic, corporate, or stock-image aesthetics?", input_type="text_area"),
            ],
        )

    def _source_use_group(self, sources: list[SourceRecord]) -> QuestionGroup:
        """Build source use questions."""
        video_question = "If using a video source, should it be matched visually, summarised, or converted into a new concept?"
        if not any(source.source_type == SourceType.VIDEO for source in sources):
            video_question = "If a video source is added later, should it be matched visually, summarised, or converted into a new concept?"
        return QuestionGroup(
            title="Source use",
            questions=[
                Question(key="source_use", prompt="Should the uploaded source be copied closely, used as inspiration/reference context, or used only for factual context?", input_type="select", options=["inspiration/reference context", "copy closely", "factual/reference context only"]),
                Question(key="rights_constraints", prompt="Are there rights or licensing constraints?", input_type="text_area"),
                Question(key="sensitive_materials", prompt="Are there people, logos, private details, or copyrighted materials that should not be reproduced?", input_type="text_area"),
                Question(key="video_source_treatment", prompt=video_question, input_type="select", options=["match visually", "summarise", "convert into a new concept", "not applicable"]),
            ],
        )

    def _budget_and_quality_group(self) -> QuestionGroup:
        """Build budget and quality questions."""
        return QuestionGroup(
            title="Budget and quality",
            questions=[
                Question(key="budget_priority", prompt="Is the priority cheapest, fastest, highest quality, or best balance?", input_type="select", options=["cheapest", "fastest", "highest quality", "best balance"]),
                Question(key="quality_level", prompt="What quality level is expected for this pass?", input_type="select", options=["good enough draft", "polished draft", "client-ready", "highest quality"]),
                Question(key="ai_video_acceptable", prompt="Is AI video generation acceptable?", input_type="checkbox"),
                Question(key="draft_variations", prompt="How many draft variations should be generated before final selection?", input_type="number"),
                Question(key="maximum_cost_band", prompt="What is the maximum acceptable estimated cost?", input_type="select", options=["free/manual", "very low", "low", "medium", "high", "unknown"]),
            ],
        )

    def _production_constraints_group(self) -> QuestionGroup:
        """Build production constraints questions."""
        return QuestionGroup(
            title="Production constraints",
            questions=[
                Question(key="needed_outputs", prompt="What outputs are needed?", input_type="multiselect", options=["finished video", "prompt pack", "script", "storyboard", "full content pack"]),
                Question(key="include_captions_hashtags", prompt="Should the output include captions and hashtags?", input_type="checkbox"),
                Question(key="editing_destination", prompt="Should the result be ready for manual editing in CapCut, Canva, Premiere, or DaVinci Resolve?", input_type="select", options=["CapCut", "Canva", "Premiere", "DaVinci Resolve", "not needed"]),
            ],
        )
