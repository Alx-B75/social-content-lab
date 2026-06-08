"""Project data models for Social Content Lab."""

from datetime import datetime
from pathlib import Path

from pydantic import BaseModel, Field


class ProjectCreate(BaseModel):
    """User-provided fields required to create a content planning project."""

    project_name: str
    working_title: str
    brand_name: str | None = None
    topic: str | None = None
    director_instructions: str


class ContentProject(BaseModel):
    """Stored project metadata for a local content planning project."""

    project_id: str
    project_name: str
    working_title: str
    brand_name: str | None = None
    topic: str | None = None
    director_instructions: str
    created_at: datetime = Field(default_factory=datetime.now)
    project_path: Path
