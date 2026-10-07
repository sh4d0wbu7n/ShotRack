from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path


SETTINGS_PATH = Path.home() / ".shotrack_settings.json"


def load_last_project() -> Path | None:
    try:
        data = json.loads(SETTINGS_PATH.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            return None
        value = data.get("last_project")
        if not isinstance(value, str) or not value:
            return None
        path = Path(value)
        return path if path.is_dir() and (path / "project.db").is_file() else None
    except (ValueError, OSError):
        return None


def save_last_project(path: Path) -> None:
    data = {"last_project": str(path.resolve())}
    temp_path = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w", encoding="utf-8", dir=SETTINGS_PATH.parent,
            prefix=".shotrack-", suffix=".tmp", delete=False,
        ) as stream:
            temp_path = Path(stream.name)
            json.dump(data, stream, indent=2)
        os.replace(temp_path, SETTINGS_PATH)
    finally:
        if temp_path is not None:
            temp_path.unlink(missing_ok=True)
