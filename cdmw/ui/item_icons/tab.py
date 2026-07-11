from __future__ import annotations

import tempfile
import re
from pathlib import Path
from typing import Callable, Optional, Sequence

from PySide6.QtCore import QSettings, Qt, QTimer, QUrl, Signal
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QLineEdit,
    QListWidgetItem,
    QMenu,
    QMessageBox,
    QSplitter,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from cdmw.domain.library.item_icons import (
    ITEM_ICON_DEFAULT_BACKGROUND_MODE,
    ITEM_ICON_SOURCE_EXTENSIONS,
    ItemIconLibraryRecord,
    ItemIconOverrideSpec,
    normalize_item_icon_background_mode,
)
from cdmw.models import TextureEditorSourceBinding
from cdmw.services.item_icon_service import ItemIconService
from cdmw.services.workspace_layout import workspace_paths
from cdmw.ui.item_icons.controller import ItemIconRecordListMixin
from cdmw.ui.item_icons.panels import build_library_panel, build_preview_panel, build_roots_panel
from cdmw.ui.item_icons.workers import ItemIconWorkerMixin
from cdmw.ui.item_icons.state import (
    path_list_to_settings as _path_list_to_settings,
    safe_icon_library_component as _safe_icon_library_component,
    safe_relative_target_path as _safe_relative_target_path,
    settings_path_list as _settings_path_list,
)
from cdmw.ui.layout_utils import responsive_sidebar_bounds


