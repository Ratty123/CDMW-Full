from __future__ import annotations

import sys
from pathlib import Path
from typing import List, Optional, Tuple

from PySide6.QtGui import QIcon


def _theme_icon_stem(theme_key: Optional[str]) -> str:
    text = str(theme_key or "").strip().lower()
    if not text:
        return ""
    return "".join(character if character.isalnum() or character in {"_", "-"} else "_" for character in text)


def iter_app_icon_candidate_paths(theme_key: Optional[str] = None) -> Tuple[Path, ...]:
    search_roots: List[Path] = []

    def add_root(root: Optional[Path]) -> None:
        if root is None:
            return
        try:
            normalized = root.resolve()
        except OSError:
            normalized = root
        if normalized not in search_roots:
            search_roots.append(normalized)

    if getattr(sys, "frozen", False):
        meipass = getattr(sys, "_MEIPASS", None)
        if meipass:
            add_root(Path(str(meipass)))
        executable_dir = Path(sys.executable).resolve().parent
        add_root(executable_dir)
        add_root(executable_dir / "_internal")
    add_root(Path(__file__).resolve().parents[2])
    add_root(Path.cwd())

    theme_stem = _theme_icon_stem(theme_key)
    theme_candidates: Tuple[Path, ...] = ()
    if theme_stem:
        theme_candidates = (
            Path("assets") / "theme_icons" / f"cdmw_{theme_stem}.ico",
            Path("assets") / "theme_icons" / f"cdmw_{theme_stem}.png",
            Path("_internal") / "assets" / "theme_icons" / f"cdmw_{theme_stem}.ico",
            Path("_internal") / "assets" / "theme_icons" / f"cdmw_{theme_stem}.png",
        )
    relative_candidates = theme_candidates + (
        Path("assets") / "cdmw.ico",
        Path("assets") / "cdmw.png",
        Path("_internal") / "assets" / "cdmw.ico",
        Path("_internal") / "assets" / "cdmw.png",
        Path("cdmw.ico"),
        Path("cdmw.png"),
    )
    candidates: List[Path] = []
    seen: set[str] = set()
    for root in search_roots:
        for relative_path in relative_candidates:
            candidate = root / relative_path
            candidate_key = str(candidate).casefold()
            if candidate_key in seen:
                continue
            seen.add(candidate_key)
            candidates.append(candidate)
    return tuple(candidates)


def resolve_app_icon_path(theme_key: Optional[str] = None) -> Optional[Path]:
    for candidate in iter_app_icon_candidate_paths(theme_key):
        if candidate.is_file():
            return candidate
    return None


def load_app_icon(theme_key: Optional[str] = None) -> Tuple[QIcon, Optional[Path]]:
    for candidate in iter_app_icon_candidate_paths(theme_key):
        if not candidate.is_file():
            continue
        icon = QIcon(str(candidate))
        if not icon.isNull():
            return icon, candidate
    return QIcon(), None
