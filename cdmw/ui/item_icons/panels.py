from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QComboBox,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QPlainTextEdit,
    QPushButton,
    QSizePolicy,
    QTreeWidget,
    QVBoxLayout,
    QWidget,
)

from cdmw.core.item_icon import ITEM_ICON_DEFAULT_BACKGROUND_MODE, normalize_item_icon_background_mode
from cdmw.ui.widgets import PreviewLabel, PreviewScrollArea


def build_roots_panel(tab: object) -> QWidget:
    panel = QWidget()
    layout = QVBoxLayout(panel)
    layout.setContentsMargins(0, 0, 0, 0)
    layout.setSpacing(6)
    roots_group = QGroupBox("Library Folders")
    roots_layout = QVBoxLayout(roots_group)
    roots_layout.setContentsMargins(8, 8, 8, 8)
    roots_layout.setSpacing(6)
    tab.roots_list = QListWidget()
    tab.roots_list.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
    roots_layout.addWidget(tab.roots_list, stretch=1)
    root_buttons = QGridLayout()
    tab.add_root_button = QPushButton("Add Folder...")
    tab.remove_root_button = QPushButton("Remove")
    tab.rescan_button = QPushButton("Rescan")
    tab.open_edited_folder_button = QPushButton("Edited Folder")
    root_buttons.addWidget(tab.add_root_button, 0, 0)
    root_buttons.addWidget(tab.remove_root_button, 0, 1)
    root_buttons.addWidget(tab.rescan_button, 1, 0)
    root_buttons.addWidget(tab.open_edited_folder_button, 1, 1)
    roots_layout.addLayout(root_buttons)
    tab.roots_status_label = QLabel("")
    tab.roots_status_label.setObjectName("HintLabel")
    tab.roots_status_label.setWordWrap(True)
    roots_layout.addWidget(tab.roots_status_label)
    layout.addWidget(roots_group, stretch=1)

    tab.add_root_button.clicked.connect(tab.add_library_root)
    tab.remove_root_button.clicked.connect(tab.remove_selected_library_root)
    tab.rescan_button.clicked.connect(lambda _checked=False: tab.scan_library(show_status=True))
    tab.open_edited_folder_button.clicked.connect(tab.open_edited_folder)
    return panel


def build_library_panel(tab: object) -> QWidget:
    panel = QWidget()
    layout = QVBoxLayout(panel)
    layout.setContentsMargins(0, 0, 0, 0)
    layout.setSpacing(6)
    filter_row = QHBoxLayout()
    tab.filter_edit = QLineEdit()
    tab.filter_edit.setPlaceholderText("Filter name, path, tags, or notes")
    tab.favorite_only_checkbox = QCheckBox("Favorites")
    filter_row.addWidget(tab.filter_edit, stretch=1)
    filter_row.addWidget(tab.favorite_only_checkbox)
    layout.addLayout(filter_row)
    tab.records_tree = QTreeWidget()
    tab.records_tree.setColumnCount(5)
    tab.records_tree.setHeaderLabels(["Name", "Size", "Tags", "Kind", "Path"])
    tab.records_tree.setRootIsDecorated(False)
    tab.records_tree.setAlternatingRowColors(True)
    tab.records_tree.setUniformRowHeights(True)
    tab.records_tree.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
    tab.records_tree.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
    tab.records_tree.setSortingEnabled(True)
    tab.records_tree.header().setStretchLastSection(True)
    tab.records_tree.header().resizeSection(0, 210)
    tab.records_tree.header().resizeSection(1, 80)
    tab.records_tree.header().resizeSection(2, 140)
    tab.records_tree.header().resizeSection(3, 80)
    layout.addWidget(tab.records_tree, stretch=1)
    tab.library_status_label = QLabel("No icon sources loaded.")
    tab.library_status_label.setObjectName("HintLabel")
    tab.library_status_label.setWordWrap(True)
    layout.addWidget(tab.library_status_label)

    tab.filter_edit.textChanged.connect(lambda _text="": tab._schedule_records_tree_population())
    tab.favorite_only_checkbox.toggled.connect(lambda _checked=False: tab._schedule_records_tree_population())
    tab.records_tree.currentItemChanged.connect(lambda current, _previous: tab._handle_record_selection(current))
    tab.records_tree.itemDoubleClicked.connect(lambda _item, _column: tab.open_selected_in_texture_editor())
    tab.records_tree.customContextMenuRequested.connect(tab._show_records_context_menu)
    return panel


