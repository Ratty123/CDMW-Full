"""Browse Archives > Files DMM adds: files a DMM mod serves that the game does not have (experimental).

The archive catalogue lists the game's own files only. DMM 5 serves its mods at run
time, and a mod can add files the game never had, such as a new mesh or texture.
This list reads DMM's manifest, asks the catalogue which of the served paths it
has, and lists the rest. They open from CDMW's own copy; DMM's files are only read.
"""

from __future__ import annotations

import shutil
import threading
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from types import MappingProxyType

from PySide6.QtCore import QObject, Qt, QUrl, Signal
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (
    QAbstractItemView, QFileDialog, QGroupBox, QHBoxLayout, QLabel, QListWidget, QListWidgetItem, QPushButton,
    QVBoxLayout, QWidget,
)

from cdmw.domain.archives.constants import ARCHIVE_MESH_EXTENSIONS
from cdmw.services.dmm_runtime_mount import (
    KEEP_GAME_EXTENSIONS, DmmServedFile, current_overlay, normalized_game_path,
)

DMM_ADDED_FILES_EMPTY = "Press Find to list the files DMM's mounted mods add to the game."


@dataclass(frozen=True, slots=True)
class DmmAddedFile:
    game_path: str
    mod: str
    source: Path


class _Relay(QObject):
    """Brings background worker results back to the UI thread."""

    done = Signal(int, object, object)


def _expected_sidecar_path(path: str) -> str:
    normalized = normalized_game_path(path)
    suffix = PurePosixPath(normalized).suffix.casefold()
    if suffix == ".pac":
        return normalized.replace("/model/", "/modelproperty/", 1) + "_xml"
    if suffix in {".pam", ".pamlod"}:
        return str(PurePosixPath(normalized).with_suffix(".pami"))
    return ""


def _referenced_game_paths(
    entry: object,
    entries: list[object] | tuple[object, ...],
    *,
    limit: int = 256,
) -> tuple[str, ...]:
    """Return normalized archive paths named by ``entries`` that DMM did not already supply."""

    from cdmw.core.appearance_composite import _extract_dds_reference_paths

    known = {normalized_game_path(getattr(item, "path", "")) for item in entries}
    missing: list[str] = []
    seen: set[str] = set()

    def add_candidate(raw_path: str) -> None:
        key = normalized_game_path(raw_path)
        if not key or key in known or key in seen or len(missing) >= limit:
            return
        seen.add(key)
        missing.append(key)

    sidecar = _expected_sidecar_path(str(getattr(entry, "path", "") or ""))
    if sidecar:
        add_candidate(sidecar)
    for item in entries:
        item_path = normalized_game_path(getattr(item, "path", ""))
        if not item_path.endswith((".pac_xml", ".pami")):
            continue
        prepared = getattr(item, "prepared_path", None)
        if prepared is None:
            continue
        try:
            text = Path(prepared).read_text("utf-8", errors="ignore")
        except OSError:
            continue
        for ref_path in _extract_dds_reference_paths(text):
            add_candidate(ref_path)
            if len(missing) >= limit:
                return tuple(missing)
    return tuple(missing)


def _build_dependency_context(entry: object, entries: list[object] | tuple[object, ...]):
    from cdmw.ui.archive_browser.workflow_dependencies import ArchiveWorkflowDependencyContext

    paths: dict[str, list] = {}
    basenames: dict[str, list] = {}
    for item in entries:
        paths.setdefault(normalized_game_path(item.path), []).append(item)
        basenames.setdefault(item.basename.casefold(), []).append(item)
    return ArchiveWorkflowDependencyContext(
        entry,
        tuple(entries),
        MappingProxyType({key: tuple(value) for key, value in paths.items()}),
        MappingProxyType({key: tuple(value) for key, value in basenames.items()}),
        remote=True,
    )


