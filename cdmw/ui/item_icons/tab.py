from __future__ import annotations

import shutil
import tempfile
import re
from pathlib import Path, PurePosixPath
from typing import Callable, Optional, Sequence

from PySide6.QtCore import QSettings, Qt, QTimer, QUrl, Signal
from PySide6.QtGui import QDesktopServices, QImageReader
from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QLabel,
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

from cdmw.core.item_icon import (
    ITEM_ICON_DEFAULT_BACKGROUND_MODE,
    ITEM_ICON_SOURCE_EXTENSIONS,
    ItemIconLibraryRecord,
    ItemIconOverrideSpec,
    build_item_icon_fit_pad_preview,
    build_item_icon_payload,
    build_item_icon_source_preview_png,
    import_edited_item_icon_source,
    normalize_item_icon_background_mode,
    patch_existing_loose_mod_with_item_icon,
    read_item_icon_template_info,
    save_item_icon_library_index,
    scan_item_icon_library,
    update_item_icon_library_record_metadata,
)
from cdmw.models import TextureEditorSourceBinding
from cdmw.services.workspace_layout import workspace_paths
from cdmw.ui.item_icons.controller import ItemIconRecordListMixin
from cdmw.ui.item_icons.panels import build_library_panel, build_preview_panel, build_roots_panel
from cdmw.ui.item_icons.state import (
    path_list_to_settings as _path_list_to_settings,
    safe_icon_library_component as _safe_icon_library_component,
    safe_relative_target_path as _safe_relative_target_path,
    settings_path_list as _settings_path_list,
)
from cdmw.ui.widgets import responsive_sidebar_bounds


