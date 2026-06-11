"""Project persistence service for Social Content Lab."""

import csv
import json
import shutil
from pathlib import Path
from typing import Any

from src.config import AppConfig
from src.models.planning import ClarifyingAnswers, ContentPack
from src.models.project import ContentProject, ProjectCreate
from src.models.source import FrameRecord, SourceRecord
from src.services.file_utils import ensure_directory, read_text_file, timestamped_project_id, write_text_file


class ProjectService:
    """Create and update local project folders and files."""

    def __init__(self, config: AppConfig) -> None:
        """Initialise the project service with app configuration."""
        self.config = config
        ensure_directory(self.config.content_path)

    def list_projects(self) -> list[dict[str, str]]:
        """List saved project folders that contain project metadata."""
        projects: list[dict[str, str]] = []
        for project_path in sorted(self.config.content_path.iterdir(), reverse=True):
            project_json_path = project_path / "project.json"
            if not project_path.is_dir() or not project_json_path.exists():
                continue
            try:
                payload = json.loads(project_json_path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                continue
            project_id = str(payload.get("project_id") or project_path.name)
            projects.append(
                {
                    "project_id": project_id,
                    "label": f"{project_id} - {payload.get('working_title') or payload.get('project_name') or 'Untitled'}",
                    "path": str(project_path),
                }
            )
        return projects

    def load_project(self, project_id: str) -> tuple[ContentProject, list[SourceRecord], ContentPack | None, ClarifyingAnswers | None]:
        """Load a saved project, sources, content pack, and answers from local files."""
        project_path = self.config.content_path / project_id
        project_json_path = project_path / "project.json"
        payload = json.loads(project_json_path.read_text(encoding="utf-8"))
        project_payload = {key: value for key, value in payload.items() if key not in {"sources", "content_pack", "clarifying_answers"}}
        project_payload["project_path"] = project_path
        project = ContentProject(**project_payload)
        sources = self._load_sources(project, payload)
        content_pack_payload = payload.get("content_pack")
        content_pack = ContentPack(**content_pack_payload) if isinstance(content_pack_payload, dict) else None
        answers_payload = payload.get("clarifying_answers")
        answers = ClarifyingAnswers(**answers_payload) if isinstance(answers_payload, dict) else self._answers_from_content_pack(content_pack)
        return project, sources, content_pack, answers

    def update_project_metadata(self, project: ContentProject, updates: dict[str, str | None]) -> ContentProject:
        """Update editable project metadata in project.json."""
        updated_project = project.model_copy(update=updates)
        payload = self._read_project_payload(project.project_path)
        payload.update(updated_project.model_dump(mode="json"))
        write_text_file(project.project_path / "project.json", json.dumps(payload, indent=2))
        return updated_project

    def duplicate_project(self, project_id: str) -> ContentProject:
        """Duplicate a saved project folder and return the duplicated project."""
        project, sources, content_pack, answers = self.load_project(project_id)
        duplicate_path = self._unique_project_path(project.project_path.with_name(f"{project.project_path.name}-copy"))
        shutil.copytree(project.project_path, duplicate_path)
        duplicate_project = project.model_copy(
            update={
                "project_id": duplicate_path.name,
                "project_name": f"{project.project_name} copy",
                "project_path": duplicate_path,
            }
        )
        self.save_project(duplicate_project, sources, content_pack, answers)
        return duplicate_project

    def delete_project(self, project_id: str) -> None:
        """Delete a saved local project folder after validating its path."""
        project_path = (self.config.content_path / project_id).resolve()
        content_path = self.config.content_path.resolve()
        if content_path not in project_path.parents:
            raise ValueError("Project path is outside the configured content folder.")
        if not project_path.exists() or not project_path.is_dir():
            raise ValueError("Project folder does not exist.")
        shutil.rmtree(project_path)

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
        answers: ClarifyingAnswers | None = None,
    ) -> None:
        """Save project metadata to project.json."""
        payload: dict[str, Any] = project.model_dump(mode="json")
        payload["sources"] = [source.model_dump(mode="json") for source in sources]
        payload["content_pack"] = content_pack.model_dump(mode="json") if content_pack else None
        payload["clarifying_answers"] = answers.model_dump(mode="json") if answers else self._existing_clarifying_answers(project)
        write_text_file(project.project_path / "project.json", json.dumps(payload, indent=2))

    def save_source_index(self, project: ContentProject, sources: list[SourceRecord]) -> None:
        """Save source metadata into sources/source-index.json."""
        payload = [source.model_dump(mode="json") for source in sources]
        write_text_file(project.project_path / "sources" / "source-index.json", json.dumps(payload, indent=2))

    def append_source_to_asset_log(self, project: ContentProject, source: SourceRecord) -> None:
        """Append a source row to asset-log.csv without duplicating asset IDs."""
        self.ensure_asset_log(project)
        asset_log_path = project.project_path / "asset-log.csv"
        rows = self._read_asset_log_rows(asset_log_path)
        if any(row.get("asset_id") == source.source_id for row in rows):
            return
        rows.append(self._source_asset_log_row(project, source))
        self._write_asset_log_rows(asset_log_path, rows)

    def append_frame_to_asset_log(self, project: ContentProject, frame: FrameRecord) -> None:
        """Append a frame row to asset-log.csv without duplicating asset IDs."""
        self.ensure_asset_log(project)
        asset_log_path = project.project_path / "asset-log.csv"
        rows = self._read_asset_log_rows(asset_log_path)
        if any(row.get("asset_id") == frame.frame_id for row in rows):
            return
        rows.append(self._frame_asset_log_row(project, frame))
        self._write_asset_log_rows(asset_log_path, rows)

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
        answers: ClarifyingAnswers | None = None,
    ) -> None:
        """Write generated content pack files into the project folder."""
        write_text_file(project.project_path / "brief.md", self._render_brief(project, sources, content_pack))
        write_text_file(project.project_path / "script.md", self._render_script(content_pack))
        write_text_file(project.project_path / "storyboard.md", self._render_storyboard(content_pack))
        write_text_file(project.project_path / "prompts.md", self._render_prompts(content_pack))
        write_text_file(project.project_path / "captions.md", self._render_captions(content_pack))
        self.save_project(project, sources, content_pack, answers)

    def ensure_asset_log(self, project: ContentProject) -> None:
        """Ensure the asset log file exists with the template columns."""
        asset_log_path = project.project_path / "asset-log.csv"
        if asset_log_path.exists():
            return
        with asset_log_path.open("w", encoding="utf-8", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=self._asset_log_columns())
            writer.writeheader()

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
        source_lines = [f"- {source.source_id}: {source.source_type.value} using {source.strategy.value}" for source in sources]
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
                "## Call To Action",
                content_pack.resolved_call_to_action or "Not specified",
                "",
                "## Resolved Production Specs",
                f"Aspect ratio: {content_pack.resolved_aspect_ratio or 'Not applicable'}",
                f"Duration: {f'{content_pack.resolved_duration_seconds} seconds' if content_pack.resolved_duration_seconds else 'Not applicable'}",
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

    def _load_sources(self, project: ContentProject, payload: dict[str, Any]) -> list[SourceRecord]:
        """Load sources from source index or project metadata."""
        source_index_path = project.project_path / "sources" / "source-index.json"
        raw_sources = payload.get("sources") or []
        if source_index_path.exists():
            try:
                raw_sources = json.loads(source_index_path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                raw_sources = payload.get("sources") or []
        return [SourceRecord(**source) for source in raw_sources if isinstance(source, dict)]

    def _read_project_payload(self, project_path: Path) -> dict[str, Any]:
        """Read project metadata payload or return an empty payload."""
        project_json_path = project_path / "project.json"
        if not project_json_path.exists():
            return {}
        try:
            return json.loads(project_json_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return {}

    def _existing_clarifying_answers(self, project: ContentProject) -> dict[str, Any] | None:
        """Return existing saved answers so unrelated writes do not erase them."""
        payload = self._read_project_payload(project.project_path)
        answers = payload.get("clarifying_answers")
        return answers if isinstance(answers, dict) else None

    def _answers_from_content_pack(self, content_pack: ContentPack | None) -> ClarifyingAnswers | None:
        """Build partial clarifying answers from an older saved content pack."""
        if content_pack is None:
            return None
        return ClarifyingAnswers(
            main_point=content_pack.core_message,
            call_to_action=content_pack.resolved_call_to_action,
            platform=content_pack.target_platform,
            aspect_ratio=content_pack.resolved_aspect_ratio,
            resolved_aspect_ratio=content_pack.resolved_aspect_ratio,
            output_format=content_pack.recommended_format,
            target_length_seconds=content_pack.resolved_duration_seconds,
            resolved_duration_seconds=content_pack.resolved_duration_seconds,
        )

    def _asset_log_columns(self) -> list[str]:
        """Return the standard asset log columns."""
        return [
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

    def _read_asset_log_rows(self, asset_log_path: Path) -> list[dict[str, str]]:
        """Read asset log rows as dictionaries."""
        with asset_log_path.open("r", encoding="utf-8", newline="") as handle:
            return list(csv.DictReader(handle))

    def _write_asset_log_rows(self, asset_log_path: Path, rows: list[dict[str, str]]) -> None:
        """Write asset log rows as dictionaries."""
        with asset_log_path.open("w", encoding="utf-8", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=self._asset_log_columns())
            writer.writeheader()
            writer.writerows(rows)

    def _source_asset_log_row(self, project: ContentProject, source: SourceRecord) -> dict[str, str]:
        """Build an asset log row for a source record."""
        stored_name = source.stored_path.name if source.stored_path else None
        file_name = source.original_filename or source.url or stored_name or source.source_id
        tool_or_model = "manual_upload" if source.original_filename else "manual_entry"
        notes = f"{source.strategy.value}; purpose: {source.declared_purpose or 'not specified'}"
        return {
            "asset_id": source.source_id,
            "project_id": project.project_id,
            "source_or_generated": "source",
            "file_name": file_name,
            "tool_or_model": tool_or_model,
            "estimated_cost_band": "free/manual",
            "time_spent_minutes": "",
            "rating": "unrated",
            "historical_or_brand_risk": "unknown",
            "keep_reject": "undecided",
            "notes": notes,
        }

    def _frame_asset_log_row(self, project: ContentProject, frame: FrameRecord) -> dict[str, str]:
        """Build an asset log row for an extracted frame."""
        timestamp = f"{frame.timestamp_seconds:.2f}s" if frame.timestamp_seconds is not None else "unknown timestamp"
        return {
            "asset_id": frame.frame_id,
            "project_id": project.project_id,
            "source_or_generated": "source_frame",
            "file_name": frame.file_name,
            "tool_or_model": "ffmpeg",
            "estimated_cost_band": "free/manual",
            "time_spent_minutes": "",
            "rating": "unrated",
            "historical_or_brand_risk": "needs_review",
            "keep_reject": "undecided",
            "notes": f"extracted from video source at {timestamp}",
        }