def _copy_added_rows(game_root: str, rows: list[DmmAddedFile] | tuple[DmmAddedFile, ...], target_root: Path) -> list[str]:
    resolved_root = target_root.resolve()
    written = []
    overlay = current_overlay()
    for row in rows:
        prepared = overlay.prepare(game_root, row.game_path)
        if prepared is None:
            raise ValueError(f"DMM no longer serves {row.game_path}. Press Find again.")
        target = target_root.joinpath(*PurePosixPath(row.game_path).parts)
        if not target.resolve().is_relative_to(resolved_root):
            raise ValueError(f"{row.game_path} is not a path inside the folder.")
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(prepared.path, target)
        written.append(str(target))
    return written


def _prepare_open(game_root: str, row: DmmAddedFile):
    """CDMW's copy of ``row`` as an archive entry, with DMM dependencies and missing vanilla refs.

    Read off the UI thread: it copies DMM's file and reads it for names.
    """
    from cdmw.services.dmm_runtime_mount import added_dependency_entries, added_entry

    overlay = current_overlay()
    mount, error = overlay.mount(game_root)
    served = overlay.served_file(game_root, row.game_path)
    prepared = overlay.prepare(game_root, row.game_path) if served is not None else None
    if mount is None or served is None or prepared is None:
        raise ValueError(error or f"DMM no longer serves {row.game_path}. Press Find again.")
    entry = added_entry(mount, served, prepared)
    seed_list = [entry]
    sidecar_path = _expected_sidecar_path(entry.path)
    if sidecar_path and sidecar_path.replace("\\", "/").casefold() != entry.path.replace("\\", "/").casefold():
        sidecar_served = overlay.served_file(game_root, sidecar_path)
        sidecar_prepared = overlay.prepare(game_root, sidecar_path) if sidecar_served is not None else None
        if sidecar_served is not None and sidecar_prepared is not None:
            seed_list.append(added_entry(mount, sidecar_served, sidecar_prepared))
    seed_entries = tuple(seed_list)
    seen_paths: set[str] = set()
    deduped_entries = []
    for candidate in (*seed_entries, *added_dependency_entries(game_root, seed_entries, overlay=overlay)):
        key = str(getattr(candidate, "path", "") or "").replace("\\", "/").casefold()
        if not key or key in seen_paths:
            continue
        seen_paths.add(key)
        deduped_entries.append(candidate)
    entries = tuple(deduped_entries)
    missing_game_paths = _referenced_game_paths(entry, entries)
    return entry, entries, missing_game_paths


def launch_dmm_mesh_editor_session(
    archive: object,
    entry: object,
    entries: tuple[object, ...],
    on_error: object,
    on_launched: object = None,
) -> bool:
    """Open ``entry`` and its DMM/vanilla dependency ``entries`` in Mesh Editor."""

    shell = getattr(archive, "shell", None)
    tab = getattr(shell, "mesh_editor_tab", None)
    context = _build_dependency_context(entry, entries)
    try:
        blocked = getattr(shell, "_mesh_editor_open_blocked", None)
        if callable(blocked) and blocked():
            return False
        # Finish, Discard or Keep editing for an unfinished edit; another file opens beside it.
        if not shell._prepare_mesh_editor_archive_launch(entry):
            return False
        tab.open_archive_session(entry, archive_dependencies=context)
        activate = getattr(shell, "_activate_tool_widget", None)
        if callable(activate):
            activate(tab)
    except (AttributeError, OSError, ValueError, RuntimeError) as exc:
        if callable(on_error):
            on_error(str(exc))
        return False
    if callable(on_launched):
        on_launched()
    return True


