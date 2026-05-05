from __future__ import annotations

import json
from pathlib import Path


SETTINGS_PATH = Path(__file__).resolve().parent.parent / ".shotrack_settings.json"


def load_last_project() -> Path | None:
    try:
        data = json.loads(SETTINGS_PATH.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return None
    value = data.get("last_project")
    if not value:
        return None
    path = Path(value)
    if not path.exists() or not path.is_dir():
        return None
    return path


def save_last_project(path: Path) -> None:
    data = {"last_project": str(path.resolve())}
    SETTINGS_PATH.write_text(json.dumps(data, indent=2), encoding="utf-8")
