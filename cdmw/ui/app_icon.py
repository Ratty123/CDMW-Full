from __future__ import annotations

import sys
from pathlib import Path
from typing import List, Optional, Tuple


def iter_app_icon_candidate_paths() -> Tuple[Path, ...]:
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

    relative_candidates = (
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


def resolve_app_icon_path() -> Optional[Path]:
    for candidate in iter_app_icon_candidate_paths():
        if candidate.is_file():
            return candidate
    return None
