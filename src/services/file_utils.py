"""Filesystem helpers for Social Content Lab."""

import re
from datetime import datetime
from pathlib import Path


def slugify(value: str) -> str:
    """Convert a string into a conservative filesystem slug."""
    cleaned = re.sub(r"[^a-zA-Z0-9]+", "-", value.strip().lower())
    cleaned = re.sub(r"-+", "-", cleaned).strip("-")
    return cleaned or "untitled-project"


def timestamped_project_id(project_name: str, created_at: datetime | None = None) -> str:
    """Create a timestamped project identifier from a project name."""
    timestamp = created_at or datetime.now()
    return f"{timestamp:%Y-%m-%d}-{slugify(project_name)}"


def ensure_directory(path: Path) -> Path:
    """Create a directory if needed and return the path."""
    path.mkdir(parents=True, exist_ok=True)
    return path


def write_text_file(path: Path, content: str) -> None:
    """Write UTF-8 text to a file after ensuring the parent directory exists."""
    ensure_directory(path.parent)
    path.write_text(content, encoding="utf-8")


def read_text_file(path: Path, fallback: str = "") -> str:
    """Read UTF-8 text from a file or return a fallback when it is missing."""
    if not path.exists():
        return fallback
    return path.read_text(encoding="utf-8")
