"""Draft requests for Mesh Editor sessions and saved-work dependency contexts."""

from __future__ import annotations

from collections import ChainMap
from collections.abc import Mapping, Sequence

from cdmw.models import ArchiveEntry
from cdmw.services.mesh_archive_results import RESULT_NOTES
from cdmw.services.mesh_saved_work_service import MeshDraftRequest
from cdmw.ui.archive_browser.workflow_dependencies import (
    ArchiveWorkflowDependencyContext,
)

_EDITED_NOTES = RESULT_NOTES


def edited_companions(
    entry: ArchiveEntry,
    dependencies: ArchiveWorkflowDependencyContext | None,
) -> tuple[ArchiveEntry, ...]:
    """Edited or added files a draft keeps a copy of, besides its own mesh."""

    if dependencies is None:
        return ()
    return tuple(
        candidate for candidate in dependencies.entries
        if candidate.prepared_note in _EDITED_NOTES
        and candidate.prepared_path is not None
        and candidate.identity != entry.identity
    )


def default_session_draft_request(
    entry: ArchiveEntry,
    dependencies: ArchiveWorkflowDependencyContext | None,
) -> MeshDraftRequest:
    """A fresh open saves a new draft; an edited result counts as a later pass."""

    return MeshDraftRequest(
        edit_pass=2 if entry.prepared_note in _EDITED_NOTES else 1,
        baseline_entries=edited_companions(entry, dependencies),
    )


def next_pass_draft_request(lineage: Mapping[str, object], prepared: object) -> MeshDraftRequest:
    """Start next edit pass: the new draft inherits its name and game file."""

    assets = tuple(getattr(prepared, "assets", ()) or ())
    selected = assets[0] if assets else None
    entries = tuple(getattr(prepared, "entries", ()) or ())
    return MeshDraftRequest(
        edit_pass=max(1, int(lineage.get("edit_pass") or 1)) + 1,
        display_name=str(lineage.get("display_name") or ""),
        game_source_sha256=str(lineage.get("game_source_sha256") or ""),
        baseline_entries=tuple(
            candidate for candidate in entries
            if candidate.prepared_note in _EDITED_NOTES and candidate.prepared_path is not None
            and (selected is None or candidate.identity != selected.identity)
        ),
    )


def _normalized(path: str) -> str:
    return str(path or "").replace("\\", "/").strip().strip("/").casefold()


def overlay_dependency_context(
    base: ArchiveWorkflowDependencyContext,
    selected: ArchiveEntry,
    replacements: Sequence[ArchiveEntry],
) -> ArchiveWorkflowDependencyContext:
    """Use saved files in place of the current game files they were made from.

    Everything else, such as materials, skeleton and textures, still comes from
    the current game files.
    """

    by_identity = {entry.identity: entry for entry in (*replacements, selected)}
    entries = [by_identity.pop(entry.identity, entry) for entry in base.entries]
    entries.extend(by_identity.values())
    paths: dict[str, tuple[ArchiveEntry, ...]] = {}
    basenames: dict[str, tuple[ArchiveEntry, ...]] = {}
    for entry in (*replacements, selected):
        paths[_normalized(entry.path)] = (entry,)
        basenames[entry.basename.casefold()] = (entry,)
    return ArchiveWorkflowDependencyContext(
        selected_entry=selected,
        entries=tuple(entries),
        # A read-only overlay; the base index may hold the whole archive.
        entries_by_normalized_path=ChainMap(paths, base.entries_by_normalized_path),
        entries_by_basename=ChainMap(basenames, base.entries_by_basename),
        remote=base.remote,
        material_contexts=base.material_contexts,
    )


__all__ = [
    "default_session_draft_request",
    "edited_companions",
    "next_pass_draft_request",
    "overlay_dependency_context",
]
