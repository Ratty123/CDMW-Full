"""Bounded source-mix scans and scene imports for UI workers."""

from __future__ import annotations

import dataclasses
import threading
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from types import MappingProxyType

from cdmw.domain.cancellation import raise_if_cancelled
from cdmw.core.source_mix import (
    SourceMixCandidate,
    normalize_source_mix_virtual_path,
    scan_loose_folder_source,
    scan_mod_archive_source,
)
from cdmw.models import ArchiveEntry
from cdmw.modding.scene_importer import SceneImportResult, import_scene_mesh_with_report


SOURCE_MIX_MAX_ENTRIES = 100_000
SOURCE_MIX_MAX_CANDIDATES = 50_000


@dataclass(frozen=True, slots=True)
class SourceMixIndexSnapshot:
    """Read-only views of atomically published archive indexes."""

    normalized_path: Mapping[str, Sequence[ArchiveEntry]]
    basename: Mapping[str, Sequence[ArchiveEntry]]

    @classmethod
    def capture(
        cls,
        normalized_path: Mapping[str, Sequence[ArchiveEntry]],
        basename: Mapping[str, Sequence[ArchiveEntry]],
    ) -> "SourceMixIndexSnapshot":
        return cls(
            MappingProxyType(normalized_path) if isinstance(normalized_path, dict) else normalized_path,
            MappingProxyType(basename) if isinstance(basename, dict) else basename,
        )


@dataclass(frozen=True, slots=True)
class SourceMixScanRequest:
    source_path: Path
    source_kind: str = "loose"
    label: str = ""
    target_entries: tuple[tuple[str, ArchiveEntry], ...] = ()
    index_snapshot: SourceMixIndexSnapshot | None = None
    max_entries: int = SOURCE_MIX_MAX_ENTRIES
    max_candidates: int = SOURCE_MIX_MAX_CANDIDATES
    request_id: int = 0


@dataclass(frozen=True, slots=True)
class SourceMixScanResult:
    request_id: int
    source_path: Path
    candidates: tuple[SourceMixCandidate, ...]


@dataclass(frozen=True, slots=True)
class SceneImportRequest:
    source_path: Path
    request_id: int = 0
    selected_member: str = ""


@dataclass(frozen=True, slots=True)
class SceneImportTaskResult:
    request_id: int
    source_path: Path
    scene: SceneImportResult


def resolve_source_mix_candidate_targets(
    candidates: Sequence[SourceMixCandidate],
    index_snapshot: SourceMixIndexSnapshot,
    *,
    stop_event: threading.Event | None = None,
) -> tuple[SourceMixCandidate, ...]:
    resolved: list[SourceMixCandidate] = []
    for index, candidate in enumerate(candidates):
        if not (index & 255):
            raise_if_cancelled(stop_event, "Source-mix target resolution cancelled.")
        normalized = candidate.normalized_virtual_path
        target_entry = next(
            (
                entry
                for entry in tuple(index_snapshot.normalized_path.get(normalized, ()) or ())
                if isinstance(entry, ArchiveEntry)
            ),
            None,
        )
        match_status = "exact" if target_entry is not None else "extra"
        confidence = "Exact virtual path" if target_entry is not None else "Extra source file"
        candidate_name = PurePosixPath(str(candidate.display_path or "").replace("\\", "/")).name.lower()
        if target_entry is None and candidate_name:
            candidate_extension = str(candidate.extension or PurePosixPath(candidate_name).suffix or "").lower()
            basename_entries = tuple(index_snapshot.basename.get(candidate_name, ()) or ())
            target_entry = next(
                (
                    entry
                    for entry in basename_entries
                    if isinstance(entry, ArchiveEntry)
                    and normalized
                    and normalize_source_mix_virtual_path(entry.path) == normalized
                ),
                None,
            )
            if target_entry is not None:
                match_status = "exact"
                confidence = "Exact virtual path"
            basename_matches: list[ArchiveEntry] = []
            for entry in basename_entries:
                if not isinstance(entry, ArchiveEntry):
                    continue
                if candidate_extension and str(entry.extension or "").lower() != candidate_extension:
                    continue
                basename_matches.append(entry)
                if len(basename_matches) > 1:
                    break
            if target_entry is None and len(basename_matches) == 1:
                target_entry = basename_matches[0]
                match_status = "basename"
                confidence = "Matched archive target by filename; common for compact or CrimsonForge-style loose packages."
            elif target_entry is None and len(basename_matches) > 1:
                confidence = "Extra source file; filename matched multiple archive targets, so no target was chosen automatically."
        default_action = "replace" if target_entry is not None else "skip"
        if candidate.conflict_status == "conflict":
            default_action = "resolve"
        resolved.append(
            dataclasses.replace(
                candidate,
                target_archive_entry=target_entry,
                match_status=match_status,
                confidence=confidence,
                default_action=default_action,
            )
        )
    raise_if_cancelled(stop_event, "Source-mix target resolution cancelled.")
    return tuple(resolved)


def run_source_mix_scan(
    request: SourceMixScanRequest,
    *,
    stop_event: threading.Event | None = None,
) -> SourceMixScanResult:
    raise_if_cancelled(stop_event, "Source-mix scan cancelled.")
    target_map = dict(request.target_entries)
    if request.source_kind == "loose":
        candidates = scan_loose_folder_source(
            request.source_path,
            label=request.label,
            target_entries_by_virtual_path=target_map,
            stop_event=stop_event,
            max_entries=request.max_entries,
            max_candidates=request.max_candidates,
        )
    elif request.source_kind == "mod_archive":
        candidates = scan_mod_archive_source(
            request.source_path,
            label=request.label,
            target_entries_by_virtual_path=target_map,
            stop_event=stop_event,
            max_candidates=request.max_candidates,
        )
    else:
        raise ValueError(f"Unsupported source-mix source kind: {request.source_kind}")
    if request.index_snapshot is not None:
        candidates = resolve_source_mix_candidate_targets(
            candidates,
            request.index_snapshot,
            stop_event=stop_event,
        )
    return SourceMixScanResult(
        request_id=int(request.request_id),
        source_path=Path(request.source_path),
        candidates=tuple(candidates),
    )


def run_scene_import(
    request: SceneImportRequest,
    *,
    stop_event: threading.Event | None = None,
) -> SceneImportTaskResult:
    scene = import_scene_mesh_with_report(
        request.source_path,
        selected_member=request.selected_member,
        stop_event=stop_event,
    )
    raise_if_cancelled(stop_event, "Scene import cancelled.")
    return SceneImportTaskResult(
        request_id=int(request.request_id),
        source_path=Path(request.source_path),
        scene=scene,
    )


__all__ = [
    "SOURCE_MIX_MAX_CANDIDATES",
    "SOURCE_MIX_MAX_ENTRIES",
    "SceneImportRequest",
    "SceneImportTaskResult",
    "SourceMixIndexSnapshot",
    "SourceMixScanRequest",
    "SourceMixScanResult",
    "resolve_source_mix_candidate_targets",
    "run_scene_import",
    "run_source_mix_scan",
]
