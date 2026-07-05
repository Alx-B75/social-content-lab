"""Shared pytest fixtures for service-layer tests."""

from pathlib import Path

import pytest

from src.config import AppConfig
from src.models.project import ContentProject


@pytest.fixture
def app_config(tmp_path: Path) -> AppConfig:
    """Return an isolated app config rooted in a temp directory."""
    return AppConfig(
        root_path=tmp_path,
        content_path=tmp_path / "content",
        template_path=tmp_path / "templates",
        openrouter_api_key=None,
        openrouter_catalog_cache_path=tmp_path / "cache" / "openrouter-model-catalog.json",
        openrouter_video_catalog_cache_path=tmp_path / "cache" / "openrouter-video-model-catalog.json",
    )


@pytest.fixture
def content_project(tmp_path: Path) -> ContentProject:
    """Return a minimal content project in a temp directory."""
    project_path = tmp_path / "content" / "project"
    project_path.mkdir(parents=True)
    return ContentProject(
        project_id="project",
        project_name="Project",
        working_title="Shakespeare chatbot teaser",
        brand_name="Places In Time",
        topic="Shakespeare chatbot teaser",
        director_instructions="Create a 10 second LinkedIn short video teaser. CTA: Ask Shakespeare a question.",
        project_path=project_path,
    )
