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
            "global_indexes",
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
