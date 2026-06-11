"""Local FFmpeg-based video metadata and frame extraction helpers."""

import json
import os
import shutil
import subprocess
from fractions import Fraction
from math import gcd
from pathlib import Path
from typing import Any

from pydantic import ValidationError

from src.models.source import FrameRecord
from src.services.file_utils import ensure_directory, write_text_file


def is_ffmpeg_available() -> bool:
    """Return whether ffmpeg is available locally."""
    return _resolve_executable("ffmpeg") is not None


def is_ffprobe_available() -> bool:
    """Return whether ffprobe is available locally."""
    return _resolve_executable("ffprobe") is not None


def extract_video_metadata(video_path: Path) -> dict[str, Any]:
    """Extract lightweight video metadata using ffprobe when available."""
    if not is_ffprobe_available():
        return {
            "duration_seconds": None,
            "width": None,
            "height": None,
            "aspect_ratio": None,
            "frame_rate": None,
            "metadata_extractor": "unavailable",
            "notes": ["Video metadata extraction unavailable because ffprobe was not found on PATH."],
        }
    command = [
        str(_resolve_executable("ffprobe")),
        "-v",
        "error",
        "-select_streams",
        "v:0",
        "-show_entries",
        "stream=width,height,duration,r_frame_rate,avg_frame_rate:format=duration",
        "-of",
        "json",
        str(video_path),
    ]
    try:
        result = subprocess.run(command, capture_output=True, text=True, check=True, timeout=12)
        payload = json.loads(result.stdout or "{}")
    except (subprocess.SubprocessError, json.JSONDecodeError, OSError) as error:
        return {
            "duration_seconds": None,
            "width": None,
            "height": None,
            "aspect_ratio": None,
            "frame_rate": None,
            "metadata_extractor": "failed",
            "notes": [f"Video metadata extraction failed: {type(error).__name__}"],
        }
    stream = (payload.get("streams") or [{}])[0]
    duration = stream.get("duration") or (payload.get("format") or {}).get("duration")
    width = _safe_int(stream.get("width"))
    height = _safe_int(stream.get("height"))
    return {
        "duration_seconds": _safe_float(duration),
        "width": width,
        "height": height,
        "aspect_ratio": _format_aspect_ratio(width, height) if width and height else None,
        "frame_rate": _parse_frame_rate(stream.get("avg_frame_rate") or stream.get("r_frame_rate")),
        "metadata_extractor": "ffprobe",
        "notes": ["Basic video metadata extracted with ffprobe."],
    }


def extract_reference_frames(
    video_path: Path,
    output_dir: Path,
    duration_seconds: float | None = None,
    max_frames: int = 5,
    source_id: str | None = None,
) -> list[FrameRecord]:
    """Extract reference frames from a video into an output directory."""
    if not is_ffmpeg_available():
        raise RuntimeError("Install FFmpeg and make sure ffmpeg/ffprobe are on PATH to enable frame extraction.")
    ensure_directory(output_dir)
    timestamps = _build_timestamps(duration_seconds, max_frames)
    frames: list[FrameRecord] = []
    for index, timestamp in enumerate(timestamps):
        label = _label_for_timestamp(index, timestamp, duration_seconds, len(timestamps))
        file_name = f"frame_{index:03d}_{label}.jpg"
        output_path = output_dir / file_name
        _extract_single_frame(video_path, output_path, timestamp)
        frames.append(
            FrameRecord(
                frame_id=f"{source_id or video_path.stem}-frame-{index:03d}",
                source_id=source_id or video_path.stem,
                file_name=file_name,
                relative_path=_relative_content_path(output_path),
                absolute_path=output_path.resolve(),
                timestamp_seconds=timestamp,
                label=label,
            )
        )
    return frames


def build_frame_index(source_id: str, frames: list[FrameRecord], frame_index_path: Path) -> dict[str, Any]:
    """Build and write a frame index for extracted video frames."""
    payload = {
        "source_id": source_id,
        "frames": [frame.model_dump(mode="json") for frame in frames],
    }
    write_text_file(frame_index_path, json.dumps(payload, indent=2))
    return payload


