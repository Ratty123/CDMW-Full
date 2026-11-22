"""Browse Archives > DMM Mounted Mods: inspect and open every file DMM serves."""

from __future__ import annotations

import threading
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, replace
from pathlib import Path, PurePosixPath

from PySide6.QtCore import QSignalBlocker, Qt, QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QComboBox,
    QDialog,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from cdmw.domain.archives.constants import ARCHIVE_MESH_EXTENSIONS
from cdmw.services.dmm_runtime_mount import (
    DMM_NOTE_PREFIX,
    KEEP_GAME_EXTENSIONS,
    SHOW_MOUNTED_MODS_SETTING,
    DmmServedFile,
    added_dependency_entries,
    added_entry,
    current_overlay,
    describe_mount,
    normalized_game_path,
    short_mod_name,
)
from cdmw.ui.archive_browser.dmm_added_files import (
    _Relay,
    _copy_added_rows,
    _expected_sidecar_path,
    _referenced_game_paths,
    resolve_missing_vanilla_and_launch_mesh_editor,
)

_TEXTURE_EXTENSIONS = frozenset({".dds"})


@dataclass(frozen=True, slots=True)
class DmmMountedFileRow:
    """One file listed in DMM's runtime mount manifest with optional vanilla catalogue match."""

    game_path: str
    mod: str
    source: Path
    extension: str
    kept_vanilla: bool
    in_catalogue: bool | None = None
    catalogue_dto: object | None = None


def _resolve_entry_from_row(mount: object, row: DmmMountedFileRow, prepared: object) -> object:
    """Attach DMM's prepared bytes while preserving vanilla archive identity when known."""

    if row.catalogue_dto is not None:
        from cdmw.services.archive_catalogue_service import ArchiveCatalogueService

        base = ArchiveCatalogueService.compatibility_entry(row.catalogue_dto)
        return replace(
            base,
            prepared_path=prepared.path,
            prepared_size=prepared.size,
            prepared_sha256=prepared.sha256,
            prepared_note=f"{DMM_NOTE_PREFIX} {prepared.mod}",
        )
    return added_entry(mount, DmmServedFile(row.game_path, row.source, row.mod), prepared)


def _attach_row_identity(
    mount: object,
    dep: object,
    rows_by_path: Mapping[str, DmmMountedFileRow] | None,
) -> object:
    if not rows_by_path:
        return dep
    known = rows_by_path.get(normalized_game_path(getattr(dep, "path", "")))
    if known is None or known.catalogue_dto is None:
        return dep
    from cdmw.services.archive_catalogue_service import ArchiveCatalogueService

    base = ArchiveCatalogueService.compatibility_entry(known.catalogue_dto)
    return replace(
        base,
        prepared_path=getattr(dep, "prepared_path", None),
        prepared_size=getattr(dep, "prepared_size", None),
        prepared_sha256=str(getattr(dep, "prepared_sha256", "") or ""),
        prepared_note=str(getattr(dep, "prepared_note", "") or ""),
    )


def _prepare_open_row(
    game_root: str,
    row: DmmMountedFileRow,
    rows_by_path: Mapping[str, DmmMountedFileRow] | None = None,
):
    """Copy DMM's served mesh plus DMM companions off the UI thread before opening Mesh Editor."""

    overlay = current_overlay()
    mount, error = overlay.mount(game_root)
    served = overlay.served_file(game_root, row.game_path)
    prepared = overlay.prepare(game_root, row.game_path) if served is not None else None
    if mount is None or served is None or prepared is None:
        raise ValueError(error or f"DMM no longer serves {row.game_path}. Refresh from DMM first.")
    entry = _resolve_entry_from_row(mount, row, prepared)
    seed_list = [entry]
    sidecar_path = _expected_sidecar_path(entry.path)
    sidecar_key = normalized_game_path(sidecar_path)
    if sidecar_key and sidecar_key != normalized_game_path(entry.path):
        sidecar_served = overlay.served_file(game_root, sidecar_path)
        sidecar_prepared = overlay.prepare(game_root, sidecar_path) if sidecar_served is not None else None
        if sidecar_served is not None and sidecar_prepared is not None:
            sidecar_row = rows_by_path.get(sidecar_key) if rows_by_path else None
            if sidecar_row is not None:
                seed_list.append(_resolve_entry_from_row(mount, sidecar_row, sidecar_prepared))
            else:
                seed_list.append(added_entry(mount, sidecar_served, sidecar_prepared))
    seed_entries = tuple(seed_list)
    seen_paths: set[str] = set()
    deduped_entries = []
    for candidate in (*seed_entries, *added_dependency_entries(game_root, seed_entries, overlay=overlay)):
        key = normalized_game_path(getattr(candidate, "path", ""))
        if not key or key in seen_paths:
            continue
        seen_paths.add(key)
        deduped_entries.append(_attach_row_identity(mount, candidate, rows_by_path))
    entries = tuple(deduped_entries)
    missing_game_paths = _referenced_game_paths(entry, entries)
    return entry, entries, missing_game_paths


