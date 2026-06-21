from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QAbstractItemView,
    QComboBox,
    QFormLayout,
    QGroupBox,
    QHeaderView,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPlainTextEdit,
    QPushButton,
    QSplitter,
    QStackedWidget,
    QTabWidget,
    QTreeWidget,
    QVBoxLayout,
    QWidget,
)

from cdmw.ui.research.help_widgets import (
    add_flat_section_help as _add_flat_section_help,
    add_titled_help_header as _add_titled_help_header,
)
from cdmw.ui.research.layout_state import (
    research_archive_picker_splitter_default_sizes,
    research_notes_splitter_default_sizes,
)
from cdmw.ui.research.models import archive_picker_item_kind as _archive_picker_item_kind
from cdmw.ui.research.tree_helpers import make_research_tree_columns_persistent
from cdmw.ui.widgets import ArchiveDetailsEditor, EmptyStateTreeWidget, FlatSectionPanel, PreviewLabel, PreviewScrollArea

def build_archive_picker_group(self) -> QWidget:
    group = FlatSectionPanel("Archive Files")
    _add_flat_section_help(
        group,
        "Uses the current Archive Browser scan/filter state so you can pick files for Research without leaving this tab. DDS semantics can still use loaded archive sidecars when they are available.",
    )
    layout = group.body_layout
    layout.setSpacing(8)

    actions = QHBoxLayout()
    actions.setSpacing(8)
    self.archive_picker_refresh_button = QPushButton("Refresh List")
    self.archive_picker_use_reference_button = QPushButton("Use In References")
    self.archive_picker_use_note_button = QPushButton("Use In Notes")
    self.archive_picker_view_combo = QComboBox()
    self.archive_picker_view_combo.addItem("Flat files", "flat")
    self.archive_picker_view_combo.addItem("Folders", "folders")
    self.archive_picker_view_combo.setToolTip(
        "Flat files lists the current Archive Browser results directly. Folders keeps the path tree for broad browsing."
    )
    actions.addWidget(self.archive_picker_refresh_button)
    actions.addWidget(self.archive_picker_use_reference_button)
    actions.addWidget(self.archive_picker_use_note_button)
    actions.addStretch(1)
    actions.addWidget(QLabel("View"))
    actions.addWidget(self.archive_picker_view_combo)
    layout.addLayout(actions)

    self.archive_picker_status_label = QLabel("Load or filter archives first to browse related files here.")
    self.archive_picker_status_label.setWordWrap(True)
    self.archive_picker_status_label.setObjectName("HintLabel")
    layout.addWidget(self.archive_picker_status_label)

    self.archive_picker_splitter = QSplitter(Qt.Horizontal)
    self.archive_picker_splitter.setChildrenCollapsible(False)
    self.archive_picker_splitter.setHandleWidth(8)

    tree_container = QWidget()
    tree_layout = QVBoxLayout(tree_container)
    tree_layout.setContentsMargins(0, 0, 0, 0)
    tree_layout.setSpacing(0)
    self.archive_picker_tree = EmptyStateTreeWidget(
        "No archive files",
        "Scan archives or broaden the Archive Browser filter to populate this picker.",
    )
    self.archive_picker_tree.setHeaderLabels(["Name", "Type", "Package"])
    self.archive_picker_tree.setSelectionMode(QAbstractItemView.SingleSelection)
    self.archive_picker_tree.setSelectionBehavior(QTreeWidget.SelectRows)
    self.archive_picker_tree.setAlternatingRowColors(False)
    self.archive_picker_tree.setRootIsDecorated(True)
    self.archive_picker_tree.setUniformRowHeights(True)
    self.archive_picker_tree.header().setStretchLastSection(False)
    self.archive_picker_tree.header().setSectionResizeMode(0, QHeaderView.Interactive)
    self.archive_picker_tree.header().setSectionResizeMode(1, QHeaderView.ResizeToContents)
    self.archive_picker_tree.header().setSectionResizeMode(2, QHeaderView.ResizeToContents)
    make_research_tree_columns_persistent(self.archive_picker_tree, self.settings, "archive_picker")
    tree_layout.addWidget(self.archive_picker_tree)
    self.archive_picker_splitter.addWidget(tree_container)

    preview_group = FlatSectionPanel("Selected Preview")
    preview_layout = preview_group.body_layout
    preview_layout.setSpacing(8)

    preview_title_row = QHBoxLayout()
    preview_title_row.setSpacing(8)
    self.archive_picker_preview_title_label = QLabel("Select an archive file")
    self.archive_picker_preview_title_label.setWordWrap(True)
    self.archive_picker_preview_zoom_out_button = QPushButton("-")
    self.archive_picker_preview_zoom_fit_button = QPushButton("Fit")
    self.archive_picker_preview_zoom_100_button = QPushButton("100%")
    self.archive_picker_preview_zoom_in_button = QPushButton("+")
    self.archive_picker_preview_zoom_value = QLabel("Fit")
    self.archive_picker_preview_zoom_value.setObjectName("HintLabel")
    preview_title_row.addWidget(self.archive_picker_preview_title_label, stretch=1)
    preview_title_row.addWidget(self.archive_picker_preview_zoom_out_button)
    preview_title_row.addWidget(self.archive_picker_preview_zoom_fit_button)
    preview_title_row.addWidget(self.archive_picker_preview_zoom_100_button)
    preview_title_row.addWidget(self.archive_picker_preview_zoom_in_button)
    preview_title_row.addWidget(self.archive_picker_preview_zoom_value)
    preview_layout.addLayout(preview_title_row)

    self.archive_picker_preview_meta_label = QLabel("Select a file in Archive Files to preview it here.")
    self.archive_picker_preview_meta_label.setWordWrap(True)
    self.archive_picker_preview_meta_label.setObjectName("HintLabel")
    preview_layout.addWidget(self.archive_picker_preview_meta_label)

    self.archive_picker_preview_warning_label = QLabel("")
    self.archive_picker_preview_warning_label.setWordWrap(True)
    self.archive_picker_preview_warning_label.setObjectName("WarningText")
    self.archive_picker_preview_warning_label.setVisible(False)
    preview_layout.addWidget(self.archive_picker_preview_warning_label)

    self.archive_picker_preview_stack = QStackedWidget()
    self.archive_picker_preview_label = PreviewLabel("Select a file to preview it here.")
    self.archive_picker_preview_scroll = PreviewScrollArea()
    self.archive_picker_preview_scroll.setWidgetResizable(False)
    self.archive_picker_preview_scroll.setAlignment(Qt.AlignCenter)
    self.archive_picker_preview_scroll.setWidget(self.archive_picker_preview_label)
    self.archive_picker_preview_label.attach_scroll_area(self.archive_picker_preview_scroll)
    self.archive_picker_preview_label.set_wheel_zoom_handler(self._adjust_archive_picker_preview_zoom)
    self.archive_picker_preview_text_edit = QPlainTextEdit()
    self.archive_picker_preview_text_edit.setReadOnly(True)
    self.archive_picker_preview_info_edit = QPlainTextEdit()
    self.archive_picker_preview_info_edit.setReadOnly(True)
    self.archive_picker_preview_stack.addWidget(self.archive_picker_preview_scroll)
    self.archive_picker_preview_stack.addWidget(self.archive_picker_preview_text_edit)
    self.archive_picker_preview_stack.addWidget(self.archive_picker_preview_info_edit)

    self.archive_picker_preview_details_edit = ArchiveDetailsEditor(
        theme_key=self.current_theme_key,
        highlight_style=self._current_text_highlight_style(),
        color_scheme=self._current_preview_color_scheme(),
    )
    self.archive_picker_preview_details_edit.document().setMaximumBlockCount(2000)
    self.archive_picker_preview_tabs = QTabWidget()
    preview_tab = QWidget()
    preview_tab_layout = QVBoxLayout(preview_tab)
    preview_tab_layout.setContentsMargins(0, 0, 0, 0)
    preview_tab_layout.setSpacing(0)
    preview_tab_layout.addWidget(self.archive_picker_preview_stack)
    details_tab = QWidget()
    details_tab_layout = QVBoxLayout(details_tab)
    details_tab_layout.setContentsMargins(0, 0, 0, 0)
    details_tab_layout.setSpacing(0)
    details_tab_layout.addWidget(self.archive_picker_preview_details_edit)
    self.archive_picker_preview_tabs.addTab(preview_tab, "Preview")
    self.archive_picker_preview_tabs.addTab(details_tab, "Details")
    preview_layout.addWidget(self.archive_picker_preview_tabs, stretch=1)
    self.archive_picker_splitter.addWidget(preview_group)
    self.archive_picker_splitter.setSizes(research_archive_picker_splitter_default_sizes())
    layout.addWidget(self.archive_picker_splitter, stretch=1)

    self.archive_picker_refresh_button.clicked.connect(self.refresh_archive_picker)
    self.archive_picker_view_combo.currentIndexChanged.connect(self._handle_archive_picker_view_changed)
    self.archive_picker_use_reference_button.clicked.connect(self.use_selected_archive_picker_for_reference)
    self.archive_picker_use_note_button.clicked.connect(self.use_selected_archive_picker_for_note)
    self.archive_picker_tree.currentItemChanged.connect(self._handle_archive_picker_current_item_change)
    self.archive_picker_tree.itemExpanded.connect(self._handle_archive_picker_item_expanded)
    self.archive_picker_tree.itemDoubleClicked.connect(
        lambda item, _column: self.use_selected_archive_picker_for_reference()
        if _archive_picker_item_kind(item) == "file"
        else None
    )
    self.archive_picker_preview_zoom_fit_button.clicked.connect(self._set_archive_picker_preview_fit_mode)
    self.archive_picker_preview_zoom_100_button.clicked.connect(lambda: self._set_archive_picker_preview_zoom_factor(1.0))
    self.archive_picker_preview_zoom_out_button.clicked.connect(lambda: self._adjust_archive_picker_preview_zoom(-1))
    self.archive_picker_preview_zoom_in_button.clicked.connect(lambda: self._adjust_archive_picker_preview_zoom(1))
    return group

