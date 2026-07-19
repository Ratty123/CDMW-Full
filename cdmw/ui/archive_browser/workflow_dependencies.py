"""Bounded archive dependency context shared by archive workflows."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass

from cdmw.models import ArchiveEntry
from cdmw.ui.archive_browser.remote_preview_dependencies import ArchivePreviewDependencySet


class ArchiveWorkflowDependenciesUnavailable(RuntimeError):
    """Raised when a v2 workflow has no complete worker-prepared dependency set."""


@dataclass(frozen=True, slots=True)
class ArchiveWorkflowDependencyContext:
    selected_entry: ArchiveEntry
    entries: tuple[ArchiveEntry, ...]
    entries_by_normalized_path: Mapping[str, Sequence[ArchiveEntry]]
    entries_by_basename: Mapping[str, Sequence[ArchiveEntry]]
    remote: bool

    def entry_for_path(self, path: str) -> ArchiveEntry | None:
        normalized = str(path or "").replace("\\", "/").strip("/").casefold()
        return next(iter(self.entries_by_normalized_path.get(normalized, ())), None)


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
        selected_entry = snapshot.selected_entry
        if selected_entry.identity != entry.identity:
            raise ArchiveWorkflowDependenciesUnavailable(
                "The prepared archive dependency set belongs to a different selected file."
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


__all__ = [
    "ArchiveWorkflowDependenciesUnavailable",
    "ArchiveWorkflowDependencyContext",
    "archive_workflow_dependency_context",
]
