"""Small pure helpers for the Item Icons UI."""

from __future__ import annotations

import json
import re
from pathlib import Path, PurePosixPath
from typing import Sequence


def settings_path_list(value: object) -> list[Path]:
    if isinstance(value, str):
        try:
            parsed = json.loads(value)
        except Exception:
            parsed = []
    elif isinstance(value, (list, tuple)):
        parsed = value
    else:
        parsed = []
    paths: list[Path] = []
    for item in parsed:
        text = str(item or "").strip()
        if text:
            paths.append(Path(text).expanduser())
    return paths


def path_list_to_settings(paths: Sequence[Path]) -> str:
    return json.dumps([str(path) for path in paths])


def safe_icon_library_component(text: object, *, fallback: str = "icon") -> str:
    raw = str(text or "").replace("\\", "/").strip()
    name = PurePosixPath(raw).stem if "/" in raw else Path(raw).stem
    if not name:
        name = raw
    safe = re.sub(r"[^A-Za-z0-9._-]+", "-", str(name or fallback)).strip("-._")
    return (safe or fallback)[:72]


def is_probable_item_icon_entry(entry: object) -> bool:
    path = str(getattr(entry, "path", "") or "").replace("\\", "/")
    lower = path.lower()
    extension = str(getattr(entry, "extension", "") or PurePosixPath(path).suffix).lower()
    if extension != ".dds":
        return False
    return "itemicon" in lower or ("/ui/" in lower and "icon" in lower)


def safe_relative_target_path(target_path: str) -> Path:
    pure = PurePosixPath(str(target_path or "").replace("\\", "/"))
    parts = [part for part in pure.parts if part not in {"", ".", "/"}]
    if not parts or any(part == ".." for part in parts):
        raise ValueError(f"Invalid target icon path: {target_path}")
    return Path(*parts)


__all__ = [
    "is_probable_item_icon_entry",
    "path_list_to_settings",
    "safe_icon_library_component",
    "safe_relative_target_path",
    "settings_path_list",
]