def resolve_missing_vanilla_and_launch_mesh_editor(
    owner: object,
    *,
    archive: object,
    generation_attr: str,
    generation: int,
    lookup_attr: str,
    cleanup_attr: str,
    entry: object,
    entries: tuple[object, ...],
    missing_game_paths: tuple[str, ...],
    on_error: object,
    on_launched: object = None,
    allow_sidecar_followup: bool = True,
) -> None:
    """Resolve missing referenced vanilla files from the catalogue, then open Mesh Editor."""

    def launch(merged: tuple[object, ...]) -> None:
        launch_dmm_mesh_editor_session(archive, entry, merged, on_error, on_launched=on_launched)

    bridge = getattr(archive, "archive_remote_bridge", None)
    session = getattr(bridge, "current_session", None)
    service = getattr(archive, "archive_catalogue_service", None)
    if (
        not missing_game_paths
        or session is None
        or service is None
        or not callable(getattr(service, "resolve_entries", None))
        or not callable(getattr(service, "prepare_entries", None))
    ):
        launch(entries)
        return

    from cdmw.domain.archives.catalogue import ArchiveLookupKind
    from cdmw.domain.archives.catalogue_operations import PrepareEntriesRequest, PrepareEntriesResult
    from cdmw.services.archive_catalogue_service import ArchiveCatalogueService
    from cdmw.ui.archive_browser.remote_entry_lookup import lookup_requests, start_live_catalogue_lookup

    requests = lookup_requests(session.session_id, ArchiveLookupKind.EXACT_PATHS, missing_game_paths)
    if not requests:
        launch(entries)
        return

    fallback_launched = False

    def is_current() -> bool:
        return int(getattr(owner, generation_attr, -1)) == generation

    def launch_fallback() -> None:
        nonlocal fallback_launched
        if fallback_launched or not is_current():
            return
        fallback_launched = True
        launch(entries)

    def on_lookup_error(_message: str) -> None:
        launch_fallback()

    def on_lookup_done(outcome) -> None:
        if not is_current():
            return
        ordered_dtos = sorted(outcome.entries, key=lambda dto: not getattr(dto, "is_active_override", False))
        chosen_by_path: dict[str, object] = {}
        for dto in ordered_dtos:
            key = normalized_game_path(dto.path)
            if key and key not in chosen_by_path:
                chosen_by_path[key] = dto
        dtos_by_id = {dto.entry_id: dto for dto in chosen_by_path.values()}
        if not dtos_by_id:
            launch_fallback()
            return
        ui_generation = int(getattr(getattr(bridge, "controller", None), "generation", 0) or 0)
        prepare_request_id: str | None = None
        collected: dict[int, object] = {}
        finished = False

        def disconnect() -> None:
            for signal_name, handler in (
                ("batch_ready", on_batch),
                ("result_ready", on_result),
                ("request_failed", on_failed),
                ("request_cancelled", on_cancelled),
            ):
                signal = getattr(service, signal_name, None)
                if signal is not None:
                    try:
                        signal.disconnect(handler)
                    except (RuntimeError, TypeError):
                        pass

        def cleanup(*, cancel_service: bool = True) -> None:
            nonlocal finished
            if finished:
                return
            finished = True
            disconnect()
            if getattr(owner, cleanup_attr, None) is cleanup:
                setattr(owner, cleanup_attr, None)
            if cancel_service and prepare_request_id is not None:
                try:
                    service.cancel(prepare_request_id)
                except (AttributeError, RuntimeError):
                    pass

        def accept_payload(payload: object) -> bool:
            if not isinstance(payload, PrepareEntriesResult) or payload.session_id != session.session_id:
                return False
            for item in payload.items:
                if item.entry.entry_id in dtos_by_id:
                    collected[item.entry.entry_id] = item
            return True

        def on_batch(req_id: str, _operation: str, payload: object) -> None:
            if not finished and prepare_request_id is not None and str(req_id) == prepare_request_id:
                accept_payload(payload)

        def on_result(req_id: str, _operation: str, payload: object) -> None:
            if finished or prepare_request_id is None or str(req_id) != prepare_request_id:
                return
            ok = accept_payload(payload)
            cleanup(cancel_service=False)
            if not is_current():
                return
            if not ok:
                launch_fallback()
                return
            seen_paths = {normalized_game_path(item.path) for item in entries}
            added_vanilla: list[object] = []
            for entry_id, item in collected.items():
                dto = dtos_by_id.get(entry_id)
                if dto is None:
                    continue
                key = normalized_game_path(dto.path)
                if not key or key in seen_paths:
                    continue
                seen_paths.add(key)
                prepared_entry = ArchiveCatalogueService.compatibility_entry(dto)
                prepared_entry.prepared_path = Path(item.prepared_path)
                prepared_entry.prepared_size = item.size
                prepared_entry.prepared_sha256 = item.sha256
                prepared_entry.prepared_note = str(item.note or "")
                added_vanilla.append(prepared_entry)
            merged = (*entries, *added_vanilla)
            if allow_sidecar_followup and added_vanilla:
                followup = _referenced_game_paths(entry, merged)
                if followup:
                    resolve_missing_vanilla_and_launch_mesh_editor(
                        owner,
                        archive=archive,
                        generation_attr=generation_attr,
                        generation=generation,
                        lookup_attr=lookup_attr,
                        cleanup_attr=cleanup_attr,
                        entry=entry,
                        entries=merged,
                        missing_game_paths=followup,
                        on_error=on_error,
                        on_launched=on_launched,
                        allow_sidecar_followup=False,
                    )
                    return
            launch(merged)

        def on_failed(req_id: str, _error: object) -> None:
            if not finished and prepare_request_id is not None and str(req_id) == prepare_request_id:
                cleanup(cancel_service=False)
                launch_fallback()

        def on_cancelled(req_id: str) -> None:
            if not finished and prepare_request_id is not None and str(req_id) == prepare_request_id:
                cleanup(cancel_service=False)

        setattr(owner, cleanup_attr, cleanup)
        for signal_name, handler in (
            ("batch_ready", on_batch),
            ("result_ready", on_result),
            ("request_failed", on_failed),
            ("request_cancelled", on_cancelled),
        ):
            signal = getattr(service, signal_name, None)
            if signal is not None:
                signal.connect(handler)

        try:
            prepare_request_id = str(
                service.prepare_entries(
                    PrepareEntriesRequest(session.session_id, tuple(dtos_by_id)),
                    ui_generation=ui_generation,
                    dmm_overlay=True,
                )
            )
        except Exception:
            cleanup(cancel_service=False)
            launch_fallback()
            return

    start_live_catalogue_lookup(
        owner,
        lookup_attr,
        requests,
        on_done=on_lookup_done,
        on_error=on_lookup_error,
    )