class ItemIconLibraryTab(ItemIconRecordListMixin, ItemIconWorkerMixin, QWidget):
    status_message_requested = Signal(str, bool)
    open_in_texture_editor_requested = Signal(str, object)
    open_target_in_archive_requested = Signal(str)
    RECORD_FILTER_DEBOUNCE_MS = 120
    RECORD_POPULATION_BATCH_SIZE = 250
    SELECTION_PREVIEW_DEBOUNCE_MS = 160

    def __init__(
        self,
        *,
        settings: QSettings,
        base_dir: Path,
        get_archive_entries: Callable[[], Sequence[object]],
        get_texconv_path: Callable[[], str],
        resolve_target_template_path: Callable[[object], Path],
        get_current_archive_path: Optional[Callable[[], str]] = None,
        item_icon_service: Optional[ItemIconService] = None,
        parent: Optional[QWidget] = None,
    ) -> None:
        super().__init__(parent)
        self.settings = settings
        self.base_dir = base_dir
        self.get_archive_entries = get_archive_entries
        self.get_texconv_path = get_texconv_path
        self.resolve_target_template_path = resolve_target_template_path
        self.get_current_archive_path = get_current_archive_path or (lambda: "")
        self.item_icon_service = item_icon_service or ItemIconService(settings=settings)
        self.library_root = workspace_paths(self.base_dir)["item_icon_library_root"]
        self.edited_root = self.library_root / "edited"
        self.preview_root = self.library_root / "previews"
        self.index_path = self.library_root / "icon_index.json"
        self.library_roots: list[Path] = _settings_path_list(self.settings.value("item_icons/library_roots", "[]"))
        self.records: list[ItemIconLibraryRecord] = []
        self._records_by_key: dict[str, ItemIconLibraryRecord] = {}
        self._target_entries: list[object] = []
        self._loading_record = False
        self._temp_preview_dir = tempfile.TemporaryDirectory(prefix="cdmw_item_icon_tab_")
        self._initialize_item_icon_workers()
        self._pending_record_rows: list[ItemIconLibraryRecord] = []
        self._pending_record_select_key = ""
        self._pending_record_total = 0
        self._record_filter_timer = QTimer(self)
        self._record_filter_timer.setSingleShot(True)
        self._record_filter_timer.setInterval(self.RECORD_FILTER_DEBOUNCE_MS)
        self._record_filter_timer.timeout.connect(self._populate_records_tree)
        self._record_population_timer = QTimer(self)
        self._record_population_timer.setSingleShot(True)
        self._record_population_timer.setInterval(0)
        self._record_population_timer.timeout.connect(self._flush_record_population_batch)
        self._target_filter_timer = QTimer(self)
        self._target_filter_timer.setSingleShot(True)
        self._target_filter_timer.setInterval(self.RECORD_FILTER_DEBOUNCE_MS)
        self._target_filter_timer.timeout.connect(self._handle_target_filter_changed)
        self._target_refresh_timer = QTimer(self)
        self._target_refresh_timer.setSingleShot(True)
        self._target_refresh_timer.setInterval(80)
        self._target_refresh_timer.timeout.connect(self._flush_scheduled_target_refresh)
        self._target_entries_signature: tuple[object, ...] = ()
        self._pending_target_refresh_update_preview = False
        self._selection_preview_timer = QTimer(self)
        self._selection_preview_timer.setSingleShot(True)
        self._selection_preview_timer.setInterval(self.SELECTION_PREVIEW_DEBOUNCE_MS)
        self._selection_preview_timer.timeout.connect(self._refresh_selected_record_previews)

        root_layout = QVBoxLayout(self)
        root_layout.setContentsMargins(10, 10, 10, 10)
        root_layout.setSpacing(8)

        splitter = QSplitter(Qt.Orientation.Horizontal)
        splitter.setChildrenCollapsible(False)
        splitter.setHandleWidth(8)
        root_layout.addWidget(splitter, stretch=1)

        roots_panel = build_roots_panel(self)
        splitter.addWidget(roots_panel)

        library_panel = build_library_panel(self)
        splitter.addWidget(library_panel)

        preview_panel = build_preview_panel(self)
        splitter.addWidget(preview_panel)

        roots_min, _roots_pref, _roots_max = responsive_sidebar_bounds(self, role="narrow")
        preview_min, _preview_pref, _preview_max = responsive_sidebar_bounds(self, role="wide")
        roots_panel.setMinimumWidth(roots_min)
        roots_panel.setMaximumWidth(_roots_max)
        preview_panel.setMinimumWidth(preview_min)
        splitter.setStretchFactor(0, 0)
        splitter.setStretchFactor(1, 1)
        splitter.setStretchFactor(2, 1)
        splitter.setSizes([roots_min, 680, preview_min])

        self._refresh_roots_list()
        self.scan_library(show_status=False)
        self.refresh_targets(force=True)

    def iter_shutdown_workers(self) -> tuple[tuple[str, Optional[object], Optional[object]], ...]:
        return self._iter_item_icon_shutdown_workers()

    def request_shutdown(self) -> None:
        self._request_item_icon_shutdown()

    def shutdown(self) -> None:
        self.request_shutdown()

    def _emit_status(self, message: str, error: bool = False) -> None:
        self.status_message_requested.emit(message, bool(error))

    def _texconv_path(self) -> Optional[Path]:
        text = str(self.get_texconv_path() or "").strip()
        return Path(text).expanduser() if text else None

    def _background_mode(self) -> str:
        if not hasattr(self, "background_mode_combo"):
            return ITEM_ICON_DEFAULT_BACKGROUND_MODE
        return normalize_item_icon_background_mode(self.background_mode_combo.currentData())

    def _handle_background_mode_changed(self) -> None:
        self.settings.setValue("item_icons/background_mode", self._background_mode())
        self.update_final_preview()

    def _save_roots(self) -> None:
        self.settings.setValue("item_icons/library_roots", _path_list_to_settings(self.library_roots))

    def _refresh_roots_list(self) -> None:
        self.roots_list.clear()
        for root in self.library_roots:
            item = QListWidgetItem(str(root))
            item.setToolTip(str(root))
            self.roots_list.addItem(item)
        self.roots_status_label.setText(
            f"{len(self.library_roots):,} folder root(s). Edited exports are stored in {self.edited_root}."
        )

    def add_library_root(self) -> None:
        selected = QFileDialog.getExistingDirectory(self, "Add Item Icon Library Folder", str(self.base_dir))
        if not selected:
            return
        root = Path(selected).expanduser()
        try:
            resolved = root.resolve()
        except OSError:
            resolved = root
        if not resolved.is_dir():
            QMessageBox.warning(self, "Icon Creator", "Choose an existing folder.")
            return
        existing = {str(path).casefold() for path in self.library_roots}
        if str(resolved).casefold() not in existing:
            self.library_roots.append(resolved)
            self._save_roots()
            self._refresh_roots_list()
        self.scan_library(show_status=True)

    def remove_selected_library_root(self) -> None:
        row = self.roots_list.currentRow()
        if row < 0 or row >= len(self.library_roots):
            return
        del self.library_roots[row]
        self._save_roots()
        self._refresh_roots_list()
        self.scan_library(show_status=True)

    def open_edited_folder(self) -> None:
        self.edited_root.mkdir(parents=True, exist_ok=True)
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(self.edited_root)))

    def export_generated_icon(self) -> None:
        source_path = self.current_source_path()
        target_entry = self._current_target_entry()
        target_path = self._current_target_path()
        if source_path is None or target_entry is None or not target_path:
            QMessageBox.warning(self, "Icon Creator", "Choose a source image and an existing target icon path.")
            return
        output_dir = QFileDialog.getExistingDirectory(self, "Export Generated Item Icon Package", str(self.library_root))
        if not output_dir:
            return
        try:
            relative = _safe_relative_target_path(target_path)
            destination = Path(output_dir).expanduser() / relative
        except Exception as exc:
            QMessageBox.warning(self, "Icon Creator", str(exc))
            self._emit_status(f"Item icon export failed: {exc}", True)
            return
        self._queue_item_icon_output(
            action="export",
            spec=ItemIconOverrideSpec(
                source_path=source_path,
                target_entry=target_entry,
                target_path=target_path,
                source_mode="library",
                background_mode=self._background_mode(),
            ),
            destination=destination,
        )

    def add_to_existing_loose_mod(self) -> None:
        source_path = self.current_source_path()
        target_entry = self._current_target_entry()
        target_path = self._current_target_path()
        if source_path is None or target_entry is None or not target_path:
            QMessageBox.warning(self, "Icon Creator", "Choose a source image and an existing target icon path.")
            return
        loose_mod_dir = QFileDialog.getExistingDirectory(
            self,
            "Choose Existing Loose Mod Folder",
            str(self.library_root),
        )
        if not loose_mod_dir:
            return
        self._queue_item_icon_output(
            action="patch",
            spec=ItemIconOverrideSpec(
                source_path=source_path,
                target_entry=target_entry,
                target_path=target_path,
                source_mode="library",
                background_mode=self._background_mode(),
            ),
            destination=Path(loose_mod_dir),
        )

    def open_selected_in_texture_editor(self) -> None:
        path = self.current_source_path()
        if path is None or not path.is_file():
            return
        binding = TextureEditorSourceBinding(
            launch_origin="item_icon_library",
            display_name=path.name,
            source_path=str(path),
            source_identity_path=str(path),
        )
        self.open_in_texture_editor_requested.emit(str(path), binding)

    def delete_selected_source(self) -> None:
        path = self.current_source_path()
        if path is None or not path.is_file():
            QMessageBox.information(self, "Icon Creator", "Select an icon source file first.")
            return
        answer = QMessageBox.question(
            self,
            "Delete Icon Source",
            f"Delete this icon source from disk?\n\n{path}",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if answer != QMessageBox.StandardButton.Yes:
            return
        self._queue_item_icon_library_mutation(action="delete", source_path=path)

    def _show_records_context_menu(self, position) -> None:
        item = self.records_tree.itemAt(position)
        if item is None:
            return
        self.records_tree.setCurrentItem(item)
        path = self.current_source_path(item)
        menu = QMenu(self)
        open_action = menu.addAction("Open In Texture Editor")
        open_action.setEnabled(bool(path is not None and path.is_file()))
        open_action.triggered.connect(self.open_selected_in_texture_editor)
        folder_action = menu.addAction("Open Folder")
        folder_action.setEnabled(bool(path is not None and path.parent.is_dir()))
        folder_action.triggered.connect(
            lambda _checked=False, source_path=path: (
                QDesktopServices.openUrl(QUrl.fromLocalFile(str(source_path.parent)))
                if source_path is not None
                else None
            )
        )
        menu.addSeparator()
        delete_action = menu.addAction("Delete Source")
        delete_action.setEnabled(bool(path is not None and path.is_file()))
        delete_action.triggered.connect(self.delete_selected_source)
        menu.exec(self.records_tree.viewport().mapToGlobal(position))

    def add_imported_source(self, source_path: Path) -> Optional[Path]:
        source = source_path.expanduser()
        if source.is_dir():
            existing = {str(path).casefold() for path in self.library_roots}
            try:
                resolved = source.resolve()
            except OSError:
                resolved = source
            if str(resolved).casefold() not in existing:
                self.library_roots.append(resolved)
                self._save_roots()
                self._refresh_roots_list()
            self.scan_library(show_status=True)
            return resolved
        if not source.is_file():
            raise FileNotFoundError(f"Edited item icon export was not found: {source}")
        if source.suffix.lower() not in ITEM_ICON_SOURCE_EXTENSIONS:
            raise ValueError(f"Unsupported edited item icon source format: {source.suffix}")
        stored = self._available_edited_source_path(source.stem, source.suffix)
        self._queue_item_icon_library_mutation(
            action="import",
            source_path=source,
            destination_path=stored,
            select=True,
        )
        return stored

    def _available_edited_source_path(self, stem: str, suffix: str) -> Path:
        self.edited_root.mkdir(parents=True, exist_ok=True)
        safe_stem = re.sub(r"[^A-Za-z0-9._-]+", "-", str(stem or "item-icon")).strip("-._")[:180] or "item-icon"
        safe_suffix = suffix.lower() if suffix and suffix.startswith(".") else ".png"
        candidate = self.edited_root / f"{safe_stem}{safe_suffix}"
        counter = 1
        while candidate.exists() or self._path_key(candidate) in self._reserved_edited_paths:
            counter += 1
            candidate = self.edited_root / f"{safe_stem}_{counter}{safe_suffix}"
        return candidate

    def mesh_editor_generated_icon_path(self, *, target_model_path: object, source_model_path: object) -> Path:
        target_label = _safe_icon_library_component(target_model_path, fallback="target")
        source_label = _safe_icon_library_component(source_model_path, fallback="source")
        stem = f"mesh-editor__target-{target_label}__source-{source_label}"
        return self._available_edited_source_path(stem, ".png")

    def register_mesh_editor_generated_icon(
        self,
        source_path: Path,
        *,
        target_model_path: object,
        source_model_path: object,
        target_icon_path: str = "",
        select: bool = False,
    ) -> Path:
        source = source_path.expanduser().resolve()
        if not source.is_file():
            raise FileNotFoundError(f"Generated Mesh Editor icon was not found: {source}")
        try:
            inside_edited_root = source.is_relative_to(self.edited_root.expanduser().resolve())
        except (AttributeError, OSError):
            inside_edited_root = False
        if inside_edited_root:
            stored = source
        else:
            target_label = _safe_icon_library_component(target_model_path, fallback="target")
            source_label = _safe_icon_library_component(source_model_path, fallback="source")
            stem = f"mesh-editor__target-{target_label}__source-{source_label}"
            stored = self._available_edited_source_path(stem, source.suffix.lower() or ".png")

        target_label = _safe_icon_library_component(target_model_path, fallback="target")
        source_label = _safe_icon_library_component(source_model_path, fallback="source")
        tags = ("mesh-editor", f"target:{target_label}", f"source:{source_label}")
        note_lines = [
            "Generated in Mesh Editor from the replacement preview.",
            f"Target model: {str(target_model_path or '').strip() or target_label}",
            f"Source model: {str(source_model_path or '').strip() or source_label}",
        ]
        if target_icon_path:
            note_lines.append(f"Initial target icon: {target_icon_path}")
        self._queue_item_icon_library_mutation(
            action="register",
            source_path=source,
            destination_path=stored,
            tags=tags,
            notes="\n".join(note_lines),
            favorite=False,
            select=select,
        )
        return stored

    def choose_source_dialog(self, parent: Optional[QWidget] = None) -> Optional[Path]:
        if not self.records:
            self.scan_library(show_status=False)
        dialog = QDialog(parent or self)
        dialog.setWindowTitle("Choose Item Icon Library Source")
        dialog.resize(880, 560)
        layout = QVBoxLayout(dialog)
        layout.setContentsMargins(10, 10, 10, 10)
        layout.setSpacing(6)
        filter_edit = QLineEdit()
        filter_edit.setPlaceholderText("Filter icon library")
        layout.addWidget(filter_edit)
        tree = QTreeWidget()
        tree.setColumnCount(4)
        tree.setHeaderLabels(["Name", "Size", "Tags", "Path"])
        tree.setRootIsDecorated(False)
        tree.setAlternatingRowColors(True)
        tree.setUniformRowHeights(True)
        tree.header().resizeSection(0, 240)
        tree.header().resizeSection(1, 80)
        tree.header().resizeSection(2, 160)
        tree.header().setStretchLastSection(True)
        layout.addWidget(tree, stretch=1)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        layout.addWidget(buttons)

        def populate() -> None:
            selected_text = str(tree.currentItem().data(0, Qt.ItemDataRole.UserRole) if tree.currentItem() is not None else "")
            tree.clear()
            text = filter_edit.text().casefold().strip()
            for record in self.records:
                haystack = " ".join((record.path.name, record.relative_path, " ".join(record.tags), record.notes)).casefold()
                if text and any(part not in haystack for part in text.split()):
                    continue
                size_text = f"{record.width}x{record.height}" if record.width and record.height else "-"
                item = QTreeWidgetItem([record.path.name, size_text, ", ".join(record.tags), record.relative_path])
                item.setData(0, Qt.ItemDataRole.UserRole, str(record.path))
                item.setToolTip(3, str(record.path))
                tree.addTopLevelItem(item)
                if selected_text and str(record.path) == selected_text:
                    tree.setCurrentItem(item)
            if tree.topLevelItemCount() > 0 and tree.currentItem() is None:
                tree.setCurrentItem(tree.topLevelItem(0))

        filter_edit.textChanged.connect(lambda _text="": populate())
        tree.itemDoubleClicked.connect(lambda _item, _column: dialog.accept())
        buttons.accepted.connect(dialog.accept)
        buttons.rejected.connect(dialog.reject)
        populate()
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return None
        current = tree.currentItem()
        if current is None:
            return None
        path_text = str(current.data(0, Qt.ItemDataRole.UserRole) or "").strip()
        return Path(path_text).expanduser() if path_text else None
