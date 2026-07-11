from __future__ import annotations

from functools import lru_cache
from pathlib import Path


# Guard inputs are immutable within one pytest process; bound retained aggregates.
@lru_cache(maxsize=4)
def mesh_editor_tab_source(repo_root: Path | None = None) -> str:
    """Return the public Mesh Editor tab plus its bounded implementation owners."""

    root = repo_root or Path(__file__).resolve().parents[1]
    owner_root = root / "cdmw" / "ui" / "mesh_editor"
    paths = (owner_root / "tab.py", *sorted(owner_root.glob("tab_*.py")))
    return "\n".join(path.read_text(encoding="utf-8") for path in paths)