def _prepare_texture_row(game_root: str, row: DmmMountedFileRow):
    """Copy DMM's served texture off the UI thread before opening Texture Editor."""

    overlay = current_overlay()
    mount, error = overlay.mount(game_root)
    served = overlay.served_file(game_root, row.game_path)
    prepared = overlay.prepare(game_root, row.game_path) if served is not None else None
    if mount is None or served is None or prepared is None:
        raise ValueError(error or f"DMM no longer serves {row.game_path}. Refresh from DMM first.")
    return _resolve_entry_from_row(mount, row, prepared), prepared.path


class DmmMountedModsDialog(QDialog):
    """Inspect all files DMM mounts from bin64/dmm/manifest.tsv and open or filter them."""

    _KIND_CHOICES: tuple[tuple[str, str], ...] = (
        ("All mounted files", "all"),
        ("Meshes (.pac, .pam, .pamlod)", "meshes"),
        ("Textures (.dds)", "textures"),
        ("Replaces game file", "replaces"),
        ("Added by mod only", "added"),
        ("Kept vanilla (game tables)", "kept_vanilla"),
    )

    def __init__(self, archive, parent: QWidget | None = None) -> None:
        parent_widget = parent if parent is not None else (archive if isinstance(archive, QWidget) else None)
        super().__init__(parent_widget)
        self.setObjectName("DmmMountedModsDialog")
        self.setWindowTitle("DMM Mounted Mods")
        self.resize(980, 640)
        self.setMinimumSize(760, 460)
        self._archive = archive
        #: Live-catalogue lookup helper inspects ``owner.archive``.
        self.archive = archive
        self._closed = False
        self._ignoring_overlay_event = False
        self._all_rows: list[DmmMountedFileRow] = []
        self._rows_by_path: dict[str, DmmMountedFileRow] = {}
        self._catalogue_lookup = None
        self._open_lookup = None
        self._prepare_cleanup = None
        self._catalogue_generation = 0
        self._open_generation = 0
        self._texture_generation = 0
        self._copy_generation = 0
        self._copy_in_progress = False
        self._open_relay = _Relay(self)
        self._open_relay.done.connect(self._open_prepared)
        self._texture_relay = _Relay(self)
        self._texture_relay.done.connect(self._texture_prepared)
        self._copy_relay = _Relay(self)
        self._copy_relay.done.connect(self._copy_finished)

        layout = QVBoxLayout(self)
        top_row = QHBoxLayout()
        self.enabled_checkbox = QCheckBox("Show DMM's mounted files in CDMW")
        self.enabled_checkbox.setObjectName("DmmDialogShowMountedMods")
        self.enabled_checkbox.setToolTip(
            "When checked, Browse Archives, Mesh Editor, Texture Editor, and Extract use the files DMM mounts instead of vanilla."
        )
        self.enabled_checkbox.setChecked(current_overlay().enabled)
        top_row.addWidget(self.enabled_checkbox)
        top_row.addStretch(1)
        self.refresh_button = QPushButton("Refresh from DMM")
        self.refresh_button.setToolTip("Read DMM's manifest again after mounting or unmounting mods in DMM.")
        top_row.addWidget(self.refresh_button)
        layout.addLayout(top_row)

        self.status_label = QLabel("")
        self.status_label.setObjectName("HintLabel")
        self.status_label.setWordWrap(True)
        layout.addWidget(self.status_label)

        filters_row = QHBoxLayout()
        self.search_edit = QLineEdit()
        self.search_edit.setPlaceholderText("Filter by file name, path, or mod...")
        self.search_edit.setClearButtonEnabled(True)
        filters_row.addWidget(self.search_edit, 2)
        self.mod_combo = QComboBox()
        self.mod_combo.setMinimumWidth(200)
        filters_row.addWidget(self.mod_combo, 1)
        self.kind_combo = QComboBox()
        for label, key in self._KIND_CHOICES:
            self.kind_combo.addItem(label, key)
        filters_row.addWidget(self.kind_combo)
        layout.addLayout(filters_row)

        self.file_tree = QTreeWidget()
        self.file_tree.setObjectName("DmmMountedModsTree")
        self.file_tree.setHeaderLabels(["File", "Status", "Mod", "Type", "Game Path"])
        self.file_tree.setRootIsDecorated(False)
        self.file_tree.setAlternatingRowColors(True)
        self.file_tree.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.file_tree.setSortingEnabled(True)
        self.file_tree.setUniformRowHeights(True)
        header = self.file_tree.header()
        header.setStretchLastSection(True)
        for col, width in enumerate((220, 155, 195, 70, 300)):
            self.file_tree.setColumnWidth(col, width)
        layout.addWidget(self.file_tree, 1)

        primary_buttons = QHBoxLayout()
        self.filter_browse_button = QPushButton("Filter Browse Archives")
        self.filter_browse_button.setToolTip("Limit Browse Archives to the currently visible mounted files that replace a game file.")
        self.show_in_browse_button = QPushButton("Show in Browse Archives")
        self.show_in_browse_button.setToolTip("Jump to the selected mounted file inside Browse Archives.")
        self.open_mesh_button = QPushButton("Open in Mesh Editor")
        self.open_texture_button = QPushButton("Open in Texture Editor")
        for button in (
            self.filter_browse_button,
            self.show_in_browse_button,
            self.open_mesh_button,
            self.open_texture_button,
        ):
            primary_buttons.addWidget(button)
        primary_buttons.addStretch(1)
        layout.addLayout(primary_buttons)

        secondary_buttons = QHBoxLayout()
        self.copy_button = QPushButton("Copy to Folder...")
        self.show_source_button = QPushButton("Show Source File")
        self.close_button = QPushButton("Close")
        secondary_buttons.addWidget(self.copy_button)
        secondary_buttons.addWidget(self.show_source_button)
        secondary_buttons.addStretch(1)
        secondary_buttons.addWidget(self.close_button)
        layout.addLayout(secondary_buttons)

        self.enabled_checkbox.toggled.connect(self._toggle_overlay)
        self.refresh_button.clicked.connect(self.refresh_from_dmm)
        self.search_edit.textChanged.connect(lambda _text: self._populate_tree())
        self.mod_combo.currentIndexChanged.connect(lambda _idx: self._populate_tree())
        self.kind_combo.currentIndexChanged.connect(lambda _idx: self._populate_tree())
        self.file_tree.itemSelectionChanged.connect(self._sync_buttons)
        self.file_tree.itemDoubleClicked.connect(self._handle_double_click)
        self.filter_browse_button.clicked.connect(self.filter_browse_archives)
        self.show_in_browse_button.clicked.connect(self.show_selected_in_browse)
        self.open_mesh_button.clicked.connect(self.open_selected_in_mesh_editor)
        self.open_texture_button.clicked.connect(self.open_selected_in_texture_editor)
        self.copy_button.clicked.connect(self.copy_selected_dialog)
        self.show_source_button.clicked.connect(self.show_selected_source)
        self.close_button.clicked.connect(self.close)

        overlay = current_overlay()
        overlay.add_listener(self._on_overlay_changed)
        self.destroyed.connect(
            lambda _obj=None, overlay=overlay, listener=self._on_overlay_changed: overlay.remove_listener(listener)
        )
        self.reload()

    def _settings(self):
        for candidate in (
            getattr(self._archive, "settings", None),
            getattr(getattr(self._archive, "shell", None), "settings", None),
            getattr(getattr(getattr(self._archive, "shell", None), "app_context", None), "settings", None),
        ):
            if candidate is not None and callable(getattr(candidate, "value", None)):
                return candidate
        try:
            from cdmw.services.settings_service import app_settings

            return app_settings()
        except Exception:  # noqa: BLE001
            return None

    def _game_root(self) -> str:
        bridge = getattr(self._archive, "archive_remote_bridge", None)
        session = getattr(bridge, "current_session", None)
        root = str(getattr(session, "package_root", "") or "").strip()
        if root:
            return root
        settings = self._settings()
        if settings is not None:
            return str(settings.value("archive/package_root", "") or "").strip()
        return ""

    def _session_loaded(self) -> bool:
        bridge = getattr(self._archive, "archive_remote_bridge", None)
        return getattr(bridge, "current_session", None) is not None

    def _on_overlay_changed(self) -> None:
        if self._closed or self._ignoring_overlay_event:
            return
        with QSignalBlocker(self.enabled_checkbox):
            self.enabled_checkbox.setChecked(current_overlay().enabled)
        self.reload()

    def _toggle_overlay(self, checked: bool) -> None:
        settings = self._settings()
        if settings is not None and callable(getattr(settings, "setValue", None)):
            settings.setValue(SHOW_MOUNTED_MODS_SETTING, bool(checked))
        self._ignoring_overlay_event = True
        try:
            current_overlay().set_enabled(checked)
        finally:
            self._ignoring_overlay_event = False
        self._update_status_text()
        self._sync_buttons()

    def refresh_from_dmm(self) -> None:
        """Force re-reading bin64/dmm/manifest.tsv and the game's build state."""

        self._ignoring_overlay_event = True
        try:
            current_overlay().refresh(self._game_root())
        finally:
            self._ignoring_overlay_event = False
        self.reload()

    def reload(self) -> None:
        """Load DMM's current manifest rows and kick off catalogue matching."""

        self._cancel_catalogue_lookup()
        overlay = current_overlay()
        with QSignalBlocker(self.enabled_checkbox):
            self.enabled_checkbox.setChecked(overlay.enabled)
        game_root = self._game_root()
        info = describe_mount(game_root, overlay)
        mount, _error = overlay.mount(game_root) if game_root else (None, "")
        rows: list[DmmMountedFileRow] = []
        if mount is not None and mount.serving:
            for key, served in mount.files.items():
                ext = PurePosixPath(key).suffix.casefold()
                kept = ext in KEEP_GAME_EXTENSIONS
                rows.append(
                    DmmMountedFileRow(
                        game_path=served.game_path,
                        mod=served.mod,
                        source=served.source,
                        extension=ext,
                        kept_vanilla=kept,
                    )
                )
        rows.sort(key=lambda row: row.game_path.casefold())
        self._all_rows = rows
        self._rows_by_path = {normalized_game_path(row.game_path): row for row in rows}
        self._rebuild_mod_combo()
        self._populate_tree()
        self._update_status_text(info)
        self._start_catalogue_lookup()

    def _update_status_text(self, info: Mapping[str, object] | None = None) -> None:
        if info is None:
            info = describe_mount(self._game_root(), current_overlay())
        message = str(info.get("message", "") or "")
        if self._catalogue_lookup is not None:
            message = f"{message} Matching mounted files against the game's archive index..."
        elif info.get("state") in {"serving", "off"} and self._all_rows:
            replaces = sum(1 for row in self._all_rows if row.in_catalogue is True and not row.kept_vanilla)
            added = sum(1 for row in self._all_rows if row.in_catalogue is False and not row.kept_vanilla)
            kept = sum(1 for row in self._all_rows if row.kept_vanilla)
            if self._session_loaded():
                message = (
                    f"{message} ({replaces:,} replace game file(s), {added:,} added by mod, "
                    f"{kept:,} kept vanilla)."
                )
            else:
                message = f"{message} Scan or load the game archives to match replaced vs. added files."
        self.status_label.setText(message)

    def _rebuild_mod_combo(self) -> None:
        previous = str(self.mod_combo.currentData() or "")
        counts: dict[str, int] = {}
        for row in self._all_rows:
            counts[row.mod] = counts.get(row.mod, 0) + 1
        with QSignalBlocker(self.mod_combo):
            self.mod_combo.clear()
            self.mod_combo.addItem(f"All mods ({len(self._all_rows):,})", "")
            for mod, count in sorted(counts.items(), key=lambda item: item[0].casefold()):
                self.mod_combo.addItem(f"{short_mod_name(mod, max_chars=48)} ({count:,})", mod)
            if previous:
                idx = self.mod_combo.findData(previous)
                if idx >= 0:
                    self.mod_combo.setCurrentIndex(idx)

    def _matches_filters(self, row: DmmMountedFileRow) -> bool:
        mod_filter = str(self.mod_combo.currentData() or "")
        if mod_filter and row.mod != mod_filter:
            return False
        kind = str(self.kind_combo.currentData() or "all")
        if kind == "meshes" and row.extension not in ARCHIVE_MESH_EXTENSIONS:
            return False
        if kind == "textures" and row.extension not in _TEXTURE_EXTENSIONS:
            return False
        if kind == "replaces" and (row.kept_vanilla or row.in_catalogue is not True):
            return False
        if kind == "added" and (row.kept_vanilla or row.in_catalogue is not False):
            return False
        if kind == "kept_vanilla" and not row.kept_vanilla:
            return False
        needle = self.search_edit.text().strip().casefold()
        if needle:
            haystack = f"{row.game_path} {row.mod} {row.source.name}".casefold()
            if needle not in haystack:
                return False
        return True

    def visible_rows(self) -> list[DmmMountedFileRow]:
        return [row for row in self._all_rows if self._matches_filters(row)]

    def _row_status_label(self, row: DmmMountedFileRow) -> str:
        if row.kept_vanilla:
            return "Kept vanilla (game table)"
        if row.in_catalogue is True:
            return "Replaces game file"
        if row.in_catalogue is False:
            return "Added by mod"
        if self._catalogue_lookup is not None:
            return "Mounted (checking...)"
        return "Mounted (not checked)"

    def _populate_tree(self) -> None:
        selected = {normalized_game_path(row.game_path) for row in self.selected_rows()}
        sorting = self.file_tree.isSortingEnabled()
        self.file_tree.setSortingEnabled(False)
        try:
            self.file_tree.clear()
            for row in self.visible_rows():
                name = PurePosixPath(row.game_path).name
                status = self._row_status_label(row)
                item = QTreeWidgetItem([name, status, short_mod_name(row.mod, max_chars=40), row.extension or "", row.game_path])
                item.setData(0, Qt.ItemDataRole.UserRole, row.game_path)
                tip = f"Game path: {row.game_path}\nStatus: {status}\nMod: {row.mod}\nDMM file: {row.source}"
                for col in range(5):
                    item.setToolTip(col, tip)
                self.file_tree.addTopLevelItem(item)
                if normalized_game_path(row.game_path) in selected:
                    item.setSelected(True)
        finally:
            self.file_tree.setSortingEnabled(sorting)
        self._sync_buttons()

    def _start_catalogue_lookup(self) -> None:
        bridge = getattr(self._archive, "archive_remote_bridge", None)
        session = getattr(bridge, "current_session", None)
        service = getattr(self._archive, "archive_catalogue_service", None)
        if session is None or service is None or not callable(getattr(service, "resolve_entries", None)):
            return
        targets = [row.game_path for row in self._all_rows if not row.kept_vanilla]
        if not targets:
            return
        from cdmw.domain.archives.catalogue import ArchiveLookupKind
        from cdmw.ui.archive_browser.remote_entry_lookup import lookup_requests, start_live_catalogue_lookup

        requests = lookup_requests(session.session_id, ArchiveLookupKind.EXACT_PATHS, targets)
        if not requests:
            return
        self._catalogue_generation += 1
        generation = self._catalogue_generation

        def on_done(outcome) -> None:
            if self._closed or generation != self._catalogue_generation:
                return
            chosen: dict[str, object] = {}
            for dto in outcome.entries:
                key = normalized_game_path(dto.path)
                if not key:
                    continue
                if key not in chosen or getattr(dto, "is_active_override", False):
                    chosen[key] = dto
            updated: list[DmmMountedFileRow] = []
            for row in self._all_rows:
                if row.kept_vanilla:
                    updated.append(row)
                    continue
                dto = chosen.get(normalized_game_path(row.game_path))
                updated.append(replace(row, in_catalogue=(dto is not None), catalogue_dto=dto))
            self._all_rows = updated
            self._rows_by_path = {normalized_game_path(row.game_path): row for row in updated}
            self._populate_tree()
            self._update_status_text()

        def on_error(message: str) -> None:
            if self._closed or generation != self._catalogue_generation:
                return
            self._populate_tree()
            if message:
                self.status_label.setText(message)

        start_live_catalogue_lookup(
            self,
            "_catalogue_lookup",
            requests,
            on_done=on_done,
            on_error=on_error,
        )
        self._update_status_text()

    def _cancel_catalogue_lookup(self) -> None:
        self._catalogue_generation += 1
        lookup = self._catalogue_lookup
        if lookup is not None:
            self._catalogue_lookup = None
            cancel = getattr(lookup, "cancel", None)
            if callable(cancel):
                cancel()

    def _cancel_pending_open(self) -> None:
        self._open_generation += 1
        self._texture_generation += 1
        for attr in ("_open_lookup",):
            lookup = getattr(self, attr, None)
            if lookup is not None:
                setattr(self, attr, None)
                cancel = getattr(lookup, "cancel", None)
                if callable(cancel):
                    cancel()
        cleanup = getattr(self, "_prepare_cleanup", None)
        if callable(cleanup):
            self._prepare_cleanup = None
            cleanup()

    def selected_rows(self) -> list[DmmMountedFileRow]:
        keys = {
            normalized_game_path(str(item.data(0, Qt.ItemDataRole.UserRole) or ""))
            for item in self.file_tree.selectedItems()
        }
        return [self._rows_by_path[key] for key in keys if key in self._rows_by_path]

    def select_paths(self, paths: Iterable[str]) -> list[str]:
        wanted = {normalized_game_path(path) for path in paths}
        self.file_tree.clearSelection()
        chosen: list[str] = []
        for index in range(self.file_tree.topLevelItemCount()):
            item = self.file_tree.topLevelItem(index)
            game_path = str(item.data(0, Qt.ItemDataRole.UserRole) or "")
            if normalized_game_path(game_path) in wanted:
                item.setSelected(True)
                chosen.append(game_path)
        return chosen

    def _sync_buttons(self) -> None:
        overlay_on = current_overlay().enabled
        rows = self.selected_rows()
        visible = self.visible_rows()
        has_visible_in_browse = any(
            not row.kept_vanilla and getattr(row.catalogue_dto, "entry_id", None) is not None
            for row in visible
        )
        self.filter_browse_button.setEnabled(has_visible_in_browse and self._session_loaded())
        single = rows[0] if len(rows) == 1 else None
        self.show_in_browse_button.setEnabled(
            single is not None and not single.kept_vanilla
            and getattr(single.catalogue_dto, "entry_id", None) is not None
            and self._session_loaded()
        )
        self.open_mesh_button.setEnabled(
            overlay_on and single is not None and not single.kept_vanilla
            and single.extension in ARCHIVE_MESH_EXTENSIONS
        )
        self.open_texture_button.setEnabled(
            overlay_on and single is not None and not single.kept_vanilla
            and single.extension in _TEXTURE_EXTENSIONS
        )
        self.copy_button.setEnabled(
            overlay_on and not self._copy_in_progress and any(not row.kept_vanilla for row in rows)
        )
        self.show_source_button.setEnabled(single is not None)

    def _handle_double_click(self, item: QTreeWidgetItem, _column: int) -> None:
        row = self._rows_by_path.get(normalized_game_path(str(item.data(0, Qt.ItemDataRole.UserRole) or "")))
        if row is None or row.kept_vanilla:
            return
        if row.extension in ARCHIVE_MESH_EXTENSIONS and current_overlay().enabled:
            self.open_selected_in_mesh_editor()
        elif row.extension in _TEXTURE_EXTENSIONS and current_overlay().enabled:
            self.open_selected_in_texture_editor()
        elif row.catalogue_dto is not None and self._session_loaded():
            self.show_selected_in_browse()

    def _activate_browse_tab(self) -> None:
        shell = getattr(self._archive, "shell", None)
        activate = getattr(shell, "_activate_tool_widget", None)
        tab = getattr(shell, "archive_browser_tab", None)
        if callable(activate) and tab is not None:
            activate(tab)

    def _report_status(self, message: str, *, error: bool = False) -> None:
        self.status_label.setText(message)
        shell = getattr(self._archive, "shell", None)
        status = getattr(shell, "set_status_message", None)
        if callable(status):
            try:
                status(message, error=error)
            except TypeError:
                status(message)

    def filter_browse_archives(self) -> bool:
        bridge = getattr(self._archive, "archive_remote_bridge", None)
        entry_ids = tuple(
            dict.fromkeys(
                int(row.catalogue_dto.entry_id)
                for row in self.visible_rows()
                if not row.kept_vanilla and getattr(row.catalogue_dto, "entry_id", None) is not None
            )
        )
        if bridge is None or not entry_ids:
            self._report_status("No visible mounted files match entries in the loaded game archive.", error=True)
            return False
        mod_filter = str(self.mod_combo.currentData() or "")
        label = f"DMM: {short_mod_name(mod_filter, max_chars=28)}" if mod_filter else "DMM mounted mods"
        if not bridge.apply_entry_id_scope(entry_ids, label=label):
            self._report_status("Could not apply the DMM filter to Browse Archives.", error=True)
            return False
        self._activate_browse_tab()
        self.accept()
        return True

    def show_selected_in_browse(self) -> bool:
        rows = self.selected_rows()
        if len(rows) != 1:
            return False
        row = rows[0]
        entry_id = getattr(row.catalogue_dto, "entry_id", None)
        bridge = getattr(self._archive, "archive_remote_bridge", None)
        if bridge is None or entry_id is None:
            self._report_status("The selected file is added by the mod and does not exist in the game's archive index.", error=True)
            return False
        label = f"DMM: {PurePosixPath(row.game_path).name}"
        if not bridge.apply_entry_id_scope((int(entry_id),), label=label):
            return False
        self._activate_browse_tab()
        self.accept()
        return True

    def open_selected_in_mesh_editor(self) -> str:
        if not current_overlay().enabled:
            self._report_status("Turn on 'Show DMM's mounted files in CDMW' first.", error=True)
            return ""
        rows = self.selected_rows()
        if len(rows) != 1 or rows[0].kept_vanilla or rows[0].extension not in ARCHIVE_MESH_EXTENSIONS:
            return ""
        row = rows[0]
        shell = getattr(self._archive, "shell", None)
        if getattr(shell, "mesh_editor_tab", None) is None or not callable(
            getattr(shell, "_prepare_mesh_editor_archive_launch", None)
        ):
            self._report_status("The Mesh Editor is unavailable.", error=True)
            return ""
        game_root = self._game_root()
        rows_snapshot = dict(self._rows_by_path)
        self._cancel_pending_open()
        self._open_generation += 1
        generation, relay = self._open_generation, self._open_relay

        def run() -> None:
            try:
                outcome: object = _prepare_open_row(game_root, row, rows_snapshot)
            except (OSError, ValueError, RuntimeError) as exc:
                outcome = exc
            try:
                relay.done.emit(generation, row, outcome)
            except RuntimeError:
                pass

        threading.Thread(target=run, name="dmm-mounted-open-mesh", daemon=True).start()
        self._report_status(f"Opening {row.game_path} from DMM's {row.mod} in the Mesh Editor...")
        return row.game_path

    def _open_prepared(self, generation: int, _row: object, outcome: object) -> None:
        if self._closed or generation != self._open_generation:
            return
        if isinstance(outcome, BaseException):
            self._report_status(str(outcome), error=True)
            return
        entry, entries, missing_game_paths = outcome
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
            on_error=lambda message: self._report_status(message, error=True),
            on_launched=self.accept,
            allow_sidecar_followup=True,
        )

    def open_selected_in_texture_editor(self) -> str:
        if not current_overlay().enabled:
            self._report_status("Turn on 'Show DMM's mounted files in CDMW' first.", error=True)
            return ""
        rows = self.selected_rows()
        if len(rows) != 1 or rows[0].kept_vanilla or rows[0].extension not in _TEXTURE_EXTENSIONS:
            return ""
        row = rows[0]
        shell = getattr(self._archive, "shell", None)
        textures = getattr(shell, "textures", None)
        if not callable(getattr(textures, "open_prepared_archive_texture", None)):
            self._report_status("The Texture Editor is unavailable.", error=True)
            return ""
        game_root = self._game_root()
        self._texture_generation += 1
        generation, relay = self._texture_generation, self._texture_relay

        def run() -> None:
            try:
                outcome: object = _prepare_texture_row(game_root, row)
            except (OSError, ValueError, RuntimeError) as exc:
                outcome = exc
            try:
                relay.done.emit(generation, row, outcome)
            except RuntimeError:
                pass

        threading.Thread(target=run, name="dmm-mounted-open-texture", daemon=True).start()
        self._report_status(f"Opening {row.game_path} from DMM's {row.mod} in Texture Editor...")
        return row.game_path

    def _texture_prepared(self, generation: int, _row: object, outcome: object) -> None:
        if self._closed or generation != self._texture_generation:
            return
        if isinstance(outcome, BaseException):
            self._report_status(str(outcome), error=True)
            return
        entry, prepared_path = outcome
        shell = getattr(self._archive, "shell", None)
        textures = getattr(shell, "textures", None)
        opener = getattr(textures, "open_prepared_archive_texture", None)
        if not callable(opener):
            self._report_status("The Texture Editor is unavailable.", error=True)
            return
        opener(entry, prepared_path)
        self.accept()

    def copy_selected(self, folder: Path | str) -> list[str]:
        """Copy selected non-kept-vanilla mounted files to ``folder`` under game paths."""

        from cdmw.domain.output_paths import check_output_path

        rows = [row for row in self.selected_rows() if not row.kept_vanilla]
        target_root = check_output_path(folder, game_folder=self._game_root() or None, allow_existing=True)
        written = _copy_added_rows(self._game_root(), rows, target_root)
        self._report_status(f"Copied {len(written):,} file(s) to {target_root}.")
        return written

    def copy_selected_dialog(self) -> None:
        from cdmw.domain.output_paths import check_output_path

        if self._copy_in_progress:
            return
        rows = tuple(row for row in self.selected_rows() if not row.kept_vanilla)
        if not rows:
            return
        folder = QFileDialog.getExistingDirectory(self, "Copy DMM's files to a folder")
        if not folder:
            return
        game_root = self._game_root()
        try:
            target_root = check_output_path(folder, game_folder=game_root or None, allow_existing=True)
        except (OSError, ValueError) as exc:
            self._report_status(str(exc), error=True)
            return
        self._copy_in_progress = True
        self._copy_generation += 1
        generation, relay = self._copy_generation, self._copy_relay
        self._sync_buttons()
        self._report_status(f"Copying {len(rows):,} file(s)...")

        def run() -> None:
            try:
                outcome: object = _copy_added_rows(game_root, rows, target_root)
            except (OSError, ValueError) as exc:
                outcome = exc
            try:
                relay.done.emit(generation, target_root, outcome)
            except RuntimeError:
                pass

        threading.Thread(target=run, name="dmm-mounted-file-copy", daemon=True).start()

    def _copy_finished(self, generation: int, target_root: object, outcome: object) -> None:
        if self._closed or generation != self._copy_generation:
            return
        self._copy_in_progress = False
        self._sync_buttons()
        if isinstance(outcome, BaseException):
            self._report_status(str(outcome), error=True)
            return
        self._report_status(f"Copied {len(outcome):,} file(s) to {target_root}.")

    def show_selected_source(self) -> None:
        rows = self.selected_rows()
        if len(rows) == 1:
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(rows[0].source.parent)))

    def reject(self) -> None:
        self._closed = True
        self._cancel_catalogue_lookup()
        self._cancel_pending_open()
        super().reject()

    def accept(self) -> None:
        self._closed = True
        self._cancel_catalogue_lookup()
        self._cancel_pending_open()
        super().accept()

    def closeEvent(self, event) -> None:  # noqa: N802 - Qt override
        self._closed = True
        self._cancel_catalogue_lookup()
        self._cancel_pending_open()
        super().closeEvent(event)


def show_dmm_mounted_mods_dialog(archive) -> DmmMountedModsDialog:
    """Open or focus the Archive Browser's DMM Mounted Mods dialog."""

    from shiboken6 import isValid

    existing = getattr(archive, "_dmm_mounted_mods_dialog", None)
    if existing is not None and isValid(existing):
        existing._closed = False
        existing.reload()
        existing.show()
        existing.raise_()
        existing.activateWindow()
        return existing
    dialog = DmmMountedModsDialog(archive)
    archive._dmm_mounted_mods_dialog = dialog
    dialog.show()
    dialog.raise_()
    dialog.activateWindow()
    return dialog


__all__ = ["DmmMountedFileRow", "DmmMountedModsDialog", "show_dmm_mounted_mods_dialog"]
