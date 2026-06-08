"""Project persistence service for Social Content Lab."""

import csv
import json
import shutil
from pathlib import Path
from typing import Any

from src.config import AppConfig
from src.models.planning import ContentPack
from src.models.project import ContentProject, ProjectCreate
from src.models.source import SourceRecord
from src.services.file_utils import ensure_directory, read_text_file, timestamped_project_id, write_text_file


class ProjectService:
    """Create and update local project folders and files."""

    def __init__(self, config: AppConfig) -> None:
        """Initialise the project service with app configuration."""
        self.config = config
        ensure_directory(self.config.content_path)

    def create_project(self, project_create: ProjectCreate) -> ContentProject:
        """Create a timestamped project folder and starter files."""
        project_id = timestamped_project_id(project_create.project_name)
        project_path = self.config.content_path / project_id
        project_path = self._unique_project_path(project_path)
        project_id = project_path.name
        ensure_directory(project_path)
        ensure_directory(project_path / "sources")

        project = ContentProject(
            project_id=project_id,
            project_name=project_create.project_name,
            working_title=project_create.working_title,
            brand_name=project_create.brand_name,
            topic=project_create.topic,
            director_instructions=project_create.director_instructions,
            project_path=project_path,
        )

        self._copy_template("content-brief-template.md", project_path / "brief.md")
        self._copy_template("script-template.md", project_path / "script.md")
        self._copy_template("storyboard-template.md", project_path / "storyboard.md")
        self._copy_template("prompt-pack-template.md", project_path / "prompts.md")
        self._copy_template("platform-caption-template.md", project_path / "captions.md")
        self._copy_template("asset-log-template.csv", project_path / "asset-log.csv")
        self.save_project(project, [], None)
        self.save_source_index(project, [])
        return project

    def save_project(
        self,
        project: ContentProject,
        sources: list[SourceRecord],
        content_pack: ContentPack | None,
    ) -> None:
        """Save project metadata to project.json."""
        payload: dict[str, Any] = project.model_dump(mode="json")
        payload["sources"] = [source.model_dump(mode="json") for source in sources]
        payload["content_pack"] = content_pack.model_dump(mode="json") if content_pack else None
        write_text_file(project.project_path / "project.json", json.dumps(payload, indent=2))

    def save_source_index(self, project: ContentProject, sources: list[SourceRecord]) -> None:
        """Save source metadata into sources/source-index.json."""
        payload = [source.model_dump(mode="json") for source in sources]
        write_text_file(project.project_path / "sources" / "source-index.json", json.dumps(payload, indent=2))

    def save_uploaded_file(self, project: ContentProject, filename: str, data: bytes) -> Path:
        """Save uploaded file bytes under the project sources folder."""
        safe_name = Path(filename).name
        target_path = self._unique_file_path(project.project_path / "sources" / safe_name)
        target_path.write_bytes(data)
        return target_path

    def save_source_text(self, project: ContentProject, base_filename: str, text: str) -> Path:
        """Save pasted source text under the project sources folder."""
        target_path = self._unique_file_path(project.project_path / "sources" / base_filename)
        write_text_file(target_path, text)
        return target_path

    def save_content_pack(
        self,
        project: ContentProject,
        sources: list[SourceRecord],
        content_pack: ContentPack,
    ) -> None:
        """Write generated content pack files into the project folder."""
        write_text_file(project.project_path / "brief.md", self._render_brief(project, sources, content_pack))
        write_text_file(project.project_path / "script.md", self._render_script(content_pack))
        write_text_file(project.project_path / "storyboard.md", self._render_storyboard(content_pack))
        write_text_file(project.project_path / "prompts.md", self._render_prompts(content_pack))
        write_text_file(project.project_path / "captions.md", self._render_captions(content_pack))
        self.save_project(project, sources, content_pack)

    def ensure_asset_log(self, project: ContentProject) -> None:
        """Ensure the asset log file exists with the template columns."""
        asset_log_path = project.project_path / "asset-log.csv"
        if asset_log_path.exists():
            return
        columns = [
            "asset_id",
            "project_id",
            "source_or_generated",
            "file_name",
            "tool_or_model",
            "estimated_cost_band",
            "time_spent_minutes",
            "rating",
            "historical_or_brand_risk",
            "keep_reject",
            "notes",
        ]
        with asset_log_path.open("w", encoding="utf-8", newline="") as handle:
            writer = csv.writer(handle)
            writer.writerow(columns)

    def _unique_project_path(self, path: Path) -> Path:
        """Return a project path that does not overwrite an existing folder."""
        if not path.exists():
            return path
        counter = 2
        while True:
            candidate = path.with_name(f"{path.name}-{counter}")
            if not candidate.exists():
                return candidate
            counter += 1

    def _unique_file_path(self, path: Path) -> Path:
        """Return a file path that does not overwrite an existing file."""
        if not path.exists():
            return path
        counter = 2
        while True:
            candidate = path.with_name(f"{path.stem}-{counter}{path.suffix}")
            if not candidate.exists():
                return candidate
            counter += 1

    def _copy_template(self, template_name: str, target_path: Path) -> None:
        """Copy a template into a project or create an empty file when missing."""
        template_path = self.config.template_path / template_name
        ensure_directory(target_path.parent)
        if template_path.exists():
            shutil.copyfile(template_path, target_path)
            return
        target_path.touch()

    def _render_brief(
        self,
        project: ContentProject,
        sources: list[SourceRecord],
        content_pack: ContentPack,
    ) -> str:
        """Render project brief markdown."""
        source_lines = [f"- {source.source_id}: {source.source_type} using {source.strategy}" for source in sources]
        return "\n".join(
            [
                f"# {project.working_title}",
                "",
                f"Project: {project.project_name}",
                f"Brand: {project.brand_name or 'Not specified'}",
                f"Topic: {project.topic or 'Not specified'}",
                "",
                "## Director Instructions",
                project.director_instructions,
                "",
                "## Core Message",
                content_pack.core_message,
                "",
                "## Target Platform",
                content_pack.target_platform,
                "",
                "## Recommended Format",
                content_pack.recommended_format,
                "",
                "## Sources",
                "\n".join(source_lines) if source_lines else "No sources added.",
                "",
                "## Risk Notes",
                "\n".join(f"- {note}" for note in content_pack.risk_notes),
            ]
        )

    def _render_script(self, content_pack: ContentPack) -> str:
        """Render script markdown."""
        return "# Script Outline\n\n" + "\n".join(f"{index}. {line}" for index, line in enumerate(content_pack.script_outline, 1))

    def _render_storyboard(self, content_pack: ContentPack) -> str:
        """Render storyboard markdown."""
        return "# Shot List\n\n" + "\n".join(f"{index}. {line}" for index, line in enumerate(content_pack.shot_list, 1))

    def _render_prompts(self, content_pack: ContentPack) -> str:
        """Render prompt pack markdown."""
        video_prompt_text = "\n".join(f"{index}. {prompt}" for index, prompt in enumerate(content_pack.video_prompts, 1))
        return "\n".join(["# Prompt Pack", "", "## Image Prompt", content_pack.image_prompt, "", "## Video Prompts", video_prompt_text])

    def _render_captions(self, content_pack: ContentPack) -> str:
        """Render caption draft markdown."""
        return "# Caption Drafts\n\n" + "\n\n".join(f"## Caption {index}\n{caption}" for index, caption in enumerate(content_pack.caption_drafts, 1))

    def read_project_file(self, project: ContentProject, filename: str) -> str:
        """Read a generated project file for display."""
        return read_text_file(project.project_path / filename)