def added_files(served: dict[str, DmmServedFile], found_paths: set[str]) -> list[DmmAddedFile]:
    """The served files whose game path the catalogue does not have, by game path."""

    rows = [DmmAddedFile(item.game_path, item.mod, item.source) for key, item in served.items()
            if key not in found_paths and PurePosixPath(key).suffix not in KEEP_GAME_EXTENSIONS]
    return sorted(rows, key=lambda row: row.game_path.casefold())


class DmmAddedFilesGroup(QGroupBox):
    def __init__(self, archive, parent=None):
        super().__init__(parent)
        self.setTitle("Files DMM adds (experimental)")
        self.setObjectName("ArchiveDmmAddedFiles")
        self.setToolTip("Files a mod mounted in DMM adds that the game does not have. Browse Archives lists "
                        "the game's files only. CDMW opens and copies its own copy; DMM's files are only read.")
        self._archive = archive
        #: The lookup helper finds the catalogue through ``owner.archive``.
        self.archive = archive
        self._lookup = None
        self._open_lookup = None
        self._prepare_cleanup = None
        self._open_generation = 0
        self._open_relay = _Relay(self)
        self._open_relay.done.connect(self._open_prepared)
        self._copy_generation = 0
        self._copy_in_progress = False
        self._copy_relay = _Relay(self)
        self._copy_relay.done.connect(self._copy_finished)
        self.rows: list[DmmAddedFile] = []
        layout = QVBoxLayout(self)
        self.status_label = QLabel(DMM_ADDED_FILES_EMPTY)
        self.status_label.setObjectName("HintLabel")
        self.status_label.setWordWrap(True)
        layout.addWidget(self.status_label)
        self.file_list = QListWidget()
        self.file_list.setObjectName("ArchiveDmmAddedFilesList")
        self.file_list.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.file_list.setMaximumHeight(160)
        self.file_list.itemDoubleClicked.connect(lambda _item: self.open_selected())
        self.file_list.itemSelectionChanged.connect(self._sync_buttons)
        layout.addWidget(self.file_list)
        buttons = QHBoxLayout()
        self.find_button = QPushButton("Find")
        self.find_button.setToolTip("Read DMM's list again and ask the catalogue which files the game lacks.")
        self.open_button = QPushButton("Open in Mesh Editor")
        self.copy_button = QPushButton("Copy to Folder...")
        self.show_button = QPushButton("Show DMM's File")
        for button in (self.find_button, self.open_button, self.copy_button, self.show_button):
            buttons.addWidget(button)
        buttons.addStretch(1)
        layout.addLayout(buttons)
        self.find_button.clicked.connect(self.find)
        self.open_button.clicked.connect(self.open_selected)
        self.copy_button.clicked.connect(self.copy_selected_dialog)
        self.show_button.clicked.connect(self.show_selected)
        self._sync_buttons()
        overlay = current_overlay()
        overlay.add_listener(self._overlay_changed)
        self.destroyed.connect(
            lambda _object=None, overlay=overlay, listener=self._overlay_changed: (
                overlay.remove_listener(listener),
                self._cancel_pending_open_prepare(),
            )
        )

    def _overlay_changed(self) -> None:
        """Turned on or off, or Check again: previews kept from before show other files."""

        clear = getattr(self._archive, "_clear_archive_preview_cache", None)
        if callable(clear):
            clear()
        clear_family = getattr(self._archive, "_clear_archive_asset_family_cache", None)
        if callable(clear_family):
            clear_family()
        refresh_button = getattr(self._archive, "_refresh_archive_dmm_mods_button", None)
        if callable(refresh_button):
            refresh_button()
        remote_bridge = getattr(self._archive, "archive_remote_bridge", None)
        cancel_deps = getattr(remote_bridge, "cancel_preview_dependencies", None)
        if callable(cancel_deps):
            cancel_deps(clear_snapshot=True)
        if self._lookup is None:
            self._show_rows([], DMM_ADDED_FILES_EMPTY)
        current_getter = getattr(self._archive, "_current_archive_entry", None)
        render = getattr(self._archive, "_render_archive_preview", None)
        if callable(current_getter) and callable(render) and not getattr(self._archive, "editing_in_place", False):
            current = current_getter()
            if current is not None:
                render(current, force=True)

    # ------------------------------------------------------------ finding

    def _game_root(self) -> str:
        bridge = getattr(self._archive, "archive_remote_bridge", None)
        session = getattr(bridge, "current_session", None)
        return str(getattr(session, "package_root", "") or "")

    def find(self) -> bool:
        """Start listing; False with the reason in the status line when it cannot start."""

        from cdmw.domain.archives.catalogue import ArchiveLookupKind
        from cdmw.ui.archive_browser.remote_entry_lookup import lookup_requests, start_live_catalogue_lookup

        overlay = current_overlay()
        game_root = self._game_root()
        if not game_root:
            return self._show_rows([], "Load the game archives first.")
        if not overlay.enabled:
            return self._show_rows([], "Showing DMM's files is turned off in Settings > Paths.")
        mount, error = overlay.mount(game_root)
        if error or mount is None or not mount.serving:
            return self._show_rows([], error or (mount.problem if mount is not None else
                                                 "DMM has nothing mounted at run time."))
        served = {key: item for key, item in mount.files.items() if PurePosixPath(key).suffix not in KEEP_GAME_EXTENSIONS}
        if not served:
            return self._show_rows([], "DMM's mounted mods change only game tables.")
        bridge = getattr(self._archive, "archive_remote_bridge", None)
        session = getattr(bridge, "current_session", None)
        requests = lookup_requests(session.session_id, ArchiveLookupKind.EXACT_PATHS, [item.game_path for item in served.values()])
        self.status_label.setText(f"Checking {len(served):,} file(s) DMM serves against the game's catalogue...")
        self.find_button.setEnabled(False)

        def done(outcome) -> None:
            found = {normalized_game_path(entry.path) for entry in outcome.entries}
            self._show_rows(added_files(served, found), "")

        def failed(message: str) -> None:
            self._show_rows([], message)

        lookup = start_live_catalogue_lookup(self, "_lookup", requests, on_done=done, on_error=failed)
        return lookup is not None

    def _show_rows(self, rows: list[DmmAddedFile], message: str) -> bool:
        self.rows = rows
        self.file_list.clear()
        for row in rows:
            item = QListWidgetItem(f"{PurePosixPath(row.game_path).name}  ({row.mod})")
            item.setToolTip(row.game_path)
            item.setData(Qt.ItemDataRole.UserRole, row.game_path)
            self.file_list.addItem(item)
        if not message:
            message = (f"{len(rows):,} file(s) the game does not have, from DMM's mounted mods." if rows
                       else "DMM's mounted mods add no files the game does not have.")
        self.status_label.setText(message)
        self.find_button.setEnabled(True)
        self._sync_buttons()
        return bool(rows) or not message

    # ------------------------------------------------------------ actions

    def selected_rows(self) -> list[DmmAddedFile]:
        chosen = {item.data(Qt.ItemDataRole.UserRole) for item in self.file_list.selectedItems()}
        return [row for row in self.rows if row.game_path in chosen]

    def select_paths(self, paths) -> list[str]:
        wanted = {normalized_game_path(path) for path in paths}
        self.file_list.clearSelection()
        chosen = []
        for index in range(self.file_list.count()):
            item = self.file_list.item(index)
            if normalized_game_path(item.data(Qt.ItemDataRole.UserRole)) in wanted:
                item.setSelected(True)
                chosen.append(item.data(Qt.ItemDataRole.UserRole))
        return chosen

    def _sync_buttons(self) -> None:
        rows = self.selected_rows()
        self.open_button.setEnabled(len(rows) == 1 and PurePosixPath(rows[0].game_path).suffix.casefold()
                                    in ARCHIVE_MESH_EXTENSIONS)
        self.copy_button.setEnabled(bool(rows) and not self._copy_in_progress)
        self.show_button.setEnabled(len(rows) == 1)

    def _show_dmm_status(self, message: str, *, error: bool = False) -> None:
        """The status line, and the window's, which stays visible when the Actions panel closes."""

        self.status_label.setText(message)
        shell = getattr(self._archive, "shell", None)
        status = getattr(shell, "set_status_message", None)
        if callable(status):
            try:
                status(message, error=error)
            except TypeError:
                status(message)

    def open_selected(self) -> str:
        """Open the selected mesh as an archive mesh, like Edited results; the game path when started.

        The copy and the search for the files it names run on a worker. The open
        then asks about an unfinished edit, or opens beside it, as every archive
        open does.
        """
        rows = self.selected_rows()
        if len(rows) != 1 or PurePosixPath(rows[0].game_path).suffix.casefold() not in ARCHIVE_MESH_EXTENSIONS:
            return ""
        row = rows[0]
        shell = getattr(self._archive, "shell", None)
        if getattr(shell, "mesh_editor_tab", None) is None or not callable(
                getattr(shell, "_prepare_mesh_editor_archive_launch", None)):
            self._show_dmm_status("The Mesh Editor is unavailable.", error=True)
            return ""
        from cdmw.ui.archive_browser.command_strip import hide_enclosing_popup

        hide_enclosing_popup(self)
        game_root = self._game_root()
        self._cancel_pending_open_prepare()
        self._open_generation += 1
        generation, relay = self._open_generation, self._open_relay

        def run() -> None:
            try:
                outcome: object = _prepare_open(game_root, row)
            except (OSError, ValueError, RuntimeError) as exc:
                outcome = exc
            try:
                relay.done.emit(generation, row, outcome)
            except RuntimeError:
                pass  # the list was deleted meanwhile

        threading.Thread(target=run, name="dmm-added-file-open", daemon=True).start()
        self._show_dmm_status(f"Opening {row.game_path} from DMM's {row.mod} in the Mesh Editor.")
        return row.game_path

    def _cancel_pending_open_prepare(self) -> None:
        lookup = getattr(self, "_open_lookup", None)
        if lookup is not None:
            self._open_lookup = None
            cancel = getattr(lookup, "cancel", None)
            if callable(cancel):
                cancel()
        cleanup = getattr(self, "_prepare_cleanup", None)
        if callable(cleanup):
            self._prepare_cleanup = None
            cleanup()

    def _open_prepared(self, generation: int, _row: object, outcome: object) -> None:
        if generation != self._open_generation:
            return
        if isinstance(outcome, BaseException):
            self._show_dmm_status(str(outcome), error=True)
            return
        entry, entries, missing_game_paths = outcome
        self._resolve_and_open_vanilla(generation, entry, entries, missing_game_paths, allow_sidecar_followup=True)

    def _resolve_and_open_vanilla(
        self,
        generation: int,
        entry: object,
        entries: tuple[object, ...],
        missing_game_paths: tuple[str, ...],
        *,
        allow_sidecar_followup: bool,
    ) -> None:
        resolve_missing_vanilla_and_launch_mesh_editor(
            self,
            archive=self._archive,
            generation_attr="_open_generation",
            generation=generation,
            lookup_attr="_open_lookup",
            cleanup_attr="_prepare_cleanup",
            entry=entry,
            entries=entries,
            missing_game_paths=missing_game_paths,
            on_error=lambda message: self._show_dmm_status(message, error=True),
            allow_sidecar_followup=allow_sidecar_followup,
        )

    def _launch_mesh_editor(self, entry: object, entries: tuple[object, ...]) -> None:
        launch_dmm_mesh_editor_session(
            self._archive,
            entry,
            entries,
            lambda message: self._show_dmm_status(message, error=True),
        )

    def copy_selected(self, folder: Path | str) -> list[str]:
        """Copy the selected files into ``folder`` under their game paths; never into the game folder."""

        from cdmw.domain.output_paths import check_output_path

        target_root = check_output_path(folder, game_folder=self._game_root() or None, allow_existing=True)
        written = _copy_added_rows(self._game_root(), self.selected_rows(), target_root)
        self._show_dmm_status(f"Copied {len(written):,} file(s) to {target_root}.")
        return written

    def copy_selected_dialog(self) -> None:
        from cdmw.domain.output_paths import check_output_path
        from cdmw.ui.archive_browser.command_strip import hide_enclosing_popup

        if self._copy_in_progress:
            return
        rows = tuple(self.selected_rows())
        if not rows:
            return
        # The folder dialog would close the Actions panel and its status line with it.
        hide_enclosing_popup(self)
        parent = self._archive if isinstance(self._archive, QWidget) else self.window()
        folder = QFileDialog.getExistingDirectory(parent, "Copy DMM's files to a folder")
        if not folder:
            return
        game_root = self._game_root()
        try:
            target_root = check_output_path(folder, game_folder=game_root or None, allow_existing=True)
        except (OSError, ValueError) as exc:
            self._show_dmm_status(str(exc), error=True)
            return
        self._copy_in_progress = True
        self._copy_generation += 1
        generation, relay = self._copy_generation, self._copy_relay
        self._sync_buttons()
        self._show_dmm_status(f"Copying {len(rows):,} file(s)...")

        def run() -> None:
            try:
                outcome: object = _copy_added_rows(game_root, rows, target_root)
            except (OSError, ValueError) as exc:
                outcome = exc
            try:
                relay.done.emit(generation, target_root, outcome)
            except RuntimeError:
                pass  # the widget was deleted meanwhile

        threading.Thread(target=run, name="dmm-added-file-copy", daemon=True).start()

    def _copy_finished(self, generation: int, target_root: object, outcome: object) -> None:
        if generation != self._copy_generation:
            return
        self._copy_in_progress = False
        self._sync_buttons()
        if isinstance(outcome, BaseException):
            self._show_dmm_status(str(outcome), error=True)
            return
        self._show_dmm_status(f"Copied {len(outcome):,} file(s) to {target_root}.")

    def show_selected(self) -> None:
        rows = self.selected_rows()
        if len(rows) == 1:
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(rows[0].source.parent)))
