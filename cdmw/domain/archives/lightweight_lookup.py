"""Pure lookup adapters for bounded archive-entry collections."""
from __future__ import annotations

from collections import Counter
import threading
from collections.abc import Sequence
from typing import Dict, List, Optional

from cdmw.models import ArchiveEntry, ArchiveEntryIdentity, RunCancelled
from cdmw.domain.archives.format import normalize_archive_extension_filter

_LIGHTWEIGHT_MESH_EXTENSIONS = frozenset({".pac", ".pam", ".pamlod"})


def build_archive_lightweight_lookup_indexes(
    entries: Sequence[ArchiveEntry],
    *,
    stop_event: Optional[threading.Event] = None,
) -> tuple[
    Dict[str, List[ArchiveEntry]],
    Counter[str],
    Dict[str, List[ArchiveEntry]],
    Dict[ArchiveEntryIdentity, ArchiveEntry],
]:
    """Build extension and companion lookups for a bounded entry snapshot."""

    extension_index: Dict[str, List[ArchiveEntry]] = {}
    mesh_path_index: Dict[str, List[ArchiveEntry]] = {}
    mesh_entries: List[ArchiveEntry] = []
    for index, entry in enumerate(entries):
        if index % 4096 == 0 and stop_event is not None and stop_event.is_set():
            raise RunCancelled("Archive lookup indexing cancelled.")
        extension = normalize_archive_extension_filter(entry.extension)
        if not extension:
            continue
        extension_index.setdefault(extension, []).append(entry)
        if extension in _LIGHTWEIGHT_MESH_EXTENSIONS:
            normalized_path = str(entry.path or "").replace("\\", "/").strip().strip("/").casefold()
            if normalized_path:
                mesh_path_index.setdefault(normalized_path, []).append(entry)
            if extension in {".pam", ".pamlod"}:
                mesh_entries.append(entry)

    companion_index: Dict[ArchiveEntryIdentity, ArchiveEntry] = {}
    for index, entry in enumerate(mesh_entries):
        if index % 1024 == 0 and stop_event is not None and stop_event.is_set():
            raise RunCancelled("Archive companion indexing cancelled.")
        normalized_path = str(entry.path or "").replace("\\", "/").strip().strip("/").casefold()
        companion_paths: List[str] = []
        if entry.extension == ".pam" and normalized_path.endswith(".pam"):
            companion_paths.append(f"{normalized_path[:-4]}.pamlod")
            stem = normalized_path[:-4]
            if stem.endswith("_breakable"):
                companion_paths.append(f"{stem[:-10]}.pamlod")
        elif entry.extension == ".pamlod" and normalized_path.endswith(".pamlod"):
            companion_paths.append(f"{normalized_path[:-7]}.pam")
        for companion_path in companion_paths:
            candidates = mesh_path_index.get(companion_path, ())
            if not candidates:
                continue
            companion = next(
                (candidate for candidate in candidates if candidate.pamt_path == entry.pamt_path),
                candidates[0],
            )
            companion_index[entry.identity] = companion
            break

    return (
        extension_index,
        Counter({extension: len(items) for extension, items in extension_index.items()}),
        mesh_path_index,
        companion_index,
    )
