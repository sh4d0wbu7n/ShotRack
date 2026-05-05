from __future__ import annotations

import re
from pathlib import Path


IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".webp"}
VIDEO_EXTENSIONS = {".mp4", ".mov"}
AUDIO_EXTENSIONS = {".wav", ".mp3"}


def snake_case(value: str) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9]+", "_", value.strip().lower())
    cleaned = re.sub(r"_+", "_", cleaned).strip("_")
    return cleaned or "untitled"


def scene_code(number: int) -> str:
    return f"SC{number:03d}"


def shot_code(number: int) -> str:
    return f"S{number:04d}"


def take_code(number: int) -> str:
    return f"TK_{number:03d}"


def media_kind(path: Path) -> str:
    suffix = path.suffix.lower()
    if suffix in IMAGE_EXTENSIONS:
        return "image"
    if suffix in VIDEO_EXTENSIONS:
        return "video"
    if suffix in AUDIO_EXTENSIONS:
        return "audio"
    return "file"


def is_png(path: Path) -> bool:
    return path.suffix.lower() == ".png"


def is_video(path: Path) -> bool:
    return path.suffix.lower() in VIDEO_EXTENSIONS


def ensure_unique_path(path: Path) -> Path:
    if not path.exists():
        return path
    stem = path.stem
    suffix = path.suffix
    parent = path.parent
    counter = 2
    while True:
        candidate = parent / f"{stem}_{counter}{suffix}"
        if not candidate.exists():
            return candidate
        counter += 1


def relative_to_project(project_root: Path, path: Path | None) -> str | None:
    if path is None:
        return None
    return path.resolve().relative_to(project_root.resolve()).as_posix()


def project_path(project_root: Path, rel_path: str | None) -> Path | None:
    if not rel_path:
        return None
    return project_root / Path(rel_path)
