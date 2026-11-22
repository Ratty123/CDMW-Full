"""Mod Management > Mounted in DMM: inspect mounted DMM files, spot overlaps, and open assets."""

from __future__ import annotations

import threading
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, replace
from pathlib import Path, PurePosixPath
import re

from PySide6.QtCore import QEvent, QSignalBlocker, Qt, QTimer, QUrl, Signal
from PySide6.QtGui import QBrush, QColor, QDesktopServices, QPalette
from PySide6.QtWidgets import (
    QAbstractItemView,
    QApplication,
    QCheckBox,
    QComboBox,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMenu,
    QPushButton,
    QSplitter,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from cdmw.domain.archives.constants import ARCHIVE_MESH_EXTENSIONS
from cdmw.services.dmm_mount_overlaps import (
    DmmOverlapAnalysis,
    format_overlap_report,
    scan_dmm_mount_overlaps,
)
from cdmw.services.dmm_runtime_mount import (
    DMM_MERGED_LABEL,
    DMM_NOTE_PREFIX,
    KEEP_GAME_EXTENSIONS,
    SHOW_MOUNTED_MODS_SETTING,
    DmmRuntimeMount,
    DmmServedFile,
    added_dependency_entries,
    added_entry,
    current_overlay,
    describe_mount,
    mod_root_from_source,
    normalized_game_path,
    short_mod_name,
)
from cdmw.services.dmm_send import DMM_FOLDER_SETTING
from cdmw.ui.archive_browser.dmm_added_files import (
    _Relay,
    _expected_sidecar_path,
    _referenced_game_paths,
    resolve_missing_vanilla_and_launch_mesh_editor,
)
from cdmw.ui.widgets import EmptyStateTreeWidget, request_settings_sync

_TEXTURE_EXTENSIONS = frozenset({".dds"})
_GROUP_FOLDER = re.compile(r"\d{4}")
_KIND_KEYS = (
    "all",
    "overlaps",
    "meshes",
    "textures",
    "replaces",
    "added",
    "merged",
    "kept_vanilla",
)
_ROLE_NONE = 0
_ROLE_WARNING = 1
_ROLE_INFO = 2
_ROLE_MUTED = 3


@dataclass(frozen=True, slots=True)
class DmmMountedFileRow:
    """One file listed in DMM's runtime mount manifest or overridden enabled mod."""

    game_path: str
    mod: str
    source: Path
    extension: str
    kept_vanilla: bool
    in_catalogue: bool | None = None
    catalogue_dto: object | None = None
    is_overridden: bool = False
    winning_mod: str = ""
    overridden_mods: tuple[str, ...] = ()
    merged_mods: tuple[str, ...] = ()
    is_merged: bool = False


def _row_storage_key(row: DmmMountedFileRow) -> str:
    return f"{int(row.is_overridden)}:{normalized_game_path(row.game_path)}:{str(row.source).casefold()}"


def _find_file_in_mod_root(mod_root: Path | None, game_path: str) -> Path | None:
    if mod_root is None:
        return None
    rel = PurePosixPath(normalized_game_path(game_path))
    if not rel.parts or ".." in rel.parts:
        return None
    try:
        if not mod_root.is_dir():
            return None
        resolved_root = mod_root.resolve()
        direct = mod_root.joinpath(*rel.parts)
        if direct.is_file() and not direct.is_symlink() and direct.resolve().is_relative_to(resolved_root):
            return direct
        for child in sorted(mod_root.iterdir(), key=lambda item: item.name.casefold()):
            if not _GROUP_FOLDER.fullmatch(child.name) or child.is_symlink() or not child.is_dir():
                continue
            nested = child.joinpath(*rel.parts)
            if nested.is_file() and not nested.is_symlink() and nested.resolve().is_relative_to(resolved_root):
                return nested
    except OSError:
        return None
    return None


def _note_for_row(row: DmmMountedFileRow, mod_name: str) -> str:
    if row.is_overridden:
        winner = row.winning_mod.replace(",", ";").strip()
        return f"{DMM_NOTE_PREFIX} {row.mod} (overridden by {winner})" if winner else f"{DMM_NOTE_PREFIX} {row.mod} (overridden)"
    return f"{DMM_NOTE_PREFIX} {mod_name}"


def _resolve_entry_from_row(mount: object, row: DmmMountedFileRow, prepared: object) -> object:
    """Attach DMM's prepared bytes while preserving vanilla archive identity when known."""

    note = _note_for_row(row, prepared.mod)
    if row.catalogue_dto is not None:
        from cdmw.services.archive_catalogue_service import ArchiveCatalogueService

        base = ArchiveCatalogueService.compatibility_entry(row.catalogue_dto)
        return replace(
            base,
            prepared_path=prepared.path,
            prepared_size=prepared.size,
            prepared_sha256=prepared.sha256,
            prepared_note=note,
        )
    entry = added_entry(mount, DmmServedFile(row.game_path, row.source, row.mod), prepared)
    if entry.prepared_note != note:
        return replace(entry, prepared_note=note)
    return entry


def _attach_row_identity(
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
    *,
    mod_root: Path | None = None,
):
    """Copy DMM's served mesh (active or overridden) plus companions off the UI thread."""

    overlay = current_overlay()
    mount, error = overlay.mount(game_root)
    if row.is_overridden:
        if mount is None or not overlay.enabled:
            raise ValueError(error or f"DMM no longer serves {row.game_path}. Refresh from DMM first.")
        prepared = overlay.prepare_served(DmmServedFile(row.game_path, row.source, row.mod))
        if prepared is None:
            raise ValueError(f"Could not read overridden file {row.source} for {row.game_path}.")
    else:
        served = overlay.served_file(game_root, row.game_path)
        prepared = overlay.prepare(game_root, row.game_path) if served is not None else None
        if mount is None or served is None or prepared is None:
            raise ValueError(error or f"DMM no longer serves {row.game_path}. Refresh from DMM first.")

    entry = _resolve_entry_from_row(mount, row, prepared)
    seed_list = [entry]
    effective_mod_root = mod_root or mod_root_from_source(row.source, row.game_path)

    def append_overridden_companion(dep_path: str) -> bool:
        if not row.is_overridden or effective_mod_root is None:
            return False
        candidate_file = _find_file_in_mod_root(effective_mod_root, dep_path)
        if candidate_file is None:
            return False
        dep_prepared = overlay.prepare_served(DmmServedFile(dep_path, candidate_file, row.mod))
        if dep_prepared is None:
            return False
        known_row = rows_by_path.get(normalized_game_path(dep_path)) if rows_by_path else None
        dep_row = DmmMountedFileRow(
            game_path=dep_path,
            mod=row.mod,
            source=candidate_file,
            extension=PurePosixPath(dep_path).suffix.casefold(),
            kept_vanilla=False,
            in_catalogue=known_row.in_catalogue if known_row else None,
            catalogue_dto=known_row.catalogue_dto if known_row else None,
            is_overridden=True,
            winning_mod=row.winning_mod,
        )
        seed_list.append(_resolve_entry_from_row(mount, dep_row, dep_prepared))
        return True

    sidecar_path = _expected_sidecar_path(entry.path)
    sidecar_key = normalized_game_path(sidecar_path)
    if sidecar_key and sidecar_key != normalized_game_path(entry.path):
        if not append_overridden_companion(sidecar_path):
            sidecar_served = overlay.served_file(game_root, sidecar_path)
            sidecar_prepared = overlay.prepare(game_root, sidecar_path) if sidecar_served is not None else None
            if sidecar_served is not None and sidecar_prepared is not None:
                sidecar_row = rows_by_path.get(sidecar_key) if rows_by_path else None
                if sidecar_row is not None:
                    seed_list.append(_resolve_entry_from_row(mount, sidecar_row, sidecar_prepared))
                else:
                    seed_list.append(added_entry(mount, sidecar_served, sidecar_prepared))

    if row.is_overridden and effective_mod_root is not None:
        for ref_path in _referenced_game_paths(entry, tuple(seed_list)):
            if any(normalized_game_path(getattr(item, "path", "")) == ref_path for item in seed_list):
                continue
            append_overridden_companion(ref_path)

    seed_entries = tuple(seed_list)
    seen_paths: set[str] = set()
    deduped_entries = []
    for candidate in (*seed_entries, *added_dependency_entries(game_root, seed_entries, overlay=overlay)):
        key = normalized_game_path(getattr(candidate, "path", ""))
        if not key or key in seen_paths:
            continue
        seen_paths.add(key)
        deduped_entries.append(_attach_row_identity(candidate, rows_by_path))
    entries = tuple(deduped_entries)
    missing_game_paths = _referenced_game_paths(entry, entries)
    return entry, entries, missing_game_paths


def _prepare_texture_row(game_root: str, row: DmmMountedFileRow):
    """Copy DMM's served texture (active or overridden) off the UI thread before Texture Editor."""

    overlay = current_overlay()
    mount, error = overlay.mount(game_root)
    if row.is_overridden:
        if mount is None or not overlay.enabled:
            raise ValueError(error or f"DMM no longer serves {row.game_path}. Refresh from DMM first.")
        prepared = overlay.prepare_served(DmmServedFile(row.game_path, row.source, row.mod))
        if prepared is None:
            raise ValueError(f"Could not read overridden file {row.source} for {row.game_path}.")
        return _resolve_entry_from_row(mount, row, prepared), prepared.path
    served = overlay.served_file(game_root, row.game_path)
    prepared = overlay.prepare(game_root, row.game_path) if served is not None else None
    if mount is None or served is None or prepared is None:
        raise ValueError(error or f"DMM no longer serves {row.game_path}. Refresh from DMM first.")
    return _resolve_entry_from_row(mount, row, prepared), prepared.path


def _copy_mounted_rows(game_root: str, rows: Iterable[DmmMountedFileRow], target_root: Path) -> list[str]:
    import shutil

    resolved_root = target_root.resolve()
    overlay = current_overlay()
    written: list[str] = []
    for row in rows:
        if row.is_overridden:
            prepared = overlay.prepare_served(DmmServedFile(row.game_path, row.source, row.mod))
        else:
            prepared = overlay.prepare(game_root, row.game_path)
        if prepared is None:
            raise ValueError(f"DMM no longer serves {row.game_path}. Refresh from DMM first.")
        rel = PurePosixPath(row.game_path)
        target = target_root.joinpath(*rel.parts)
        if not target.resolve().is_relative_to(resolved_root):
            raise ValueError(f"{row.game_path} is not a path inside the folder.")
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(prepared.path, target)
        written.append(str(target))
    return written


def _semantic_color(widget: QWidget, role: int) -> QColor:
    dark = widget.palette().color(QPalette.ColorRole.Window).lightness() < 128
    if role == _ROLE_WARNING:
        return QColor(229, 183, 117) if dark else QColor(133, 88, 20)
    if role == _ROLE_INFO:
        return QColor(127, 184, 230) if dark else QColor(30, 92, 148)
    return QColor(143, 153, 163) if dark else QColor(100, 108, 117)


class DmmMountedModsPage(QWidget):
    """Inspect all files DMM mounts, detect overlaps across enabled mods, and open assets."""

    activity = Signal(str)

    def __init__(
        self,
        archive: object = None,
        parent: QWidget | None = None,
        *,
        get_game_root=None,
        settings=None,
        on_navigated=None,
        show_close_button: bool = False,
        defer_initial_load: bool = False,
    ) -> None:
        super().__init__(parent)
        self.setObjectName("mod_management_dmm_mounted")
        self._archive = archive
        #: Live-catalogue lookup helper inspects ``owner.archive``.
        self.archive = archive
        self._get_game_root = get_game_root
        self._explicit_settings = settings
        self._on_navigated = on_navigated
        self._closed = False
        self._dirty = True
        self._last_game_root = ""
        self._ignoring_overlay_event = False
        self._mount_snapshot: DmmRuntimeMount | None = None
        self._overlap_analysis: DmmOverlapAnalysis | None = None
        self._all_rows: list[DmmMountedFileRow] = []
        self._rows_by_path: dict[str, DmmMountedFileRow] = {}
        self._overridden_rows_by_mod: dict[str, list[DmmMountedFileRow]] = {}
        self._displayed_rows_by_key: dict[str, DmmMountedFileRow] = {}
        self._mod_folders: dict[str, Path] = {}
        self._selected_mod: str = ""
        self._catalogue_lookup = None
        self._open_lookup = None
        self._prepare_cleanup = None
        self._overlap_stop: threading.Event | None = None
        self._catalogue_generation = 0
        self._overlap_generation = 0
        self._open_generation = 0
        self._texture_generation = 0
        self._copy_generation = 0
        self._overlap_scanning = False
        self._copy_in_progress = False

        self._overlap_relay = _Relay(self)
        self._overlap_relay.done.connect(self._overlap_finished)
        self._open_relay = _Relay(self)
        self._open_relay.done.connect(self._open_prepared)
        self._texture_relay = _Relay(self)
        self._texture_relay.done.connect(self._texture_prepared)
        self._copy_relay = _Relay(self)
        self._copy_relay.done.connect(self._copy_finished)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)

        top_row = QHBoxLayout()
        top_row.setSpacing(8)
        self.enabled_checkbox = QCheckBox(self.tr("Show DMM's mounted files in CDMW"))
        self.enabled_checkbox.setObjectName("DmmDialogShowMountedMods")
        self.enabled_checkbox.setToolTip(
            self.tr("When checked, Browse Archives, Mesh Editor, Texture Editor, and Extract use the files DMM mounts instead of vanilla.")
        )
        self.enabled_checkbox.setChecked(current_overlay().enabled)
        top_row.addWidget(self.enabled_checkbox)
        top_row.addStretch(1)
        self.copy_report_button = QPushButton(self.tr("Copy Overlap Report"))
        self.copy_report_button.setObjectName("mod_management_dmm_copy_report")
        self.copy_report_button.setToolTip(self.tr("Copy a plain-text summary of mounted mods and file overlaps to the clipboard."))
        top_row.addWidget(self.copy_report_button)
        self.refresh_button = QPushButton(self.tr("Refresh from DMM"))
        self.refresh_button.setObjectName("mod_management_dmm_refresh")
        self.refresh_button.setToolTip(self.tr("Read DMM's manifest again after mounting or unmounting mods in DMM."))
        top_row.addWidget(self.refresh_button)
        layout.addLayout(top_row)

        self.notice_label = QLabel("")
        self.notice_label.setObjectName("mod_management_dmm_notice")
        self.notice_label.setProperty("managementRole", "notice")
        self.notice_label.setTextFormat(Qt.TextFormat.PlainText)
        self.notice_label.setWordWrap(True)
        self.notice_label.hide()
        layout.addWidget(self.notice_label)

        self.status_label = QLabel("")
        self.status_label.setObjectName("mod_management_dmm_status")
        self.status_label.setProperty("hintText", True)
        self.status_label.setTextFormat(Qt.TextFormat.PlainText)
        self.status_label.setWordWrap(True)
        layout.addWidget(self.status_label)

        self.splitter = QSplitter(Qt.Orientation.Horizontal, self)
        self.splitter.setObjectName("mod_management_dmm_splitter")

        # Left pane: mounted mods list + overlap summary
        left_pane = QWidget(self.splitter)
        left_layout = QVBoxLayout(left_pane)
        left_layout.setContentsMargins(0, 0, 0, 0)
        left_layout.setSpacing(6)
        mods_header = QHBoxLayout()
        mods_header.setSpacing(6)
        mods_title = QLabel(self.tr("Mounted mods"))
        mods_header.addWidget(mods_title)
        mods_header.addStretch(1)
        self.open_mod_folder_button = QPushButton(self.tr("Open Mod Folder"))
        self.open_mod_folder_button.setObjectName("mod_management_dmm_open_mod_folder")
        self.open_mod_folder_button.setToolTip(self.tr("Open the selected mod's folder in Explorer."))
        mods_header.addWidget(self.open_mod_folder_button)
        left_layout.addLayout(mods_header)

        self.mod_tree = EmptyStateTreeWidget(
            self.tr("No mounted mods"),
            self.tr("Mount mods in DMM, then click Refresh from DMM."),
        )
        self.mod_tree.setObjectName("mod_management_dmm_mods_tree")
        self.mod_tree.setHeaderLabels([self.tr("Mod"), self.tr("Files"), self.tr("Overlaps")])
        self.mod_tree.setRootIsDecorated(False)
        self.mod_tree.setAlternatingRowColors(True)
        self.mod_tree.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.mod_tree.setUniformRowHeights(True)
        self.mod_tree.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        mod_header = self.mod_tree.header()
        mod_header.setStretchLastSection(True)
        for col, width in enumerate((175, 52, 95)):
            self.mod_tree.setColumnWidth(col, width)
        left_layout.addWidget(self.mod_tree, 1)

        # Right pane: filterable file list + selection detail bar
        right_pane = QWidget(self.splitter)
        right_layout = QVBoxLayout(right_pane)
        right_layout.setContentsMargins(0, 0, 0, 0)
        right_layout.setSpacing(6)

        filters_row = QHBoxLayout()
        filters_row.setSpacing(8)
        self.search_edit = QLineEdit()
        self.search_edit.setObjectName("mod_management_dmm_search")
        self.search_edit.setPlaceholderText(self.tr("Filter by file name, path, or mod..."))
        self.search_edit.setClearButtonEnabled(True)
        filters_row.addWidget(self.search_edit, 2)
        self.kind_combo = QComboBox()
        self.kind_combo.setObjectName("mod_management_dmm_kind")
        kind_labels = (
            self.tr("All mounted files"),
            self.tr("Overlaps / conflicts only"),
            self.tr("Meshes (.pac, .pam, .pamlod)"),
            self.tr("Textures (.dds)"),
            self.tr("Replaces game file"),
            self.tr("Added by mod only"),
            self.tr("Merged by DMM"),
            self.tr("Kept vanilla (game tables)"),
        )
        for label, key in zip(kind_labels, _KIND_KEYS):
            self.kind_combo.addItem(label, key)
        filters_row.addWidget(self.kind_combo, 1)
        right_layout.addLayout(filters_row)

        self.file_tree = EmptyStateTreeWidget(
            self.tr("No mounted files"),
            self.tr("No DMM mounted files match the current filter."),
        )
        self.file_tree.setObjectName("DmmMountedModsTree")
        self.file_tree.setHeaderLabels([
            self.tr("File"),
            self.tr("Status"),
            self.tr("Mod"),
            self.tr("Type"),
            self.tr("Game Path"),
        ])
        self.file_tree.setRootIsDecorated(False)
        self.file_tree.setAlternatingRowColors(True)
        self.file_tree.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.file_tree.setSortingEnabled(True)
        self.file_tree.setUniformRowHeights(True)
        file_header = self.file_tree.header()
        file_header.setStretchLastSection(True)
        for col, width in enumerate((210, 165, 175, 65, 270)):
            self.file_tree.setColumnWidth(col, width)
        right_layout.addWidget(self.file_tree, 1)

        self.detail_label = QLabel(self.tr("Select a file to see active vs. overridden mods and source paths."))
        self.detail_label.setObjectName("mod_management_dmm_detail")
        self.detail_label.setProperty("hintText", True)
        self.detail_label.setTextFormat(Qt.TextFormat.PlainText)
        self.detail_label.setWordWrap(True)
        right_layout.addWidget(self.detail_label)

        self.splitter.addWidget(left_pane)
        self.splitter.addWidget(right_pane)
        self.splitter.setSizes([280, 680])
        layout.addWidget(self.splitter, 1)

        primary_buttons = QHBoxLayout()
        primary_buttons.setSpacing(8)
        self.filter_browse_button = QPushButton(self.tr("Filter Browse Archives"))
        self.filter_browse_button.setObjectName("mod_management_dmm_filter_browse")
        self.filter_browse_button.setToolTip(
            self.tr("Limit Browse Archives to the currently visible mounted files that replace a game file.")
        )
        self.show_in_browse_button = QPushButton(self.tr("Show in Browse Archives"))
        self.show_in_browse_button.setObjectName("mod_management_dmm_show_browse")
        self.show_in_browse_button.setToolTip(self.tr("Jump to the selected mounted file inside Browse Archives."))
        self.open_mesh_button = QPushButton(self.tr("Open in Mesh Editor"))
        self.open_mesh_button.setObjectName("mod_management_dmm_open_mesh")
        self.open_texture_button = QPushButton(self.tr("Open in Texture Editor"))
        self.open_texture_button.setObjectName("mod_management_dmm_open_texture")
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
        secondary_buttons.setSpacing(8)
        self.copy_button = QPushButton(self.tr("Copy to Folder..."))
        self.copy_button.setObjectName("mod_management_dmm_copy_folder")
        self.show_source_button = QPushButton(self.tr("Show Source File"))
        self.show_source_button.setObjectName("mod_management_dmm_show_source")
        secondary_buttons.addWidget(self.copy_button)
        secondary_buttons.addWidget(self.show_source_button)
        secondary_buttons.addStretch(1)
        self.close_button = QPushButton(self.tr("Close")) if show_close_button else None
        if self.close_button is not None:
            secondary_buttons.addWidget(self.close_button)
        layout.addLayout(secondary_buttons)

        self.enabled_checkbox.toggled.connect(self._toggle_overlay)
        self.refresh_button.clicked.connect(self.refresh_from_dmm)
        self.copy_report_button.clicked.connect(self.copy_overlap_report)
        self.open_mod_folder_button.clicked.connect(self.open_selected_mod_folder)
        self.mod_tree.itemSelectionChanged.connect(self._on_mod_selection_changed)
        self.mod_tree.customContextMenuRequested.connect(self._mod_tree_context_menu)
        self._search_interactive = False
        self._search_timer = QTimer(self)
        self._search_timer.setSingleShot(True)
        self._search_timer.setInterval(150)
        self._search_timer.timeout.connect(self._populate_tree)
        self.search_edit.textEdited.connect(self._on_search_text_edited)
        self.search_edit.textChanged.connect(self._on_search_text_changed)
        self.search_edit.returnPressed.connect(self._flush_search_filter)
        self.kind_combo.currentIndexChanged.connect(self._on_kind_changed)
        self.file_tree.itemSelectionChanged.connect(self._on_file_selection_changed)
        self.file_tree.itemDoubleClicked.connect(self._handle_double_click)
        self.filter_browse_button.clicked.connect(self.filter_browse_archives)
        self.show_in_browse_button.clicked.connect(self.show_selected_in_browse)
        self.open_mesh_button.clicked.connect(self.open_selected_in_mesh_editor)
        self.open_texture_button.clicked.connect(self.open_selected_in_texture_editor)
        self.copy_button.clicked.connect(self.copy_selected_dialog)
        self.show_source_button.clicked.connect(self.show_selected_source)

        overlay = current_overlay()
        self._overlay_listener = self._on_overlay_changed
        overlay.add_listener(self._overlay_listener)
        self.destroyed.connect(
            lambda _obj=None, ov=overlay, listener=self._overlay_listener: ov.remove_listener(listener)
        )

        if not defer_initial_load:
            self.reload()
        else:
            self._update_status_text()
            self._sync_buttons()

    def _settings(self):
        if self._explicit_settings is not None and callable(getattr(self._explicit_settings, "value", None)):
            return self._explicit_settings
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
        if callable(self._get_game_root):
            root = str(self._get_game_root() or "").strip()
            if root:
                return root
        bridge = getattr(self._archive, "archive_remote_bridge", None)
        session = getattr(bridge, "current_session", None)
        root = str(getattr(session, "package_root", "") or "").strip()
        if root:
            return root
        settings = self._settings()
        if settings is not None:
            return str(settings.value("archive/package_root", "") or "").strip()
        return ""

    def _saved_dmm_folder(self) -> str:
        settings = self._settings()
        if settings is None:
            return ""
        return str(settings.value(DMM_FOLDER_SETTING, "") or "").strip()

    def _session_loaded(self) -> bool:
        bridge = getattr(self._archive, "archive_remote_bridge", None)
        return getattr(bridge, "current_session", None) is not None

    def set_game_root(self, root: str) -> None:
        normalized = str(root or "").strip()
        if normalized != self._last_game_root:
            self._dirty = True
            if self.isVisible():
                self.reload()

    def refresh_if_needed(self) -> None:
        if not self._closed and self._dirty:
            self.reload()

    def showEvent(self, event) -> None:  # noqa: N802 - Qt override
        super().showEvent(event)
        if not self._closed:
            self.refresh_if_needed()

    def changeEvent(self, event) -> None:  # noqa: N802 - Qt override
        super().changeEvent(event)
        if event.type() == QEvent.Type.PaletteChange and not self._closed and not self._dirty:
            self._rebuild_mod_tree()
            self._populate_tree()

    def _on_overlay_changed(self) -> None:
        if self._closed or self._ignoring_overlay_event:
            return
        with QSignalBlocker(self.enabled_checkbox):
            self.enabled_checkbox.setChecked(current_overlay().enabled)
        if self.isVisible() or not self._dirty:
            self.reload()

    def _toggle_overlay(self, checked: bool) -> None:
        settings = self._settings()
        if settings is not None and callable(getattr(settings, "setValue", None)):
            settings.setValue(SHOW_MOUNTED_MODS_SETTING, bool(checked))
            request_settings_sync(settings)
        self._ignoring_overlay_event = True
        try:
            current_overlay().set_enabled(checked)
        finally:
            self._ignoring_overlay_event = False
        self._update_status_text()
        self._sync_buttons()

    def refresh_from_dmm(self) -> None:
        """Force re-reading bin64/dmm/manifest.tsv and enabled DMM mods."""

        self._ignoring_overlay_event = True
        try:
            current_overlay().refresh(self._game_root())
        finally:
            self._ignoring_overlay_event = False
        self.reload()

    def reload(self) -> None:
        """Load DMM's current manifest rows and kick off catalogue and overlap checks."""

        self._dirty = False
        self._cancel_catalogue_lookup()
        self._cancel_overlap_scan()
        overlay = current_overlay()
        with QSignalBlocker(self.enabled_checkbox):
            self.enabled_checkbox.setChecked(overlay.enabled)
        game_root = self._game_root()
        self._last_game_root = game_root
        info = describe_mount(game_root, overlay)
        mount, _error = overlay.mount(game_root) if game_root else (None, "")
        self._mount_snapshot = mount
        self._overlap_analysis = None
        self._overridden_rows_by_mod = {}
        self._mod_folders = {}

        rows: list[DmmMountedFileRow] = []
        if mount is not None and mount.serving:
            for key, served in mount.files.items():
                ext = PurePosixPath(key).suffix.casefold()
                kept = ext in KEEP_GAME_EXTENSIONS
                is_merged = served.mod == DMM_MERGED_LABEL
                if not is_merged:
                    folder = mod_root_from_source(served.source, served.game_path)
                    if folder is not None and served.mod not in self._mod_folders:
                        self._mod_folders[served.mod] = folder
                dups = mount.duplicates.get(key, ())
                overridden_mods = tuple(
                    dict.fromkeys(
                        dup.mod
                        for dup in dups
                        if dup.mod.casefold() != served.mod.casefold()
                    )
                )
                rows.append(
                    DmmMountedFileRow(
                        game_path=served.game_path,
                        mod=served.mod,
                        source=served.source,
                        extension=ext,
                        kept_vanilla=kept,
                        overridden_mods=overridden_mods,
                        is_merged=is_merged,
                    )
                )
                for dup in dups:
                    if dup.mod.casefold() == served.mod.casefold():
                        continue
                    dup_folder = mod_root_from_source(dup.source, dup.game_path)
                    if dup_folder is not None and dup.mod not in self._mod_folders:
                        self._mod_folders[dup.mod] = dup_folder
                    self._overridden_rows_by_mod.setdefault(dup.mod, []).append(
                        DmmMountedFileRow(
                            game_path=served.game_path,
                            mod=dup.mod,
                            source=dup.source,
                            extension=ext,
                            kept_vanilla=kept,
                            is_overridden=True,
                            winning_mod=served.mod,
                        )
                    )
        rows.sort(key=lambda row: row.game_path.casefold())
        self._all_rows = rows
        self._rows_by_path = {normalized_game_path(row.game_path): row for row in rows}
        self._rebuild_mod_tree()
        self._populate_tree()
        self._update_notice_banner(info, mount, None)
        self._update_status_text(info)
        self._update_detail_bar()
        self._start_catalogue_lookup()
        self._start_overlap_scan(mount)

    def _start_overlap_scan(self, mount: DmmRuntimeMount | None) -> None:
        if mount is None or not mount.serving:
            return
        self._overlap_generation += 1
        generation = self._overlap_generation
        stop_event = threading.Event()
        self._overlap_stop = stop_event
        self._overlap_scanning = True
        saved_dmm = self._saved_dmm_folder()
        relay = self._overlap_relay
        self._update_status_text()

        def run() -> None:
            try:
                outcome: object = scan_dmm_mount_overlaps(
                    mount,
                    saved_dmm_folder=saved_dmm,
                    stop_event=stop_event,
                )
            except Exception as exc:  # noqa: BLE001 - surface cleanly in status
                outcome = exc
            if stop_event.is_set():
                return
            try:
                relay.done.emit(generation, mount, outcome)
            except RuntimeError:
                pass

        threading.Thread(target=run, name="dmm-mount-overlap-scan", daemon=True).start()

    def _cancel_overlap_scan(self) -> None:
        self._overlap_generation += 1
        self._overlap_scanning = False
        stop = self._overlap_stop
        if stop is not None:
            self._overlap_stop = None
            stop.set()

    def _overlap_finished(self, generation: int, _mount: object, outcome: object) -> None:
        if self._closed or generation != self._overlap_generation:
            return
        self._overlap_scanning = False
        self._overlap_stop = None
        if isinstance(outcome, BaseException):
            self._update_status_text()
            return
        analysis: DmmOverlapAnalysis = outcome
        self._overlap_analysis = analysis
        self._mod_folders = dict(analysis.mod_folders)

        updated_all: list[DmmMountedFileRow] = []
        overridden_by_mod: dict[str, list[DmmMountedFileRow]] = {}
        for row in self._all_rows:
            key = normalized_game_path(row.game_path)
            losers = analysis.overlaps_by_path.get(key, ())
            overridden_mods = tuple(dict.fromkeys(loser.mod for loser in losers))
            contributors = analysis.merged_contributors_by_path.get(key, ())
            merged_mods = tuple(dict.fromkeys(item.mod for item in contributors))
            updated_row = replace(
                row,
                overridden_mods=overridden_mods,
                merged_mods=merged_mods,
            )
            updated_all.append(updated_row)
            for loser in losers:
                overridden_by_mod.setdefault(loser.mod, []).append(
                    DmmMountedFileRow(
                        game_path=row.game_path,
                        mod=loser.mod,
                        source=loser.source,
                        extension=row.extension,
                        kept_vanilla=row.kept_vanilla,
                        in_catalogue=row.in_catalogue,
                        catalogue_dto=row.catalogue_dto,
                        is_overridden=True,
                        winning_mod=row.mod,
                    )
                )
        for mod_rows in overridden_by_mod.values():
            mod_rows.sort(key=lambda item: item.game_path.casefold())

        self._all_rows = updated_all
        self._rows_by_path = {normalized_game_path(row.game_path): row for row in updated_all}
        self._overridden_rows_by_mod = overridden_by_mod
        self._rebuild_mod_tree()
        self._populate_tree()
        self._update_notice_banner(None, self._mount_snapshot, analysis)
        self._update_status_text()
        self._update_detail_bar()

    def _update_notice_banner(
        self,
        info: Mapping[str, object] | None,
        mount: DmmRuntimeMount | None,
        analysis: DmmOverlapAnalysis | None,
    ) -> None:
        messages: list[str] = []
        if info is None:
            info = describe_mount(self._game_root(), current_overlay())
        state = str(info.get("state", "") or "")
        if state == "stale" and mount is not None and mount.problem:
            messages.append(mount.problem)
        elif state == "unreadable" and info.get("message"):
            messages.append(str(info["message"]))
        if analysis is not None and mount is not None and mount.serving:
            if analysis.unmounted_enabled_mods:
                messages.append(
                    self.tr("Enabled in DMM but not in the current mount: {value_0}.").format(
                        value_0=", ".join(analysis.unmounted_enabled_mods)
                    )
                )
            if analysis.disabled_but_mounted_mods:
                messages.append(
                    self.tr("Currently mounted but disabled in DMM: {value_0}.").format(
                        value_0=", ".join(analysis.disabled_but_mounted_mods)
                    )
                )
            if analysis.unmounted_enabled_mods or analysis.disabled_but_mounted_mods:
                messages.append(self.tr("Click Mount in DMM, then Refresh from DMM."))
        text = " ".join(part for part in messages if part).strip()
        self.notice_label.setText(text)
        self.notice_label.setVisible(bool(text))

    def _update_status_text(self, info: Mapping[str, object] | None = None) -> None:
        if info is None:
            info = describe_mount(self._game_root(), current_overlay())
        message = str(info.get("message", "") or "")
        details: list[str] = []
        if info.get("state") in {"serving", "off"} and self._all_rows:
            overlap_count = sum(1 for row in self._all_rows if row.overridden_mods)
            if overlap_count:
                details.append(self.tr("{value_0} overlapping file(s)").format(value_0=f"{overlap_count:,}"))
            if self._catalogue_lookup is None and self._session_loaded():
                replaces = sum(1 for row in self._all_rows if row.in_catalogue is True and not row.kept_vanilla)
                added = sum(1 for row in self._all_rows if row.in_catalogue is False and not row.kept_vanilla)
                kept = sum(1 for row in self._all_rows if row.kept_vanilla)
                details.append(
                    self.tr("{value_0} replace game file(s), {value_1} added by mod, {value_2} kept vanilla").format(
                        value_0=f"{replaces:,}",
                        value_1=f"{added:,}",
                        value_2=f"{kept:,}",
                    )
                )
            elif self._catalogue_lookup is None and not self._session_loaded():
                details.append(self.tr("Scan or load the game archives to match replaced vs. added files"))
        if self._catalogue_lookup is not None:
            details.append(self.tr("Matching mounted files against the game's archive index..."))
        if self._overlap_scanning:
            details.append(self.tr("Checking enabled DMM mods for overlaps..."))
        elif self._overlap_analysis is not None and self._overlap_analysis.config_note:
            details.append(self._overlap_analysis.config_note)
        if details:
            message = f"{message} ({'; '.join(details)})." if message else "; ".join(details)
        self.status_label.setText(message)

    def _rebuild_mod_tree(self) -> None:
        active_counts: dict[str, int] = {}
        wins_counts: dict[str, int] = {}
        for row in self._all_rows:
            active_counts[row.mod] = active_counts.get(row.mod, 0) + 1
            if row.overridden_mods:
                wins_counts[row.mod] = wins_counts.get(row.mod, 0) + 1
        all_mods = set(active_counts) | set(self._overridden_rows_by_mod)
        ordered_mods = sorted(
            (mod for mod in all_mods if mod != DMM_MERGED_LABEL),
            key=str.casefold,
        )
        if DMM_MERGED_LABEL in all_mods:
            ordered_mods.append(DMM_MERGED_LABEL)

        total_overlaps = sum(1 for row in self._all_rows if row.overridden_mods)
        previous_mod = self._selected_mod
        if previous_mod and previous_mod not in all_mods:
            previous_mod = ""
            self._selected_mod = ""

        warning_brush = QBrush(_semantic_color(self, _ROLE_WARNING))
        info_brush = QBrush(_semantic_color(self, _ROLE_INFO))

        with QSignalBlocker(self.mod_tree):
            self.mod_tree.clear()
            all_item = QTreeWidgetItem([
                self.tr("All mounted mods"),
                f"{len(self._all_rows):,}",
                self.tr("{value_0} overlap(s)").format(value_0=f"{total_overlaps:,}") if total_overlaps else "",
            ])
            all_item.setData(0, Qt.ItemDataRole.UserRole, "")
            if total_overlaps:
                all_item.setForeground(2, warning_brush)
            self.mod_tree.addTopLevelItem(all_item)

            target_item = all_item
            for mod in ordered_mods:
                active = active_counts.get(mod, 0)
                wins = wins_counts.get(mod, 0)
                lost = len(self._overridden_rows_by_mod.get(mod, ()))
                if mod == DMM_MERGED_LABEL:
                    overlap_text = self.tr("Merged")
                elif wins and lost:
                    overlap_text = self.tr("{value_0} win / {value_1} lost").format(value_0=wins, value_1=lost)
                elif lost:
                    overlap_text = self.tr("{value_0} overridden").format(value_0=lost)
                elif wins:
                    overlap_text = self.tr("{value_0} overrides").format(value_0=wins)
                else:
                    overlap_text = ""

                item = QTreeWidgetItem([
                    short_mod_name(mod, max_chars=36),
                    f"{active:,}",
                    overlap_text,
                ])
                item.setData(0, Qt.ItemDataRole.UserRole, mod)
                if mod == DMM_MERGED_LABEL:
                    item.setForeground(0, info_brush)
                    item.setForeground(2, info_brush)
                elif wins or lost:
                    item.setForeground(2, warning_brush)
                    if active == 0 and lost > 0:
                        item.setForeground(0, warning_brush)
                folder = self._mod_folders.get(mod)
                tip_lines = [mod, self.tr("Active files: {value_0}").format(value_0=f"{active:,}")]
                if wins:
                    tip_lines.append(self.tr("Overrides other mods: {value_0}").format(value_0=f"{wins:,}"))
                if lost:
                    tip_lines.append(self.tr("Overridden by higher-priority mods: {value_0}").format(value_0=f"{lost:,}"))
                if folder is not None:
                    tip_lines.append(self.tr("Folder: {value_0}").format(value_0=str(folder)))
                tip = "\n".join(tip_lines)
                for col in range(3):
                    item.setToolTip(col, tip)
                self.mod_tree.addTopLevelItem(item)
                if previous_mod and mod == previous_mod:
                    target_item = item

            target_item.setSelected(True)
            self.mod_tree.setCurrentItem(target_item)
        self._sync_mod_buttons()

    def selected_mod(self) -> str:
        return self._selected_mod

    def select_mod(self, mod: str) -> bool:
        target = str(mod or "")
        for index in range(self.mod_tree.topLevelItemCount()):
            item = self.mod_tree.topLevelItem(index)
            if str(item.data(0, Qt.ItemDataRole.UserRole) or "") == target:
                self.mod_tree.setCurrentItem(item)
                return True
        return False

    def _on_mod_selection_changed(self) -> None:
        items = self.mod_tree.selectedItems()
        self._selected_mod = str(items[0].data(0, Qt.ItemDataRole.UserRole) or "") if items else ""
        self._sync_mod_buttons()
        self._populate_tree()
        self._update_detail_bar()

    def _selected_mod_folder(self) -> Path | None:
        if not self._selected_mod:
            return None
        folder = self._mod_folders.get(self._selected_mod)
        if folder is not None and folder.is_dir():
            return folder
        return None

    def _sync_mod_buttons(self) -> None:
        self.open_mod_folder_button.setEnabled(self._selected_mod_folder() is not None)
        self.copy_report_button.setEnabled(self._mount_snapshot is not None)

    def open_selected_mod_folder(self) -> bool:
        folder = self._selected_mod_folder()
        if folder is None:
            return False
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(folder)))
        return True

    def _mod_tree_context_menu(self, position) -> None:
        item = self.mod_tree.itemAt(position)
        if item is None:
            return
        if not item.isSelected():
            self.mod_tree.setCurrentItem(item)
        mod = str(item.data(0, Qt.ItemDataRole.UserRole) or "")
        if not mod:
            return
        folder = self._mod_folders.get(mod)
        menu = QMenu(self.mod_tree)
        action = menu.addAction(self.tr("Open Mod Folder"))
        action.setEnabled(folder is not None and folder.is_dir())
        action.triggered.connect(self.open_selected_mod_folder)
        menu.aboutToHide.connect(menu.deleteLater)
        menu.popup(self.mod_tree.viewport().mapToGlobal(position))

    def _rows_for_selected_mod(self) -> list[DmmMountedFileRow]:
        if not self._selected_mod:
            return list(self._all_rows)
        active = [row for row in self._all_rows if row.mod == self._selected_mod]
        overridden = list(self._overridden_rows_by_mod.get(self._selected_mod, ()))
        combined = active + overridden
        combined.sort(key=lambda row: (row.game_path.casefold(), row.is_overridden))
        return combined

    def _matches_filters(self, row: DmmMountedFileRow) -> bool:
        kind = str(self.kind_combo.currentData() or "all")
        if kind == "overlaps" and not (row.is_overridden or row.overridden_mods):
            return False
        if kind == "meshes" and row.extension not in ARCHIVE_MESH_EXTENSIONS:
            return False
        if kind == "textures" and row.extension not in _TEXTURE_EXTENSIONS:
            return False
        if kind == "replaces" and (row.kept_vanilla or row.in_catalogue is not True):
            return False
        if kind == "added" and (row.kept_vanilla or row.in_catalogue is not False):
            return False
        if kind == "merged" and not row.is_merged:
            return False
        if kind == "kept_vanilla" and not row.kept_vanilla:
            return False
        needle = self.search_edit.text().strip().casefold()
        if needle:
            extra = " ".join((*row.overridden_mods, *row.merged_mods, row.winning_mod))
            haystack = f"{row.game_path} {row.mod} {row.source.name} {extra}".casefold()
            if needle not in haystack:
                return False
        return True

    def visible_rows(self) -> list[DmmMountedFileRow]:
        return [row for row in self._rows_for_selected_mod() if self._matches_filters(row)]

    def _row_status_label_and_role(self, row: DmmMountedFileRow) -> tuple[str, int]:
        if row.is_overridden:
            winner = short_mod_name(row.winning_mod, max_chars=26) if row.winning_mod else self.tr("another mod")
            return self.tr("Overridden by {value_0}").format(value_0=winner), _ROLE_WARNING
        if row.kept_vanilla:
            return self.tr("Kept vanilla (game table)"), _ROLE_MUTED
        if row.overridden_mods:
            count = len(row.overridden_mods)
            if count == 1:
                return self.tr("Overrides 1 mod"), _ROLE_WARNING
            return self.tr("Overrides {value_0} mods").format(value_0=count), _ROLE_WARNING
        if row.is_merged:
            return self.tr("Merged by DMM"), _ROLE_INFO
        if row.in_catalogue is True:
            return self.tr("Replaces game file"), _ROLE_NONE
        if row.in_catalogue is False:
            return self.tr("Added by mod"), _ROLE_NONE
        if self._catalogue_lookup is not None:
            return self.tr("Mounted (checking...)"), _ROLE_NONE
        return self.tr("Mounted (not checked)"), _ROLE_NONE

    def _row_status_label(self, row: DmmMountedFileRow) -> str:
        return self._row_status_label_and_role(row)[0]

    def _row_tooltip(self, row: DmmMountedFileRow, status: str) -> str:
        lines = [
            self.tr("Game path: {value_0}").format(value_0=row.game_path),
            self.tr("Status: {value_0}").format(value_0=status),
            self.tr("Mod: {value_0}").format(value_0=row.mod),
        ]
        if row.is_overridden and row.winning_mod:
            lines.append(self.tr("Active (served) mod: {value_0}").format(value_0=row.winning_mod))
        elif row.overridden_mods:
            lines.append(self.tr("Also in (overridden): {value_0}").format(value_0=", ".join(row.overridden_mods)))
        elif row.is_merged and row.merged_mods:
            lines.append(self.tr("Merged from: {value_0}").format(value_0=", ".join(row.merged_mods)))
        lines.append(self.tr("DMM file: {value_0}").format(value_0=str(row.source)))
        return "\n".join(lines)

    def _on_search_text_edited(self, _text: str = "") -> None:
        self._search_interactive = True
        self._search_timer.start()

    def _on_search_text_changed(self, _text: str = "") -> None:
        if self._search_interactive:
            self._search_interactive = False
            return
        self._search_timer.stop()
        self._populate_tree()

    def _flush_search_filter(self) -> None:
        if self._search_timer.isActive():
            self._search_timer.stop()
            self._populate_tree()

    def _on_kind_changed(self, _index: int = 0) -> None:
        self._search_timer.stop()
        self._populate_tree()

    def _populate_tree(self) -> None:
        timer = getattr(self, "_search_timer", None)
        if timer is not None:
            timer.stop()
        selected_keys = {
            str(item.data(0, Qt.ItemDataRole.UserRole + 1) or "")
            for item in self.file_tree.selectedItems()
        }
        visible = self.visible_rows()
        self._displayed_rows_by_key = {_row_storage_key(row): row for row in visible}
        brushes = {
            _ROLE_WARNING: QBrush(_semantic_color(self, _ROLE_WARNING)),
            _ROLE_INFO: QBrush(_semantic_color(self, _ROLE_INFO)),
            _ROLE_MUTED: QBrush(_semantic_color(self, _ROLE_MUTED)),
        }

        sorting = self.file_tree.isSortingEnabled()
        self.file_tree.setSortingEnabled(False)
        self.file_tree.setUpdatesEnabled(False)
        try:
            self.file_tree.clear()
            items: list[QTreeWidgetItem] = []
            to_select: list[QTreeWidgetItem] = []
            for row in visible:
                name = PurePosixPath(row.game_path).name
                status, role = self._row_status_label_and_role(row)
                mod_display = short_mod_name(row.mod, max_chars=36)
                if not row.is_overridden and row.overridden_mods:
                    mod_display = f"{mod_display} (+{len(row.overridden_mods)})"
                item = QTreeWidgetItem([name, status, mod_display, row.extension or "", row.game_path])
                row_key = _row_storage_key(row)
                item.setData(0, Qt.ItemDataRole.UserRole, row.game_path)
                item.setData(0, Qt.ItemDataRole.UserRole + 1, row_key)
                if role in brushes:
                    item.setForeground(1, brushes[role])
                tip = self._row_tooltip(row, status)
                for col in range(5):
                    item.setToolTip(col, tip)
                items.append(item)
                if row_key in selected_keys:
                    to_select.append(item)
            if items:
                self.file_tree.addTopLevelItems(items)
                for item in to_select:
                    item.setSelected(True)
        finally:
            self.file_tree.setSortingEnabled(sorting)
            self.file_tree.setUpdatesEnabled(True)
        self._sync_buttons()
        self._update_detail_bar()

    def _on_file_selection_changed(self) -> None:
        self._sync_buttons()
        self._update_detail_bar()

    def _update_detail_bar(self) -> None:
        rows = self.selected_rows()
        if not rows:
            if self._selected_mod:
                active = sum(1 for row in self._all_rows if row.mod == self._selected_mod)
                lost = len(self._overridden_rows_by_mod.get(self._selected_mod, ()))
                text = self.tr("Mod: {value_0} · {value_1} active, {value_2} overridden").format(
                    value_0=self._selected_mod,
                    value_1=f"{active:,}",
                    value_2=f"{lost:,}",
                )
                folder = self._mod_folders.get(self._selected_mod)
                if folder is not None:
                    folder_line = self.tr("Folder: {value_0}").format(value_0=str(folder))
                    text = f"{text}\n{folder_line}"
                self.detail_label.setText(text)
            else:
                self.detail_label.setText(self.tr("Select a file to see active vs. overridden mods and source paths."))
            return
        if len(rows) > 1:
            overlaps = sum(1 for row in rows if row.is_overridden or row.overridden_mods)
            if overlaps:
                self.detail_label.setText(
                    self.tr("{value_0} files selected ({value_1} overlapping).").format(
                        value_0=f"{len(rows):,}",
                        value_1=f"{overlaps:,}",
                    )
                )
            else:
                self.detail_label.setText(self.tr("{value_0} files selected.").format(value_0=f"{len(rows):,}"))
            return
        row = rows[0]
        if row.is_overridden:
            first_line = self.tr("Active (served): {value_0} · Selected (overridden): {value_1}").format(
                value_0=row.winning_mod or "?",
                value_1=row.mod,
            )
            second_line = self.tr("Overridden file: {value_0}").format(value_0=str(row.source))
        elif row.overridden_mods:
            first_line = self.tr("Active (served): {value_0} · Also in (overridden): {value_1}").format(
                value_0=row.mod,
                value_1=", ".join(row.overridden_mods),
            )
            second_line = self.tr("Source: {value_0}").format(value_0=str(row.source))
        elif row.is_merged:
            contributors = ", ".join(row.merged_mods) if row.merged_mods else self.tr("multiple DMM mods")
            first_line = self.tr("Merged by DMM (from: {value_0})").format(value_0=contributors)
            second_line = self.tr("Source: {value_0}").format(value_0=str(row.source))
        else:
            first_line = self.tr("Active (served): {value_0} ({value_1})").format(
                value_0=row.mod,
                value_1=self._row_status_label(row),
            )
            second_line = self.tr("Source: {value_0}").format(value_0=str(row.source))
        self.detail_label.setText(f"{first_line}\n{second_line}")

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
            for mod, mod_rows in self._overridden_rows_by_mod.items():
                self._overridden_rows_by_mod[mod] = [
                    row if row.kept_vanilla else replace(
                        row,
                        in_catalogue=(chosen.get(normalized_game_path(row.game_path)) is not None),
                        catalogue_dto=chosen.get(normalized_game_path(row.game_path)),
                    )
                    for row in mod_rows
                ]
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
        rows: list[DmmMountedFileRow] = []
        seen: set[str] = set()
        for item in self.file_tree.selectedItems():
            key = str(item.data(0, Qt.ItemDataRole.UserRole + 1) or "")
            if key and key not in seen and key in self._displayed_rows_by_key:
                seen.add(key)
                rows.append(self._displayed_rows_by_key[key])
        return rows

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
        self._sync_buttons()
        self._update_detail_bar()
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
            single is not None
            and not single.kept_vanilla
            and getattr(single.catalogue_dto, "entry_id", None) is not None
            and self._session_loaded()
        )
        self.open_mesh_button.setEnabled(
            overlay_on
            and single is not None
            and not single.kept_vanilla
            and single.extension in ARCHIVE_MESH_EXTENSIONS
        )
        self.open_texture_button.setEnabled(
            overlay_on
            and single is not None
            and not single.kept_vanilla
            and single.extension in _TEXTURE_EXTENSIONS
        )
        self.copy_button.setEnabled(
            overlay_on and not self._copy_in_progress and any(not row.kept_vanilla for row in rows)
        )
        self.show_source_button.setEnabled(single is not None)
        self.copy_report_button.setEnabled(self._mount_snapshot is not None)

    def _handle_double_click(self, item: QTreeWidgetItem, _column: int) -> None:
        key = str(item.data(0, Qt.ItemDataRole.UserRole + 1) or "")
        row = self._displayed_rows_by_key.get(key)
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
        self.activity.emit(message)
        shell = getattr(self._archive, "shell", None)
        status = getattr(shell, "set_status_message", None)
        if callable(status):
            try:
                status(message, error=error)
            except TypeError:
                status(message)

    def copy_overlap_report(self) -> str:
        report = format_overlap_report(
            self._mount_snapshot,
            self._overlap_analysis,
            overlay_enabled=current_overlay().enabled,
        )
        app = QApplication.instance()
        if app is not None:
            app.clipboard().setText(report)
        self._report_status(self.tr("Copied overlap report to the clipboard."))
        return report

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
            self._report_status(self.tr("No visible mounted files match entries in the loaded game archive."), error=True)
            return False
        mod_filter = self._selected_mod
        label = f"DMM: {short_mod_name(mod_filter, max_chars=28)}" if mod_filter else "DMM mounted mods"
        if not bridge.apply_entry_id_scope(entry_ids, label=label):
            self._report_status(self.tr("Could not apply the DMM filter to Browse Archives."), error=True)
            return False
        self._activate_browse_tab()
        if callable(self._on_navigated):
            self._on_navigated()
        return True

    def show_selected_in_browse(self) -> bool:
        rows = self.selected_rows()
        if len(rows) != 1:
            return False
        row = rows[0]
        entry_id = getattr(row.catalogue_dto, "entry_id", None)
        bridge = getattr(self._archive, "archive_remote_bridge", None)
        if bridge is None or entry_id is None:
            self._report_status(
                self.tr("The selected file is added by the mod and does not exist in the game's archive index."),
                error=True,
            )
            return False
        label = f"DMM: {PurePosixPath(row.game_path).name}"
        if not bridge.apply_entry_id_scope((int(entry_id),), label=label):
            return False
        self._activate_browse_tab()
        if callable(self._on_navigated):
            self._on_navigated()
        return True

    def open_selected_in_mesh_editor(self) -> str:
        if not current_overlay().enabled:
            self._report_status(self.tr("Turn on 'Show DMM's mounted files in CDMW' first."), error=True)
            return ""
        rows = self.selected_rows()
        if len(rows) != 1 or rows[0].kept_vanilla or rows[0].extension not in ARCHIVE_MESH_EXTENSIONS:
            return ""
        row = rows[0]
        shell = getattr(self._archive, "shell", None)
        if getattr(shell, "mesh_editor_tab", None) is None or not callable(
            getattr(shell, "_prepare_mesh_editor_archive_launch", None)
        ):
            self._report_status(self.tr("The Mesh Editor is unavailable."), error=True)
            return ""
        game_root = self._game_root()
        rows_snapshot = dict(self._rows_by_path)
        mod_root = self._mod_folders.get(row.mod)
        self._cancel_pending_open()
        self._open_generation += 1
        generation, relay = self._open_generation, self._open_relay

        def run() -> None:
            try:
                outcome: object = _prepare_open_row(game_root, row, rows_snapshot, mod_root=mod_root)
            except (OSError, ValueError, RuntimeError) as exc:
                outcome = exc
            try:
                relay.done.emit(generation, row, outcome)
            except RuntimeError:
                pass

        threading.Thread(target=run, name="dmm-mounted-open-mesh", daemon=True).start()
        if row.is_overridden:
            self._report_status(
                self.tr("Opening overridden {value_0} from {value_1} in Mesh Editor (overridden by {value_2})...").format(
                    value_0=row.game_path,
                    value_1=row.mod,
                    value_2=row.winning_mod,
                )
            )
        else:
            self._report_status(
                self.tr("Opening {value_0} from DMM's {value_1} in the Mesh Editor...").format(
                    value_0=row.game_path,
                    value_1=row.mod,
                )
            )
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
            on_launched=self._on_navigated,
            allow_sidecar_followup=True,
        )

    def open_selected_in_texture_editor(self) -> str:
        if not current_overlay().enabled:
            self._report_status(self.tr("Turn on 'Show DMM's mounted files in CDMW' first."), error=True)
            return ""
        rows = self.selected_rows()
        if len(rows) != 1 or rows[0].kept_vanilla or rows[0].extension not in _TEXTURE_EXTENSIONS:
            return ""
        row = rows[0]
        shell = getattr(self._archive, "shell", None)
        textures = getattr(shell, "textures", None)
        if not callable(getattr(textures, "open_prepared_archive_texture", None)):
            self._report_status(self.tr("The Texture Editor is unavailable."), error=True)
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
        if row.is_overridden:
            self._report_status(
                self.tr("Opening overridden {value_0} from {value_1} in Texture Editor (overridden by {value_2})...").format(
                    value_0=row.game_path,
                    value_1=row.mod,
                    value_2=row.winning_mod,
                )
            )
        else:
            self._report_status(
                self.tr("Opening {value_0} from DMM's {value_1} in Texture Editor...").format(
                    value_0=row.game_path,
                    value_1=row.mod,
                )
            )
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
            self._report_status(self.tr("The Texture Editor is unavailable."), error=True)
            return
        opener(entry, prepared_path)
        if callable(self._on_navigated):
            self._on_navigated()

    def copy_selected(self, folder: Path | str) -> list[str]:
        """Copy selected non-kept-vanilla mounted files to ``folder`` under game paths."""

        from cdmw.domain.output_paths import check_output_path

        rows = [row for row in self.selected_rows() if not row.kept_vanilla]
        target_root = check_output_path(folder, game_folder=self._game_root() or None, allow_existing=True)
        written = _copy_mounted_rows(self._game_root(), rows, target_root)
        self._report_status(
            self.tr("Copied {value_0} file(s) to {value_1}.").format(
                value_0=f"{len(written):,}",
                value_1=str(target_root),
            )
        )
        return written

    def copy_selected_dialog(self) -> None:
        from cdmw.domain.output_paths import check_output_path

        if self._copy_in_progress:
            return
        rows = tuple(row for row in self.selected_rows() if not row.kept_vanilla)
        if not rows:
            return
        folder = QFileDialog.getExistingDirectory(self, self.tr("Copy DMM's files to a folder"))
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
        self._report_status(self.tr("Copying {value_0} file(s)...").format(value_0=f"{len(rows):,}"))

        def run() -> None:
            try:
                outcome: object = _copy_mounted_rows(game_root, rows, target_root)
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
        self._report_status(
            self.tr("Copied {value_0} file(s) to {value_1}.").format(
                value_0=f"{len(outcome):,}",
                value_1=str(target_root),
            )
        )

    def show_selected_source(self) -> None:
        rows = self.selected_rows()
        if len(rows) == 1:
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(rows[0].source.parent)))

    def request_shutdown(self) -> None:
        self._closed = True
        self._cancel_overlap_scan()
        self._cancel_catalogue_lookup()
        self._cancel_pending_open()
        current_overlay().remove_listener(self._overlay_listener)


__all__ = [
    "DmmMountedFileRow",
    "DmmMountedModsPage",
    "_prepare_open_row",
    "_prepare_texture_row",
]
