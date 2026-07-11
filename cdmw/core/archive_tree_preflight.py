"""Archive installation tree preflight checks."""

from __future__ import annotations

import re
from pathlib import Path

from cdmw.core.archive_scan_cache import discover_pamt_files


def find_suspicious_archive_tree_roots(package_root: Path) -> tuple[Path, ...]:
    """Return nested PAMT locations outside the game's canonical archive layout."""
    root = package_root.expanduser().resolve()
    if root.is_file():
        return ()
    suspicious: set[Path] = set()
    for path in discover_pamt_files(root):
        parts = path.relative_to(root).parts
        if len(parts) == 1 or len(parts) == 2 and re.fullmatch(r"\d{4}", parts[0]):
            continue
        if parts[0].casefold() == "game_files":
            if len(parts) == 2 or len(parts) == 3 and re.fullmatch(r"\d{4}", parts[1]):
                continue
            suspicious.add(root.joinpath(*parts[:-1]))
            continue
        suspicious.add(root.joinpath(*parts[:-1]) if re.fullmatch(r"\d{4}", parts[0]) else root / parts[0])
    return tuple(sorted(suspicious, key=lambda path: str(path).casefold()))


__all__ = ["find_suspicious_archive_tree_roots"]