def build_analysis_detail_group(self) -> QGroupBox:
    detail_group = QGroupBox("Selected Result Details")
    detail_layout = QVBoxLayout(detail_group)
    detail_layout.setContentsMargins(10, 12, 10, 10)
    detail_layout.setSpacing(8)
    self.analysis_detail_label = QLabel(
        "Select a row in Mip Analysis or Bulk Normal Validator to see where the result came from and what it means."
    )
    self.analysis_detail_label.setWordWrap(True)
    self.analysis_detail_label.setObjectName("HintLabel")
    detail_layout.addWidget(self.analysis_detail_label)
    self.analysis_detail_edit = QPlainTextEdit()
    self.analysis_detail_edit.setReadOnly(True)
    self.analysis_detail_edit.setPlaceholderText(
        "Detailed analysis context and warnings will appear here."
    )
    detail_layout.addWidget(self.analysis_detail_edit, stretch=1)
    return detail_group

def build_notes_tab(self) -> QWidget:
    tab = QWidget()
    layout = QVBoxLayout(tab)
    layout.setContentsMargins(0, 0, 0, 0)
    layout.setSpacing(10)

    self.notes_splitter = QSplitter(Qt.Horizontal)
    splitter = self.notes_splitter
    splitter.setChildrenCollapsible(False)
    layout.addWidget(splitter, stretch=1)

    notes_group = QGroupBox("")
    notes_layout = QVBoxLayout(notes_group)
    notes_layout.setContentsMargins(10, 8, 10, 10)
    notes_layout.setSpacing(6)
    _add_titled_help_header(
        notes_layout,
        "Tagging And Notes",
        "Annotate archive files, text-search results, or compare targets while you research. Notes are stored locally beside the EXE."
    )
    use_row = QHBoxLayout()
    self.notes_use_archive_button = QPushButton("Use Selected File")
    self.notes_use_search_button = QPushButton("Use Selected Search Result")
    self.notes_use_compare_button = QPushButton("Use Selected Compare File")
    use_row.addWidget(self.notes_use_archive_button)
    use_row.addWidget(self.notes_use_search_button)
    use_row.addWidget(self.notes_use_compare_button)
    notes_layout.addLayout(use_row)

    form = QFormLayout()
    form.setHorizontalSpacing(10)
    form.setVerticalSpacing(8)
    self.notes_target_edit = QLineEdit()
    self.notes_source_label = QLabel("manual")
    self.notes_tags_edit = QLineEdit()
    self.notes_tags_edit.setPlaceholderText("comma,separated,tags")
    form.addRow("Target", self.notes_target_edit)
    form.addRow("Source", self.notes_source_label)
    form.addRow("Tags", self.notes_tags_edit)
    notes_layout.addLayout(form)
    self.notes_edit = QPlainTextEdit()
    self.notes_edit.setPlaceholderText(
        "Add freeform notes, discoveries, unresolved questions, or file relationships here."
    )
    notes_layout.addWidget(self.notes_edit, stretch=1)
    buttons = QHBoxLayout()
    self.notes_save_button = QPushButton("Save Note")
    self.notes_delete_button = QPushButton("Delete Note")
    buttons.addWidget(self.notes_save_button)
    buttons.addWidget(self.notes_delete_button)
    buttons.addStretch(1)
    notes_layout.addLayout(buttons)
    splitter.addWidget(notes_group)

    list_group = QGroupBox("Saved Notes")
    list_layout = QVBoxLayout(list_group)
    list_layout.setContentsMargins(10, 12, 10, 10)
    list_layout.setSpacing(8)
    self.notes_tree = EmptyStateTreeWidget(
        "No notes saved",
        "Saved research notes for archive, search, and compare targets will appear here.",
    )
    self.notes_tree.setRootIsDecorated(False)
    self.notes_tree.setAlternatingRowColors(True)
    self.notes_tree.setHeaderLabels(["Target", "Tags", "Updated", "Source"])
    self.notes_tree.header().resizeSection(0, 360)
    self.notes_tree.header().resizeSection(1, 200)
    self.notes_tree.header().resizeSection(2, 180)
    make_research_tree_columns_persistent(self.notes_tree, self.settings, "notes")
    list_layout.addWidget(self.notes_tree)
    splitter.addWidget(list_group)
    splitter.setSizes(research_notes_splitter_default_sizes())
    return tab
