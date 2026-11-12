"""Prepare each worn PAC's own archive context without blocking the editor."""
from __future__ import annotations

from cdmw.domain.archives.item_sets import MAX_SET_FILES

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
        if (session is None or not 1 <= len(members) <= MAX_SET_FILES or len(matching) != 1
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


def _path_key(value: object) -> str:
    return str(value or "").replace("\\", "/").strip().casefold()


def open_ticked_parts(shell: object) -> bool:
    """Open in Mesh Editor every file with a ticked part in the Scene panel, as one session (P5).

    An Item Finder set opens its ticked members; any other preview opens the
    previewed file, with the prefab components that are loaded and ticked as
    further files of the same session. Files with no ticked part are not
    opened. In a single file, the parts left unticked start with View off; no
    part is excluded from output unless the user changes Include.
    """

    archive = shell.archive
    panel = getattr(archive, "archive_item_set_components", None)
    files = tuple(panel.ticked_files()) if panel is not None else ()
    if not files:
        shell.set_status_message("Tick at least one part in the Scene panel to open it in Mesh Editor.", error=True)
        return False
    wanted = [path for path, _unticked in files]
    bridge = getattr(archive, "archive_remote_bridge", None)
    current = archive._current_archive_entry()
    if bridge is not None and bridge.item_set_contains(getattr(archive, "archive_preview_request_entry", None)):
        members = tuple(member for member in bridge.item_set_members if _path_key(member.path) in wanted)
        return _open_members(shell, members, files)
    if len(wanted) == 1:
        # One file: the ordinary open, its unticked parts hidden in the editor's view.
        entry = current if _path_key(getattr(current, "path", "")) == wanted[0] else None
        if entry is None:
            shell.set_status_message("Select the file in Browse Archives before opening it in Mesh Editor.", error=True)
            return False
        shell._mesh_editor_pending_hidden_parts = {wanted[0]: dict(files)[wanted[0]]}
        shell._launch_archive_mesh_editor_for_entry(entry)
        return True
    from cdmw.domain.archives.catalogue import ArchiveLookupKind
    from cdmw.ui.archive_browser.remote_entry_lookup import lookup_requests, start_live_catalogue_lookup

    session = getattr(bridge, "current_session", None)
    if session is None:
        shell.set_status_message("Load the game's archives before opening several files.", error=True)
        return False
    primary = _path_key(getattr(current, "path", ""))
    ordered = sorted(wanted, key=lambda path: path != primary)

    def found(outcome) -> None:
        by_path = {}
        for dto in outcome.entries:
            key = _path_key(dto.path)
            if key in ordered and (key not in by_path or dto.is_active_override):
                by_path[key] = dto
        if len(by_path) != len(ordered):
            missing = ", ".join(path for path in ordered if path not in by_path)
            shell.set_status_message(f"These files could not be found in the archives: {missing}", error=True)
            return
        _open_members(shell, tuple(by_path[path] for path in ordered), files)

    start_live_catalogue_lookup(
        archive, "_scene_ticked_lookup",
        lookup_requests(session.session_id, ArchiveLookupKind.EXACT_PATHS, ordered),
        on_done=found,
        on_error=lambda message: shell.set_status_message(str(message), error=True),
    )
    return True


def _open_members(shell: object, members: tuple, files: tuple) -> bool:
    if not members:
        shell.set_status_message("None of the ticked files is part of this preview.", error=True)
        return False
    if len(members) > MAX_SET_FILES:
        shell.set_status_message(f"One Mesh Editor session holds at most {MAX_SET_FILES} files.", error=True)
        return False
    from cdmw.ui.mesh_editor.tab_rust_editor import hold_warmups_for_mesh_editor_open

    hold_warmups_for_mesh_editor_open(shell.archive, shell)
    shell._mesh_editor_pending_hidden_parts = dict(files)
    tab = shell.mesh_editor_tab
    preparation = getattr(tab, "item_set_preparation", None)
    if preparation is None:
        preparation = ItemSetEditorPreparation(shell.archive.archive_catalogue_service, tab)
        tab.item_set_preparation = preparation
        preparation.ready.connect(lambda contexts: open_prepared_item_piece(shell, contexts, edit_set=preparation.edit_set))
        preparation.failed.connect(lambda message: shell.set_status_message(message, error=True))
    preparation.edit_set = True
    return bool(preparation.start(ArchiveCatalogueService.compatibility_entry(members[0]), members))
