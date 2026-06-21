from __future__ import annotations

import threading
from collections import defaultdict
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Tuple

from cdmw.core.common import raise_if_cancelled
from cdmw.core.texture_pipeline.config import filter_matches

def collect_dds_files(
    original_root: Path,
    include_filter_patterns: Sequence[str],
    stop_event: Optional[threading.Event] = None,
) -> List[Path]:
    files: List[Path] = []

    for path in original_root.rglob("*"):
        raise_if_cancelled(stop_event, "Scan cancelled by user.")
        if not path.is_file() or path.suffix.lower() != ".dds":
            continue

        relative_path = path.relative_to(original_root)
        if filter_matches(relative_path, include_filter_patterns):
            files.append(path)

    files.sort()
    return files


def find_png_matches(
    png_root: Path,
    stop_event: Optional[threading.Event] = None,
) -> Tuple[Dict[str, Path], Dict[str, List[Path]], int]:
    relative_index: Dict[str, Path] = {}
    basename_index: Dict[str, List[Path]] = defaultdict(list)
    count = 0

    for path in png_root.rglob("*"):
        raise_if_cancelled(stop_event)
        if not path.is_file() or path.suffix.lower() != ".png":
            continue
        rel_key = path.relative_to(png_root).as_posix().lower()
        relative_index[rel_key] = path
        basename_index[path.name.lower()].append(path)
        count += 1

    return relative_index, basename_index, count


def find_png_matches_across_roots(
    png_roots: Sequence[Optional[Path]],
    stop_event: Optional[threading.Event] = None,
) -> Tuple[Dict[str, Path], Dict[str, List[Path]], int]:
    relative_index: Dict[str, Path] = {}
    basename_index: Dict[str, List[Path]] = defaultdict(list)
    total_count = 0
    seen_roots: set[str] = set()

    for root in png_roots:
        if root is None:
            continue
        try:
            normalized_root_key = str(root.resolve())
        except OSError:
            normalized_root_key = str(root)
        if normalized_root_key in seen_roots:
            continue
        seen_roots.add(normalized_root_key)
        root_relative_index, root_basename_index, root_count = find_png_matches(root, stop_event=stop_event)
        relative_index.update(root_relative_index)
        for basename, paths in root_basename_index.items():
            basename_index[basename].extend(paths)
        total_count += root_count

    return relative_index, basename_index, total_count


def resolve_png(
    rel_path_from_original_root: Path,
    relative_index: Dict[str, Path],
    basename_index: Dict[str, List[Path]],
    allow_unique_basename_fallback: bool,
) -> Tuple[Optional[Path], str]:
    rel_png = rel_path_from_original_root.with_suffix(".png").as_posix().lower()
    exact = relative_index.get(rel_png)
    if exact:
        return exact, "exact relative match"

    if not allow_unique_basename_fallback:
        return None, "no exact relative PNG match found"

    same_name = basename_index.get(rel_path_from_original_root.with_suffix(".png").name.lower(), [])
    if len(same_name) == 1:
        return same_name[0], "unique basename fallback"
    if len(same_name) > 1:
        return None, f"ambiguous basename fallback, {len(same_name)} matches found"

    return None, "no matching PNG found"
