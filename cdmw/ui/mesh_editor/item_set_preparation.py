"""Prepare each worn PAC's own archive context without blocking the editor."""
from __future__ import annotations

from PySide6.QtCore import QObject, Signal

from cdmw.domain.archives.catalogue import ArchiveEntryDto
from cdmw.models import ArchiveEntry
from cdmw.services.archive_catalogue_service import ArchiveCatalogueService
from cdmw.ui.archive_browser.remote_preview_dependencies import (
    ArchivePreviewDependencySet,
    ArchiveRemotePreviewDependencyProvider,
)
from cdmw.ui.archive_browser.workflow_dependencies import ArchiveWorkflowDependencyContext


class ItemSetEditorPreparation(QObject):
    ready = Signal(object)
    failed = Signal(str)

    def __init__(self, service: object, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._service = service
        self._generation = 0
        self._members: tuple[ArchiveEntryDto, ...] = ()
        self._contexts: list[ArchiveWorkflowDependencyContext] = []
        self.edit_set = False
        self._provider = ArchiveRemotePreviewDependencyProvider(service, self, include_content_analysis=False)
        self._provider.ready.connect(self._prepared)
        self._provider.failed.connect(self._failed)
        service.session_published.connect(self._session_changed)
        if parent is not None:
            parent.destroyed.connect(self.cancel)

    @property
    def pending(self) -> bool:
        return bool(self._members)

    def start(self, selected: ArchiveEntry, members: tuple[ArchiveEntryDto, ...]) -> bool:
        self.cancel()
        session = self._service.current_session
        matching = [member for member in members
                    if ArchiveCatalogueService.compatibility_entry(member).identity == selected.identity]
        if (session is None or not 1 <= len(members) <= 33 or len(matching) != 1
                or len({member.entry_id for member in members}) != len(members)
                or any(member.session_id != session.session_id or member.extension.casefold() != ".pac"
                       for member in members)):
            self.failed.emit("This choice has incomplete or ambiguous dependencies.")
            return False
        self._members = (matching[0], *(member for member in members if member is not matching[0]))
        return self._request_next()

    def cancel(self, *_: object) -> None:
        self._generation += 1
        self._members = ()
        self._contexts.clear()
        self._provider.cancel(clear_snapshot=True)

    def _request_next(self) -> bool:
        return self._provider.request(self._members[len(self._contexts)], ui_request_id=self._generation)

    def _prepared(self, generation: int, snapshot: object) -> None:
        if generation != self._generation or not self._members:
            return
        member = self._members[len(self._contexts)]
        if (not isinstance(snapshot, ArchivePreviewDependencySet) or snapshot.truncated
                or snapshot.session_id != member.session_id or snapshot.entry_id != member.entry_id):
            self._failed(generation, "This choice has incomplete or ambiguous dependencies.")
            return
        self._contexts.append(ArchiveWorkflowDependencyContext(
            snapshot.selected_entry, snapshot.entries, snapshot.entries_by_normalized_path,
            snapshot.entries_by_basename, True,
        ))
        if len(self._contexts) < len(self._members):
            self._request_next()
            return
        contexts = tuple(self._contexts)
        self._members = ()
        self._contexts.clear()
        self.ready.emit(contexts)

    def _failed(self, generation: int, message: str) -> None:
        if generation != self._generation or not self._members:
            return
        self.cancel()
        self.failed.emit(message)

    def _session_changed(self, _session: object) -> None:
        if self.pending:
            self.cancel()
            self.failed.emit("The archive catalogue changed while preparing the item set.")


def prepare_item_set_for_editor(shell: object, entry: ArchiveEntry, *, edit_set: bool = False) -> bool:
    """Capture browser membership before any selection or catalogue can change."""
    bridge = getattr(shell.archive, "archive_remote_bridge", None)
    contains = getattr(bridge, "item_set_contains", None)
    if not callable(contains) or not contains(entry):
        pending = getattr(getattr(shell, "mesh_editor_tab", None), "item_set_preparation", None)
        if pending is not None:
            pending.cancel()
        return False
    tab = shell.mesh_editor_tab
    preparation = getattr(tab, "item_set_preparation", None)
    if preparation is None:
        preparation = ItemSetEditorPreparation(shell.archive.archive_catalogue_service, tab)
        tab.item_set_preparation = preparation
        preparation.ready.connect(lambda contexts: open_prepared_item_piece(shell, contexts, edit_set=preparation.edit_set))
        preparation.failed.connect(lambda message: shell.set_status_message(message, error=True))
    preparation.edit_set = bool(edit_set)
    preparation.start(entry, tuple(bridge.item_set_members))
    return True


def open_prepared_item_piece(shell: object, contexts: tuple, *, edit_set: bool = False) -> None:
    if not contexts or getattr(shell, "_shutting_down", False):
        return
    shell._open_archive_mesh_editor_with_dependencies(
        contexts[0].selected_entry, contexts[0], item_set_contexts=contexts,
        **({"edit_item_set": True} if edit_set else {}),
    )


def switch_item_piece(shell: object, index: int) -> None:
    contexts = tuple(getattr(shell.mesh_editor_tab, "item_set_contexts", ()))
    if isinstance(index, int) and 0 < index < len(contexts):
        open_prepared_item_piece(shell, (contexts[index], *contexts[:index], *contexts[index + 1:]))


def open_current_item_set(shell: object) -> None:
    bridge = getattr(shell.archive, "archive_remote_bridge", None)
    members = tuple(getattr(bridge, "item_set_members", ()))
    if members:
        from cdmw.ui.mesh_editor.tab_rust_editor import hold_warmups_for_mesh_editor_open

        hold_warmups_for_mesh_editor_open(shell.archive, shell)
        prepare_item_set_for_editor(shell, ArchiveCatalogueService.compatibility_entry(members[0]), edit_set=True)
