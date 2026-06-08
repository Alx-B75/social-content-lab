"""Configuration objects for Social Content Lab."""

import os
from pathlib import Path

from pydantic import BaseModel, Field


class AppConfig(BaseModel):
    """Application configuration loaded from the local environment."""

    root_path: Path
    content_path: Path
    template_path: Path
    openrouter_api_key: str | None = Field(default=None)
    fal_key: str | None = Field(default=None)
    replicate_api_token: str | None = Field(default=None)
    elevenlabs_api_key: str | None = Field(default=None)

    @classmethod
    def from_environment(cls, root_path: Path) -> "AppConfig":
        """Create configuration from environment variables and project paths."""
        return cls(
            root_path=root_path,
            content_path=root_path / "content",
            template_path=root_path / "templates",
            openrouter_api_key=os.getenv("OPENROUTER_API_KEY") or None,
            fal_key=os.getenv("FAL_KEY") or None,
            replicate_api_token=os.getenv("REPLICATE_API_TOKEN") or None,
            elevenlabs_api_key=os.getenv("ELEVENLABS_API_KEY") or None,
        )