class ItemIconLibraryTab(ItemIconRecordListMixin, QWidget):
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
        parent: Optional[QWidget] = None,
    ) -> None:
        super().__init__(parent)
        self.settings = settings
        self.base_dir = base_dir
        self.get_archive_entries = get_archive_entries
        self.get_texconv_path = get_texconv_path
        self.resolve_target_template_path = resolve_target_template_path
        self.get_current_archive_path = get_current_archive_path or (lambda: "")
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

        header = QLabel("Icon Creator")
        header.setObjectName("SectionTitle")
        root_layout.addWidget(header)

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
        return ()

    def request_shutdown(self) -> None:
        self._temp_preview_dir.cleanup()

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

    def scan_library(self, *, show_status: bool) -> None:
        self.library_root.mkdir(parents=True, exist_ok=True)
        self.edited_root.mkdir(parents=True, exist_ok=True)
        self.preview_root.mkdir(parents=True, exist_ok=True)
        selected = self.current_source_path()
        self.records = list(
            scan_item_icon_library(
                self.library_roots,
                index_path=self.index_path,
                edited_root=self.edited_root,
            )
        )
        save_item_icon_library_index(
            self.index_path,
            roots=tuple(self.library_roots) + (self.edited_root,),
            records=self.records,
        )
        self._records_by_key = {str(record.path).casefold(): record for record in self.records}
        self._populate_records_tree(select_path=selected)
        message = f"Item icon library scanned: {len(self.records):,} supported source image(s)."
        self.library_status_label.setText(message)
        if show_status:
            self._emit_status(message)

    def save_selected_metadata(self) -> None:
        if self._loading_record:
            return
        path = self.current_source_path()
        if path is None:
            return
        tags = [part.strip() for part in self.tags_edit.text().split(",") if part.strip()]
        update_item_icon_library_record_metadata(
            self.index_path,
            path,
            tags=tags,
            notes=self.notes_edit.toPlainText(),
            favorite=self.favorite_checkbox.isChecked(),
        )
        self.scan_library(show_status=False)
        self.select_source_path(path)
        self._emit_status(f"Saved item icon metadata for {path.name}.")

    def update_source_preview(self) -> None:
        path = self.current_source_path()
        record = self._record_for_path(path)
        if path is None or record is None:
            self.source_preview_label.clear_preview("Select an icon source.")
            self.source_meta_label.setText("")
            return
        if not path.is_file():
            self.source_preview_label.clear_preview("Source file is missing.")
            self.source_meta_label.setText(str(path))
            return
        try:
            preview_path = build_item_icon_source_preview_png(
                path,
                output_dir=Path(self._temp_preview_dir.name),
                texconv_path=self._texconv_path(),
            )
            if path.suffix.lower() != ".dds":
                reader = QImageReader(str(preview_path))
                if not reader.size().isValid():
                    raise ValueError("Qt could not read this image for preview.")
            self.source_preview_label.set_preview_image_path(str(preview_path), path.name)
        except Exception as exc:
            self.source_preview_label.clear_preview(str(exc))
        warning = f" Warning: {record.warning}" if record.warning else ""
        self.source_meta_label.setText(
            f"{record.width or '-'}x{record.height or '-'} | {record.source_kind} | {record.path}{warning}"
        )

    def update_final_preview(self, *, show_errors: bool = False) -> None:
        source_path = self.current_source_path()
        target_entry = self._current_target_entry()
        target_path = self._current_target_path()
        if source_path is None:
            self.final_preview_label.clear_preview("Select an icon source.")
            self.target_meta_label.setText("")
            return
        if target_entry is None or not target_path:
            self.final_preview_label.clear_preview("Choose an existing target icon path.")
            self.target_meta_label.setText("Archive target icon data is required before compatible output can be generated.")
            return
        try:
            template_path = self.resolve_target_template_path(target_entry)
            preview_path = self.preview_root / f"{PurePosixPath(target_path).stem}_{source_path.stem}_preview.png"
            preview_path.parent.mkdir(parents=True, exist_ok=True)
            _preview_path, target_info, source_dimensions, warnings = build_item_icon_fit_pad_preview(
                source_path,
                target_path=target_path,
                target_template_path=template_path,
                output_path=preview_path,
                texconv_path=self._texconv_path(),
                background_mode=self._background_mode(),
            )
            self.final_preview_label.set_preview_image_path(str(preview_path), "Final item icon preview")
            warning_text = f" | {'; '.join(warnings)}" if warnings else ""
            self.target_meta_label.setText(
                f"Final: {target_path} | target {target_info.width}x{target_info.height}, "
                f"{target_info.target_format}, {target_info.mip_count} mip(s) | source {source_dimensions[0]}x{source_dimensions[1]}"
                f" | background {self._background_mode()}{warning_text}"
            )
        except Exception as exc:
            self.final_preview_label.clear_preview(str(exc))
            self.target_meta_label.setText(str(exc))
            if show_errors:
                QMessageBox.warning(self, "Icon Creator", str(exc))

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
            template_path = self.resolve_target_template_path(target_entry)
            payload = build_item_icon_payload(
                ItemIconOverrideSpec(
                    source_path=source_path,
                    target_entry=target_entry,
                    target_path=target_path,
                    source_mode="library",
                    background_mode=self._background_mode(),
                ),
                target_template_path=template_path,
                texconv_path=self._texconv_path(),
            )
            relative = _safe_relative_target_path(payload.target_path)
            destination = Path(output_dir).expanduser() / relative
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_bytes(payload.payload_data)
        except Exception as exc:
            QMessageBox.warning(self, "Icon Creator", str(exc))
            self._emit_status(f"Item icon export failed: {exc}", True)
            return
        self._emit_status(f"Exported generated item icon: {destination}")
        QMessageBox.information(self, "Icon Creator", f"Generated icon written to:\n{destination}")

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
        try:
            template_path = self.resolve_target_template_path(target_entry)
            payload = build_item_icon_payload(
                ItemIconOverrideSpec(
                    source_path=source_path,
                    target_entry=target_entry,
                    target_path=target_path,
                    source_mode="library",
                    background_mode=self._background_mode(),
                ),
                target_template_path=template_path,
                texconv_path=self._texconv_path(),
            )
            result = patch_existing_loose_mod_with_item_icon(
                Path(loose_mod_dir),
                target_path=payload.target_path,
                payload_data=payload.payload_data,
                target_entry=target_entry,
            )
        except Exception as exc:
            QMessageBox.warning(self, "Icon Creator", str(exc))
            self._emit_status(f"Existing loose mod icon patch failed: {exc}", True)
            return

        details = [
            f"Patched copy:\n{result.output_root}",
            f"Icon:\n{result.icon_path}",
        ]
        if result.manifest_path is not None:
            details.append(f"Manifest updated:\n{result.manifest_path}")
        if result.zip_path is not None:
            details.append(f"Fresh zip:\n{result.zip_path}")
        if payload.warnings:
            details.append("Warnings:\n" + "\n".join(payload.warnings))
        self._emit_status(f"Added generated item icon to patched loose mod copy: {result.output_root}")
        QMessageBox.information(self, "Icon Creator", "\n\n".join(details))

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
        try:
            path.unlink()
        except OSError as exc:
            QMessageBox.warning(self, "Icon Creator", f"Could not delete icon source:\n{exc}")
            self._emit_status(f"Icon source delete failed: {exc}", True)
            return
        self.source_preview_label.clear_preview("Select an icon source.")
        self.final_preview_label.clear_preview("Select a source and target icon.")
        self._emit_status(f"Deleted icon source: {path.name}")
        self.scan_library(show_status=False)

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
        copied = import_edited_item_icon_source(source, self.edited_root)
        self.scan_library(show_status=True)
        self.select_source_path(copied)
        return copied

    def _available_edited_source_path(self, stem: str, suffix: str) -> Path:
        self.edited_root.mkdir(parents=True, exist_ok=True)
        safe_stem = re.sub(r"[^A-Za-z0-9._-]+", "-", str(stem or "item-icon")).strip("-._")[:180] or "item-icon"
        safe_suffix = suffix.lower() if suffix and suffix.startswith(".") else ".png"
        candidate = self.edited_root / f"{safe_stem}{safe_suffix}"
        counter = 1
        while candidate.exists():
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
            shutil.copy2(source, stored)

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
        update_item_icon_library_record_metadata(
            self.index_path,
            stored,
            tags=tags,
            notes="\n".join(note_lines),
            favorite=False,
        )
        self.scan_library(show_status=False)
        if select:
            self.select_source_path(stored)
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
