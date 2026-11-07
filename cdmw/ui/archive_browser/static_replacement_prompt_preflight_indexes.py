"""Texture lookup indexes for the static replacement preflight.

Split out of :mod:`static_replacement_prompt_preflight` to keep that module
inside its declared line cap. The preflight either inherits the caller's
already-built global indexes or builds a local one from the target's own
relationship graph, and it reports which of the two happened, so the choice
is worth reading on its own.
"""

from __future__ import annotations

import threading
from collections.abc import Mapping, Sequence
from typing import TYPE_CHECKING

from cdmw.domain.cancellation import raise_if_cancelled
from cdmw.models import ArchiveEntry
from cdmw.services.archive_query_service import build_archive_relationship_references
from cdmw.services.archive_workflow_service import _collect_same_stem_related_target_basenames
from cdmw.ui.archive_browser.static_replacement_texture_sources import (
    archive_texture_lookup_indexes_for_alignment,
)

if TYPE_CHECKING:  # the request type lives in the module this was split from
    from cdmw.ui.archive_browser.static_replacement_prompt_preflight import (
        StaticReplacementPromptPreflightRequest,
    )


PREPARED_DEPENDENCY_SCOPE = "prepared_dependencies"


def preflight_archive_indexes(
    owner: object,
    entry: ArchiveEntry,
) -> tuple[
    Mapping[str, Sequence[ArchiveEntry]],
    Mapping[str, Sequence[ArchiveEntry]],
    Mapping[str, Sequence[ArchiveEntry]],
    str,
]:
    """Return the path, basename and extension indexes the preflight searches.

    The legacy catalogue publishes global indexes. The live catalogue never fills
    them; it prepares each selected model with its bounded dependency set (the
    material sidecar and its textures among them), so the preflight searches that
    set instead of empty maps that would hide the model's own ``.pac_xml``.
    """

    archive = getattr(owner, "archive", owner)
    path_index = getattr(archive, "archive_entries_by_normalized_path", {}) or {}
    basename_index = getattr(archive, "archive_entries_by_basename", {}) or {}
    extension_index = getattr(archive, "archive_entries_by_extension", {}) or {}
    if path_index and basename_index:
        return path_index, basename_index, extension_index, "global_indexes"
    from cdmw.ui.archive_browser.workflow_dependencies import (
        ArchiveWorkflowDependenciesUnavailable,
        archive_workflow_dependency_context,
    )

    try:
        dependencies = archive_workflow_dependency_context(owner, entry)
    except ArchiveWorkflowDependenciesUnavailable:
        return path_index, basename_index, extension_index, "global_indexes"
    if not dependencies.remote or not dependencies.entries_by_normalized_path:
        return path_index, basename_index, extension_index, "global_indexes"
    by_extension: dict[str, list[ArchiveEntry]] = {}
    for dependency in dependencies.entries:
        extension = str(getattr(dependency, "extension", "") or "").lower()
        if extension:
            by_extension.setdefault(extension, []).append(dependency)
    return (
        dependencies.entries_by_normalized_path,
        dependencies.entries_by_basename,
        {key: tuple(value) for key, value in by_extension.items()},
        PREPARED_DEPENDENCY_SCOPE,
    )


def texture_lookup_indexes(
    request: "StaticReplacementPromptPreflightRequest",
    stop_event: threading.Event,
) -> tuple[
    Mapping[str, Sequence[ArchiveEntry]],
    Mapping[str, Sequence[ArchiveEntry]],
    str,
    int,
    int,
    int,
]:
    if request.archive_entries_by_normalized_path and request.archive_entries_by_basename:
        return (
            request.archive_entries_by_normalized_path,
            request.archive_entries_by_basename,
            request.index_scope,
            len(tuple(request.archive_entries_by_extension.get(".dds", ()) or ())),
            0,
            0,
        )
    raise_if_cancelled(stop_event, "Static replacement preflight stopped by user.")
    references = build_archive_relationship_references(
        request.entry,
        archive_entries_by_normalized_path=request.archive_entries_by_normalized_path,
        archive_entries_by_basename=request.archive_entries_by_basename,
    )
    related_basenames = _collect_same_stem_related_target_basenames(request.entry)
    indexes = archive_texture_lookup_indexes_for_alignment(
        target_entry=request.entry,
        graph_references=references,
        related_target_basenames=tuple(related_basenames),
        extension_index=request.archive_entries_by_extension,
    )
    raise_if_cancelled(stop_event, "Static replacement preflight stopped by user.")
    return (
        indexes.path_index,
        indexes.basename_index,
        "local_dds_extension",
        indexes.dds_count,
        indexes.sidecar_count,
        indexes.graph_reference_count,
    )