def load_frame_index(frame_index_path: Path | None) -> list[FrameRecord]:
    """Load frame records from a frame index file."""
    if frame_index_path is None or not frame_index_path.exists():
        return []
    try:
        payload = json.loads(frame_index_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    frames = payload.get("frames") if isinstance(payload, dict) else []
    loaded_frames: list[FrameRecord] = []
    for frame in frames:
        if not isinstance(frame, dict):
            continue
        try:
            loaded_frames.append(FrameRecord(**frame))
        except ValidationError:
            continue
    return loaded_frames


def save_frame_index(source_id: str, frame_index_path: Path, frames: list[FrameRecord]) -> None:
    """Save frame records to a frame index file."""
    build_frame_index(source_id, frames, frame_index_path)


def _extract_single_frame(video_path: Path, output_path: Path, timestamp: float | None) -> None:
    """Extract a single frame with ffmpeg."""
    command = [str(_resolve_executable("ffmpeg")), "-y"]
    if timestamp is not None:
        command.extend(["-ss", f"{max(timestamp, 0):.3f}"])
    command.extend(["-i", str(video_path), "-frames:v", "1", "-q:v", "2", str(output_path)])
    subprocess.run(command, capture_output=True, text=True, check=True, timeout=20)


def _build_timestamps(duration_seconds: float | None, max_frames: int) -> list[float | None]:
    """Build safe representative timestamps for extraction."""
    if duration_seconds is None or duration_seconds <= 0:
        return [0.0]
    if duration_seconds < 2:
        return [0.0]
    fractions = [0.0, 0.25, 0.5, 0.75, 0.95]
    if max_frames < len(fractions):
        fractions = fractions[:max(max_frames, 1)]
    timestamps = [min(max(duration_seconds * fraction, 0), max(duration_seconds - 0.2, 0)) for fraction in fractions]
    unique: list[float] = []
    for timestamp in timestamps:
        rounded = round(timestamp, 2)
        if rounded not in unique:
            unique.append(rounded)
    return unique


def _resolve_executable(tool_name: str) -> Path | None:
    """Resolve an FFmpeg executable from PATH or the common winget package folder."""
    path_match = shutil.which(tool_name)
    if path_match:
        return Path(path_match)

    executable_name = f"{tool_name}.exe" if os.name == "nt" else tool_name
    for directory in _candidate_ffmpeg_bin_dirs():
        candidate = directory / executable_name
        if candidate.exists():
            return candidate
    return None


def _candidate_ffmpeg_bin_dirs() -> list[Path]:
    """Return likely FFmpeg binary folders for local Windows package installs."""
    if os.name != "nt":
        return []

    local_app_data = os.environ.get("LOCALAPPDATA")
    if not local_app_data:
        return []

    winget_packages = Path(local_app_data) / "Microsoft" / "WinGet" / "Packages"
    if not winget_packages.exists():
        return []

    candidates: list[Path] = []
    for package_path in winget_packages.glob("Gyan.FFmpeg*"):
        candidates.extend(package_path.glob("ffmpeg-*/*/bin"))
        candidates.extend(package_path.glob("ffmpeg-*/bin"))
    return candidates


def _label_for_timestamp(index: int, timestamp: float | None, duration_seconds: float | None, frame_count: int) -> str:
    """Return a stable filename label for a timestamp."""
    if index == 0:
        return "start"
    if duration_seconds is None or duration_seconds <= 0 or frame_count == 1:
        return f"{index:03d}"
    percent = round(((timestamp or 0) / duration_seconds) * 100)
    if index == frame_count - 1:
        return "end"
    return f"{percent}pct"


def _relative_content_path(path: Path) -> Path:
    """Return a content-relative path when possible."""
    parts = path.resolve().parts
    if "content" in parts:
        index = parts.index("content")
        return Path(*parts[index:])
    return Path(path.name)


def _parse_frame_rate(value: object) -> float | None:
    """Parse an ffprobe frame rate string."""
    if value in {None, "0/0"}:
        return None
    try:
        return float(Fraction(str(value)))
    except (ValueError, ZeroDivisionError):
        return None


def _format_aspect_ratio(width: int, height: int) -> str:
    """Format width and height as a reduced aspect ratio."""
    divisor = gcd(width, height)
    return f"{width // divisor}:{height // divisor}"


def _safe_int(value: object) -> int | None:
    """Convert a value to int when possible."""
    try:
        return int(value) if value is not None else None
    except (TypeError, ValueError):
        return None


def _safe_float(value: object) -> float | None:
    """Convert a value to float when possible."""
    try:
        return float(value) if value is not None else None
    except (TypeError, ValueError):
        return None
