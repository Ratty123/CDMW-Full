"""Bounded archive dependency context shared by archive workflows."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from itertools import chain
from types import MappingProxyType

from cdmw.models import ArchiveEntry
from cdmw.ui.archive_browser.remote_preview_dependencies import (
    MAX_ARCHIVE_PREVIEW_ENTRIES,
    ArchivePreviewDependencySet,
)


MAX_MERGED_ARCHIVE_WORKFLOW_ENTRIES = MAX_ARCHIVE_PREVIEW_ENTRIES * 2


class ArchiveWorkflowDependenciesUnavailable(RuntimeError):
    """Raised when a v2 workflow has no complete worker-prepared dependency set."""


@dataclass(frozen=True, slots=True)
class ArchiveWorkflowDependencyContext:
    selected_entry: ArchiveEntry
    entries: Sequence[ArchiveEntry]
    entries_by_normalized_path: Mapping[str, Sequence[ArchiveEntry]]
    entries_by_basename: Mapping[str, Sequence[ArchiveEntry]]
    remote: bool

    def entry_for_path(self, path: str) -> ArchiveEntry | None:
        normalized = str(path or "").replace("\\", "/").strip("/").casefold()
        return next(iter(self.entries_by_normalized_path.get(normalized, ())), None)

    def entry_matching(self, entry: ArchiveEntry) -> ArchiveEntry | None:
        """Return the prepared/bounded context member for an entry identity."""

        if not isinstance(entry, ArchiveEntry):
            return None
        return next((candidate for candidate in self.entries if candidate.identity == entry.identity), None)


def archive_workflow_dependency_context(
    owner: object,
    entry: ArchiveEntry,
) -> ArchiveWorkflowDependencyContext:
    """Return legacy indexes or the bounded prepared v2 snapshot for ``entry``."""

    if not isinstance(entry, ArchiveEntry):
        raise ArchiveWorkflowDependenciesUnavailable("The archive workflow has no valid selected entry.")
    remote_bridge = getattr(owner, "archive_remote_bridge", None)
    if remote_bridge is not None and bool(getattr(remote_bridge, "displays_v2", False)):
        resolver = getattr(remote_bridge, "prepared_dependencies_for", None)
        snapshot = resolver(entry) if callable(resolver) else None
        if not isinstance(snapshot, ArchivePreviewDependencySet):
            raise ArchiveWorkflowDependenciesUnavailable(
                "The archive worker is still preparing the selected file and its dependencies."
            )
        if snapshot.truncated:
            raise ArchiveWorkflowDependenciesUnavailable(
                "The archive dependency set exceeded the 4,096-entry safety bound."
            )
        selected_entry = next(
            (candidate for candidate in snapshot.entries if candidate.identity == entry.identity),
            None,
        )
        if selected_entry is None:
            raise ArchiveWorkflowDependenciesUnavailable(
                "The prepared archive dependency set does not contain the requested file."
            )
        if any(candidate.prepared_path is None for candidate in snapshot.entries):
            raise ArchiveWorkflowDependenciesUnavailable(
                "The archive worker did not materialize every bounded workflow dependency."
            )
        return ArchiveWorkflowDependencyContext(
            selected_entry=selected_entry,
            entries=snapshot.entries,
            entries_by_normalized_path=snapshot.entries_by_normalized_path,
            entries_by_basename=snapshot.entries_by_basename,
            remote=True,
        )

    return ArchiveWorkflowDependencyContext(
        selected_entry=entry,
        entries=tuple(getattr(owner, "archive_entries", ()) or ()),
        entries_by_normalized_path=getattr(owner, "archive_entries_by_normalized_path", {}) or {},
        entries_by_basename=getattr(owner, "archive_entries_by_basename", {}) or {},
        remote=False,
    )


def merge_archive_workflow_dependency_contexts(
    selected_entry: ArchiveEntry,
    *contexts: ArchiveWorkflowDependencyContext,
) -> ArchiveWorkflowDependencyContext:
    """Merge bounded contexts for a workflow that compares multiple entries."""

    if not isinstance(selected_entry, ArchiveEntry) or not contexts:
        raise ArchiveWorkflowDependenciesUnavailable(
            "The archive workflow has no dependency contexts to merge."
        )
    if not all(context.remote for context in contexts):
        raise ArchiveWorkflowDependenciesUnavailable(
            "Only prepared standalone-worker dependency contexts may be merged."
        )
    entries: list[ArchiveEntry] = []
    seen_identities: set[object] = set()
    for context in contexts:
        for entry in chain((context.selected_entry,), context.entries):
            identity = entry.identity
            if identity in seen_identities:
                continue
            if len(entries) >= MAX_MERGED_ARCHIVE_WORKFLOW_ENTRIES:
                raise ArchiveWorkflowDependenciesUnavailable(
                    "The merged archive dependency set exceeded the 8,192-entry safety bound."
                )
            entries.append(entry)
            seen_identities.add(identity)
    merged_selected = next(
        (entry for entry in entries if entry.identity == selected_entry.identity),
        None,
    )
    if merged_selected is None:
        raise ArchiveWorkflowDependenciesUnavailable(
            "The merged archive dependency set does not contain the selected file."
        )
    paths: dict[str, list[ArchiveEntry]] = {}
    basenames: dict[str, list[ArchiveEntry]] = {}
    for entry in entries:
        normalized_path = str(entry.path or "").replace("\\", "/").strip("/").casefold()
        if normalized_path:
            paths.setdefault(normalized_path, []).append(entry)
        basename = entry.basename.strip().casefold()
        if basename:
            basenames.setdefault(basename, []).append(entry)
    return ArchiveWorkflowDependencyContext(
        selected_entry=merged_selected,
        entries=tuple(entries),
        entries_by_normalized_path=MappingProxyType(
            {key: tuple(value) for key, value in paths.items()}
        ),
        entries_by_basename=MappingProxyType(
            {key: tuple(value) for key, value in basenames.items()}
        ),
        remote=True,
    )


__all__ = [
    "ArchiveWorkflowDependenciesUnavailable",
    "ArchiveWorkflowDependencyContext",
    "MAX_MERGED_ARCHIVE_WORKFLOW_ENTRIES",
    "archive_workflow_dependency_context",
    "merge_archive_workflow_dependency_contexts",
]