def build_preview_panel(tab: object) -> QWidget:
    panel = QWidget()
    layout = QVBoxLayout(panel)
    layout.setContentsMargins(0, 0, 0, 0)
    layout.setSpacing(6)

    source_group = QGroupBox("Source")
    source_layout = QVBoxLayout(source_group)
    source_layout.setContentsMargins(8, 8, 8, 8)
    source_layout.setSpacing(6)
    tab.source_preview_label = PreviewLabel("Select an icon source.")
    tab.source_preview_scroll = PreviewScrollArea()
    tab.source_preview_scroll.setWidgetResizable(False)
    tab.source_preview_scroll.setAlignment(Qt.AlignmentFlag.AlignCenter)
    tab.source_preview_scroll.setWidget(tab.source_preview_label)
    tab.source_preview_label.attach_scroll_area(tab.source_preview_scroll)
    source_layout.addWidget(tab.source_preview_scroll, stretch=1)
    tab.source_meta_label = QLabel("")
    tab.source_meta_label.setObjectName("HintLabel")
    tab.source_meta_label.setWordWrap(True)
    source_layout.addWidget(tab.source_meta_label)

    metadata_grid = QGridLayout()
    tab.favorite_checkbox = QCheckBox("Favorite")
    tab.tags_edit = QLineEdit()
    tab.tags_edit.setPlaceholderText("comma separated tags")
    tab.notes_edit = QPlainTextEdit()
    tab.notes_edit.setMaximumHeight(72)
    tab.notes_edit.setPlaceholderText("Notes")
    tab.save_metadata_button = QPushButton("Save Metadata")
    tab.open_editor_button = QPushButton("Open In Texture Editor")
    tab.delete_source_button = QPushButton("Delete Source")
    tab.delete_source_button.setEnabled(False)
    metadata_grid.addWidget(tab.favorite_checkbox, 0, 0, 1, 2)
    metadata_grid.addWidget(QLabel("Tags"), 1, 0)
    metadata_grid.addWidget(tab.tags_edit, 1, 1)
    metadata_grid.addWidget(QLabel("Notes"), 2, 0)
    metadata_grid.addWidget(tab.notes_edit, 2, 1)
    metadata_grid.addWidget(tab.save_metadata_button, 3, 0)
    metadata_grid.addWidget(tab.open_editor_button, 3, 1)
    metadata_grid.addWidget(tab.delete_source_button, 4, 0, 1, 2)
    metadata_grid.setColumnStretch(1, 1)
    source_layout.addLayout(metadata_grid)
    layout.addWidget(source_group, stretch=1)

    target_group = QGroupBox("Compatible Output")
    target_layout = QVBoxLayout(target_group)
    target_layout.setContentsMargins(8, 8, 8, 8)
    target_layout.setSpacing(6)
    tab.target_filter_edit = QLineEdit()
    tab.target_filter_edit.setPlaceholderText("Filter or paste an existing archive item icon path")
    target_layout.addWidget(tab.target_filter_edit)
    target_row = QHBoxLayout()
    tab.target_combo = QComboBox()
    tab.target_combo.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
    tab.refresh_targets_button = QPushButton("Refresh Targets")
    tab.use_archive_selection_button = QPushButton("Use Archive Selection")
    tab.open_target_archive_button = QPushButton("Open In Archive Browser")
    target_row.addWidget(tab.target_combo, stretch=1)
    target_row.addWidget(tab.refresh_targets_button)
    target_layout.addLayout(target_row)
    target_button_row = QHBoxLayout()
    target_button_row.addWidget(tab.use_archive_selection_button)
    target_button_row.addWidget(tab.open_target_archive_button)
    target_button_row.addStretch(1)
    target_layout.addLayout(target_button_row)
    background_row = QHBoxLayout()
    background_row.addWidget(QLabel("Background"))
    tab.background_mode_combo = QComboBox()
    tab.background_mode_combo.addItem("Auto transparent", "auto_transparent")
    tab.background_mode_combo.addItem("Keep source", "keep_source")
    tab.background_mode_combo.addItem("Target underlay", "target_underlay")
    saved_background_mode = normalize_item_icon_background_mode(
        tab.settings.value("item_icons/background_mode", ITEM_ICON_DEFAULT_BACKGROUND_MODE)
    )
    saved_index = tab.background_mode_combo.findData(saved_background_mode)
    if saved_index >= 0:
        tab.background_mode_combo.setCurrentIndex(saved_index)
    background_row.addWidget(tab.background_mode_combo, stretch=1)
    target_layout.addLayout(background_row)
    tab.target_match_label = QLabel("")
    tab.target_match_label.setObjectName("HintLabel")
    tab.target_match_label.setWordWrap(True)
    target_layout.addWidget(tab.target_match_label)
    tab.final_preview_label = PreviewLabel("Select a source and target icon.")
    tab.final_preview_scroll = PreviewScrollArea()
    tab.final_preview_scroll.setWidgetResizable(False)
    tab.final_preview_scroll.setAlignment(Qt.AlignmentFlag.AlignCenter)
    tab.final_preview_scroll.setWidget(tab.final_preview_label)
    tab.final_preview_label.attach_scroll_area(tab.final_preview_scroll)
    target_layout.addWidget(tab.final_preview_scroll, stretch=1)
    tab.target_meta_label = QLabel("")
    tab.target_meta_label.setObjectName("HintLabel")
    tab.target_meta_label.setWordWrap(True)
    target_layout.addWidget(tab.target_meta_label)
    export_row = QHBoxLayout()
    tab.preview_final_button = QPushButton("Preview Final")
    tab.export_generated_button = QPushButton("Export Generated Icon...")
    tab.add_to_loose_mod_button = QPushButton("Add To Existing Loose Mod...")
    export_row.addWidget(tab.preview_final_button)
    export_row.addWidget(tab.export_generated_button)
    export_row.addWidget(tab.add_to_loose_mod_button)
    export_row.addStretch(1)
    target_layout.addLayout(export_row)
    layout.addWidget(target_group, stretch=1)

    tab.save_metadata_button.clicked.connect(tab.save_selected_metadata)
    tab.open_editor_button.clicked.connect(tab.open_selected_in_texture_editor)
    tab.delete_source_button.clicked.connect(tab.delete_selected_source)
    tab.refresh_targets_button.clicked.connect(lambda _checked=False: tab.refresh_targets(force=True))
    tab.target_filter_edit.textChanged.connect(lambda _text="": tab._target_filter_timer.start())
    tab.target_combo.currentIndexChanged.connect(lambda _index=0: tab.update_final_preview())
    tab.background_mode_combo.currentIndexChanged.connect(lambda _index=0: tab._handle_background_mode_changed())
    tab.use_archive_selection_button.clicked.connect(tab.use_archive_selection_as_target)
    tab.open_target_archive_button.clicked.connect(tab.open_current_target_in_archive_browser)
    tab.preview_final_button.clicked.connect(lambda _checked=False: tab.update_final_preview(show_errors=True))
    tab.export_generated_button.clicked.connect(tab.export_generated_icon)
    tab.add_to_loose_mod_button.clicked.connect(tab.add_to_existing_loose_mod)
    return panel


__all__ = ["build_library_panel", "build_preview_panel", "build_roots_panel"]
