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
    openrouter_base_url: str = "https://openrouter.ai/api/v1"
    openrouter_app_name: str = "Social Content Lab"
    openrouter_default_model: str | None = Field(default=None)
    openrouter_catalog_cache_path: Path
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
            openrouter_base_url=os.getenv("OPENROUTER_BASE_URL") or "https://openrouter.ai/api/v1",
            openrouter_app_name=os.getenv("OPENROUTER_APP_NAME") or "Social Content Lab",
            openrouter_default_model=os.getenv("OPENROUTER_DEFAULT_MODEL") or None,
            openrouter_catalog_cache_path=root_path / (os.getenv("OPENROUTER_CATALOG_CACHE_PATH") or "cache/openrouter-model-catalog.json"),
            fal_key=os.getenv("FAL_KEY") or None,
            replicate_api_token=os.getenv("REPLICATE_API_TOKEN") or None,
            elevenlabs_api_key=os.getenv("ELEVENLABS_API_KEY") or None,
        )
