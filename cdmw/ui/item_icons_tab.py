from __future__ import annotations

import json
import tempfile
from pathlib import Path, PurePosixPath
from typing import Callable, Optional, Sequence

from PySide6.QtCore import QSettings, Qt, QUrl, Signal
from PySide6.QtGui import QDesktopServices, QImageReader
from PySide6.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QFrame,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMenu,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QScrollArea,
    QSizePolicy,
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
from cdmw.ui.widgets import PreviewLabel, PreviewScrollArea, responsive_sidebar_bounds


def _settings_path_list(value: object) -> list[Path]:
    if isinstance(value, str):
        try:
            parsed = json.loads(value)
        except Exception:
            parsed = []
    elif isinstance(value, (list, tuple)):
        parsed = value
    else:
        parsed = []
    paths: list[Path] = []
    for item in parsed:
        text = str(item or "").strip()
        if text:
            paths.append(Path(text).expanduser())
    return paths


def _path_list_to_settings(paths: Sequence[Path]) -> str:
    return json.dumps([str(path) for path in paths])


def _is_probable_item_icon_entry(entry: object) -> bool:
    path = str(getattr(entry, "path", "") or "").replace("\\", "/")
    lower = path.lower()
    extension = str(getattr(entry, "extension", "") or PurePosixPath(path).suffix).lower()
    if extension != ".dds":
        return False
    return "itemicon" in lower or ("/ui/" in lower and "icon" in lower)


def _safe_relative_target_path(target_path: str) -> Path:
    pure = PurePosixPath(str(target_path or "").replace("\\", "/"))
    parts = [part for part in pure.parts if part not in {"", ".", "/"}]
    if not parts or any(part == ".." for part in parts):
        raise ValueError(f"Invalid target icon path: {target_path}")
    return Path(*parts)


