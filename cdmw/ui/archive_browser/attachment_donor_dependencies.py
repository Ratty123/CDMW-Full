"""Bounded archive dependency helpers for attachment donor selection."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from pathlib import PurePosixPath
from typing import List, Optional, Tuple

from cdmw.models import ArchiveEntry
from cdmw.ui.archive_browser.workflow_dependencies import (
    ArchiveWorkflowDependenciesUnavailable,
    ArchiveWorkflowDependencyContext,
    archive_workflow_dependency_context,
)


def attachment_donor_dependencies(owner: object, target_entry: object):
    if not isinstance(target_entry, ArchiveEntry):
        return None
    try:
        dependencies = archive_workflow_dependency_context(owner, target_entry)
    except ArchiveWorkflowDependenciesUnavailable as exc:
        owner.set_status_message(f"Attachment source picker is unavailable: {exc}", error=True)
        return None
    prepared_by_identity = (
        {entry.identity: entry for entry in dependencies.entries}
        if dependencies.remote
        else None
    )
    sidecars_by_path = {} if dependencies.remote else owner.archive_sidecar_entries_by_texture_path
    sidecars_by_basename = {} if dependencies.remote else owner.archive_sidecar_entries_by_texture_basename
    return (
        dependencies.selected_entry,
        dependencies,
        prepared_by_identity,
        sidecars_by_path,
        sidecars_by_basename,
    )


def attachment_donor_preview_inputs(
    owner: object,
    preview_entry: ArchiveEntry,
    dependencies: ArchiveWorkflowDependencyContext,
    sidecars_by_path: Mapping[str, Sequence[ArchiveEntry]],
    sidecars_by_basename: Mapping[str, Sequence[ArchiveEntry]],
) -> tuple[object, ...]:
    return (
        owner._find_archive_preview_companion_entry(
            preview_entry,
            entries_by_normalized_path=dependencies.entries_by_normalized_path,
        ),
        dependencies.entries_by_normalized_path,
        dependencies.entries_by_basename,
        sidecars_by_path,
        sidecars_by_basename,
    )


def prepared_attachment_donor_candidate(
    prepared_by_identity: Optional[Mapping[object, ArchiveEntry]],
    candidate: object,
) -> Optional[ArchiveEntry]:
    if not isinstance(candidate, ArchiveEntry):
        return None
    return candidate if prepared_by_identity is None else prepared_by_identity.get(candidate.identity)


def attachment_donor_catalog_scope_entries(
    owner: object,
    row: Mapping[str, object],
    dependencies: ArchiveWorkflowDependencyContext,
) -> Tuple[List[ArchiveEntry], int, int]:
    if not dependencies.remote:
        return owner._resolve_archive_asset_catalog_scope_entries(row, include_related=True)
    values: List[str] = []
    for key in ("pac_files", "model_stems", "icon_paths"):
        values.extend(owner._archive_asset_catalog_row_values(row, key))
    normalized_values = tuple(
        str(value or "").replace("\\", "/").strip().strip("/").casefold()
        for value in values
        if str(value or "").strip()
    )
    matches: List[ArchiveEntry] = []
    for candidate in dependencies.entries:
        candidate_path = candidate.path.replace("\\", "/").strip().strip("/").casefold()
        candidate_name = PurePosixPath(candidate_path).name.casefold()
        candidate_stem = PurePosixPath(candidate_name).stem.casefold()
        if any(
            value in {candidate_path, candidate_name, candidate_stem}
            or (not PurePosixPath(value).suffix and candidate_stem == PurePosixPath(value).name.casefold())
            for value in normalized_values
        ):
            matches.append(candidate)
    bounded_matches = matches[:1000]
    return bounded_matches, len(bounded_matches), 0


__all__ = [
    "attachment_donor_catalog_scope_entries",
    "attachment_donor_dependencies",
    "attachment_donor_preview_inputs",
    "prepared_attachment_donor_candidate",
]
