"""Pure archive filter state and category rules."""

from __future__ import annotations

import re
import threading
from dataclasses import dataclass
from typing import Callable, Dict, List, Optional, Sequence

from cdmw.constants import (
    ARCHIVE_AUDIO_EXTENSIONS,
    ARCHIVE_IMAGE_EXTENSIONS,
    ARCHIVE_TEXT_EXTENSIONS,
    ARCHIVE_VIDEO_EXTENSIONS,
)
from cdmw.models import RunCancelled


@dataclass(frozen=True, slots=True)
class ArchiveFilterState:
    query: str = ""
    asset_family: str = ""
    case_sensitive: bool = False

    @property
    def normalized_query(self) -> str:
        value = self.query.strip()
        return value if self.case_sensitive else value.lower()


def archive_browser_entry_category(entry: object) -> str:
    ext = str(getattr(entry, "extension", "") or "").lower()
    path = str(getattr(entry, "path", "") or "").replace("\\", "/").lower()
    if ext in ARCHIVE_IMAGE_EXTENSIONS:
        return "Texture"
    if ext in {".pami", ".pac_xml", ".pam_xml", ".pamlod_xml"}:
        return "Material Sidecar"
    if ext in {".pab"}:
        return "Skeleton/Rig"
    if ext in {".hkx", ".hkt"} and any(token in path for token in ("meshphysics", "havokphysics", "ragdoll", "physics")):
        return "Physics"
    if ext in {".hkx", ".hkt", ".paa", ".paa_metabin", ".motionblending", ".pae", ".paem"}:
        return "Animation"
    if ext in ARCHIVE_AUDIO_EXTENSIONS:
        return "Audio"
    if ext in ARCHIVE_VIDEO_EXTENSIONS:
        return "Video"
    if ext in {".pac", ".pam", ".pamlod", ".obj", ".fbx", ".dae", ".gltf", ".glb", ".mesh", ".mdl", ".model", ".pat", ".patx"}:
        return "Mesh"
    if ext in ARCHIVE_TEXT_EXTENSIONS or ext in {".meshinfo", ".motionblending", ".paa_metabin", ".prefab", ".pappt", ".pamhc", ".seqmt"}:
        return "Text/Metadata"
    return "Other"


def build_archive_category_entry_index(
    entries: Sequence[object],
    *,
    on_progress: Optional[Callable[[int, int, str], None]] = None,
    stop_event: Optional[threading.Event] = None,
) -> Dict[str, List[int]]:
    grouped: Dict[str, List[int]] = {}
    total_entries = len(entries)
    progress_total = max(total_entries, 1)
    update_every = 50_000 if total_entries >= 500_000 else 10_000 if total_entries >= 100_000 else 2_000
    if on_progress:
        on_progress(0 if total_entries > 0 else 1, progress_total, f"Indexing archive categories... 0 / {total_entries:,} entries")
    for entry_index, entry in enumerate(entries):
        current = entry_index + 1
        if stop_event is not None and (current == 1 or current % 2048 == 0) and stop_event.is_set():
            raise RunCancelled("Archive category indexing cancelled.")
        grouped.setdefault(archive_browser_entry_category(entry), []).append(entry_index)
        if on_progress and (current == 1 or current % update_every == 0 or current == total_entries):
            on_progress(current, progress_total, f"Indexing archive categories... {current:,} / {total_entries:,} entries")
    return grouped


def archive_filter_text_explicitly_requests_item_name(filter_text: object) -> bool:
    return bool(re.search(r"(^|\s)name\s*:", str(filter_text or "").strip(), flags=re.IGNORECASE))


def archive_filter_text_needs_item_name_search(filter_text: object) -> bool:
    text = str(filter_text or "").strip()
    if not text:
        return False
    if archive_filter_text_explicitly_requests_item_name(text):
        return True
    return not any(char in text for char in "/\\_*.?[]")


__all__ = [
    "ArchiveFilterState",
    "archive_browser_entry_category",
    "archive_filter_text_explicitly_requests_item_name",
    "archive_filter_text_needs_item_name_search",
    "build_archive_category_entry_index",
]