class ItemIconLibraryTab(QWidget):
    status_message_requested = Signal(str, bool)
    open_in_texture_editor_requested = Signal(str, object)
    open_target_in_archive_requested = Signal(str)

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
        self.library_root = (self.base_dir / "item_icon_library").resolve()
        self.edited_root = self.library_root / "edited"
        self.preview_root = self.library_root / "previews"
        self.index_path = self.library_root / "icon_index.json"
        self.library_roots: list[Path] = _settings_path_list(self.settings.value("item_icons/library_roots", "[]"))
        self.records: list[ItemIconLibraryRecord] = []
        self._records_by_key: dict[str, ItemIconLibraryRecord] = {}
        self._target_entries: list[object] = []
        self._loading_record = False
        self._temp_preview_dir = tempfile.TemporaryDirectory(prefix="cdmw_item_icon_tab_")

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

        roots_panel = self._build_roots_panel()
        splitter.addWidget(roots_panel)

        library_panel = self._build_library_panel()
        splitter.addWidget(library_panel)

        preview_panel = self._build_preview_panel()
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
        self.refresh_targets()

    def _build_roots_panel(self) -> QWidget:
        panel = QWidget()
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(6)
        roots_group = QGroupBox("Library Folders")
        roots_layout = QVBoxLayout(roots_group)
        roots_layout.setContentsMargins(8, 8, 8, 8)
        roots_layout.setSpacing(6)
        self.roots_list = QListWidget()
        self.roots_list.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        roots_layout.addWidget(self.roots_list, stretch=1)
        root_buttons = QGridLayout()
        self.add_root_button = QPushButton("Add Folder...")
        self.remove_root_button = QPushButton("Remove")
        self.rescan_button = QPushButton("Rescan")
        self.open_edited_folder_button = QPushButton("Edited Folder")
        root_buttons.addWidget(self.add_root_button, 0, 0)
        root_buttons.addWidget(self.remove_root_button, 0, 1)
        root_buttons.addWidget(self.rescan_button, 1, 0)
        root_buttons.addWidget(self.open_edited_folder_button, 1, 1)
        roots_layout.addLayout(root_buttons)
        self.roots_status_label = QLabel("")
        self.roots_status_label.setObjectName("HintLabel")
        self.roots_status_label.setWordWrap(True)
        roots_layout.addWidget(self.roots_status_label)
        layout.addWidget(roots_group, stretch=1)

        self.add_root_button.clicked.connect(self.add_library_root)
        self.remove_root_button.clicked.connect(self.remove_selected_library_root)
        self.rescan_button.clicked.connect(lambda _checked=False: self.scan_library(show_status=True))
        self.open_edited_folder_button.clicked.connect(self.open_edited_folder)
        return panel

    def _build_library_panel(self) -> QWidget:
        panel = QWidget()
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(6)
        filter_row = QHBoxLayout()
        self.filter_edit = QLineEdit()
        self.filter_edit.setPlaceholderText("Filter name, path, tags, or notes")
        self.favorite_only_checkbox = QCheckBox("Favorites")
        filter_row.addWidget(self.filter_edit, stretch=1)
        filter_row.addWidget(self.favorite_only_checkbox)
        layout.addLayout(filter_row)
        self.records_tree = QTreeWidget()
        self.records_tree.setColumnCount(5)
        self.records_tree.setHeaderLabels(["Name", "Size", "Tags", "Kind", "Path"])
        self.records_tree.setRootIsDecorated(False)
        self.records_tree.setAlternatingRowColors(True)
        self.records_tree.setUniformRowHeights(True)
        self.records_tree.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.records_tree.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.records_tree.setSortingEnabled(True)
        self.records_tree.header().setStretchLastSection(True)
        self.records_tree.header().resizeSection(0, 210)
        self.records_tree.header().resizeSection(1, 80)
        self.records_tree.header().resizeSection(2, 140)
        self.records_tree.header().resizeSection(3, 80)
        layout.addWidget(self.records_tree, stretch=1)
        self.library_status_label = QLabel("No icon sources loaded.")
        self.library_status_label.setObjectName("HintLabel")
        self.library_status_label.setWordWrap(True)
        layout.addWidget(self.library_status_label)

        self.filter_edit.textChanged.connect(lambda _text="": self._populate_records_tree())
        self.favorite_only_checkbox.toggled.connect(lambda _checked=False: self._populate_records_tree())
        self.records_tree.currentItemChanged.connect(lambda current, _previous: self._handle_record_selection(current))
        self.records_tree.itemDoubleClicked.connect(lambda _item, _column: self.open_selected_in_texture_editor())
        self.records_tree.customContextMenuRequested.connect(self._show_records_context_menu)
        return panel

    def _build_preview_panel(self) -> QWidget:
        panel = QWidget()
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(6)

        source_group = QGroupBox("Source")
        source_layout = QVBoxLayout(source_group)
        source_layout.setContentsMargins(8, 8, 8, 8)
        source_layout.setSpacing(6)
        self.source_preview_label = PreviewLabel("Select an icon source.")
        self.source_preview_scroll = PreviewScrollArea()
        self.source_preview_scroll.setWidgetResizable(False)
        self.source_preview_scroll.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.source_preview_scroll.setWidget(self.source_preview_label)
        self.source_preview_label.attach_scroll_area(self.source_preview_scroll)
        source_layout.addWidget(self.source_preview_scroll, stretch=1)
        self.source_meta_label = QLabel("")
        self.source_meta_label.setObjectName("HintLabel")
        self.source_meta_label.setWordWrap(True)
        source_layout.addWidget(self.source_meta_label)

        metadata_grid = QGridLayout()
        self.favorite_checkbox = QCheckBox("Favorite")
        self.tags_edit = QLineEdit()
        self.tags_edit.setPlaceholderText("comma separated tags")
        self.notes_edit = QPlainTextEdit()
        self.notes_edit.setMaximumHeight(72)
        self.notes_edit.setPlaceholderText("Notes")
        self.save_metadata_button = QPushButton("Save Metadata")
        self.open_editor_button = QPushButton("Open In Texture Editor")
        self.delete_source_button = QPushButton("Delete Source")
        self.delete_source_button.setEnabled(False)
        metadata_grid.addWidget(self.favorite_checkbox, 0, 0, 1, 2)
        metadata_grid.addWidget(QLabel("Tags"), 1, 0)
        metadata_grid.addWidget(self.tags_edit, 1, 1)
        metadata_grid.addWidget(QLabel("Notes"), 2, 0)
        metadata_grid.addWidget(self.notes_edit, 2, 1)
        metadata_grid.addWidget(self.save_metadata_button, 3, 0)
        metadata_grid.addWidget(self.open_editor_button, 3, 1)
        metadata_grid.addWidget(self.delete_source_button, 4, 0, 1, 2)
        metadata_grid.setColumnStretch(1, 1)
        source_layout.addLayout(metadata_grid)
        layout.addWidget(source_group, stretch=1)

        target_group = QGroupBox("Compatible Output")
        target_layout = QVBoxLayout(target_group)
        target_layout.setContentsMargins(8, 8, 8, 8)
        target_layout.setSpacing(6)
        self.target_filter_edit = QLineEdit()
        self.target_filter_edit.setPlaceholderText("Filter or paste an existing archive item icon path")
        target_layout.addWidget(self.target_filter_edit)
        target_row = QHBoxLayout()
        self.target_combo = QComboBox()
        self.target_combo.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.refresh_targets_button = QPushButton("Refresh Targets")
        self.use_archive_selection_button = QPushButton("Use Archive Selection")
        self.open_target_archive_button = QPushButton("Open In Archive Browser")
        target_row.addWidget(self.target_combo, stretch=1)
        target_row.addWidget(self.refresh_targets_button)
        target_layout.addLayout(target_row)
        target_button_row = QHBoxLayout()
        target_button_row.addWidget(self.use_archive_selection_button)
        target_button_row.addWidget(self.open_target_archive_button)
        target_button_row.addStretch(1)
        target_layout.addLayout(target_button_row)
        background_row = QHBoxLayout()
        background_row.addWidget(QLabel("Background"))
        self.background_mode_combo = QComboBox()
        self.background_mode_combo.addItem("Auto transparent", "auto_transparent")
        self.background_mode_combo.addItem("Keep source", "keep_source")
        self.background_mode_combo.addItem("Target underlay", "target_underlay")
        saved_background_mode = normalize_item_icon_background_mode(
            self.settings.value("item_icons/background_mode", ITEM_ICON_DEFAULT_BACKGROUND_MODE)
        )
        saved_index = self.background_mode_combo.findData(saved_background_mode)
        if saved_index >= 0:
            self.background_mode_combo.setCurrentIndex(saved_index)
        background_row.addWidget(self.background_mode_combo, stretch=1)
        target_layout.addLayout(background_row)
        self.target_match_label = QLabel("")
        self.target_match_label.setObjectName("HintLabel")
        self.target_match_label.setWordWrap(True)
        target_layout.addWidget(self.target_match_label)
        self.final_preview_label = PreviewLabel("Select a source and target icon.")
        self.final_preview_scroll = PreviewScrollArea()
        self.final_preview_scroll.setWidgetResizable(False)
        self.final_preview_scroll.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.final_preview_scroll.setWidget(self.final_preview_label)
        self.final_preview_label.attach_scroll_area(self.final_preview_scroll)
        target_layout.addWidget(self.final_preview_scroll, stretch=1)
        self.target_meta_label = QLabel("")
        self.target_meta_label.setObjectName("HintLabel")
        self.target_meta_label.setWordWrap(True)
        target_layout.addWidget(self.target_meta_label)
        export_row = QHBoxLayout()
        self.preview_final_button = QPushButton("Preview Final")
        self.export_generated_button = QPushButton("Export Generated Icon...")
        self.add_to_loose_mod_button = QPushButton("Add To Existing Loose Mod...")
        export_row.addWidget(self.preview_final_button)
        export_row.addWidget(self.export_generated_button)
        export_row.addWidget(self.add_to_loose_mod_button)
        export_row.addStretch(1)
        target_layout.addLayout(export_row)
        layout.addWidget(target_group, stretch=1)

        self.save_metadata_button.clicked.connect(self.save_selected_metadata)
        self.open_editor_button.clicked.connect(self.open_selected_in_texture_editor)
        self.delete_source_button.clicked.connect(self.delete_selected_source)
        self.refresh_targets_button.clicked.connect(self.refresh_targets)
        self.target_filter_edit.textChanged.connect(lambda _text="": self._handle_target_filter_changed())
        self.target_combo.currentIndexChanged.connect(lambda _index=0: self.update_final_preview())
        self.background_mode_combo.currentIndexChanged.connect(lambda _index=0: self._handle_background_mode_changed())
        self.use_archive_selection_button.clicked.connect(self.use_archive_selection_as_target)
        self.open_target_archive_button.clicked.connect(self.open_current_target_in_archive_browser)
        self.preview_final_button.clicked.connect(lambda _checked=False: self.update_final_preview(show_errors=True))
        self.export_generated_button.clicked.connect(self.export_generated_icon)
        self.add_to_loose_mod_button.clicked.connect(self.add_to_existing_loose_mod)
        return panel

    def shutdown(self) -> None:
        self._temp_preview_dir.cleanup()

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

    def _record_matches_filter(self, record: ItemIconLibraryRecord, text: str) -> bool:
        if self.favorite_only_checkbox.isChecked() and not record.favorite:
            return False
        if not text:
            return True
        haystack = " ".join(
            (
                record.path.name,
                record.relative_path,
                str(record.path),
                " ".join(record.tags),
                record.notes,
                record.source_kind,
            )
        ).casefold()
        return all(part in haystack for part in text.casefold().split())

    def _populate_records_tree(self, *, select_path: Optional[Path] = None) -> None:
        self.records_tree.blockSignals(True)
        self.records_tree.clear()
        filter_text = self.filter_edit.text().strip()
        selected_key = str(select_path).casefold() if select_path is not None else ""
        item_to_select: Optional[QTreeWidgetItem] = None
        shown = 0
        for record in self.records:
            if not self._record_matches_filter(record, filter_text):
                continue
            shown += 1
            size_text = f"{record.width}x{record.height}" if record.width and record.height else "-"
            name = ("* " if record.favorite else "") + record.path.name
            item = QTreeWidgetItem([name, size_text, ", ".join(record.tags), record.source_kind, record.relative_path])
            item.setData(0, Qt.ItemDataRole.UserRole, str(record.path))
            item.setToolTip(0, str(record.path))
            item.setToolTip(4, str(record.path))
            self.records_tree.addTopLevelItem(item)
            if selected_key and str(record.path).casefold() == selected_key:
                item_to_select = item
        self.records_tree.blockSignals(False)
        if item_to_select is not None:
            self.records_tree.setCurrentItem(item_to_select)
        elif self.records_tree.topLevelItemCount() > 0 and self.records_tree.currentItem() is None:
            self.records_tree.setCurrentItem(self.records_tree.topLevelItem(0))
        self.library_status_label.setText(f"{shown:,}/{len(self.records):,} icon source(s) shown.")

    def _handle_record_selection(self, item: Optional[QTreeWidgetItem]) -> None:
        path = self.current_source_path(item)
        record = self._record_for_path(path) if path is not None else None
        self._loading_record = True
        try:
            self.favorite_checkbox.setChecked(bool(record.favorite) if record else False)
            self.tags_edit.setText(", ".join(record.tags) if record else "")
            self.notes_edit.setPlainText(record.notes if record else "")
        finally:
            self._loading_record = False
        if hasattr(self, "delete_source_button"):
            self.delete_source_button.setEnabled(bool(path is not None and path.is_file()))
        self.update_source_preview()
        self.update_final_preview()

    def _record_for_path(self, path: Optional[Path]) -> Optional[ItemIconLibraryRecord]:
        if path is None:
            return None
        return self._records_by_key.get(str(path).casefold())

    def current_source_path(self, item: Optional[QTreeWidgetItem] = None) -> Optional[Path]:
        current = item or self.records_tree.currentItem()
        if current is None:
            return None
        text = str(current.data(0, Qt.ItemDataRole.UserRole) or "").strip()
        return Path(text).expanduser() if text else None

    def selected_library_source_path(self) -> Optional[Path]:
        return self.current_source_path()

    def select_source_path(self, source_path: Path) -> None:
        target = str(source_path.expanduser()).casefold()
        for index in range(self.records_tree.topLevelItemCount()):
            item = self.records_tree.topLevelItem(index)
            if str(item.data(0, Qt.ItemDataRole.UserRole) or "").casefold() == target:
                self.records_tree.setCurrentItem(item)
                self.records_tree.scrollToItem(item, QAbstractItemView.ScrollHint.PositionAtCenter)
                return

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

    def _target_path_for_entry(self, entry: object) -> str:
        return str(getattr(entry, "path", "") or "").replace("\\", "/").strip()

    def _target_entry_for_path(self, target_path: str) -> Optional[object]:
        normalized = str(target_path or "").replace("\\", "/").strip().casefold()
        if not normalized:
            return None
        return next((entry for entry in self._target_entries if self._target_path_for_entry(entry).casefold() == normalized), None)

    def _matching_target_entries(self, filter_text: str) -> list[object]:
        text = str(filter_text or "").replace("\\", "/").strip().casefold()
        if not text:
            return list(self._target_entries)
        terms = [part for part in text.split() if part]
        exact = self._target_entry_for_path(text)
        matches = [
            entry
            for entry in self._target_entries
            if all(term in self._target_path_for_entry(entry).casefold() for term in terms)
        ]
        if exact is not None and exact not in matches:
            matches.insert(0, exact)
        return matches

    def _populate_target_combo(self, *, select_path: str = "") -> None:
        filter_text = self.target_filter_edit.text().strip()
        matches = self._matching_target_entries(filter_text)
        exact_filter_entry = self._target_entry_for_path(filter_text)
        selected_entry = self._target_entry_for_path(select_path) or exact_filter_entry
        display_limit = 300
        shown = list(matches[:display_limit])
        if selected_entry is not None and selected_entry not in shown:
            shown.insert(0, selected_entry)
        self.target_combo.blockSignals(True)
        self.target_combo.clear()
        for entry in shown:
            path = self._target_path_for_entry(entry)
            self.target_combo.addItem(path, entry)
        if not self._target_entries:
            self.target_combo.addItem("Load archive data to choose existing item icon targets", None)
        elif not shown:
            self.target_combo.addItem("No existing item icon target matches this filter", None)
        if selected_entry is not None:
            selected_path = self._target_path_for_entry(selected_entry)
            selected_index = self.target_combo.findText(selected_path)
            if selected_index >= 0:
                self.target_combo.setCurrentIndex(selected_index)
        self.target_combo.blockSignals(False)
        if not self._target_entries:
            self.target_match_label.setText("No archive item icon targets are loaded yet.")
        elif len(matches) > len(shown):
            self.target_match_label.setText(
                f"Showing {len(shown):,} of {len(matches):,} matching existing icon target(s). Type more of the path/name to narrow it."
            )
        else:
            self.target_match_label.setText(f"{len(matches):,} matching existing icon target(s).")

    def _handle_target_filter_changed(self) -> None:
        self._populate_target_combo(select_path=self.target_filter_edit.text().strip())
        self.update_final_preview()

    def refresh_targets(self) -> None:
        current_entry = self._current_target_entry()
        current_path = str(getattr(current_entry, "path", "") or "") if current_entry is not None else ""
        self._target_entries = sorted(
            (entry for entry in self.get_archive_entries() if _is_probable_item_icon_entry(entry)),
            key=lambda entry: str(getattr(entry, "path", "") or "").casefold(),
        )
        self._populate_target_combo(select_path=current_path)
        self.update_final_preview()

    def _current_target_entry(self) -> Optional[object]:
        typed_entry = self._target_entry_for_path(self.target_filter_edit.text().strip())
        if typed_entry is not None:
            return typed_entry
        entry = self.target_combo.currentData()
        return entry if entry is not None else None

    def _current_target_path(self) -> str:
        entry = self._current_target_entry()
        return str(getattr(entry, "path", "") or "") if entry is not None else ""

    def use_archive_selection_as_target(self) -> None:
        selected_path = str(self.get_current_archive_path() or "").replace("\\", "/").strip()
        if not selected_path:
            QMessageBox.information(self, "Icon Creator", "Select an item icon DDS in Archive Browser first.")
            return
        entry = self._target_entry_for_path(selected_path)
        if entry is None:
            QMessageBox.warning(
                self,
                "Icon Creator",
                "The current Archive Browser selection is not a loaded existing item icon target.",
            )
            return
        self.target_filter_edit.setText(self._target_path_for_entry(entry))
        self._populate_target_combo(select_path=self._target_path_for_entry(entry))
        self.update_final_preview()

    def open_current_target_in_archive_browser(self) -> None:
        target_path = self._current_target_path()
        if not target_path:
            QMessageBox.information(self, "Icon Creator", "Choose an existing target icon path first.")
            return
        self.open_target_in_archive_requested.emit(target_path)

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
