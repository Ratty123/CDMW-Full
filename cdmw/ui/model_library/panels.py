"""Panel construction for the Model Library tab.

The tab is a command strip (view, search, filters) above three panes: the
Sources lane, the results table, and the selection pane. The Sources lane
shows only the active view's source: mirror catalogue settings or local
folders. Filters and the Sources lane collapse and remember their state.
"""

from __future__ import annotations

from typing import Optional

from PySide6.QtCore import QEvent, QSize, Qt
from PySide6.QtGui import QFont, QFontMetrics
from PySide6.QtWidgets import (
    QAbstractItemView,
    QButtonGroup,
    QCheckBox,
    QComboBox,
    QFrame,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMenu,
    QPlainTextEdit,
    QProgressBar,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QSpinBox,
    QStackedWidget,
    QTreeWidget,
    QVBoxLayout,
    QWidget,
)

from cdmw.domain.library.models import DEFAULT_MODEL_MIRROR_URL
from cdmw.models import ModelPreviewRenderSettings, clamp_model_preview_render_settings
from cdmw.ui.model_library.settings import MODEL_LIBRARY_FILTER_COLUMNS
from cdmw.ui.wrapping_layout import WrappingLayout

SOURCES_LANE_MIN_WIDTH = 256
SOURCES_LANE_MAX_WIDTH = 300


class _ElidedLabel(QLabel):
    """One-line hint that elides rather than widening its pane.

    ``text()`` keeps the full message for translation and callers; the tooltip
    shows it when the visible copy is cut short.
    """

    def __init__(self, text: str = "", parent: Optional[QWidget] = None) -> None:
        self._full_text = ""
        super().__init__(parent)
        self.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Fixed)
        self.setMinimumWidth(0)
        self.setText(text)

    def text(self) -> str:
        return self._full_text

    def setText(self, text: str) -> None:  # noqa: N802 - Qt override
        self._full_text = str(text or "")
        self.setToolTip(self._full_text)
        self._render_text()

    def _render_text(self) -> None:
        width = max(0, self.contentsRect().width())
        super().setText(self.fontMetrics().elidedText(self._full_text, Qt.TextElideMode.ElideRight, width))

    def resizeEvent(self, event) -> None:  # noqa: N802 - Qt override
        super().resizeEvent(event)
        self._render_text()

    def changeEvent(self, event) -> None:  # noqa: N802 - Qt override
        super().changeEvent(event)
        if event.type() in (QEvent.Type.FontChange, QEvent.Type.StyleChange):
            self._render_text()


class ModelLibraryColumnFilterRow(QWidget):
    """Column filter boxes placed directly above the columns they filter."""

    def __init__(self, tree: QTreeWidget, edits: dict[int, QLineEdit], parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.setObjectName("ModelLibraryColumnFilterRow")
        self.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Fixed)
        self.setMinimumWidth(0)
        self._tree = tree
        self._edits = dict(edits)
        for edit in self._edits.values():
            edit.setParent(self)
        self._update_height()
        header = tree.header()
        header.sectionResized.connect(self._sync_geometry)
        header.sectionMoved.connect(self._sync_geometry)
        header.geometriesChanged.connect(self._sync_geometry)
        tree.horizontalScrollBar().valueChanged.connect(self._sync_geometry)

    def _update_height(self) -> None:
        heights = [edit.sizeHint().height() for edit in self._edits.values()]
        self.setFixedHeight(max(heights, default=24))

    def _sync_geometry(self, *_args: object) -> None:
        header = self._tree.header()
        left = self._tree.viewport().geometry().left()
        for column, edit in self._edits.items():
            if header.isSectionHidden(column):
                edit.hide()
                continue
            x = left + header.sectionViewportPosition(column)
            width = header.sectionSize(column)
            edit.setGeometry(x + 1, 0, max(0, width - 2), self.height())
            edit.show()

    def resizeEvent(self, event) -> None:  # noqa: N802 - Qt override
        super().resizeEvent(event)
        self._sync_geometry()

    def showEvent(self, event) -> None:  # noqa: N802 - Qt override
        super().showEvent(event)
        self._sync_geometry()

    def changeEvent(self, event) -> None:  # noqa: N802 - Qt override
        super().changeEvent(event)
        if event.type() in (QEvent.Type.FontChange, QEvent.Type.StyleChange):
            self._update_height()
            self._sync_geometry()


class _ViewButton(QPushButton):
    """Checkable view switch sized for the bold text the theme gives it when checked."""

    def __init__(self, text: str) -> None:
        super().__init__()
        self.setCheckable(True)
        self.setText(text)

    def _bold_extra_width(self) -> int:
        text = self.text().replace("&&", "\0").replace("&", "").replace("\0", "&")
        bold = QFont(self.font())
        bold.setWeight(QFont.Weight.DemiBold)
        return max(0, QFontMetrics(bold).horizontalAdvance(text) - self.fontMetrics().horizontalAdvance(text))

    def sizeHint(self) -> QSize:  # noqa: N802 - Qt override
        hint = super().sizeHint()
        return QSize(hint.width() + self._bold_extra_width(), hint.height())

    def minimumSizeHint(self) -> QSize:  # noqa: N802 - Qt override
        hint = super().minimumSizeHint()
        return QSize(hint.width() + self._bold_extra_width(), hint.height())


def _fixed_button(text: str, *, tooltip: str = "", view_switch: bool = False) -> QPushButton:
    # Pass the text straight to a known widget so the localization manifest
    # generator infers this helper as a text sink.
    button = _ViewButton(text) if view_switch else QPushButton(text)
    button.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
    if tooltip:
        button.setToolTip(tooltip)
    return button


def _field_label(text: str) -> QLabel:
    label = QLabel(text)
    label.setObjectName("HintLabel")
    return label


def build_command_strip(tab: object) -> QWidget:
    """View switch, search, and the toggles for the Sources lane and filters."""

    strip = tab._model_library_command_strip = QFrame()
    strip.setObjectName("ModelLibraryCommandStrip")
    strip.setFrameShape(QFrame.Shape.NoFrame)
    strip.setProperty("compactStructural", True)
    layout = QHBoxLayout(strip)
    layout.setContentsMargins(0, 0, 0, 0)
    layout.setSpacing(6)

    tab._updating_results_query = False
    # The panel toggles are plain buttons so that only the view switch reads as
    # a selected segment; the panels themselves show whether they are open.
    tab.sources_toggle_button = _fixed_button(
        "Sources",
        tooltip="Show or hide mirror catalogue settings and local model folders.",
    )
    tab.mirror_results_view_button = _fixed_button("Mirror", tooltip="Mirror Catalogue", view_switch=True)
    tab.local_results_view_button = _fixed_button("Local", tooltip="Local Library", view_switch=True)
    tab.results_view_button_group = QButtonGroup(tab)
    tab.results_view_button_group.setExclusive(True)
    tab.results_view_button_group.addButton(tab.mirror_results_view_button)
    tab.results_view_button_group.addButton(tab.local_results_view_button)

    tab.search_edit = QLineEdit()
    tab.search_edit.setPlaceholderText("Search by name, tag, creator, or UID")
    tab.search_edit.setText(str(tab.settings.value("model_library/search_query", "sword") or "sword"))
    tab.search_edit.setMinimumWidth(120)
    tab.search_edit.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
    tab.results_filter_field_combo = QComboBox()
    tab.results_filter_field_combo.addItem("All fields", "all")
    tab.results_filter_field_combo.addItem("Name", "name")
    tab.results_filter_field_combo.addItem("Creator", "creator")
    tab.results_filter_field_combo.addItem("License", "license")
    tab.results_filter_field_combo.addItem("Format", "format")
    tab.results_filter_field_combo.addItem("Path / URL", "path")
    tab.results_filter_field_combo.addItem("UID", "uid")
    tab.results_filter_field_combo.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
    tab.apply_results_query_button = _fixed_button("Search")
    tab.clear_results_query_button = _fixed_button("Clear")
    tab.filters_toggle_button = _fixed_button(
        "Filters",
        tooltip="Show or hide catalogue and column filters.",
    )
    tab.refresh_results_view_button = _fixed_button("Reload", tooltip="Refresh")

    layout.addWidget(tab.sources_toggle_button)
    layout.addSpacing(6)
    layout.addWidget(tab.mirror_results_view_button)
    layout.addWidget(tab.local_results_view_button)
    layout.addSpacing(6)
    layout.addWidget(tab.search_edit, stretch=1)
    layout.addWidget(tab.results_filter_field_combo)
    layout.addWidget(tab.apply_results_query_button)
    layout.addWidget(tab.clear_results_query_button)
    layout.addSpacing(6)
    layout.addWidget(tab.filters_toggle_button)
    layout.addWidget(tab.refresh_results_view_button)

    tab.sources_toggle_button.clicked.connect(
        lambda _checked=False: tab._set_sources_panel_visible(tab._model_library_controls_panel.isHidden())
    )
    tab.filters_toggle_button.clicked.connect(lambda _checked=False: tab._set_filters_visible(tab.filters_strip.isHidden()))
    tab.mirror_results_view_button.clicked.connect(lambda _checked=False: tab.show_mirror_catalogue_view())
    tab.local_results_view_button.clicked.connect(lambda _checked=False: tab.show_local_library_view())
    tab.refresh_results_view_button.clicked.connect(lambda _checked=False: tab.refresh_active_results_view())
    tab.apply_results_query_button.clicked.connect(tab._apply_active_results_query)
    tab.clear_results_query_button.clicked.connect(tab._clear_active_results_query)
    tab.search_edit.returnPressed.connect(tab._apply_active_results_query)
    tab.search_edit.textChanged.connect(tab._handle_results_query_changed)
    tab.results_filter_field_combo.currentIndexChanged.connect(lambda _index=0: tab._handle_results_filter_field_changed())
    return strip


def build_filters_strip(tab: object) -> QWidget:
    """Catalogue filters (mirror) or texture filter (local), plus Clear filters."""

    strip = tab.filters_strip = QFrame()
    strip.setObjectName("ModelLibraryFiltersStrip")
    strip.setFrameShape(QFrame.Shape.NoFrame)
    strip.setProperty("compactStructural", True)
    layout = QHBoxLayout(strip)
    layout.setContentsMargins(0, 0, 0, 0)
    layout.setSpacing(12)

    mirror_fields = tab._mirror_filter_fields = QWidget()
    mirror_grid = QGridLayout(mirror_fields)
    mirror_grid.setContentsMargins(0, 0, 0, 0)
    mirror_grid.setHorizontalSpacing(6)
    mirror_grid.setVerticalSpacing(4)
    tab.license_filter_edit = QLineEdit()
    tab.license_filter_edit.setPlaceholderText("CC0, Attribution, NonCommercial")
    tab.creator_filter_edit = QLineEdit()
    tab.creator_filter_edit.setPlaceholderText("Creator name")
    tab.creator_exclude_edit = QLineEdit()
    tab.creator_exclude_edit.setPlaceholderText("Creator names/usernames, comma separated")
    tab.format_filter_combo = QComboBox()
    tab.format_filter_combo.addItem("Any format", "")
    tab.format_filter_combo.addItem("glTF ZIP", "gltf")
    tab.format_filter_combo.addItem("GLB", "glb")
    tab.format_filter_combo.addItem("Original source", "source")
    tab.hide_downloaded_checkbox = QCheckBox("Hide downloaded")
    tab.hide_downloaded_checkbox.setChecked(bool(tab.settings.value("model_library/hide_downloaded", False, type=bool)))
    mirror_grid.addWidget(QLabel("License"), 0, 0)
    mirror_grid.addWidget(tab.license_filter_edit, 0, 1)
    mirror_grid.addWidget(QLabel("Creator"), 0, 2)
    mirror_grid.addWidget(tab.creator_filter_edit, 0, 3)
    mirror_grid.addWidget(QLabel("Format"), 0, 4)
    mirror_grid.addWidget(tab.format_filter_combo, 0, 5)
    mirror_grid.addWidget(QLabel("Exclude creators"), 1, 0)
    mirror_grid.addWidget(tab.creator_exclude_edit, 1, 1, 1, 3)
    mirror_grid.addWidget(tab.hide_downloaded_checkbox, 1, 4, 1, 2)
    mirror_grid.setColumnStretch(1, 1)
    mirror_grid.setColumnStretch(3, 1)

    local_fields = tab._local_filter_fields = QWidget()
    local_row = QHBoxLayout(local_fields)
    local_row.setContentsMargins(0, 0, 0, 0)
    local_row.setSpacing(6)
    tab.local_texture_filter_label = QLabel("Textures")
    tab.local_texture_filter_combo = QComboBox()
    tab.local_texture_filter_combo.addItem("All", "all")
    tab.local_texture_filter_combo.addItem("Has textures", "has")
    tab.local_texture_filter_combo.addItem("No textures found", "missing")
    local_row.addWidget(tab.local_texture_filter_label)
    local_row.addWidget(tab.local_texture_filter_combo)
    local_row.addStretch(1)

    tab.clear_filters_button = _fixed_button("Clear filters")
    layout.addWidget(mirror_fields, stretch=1)
    layout.addWidget(local_fields, stretch=1)
    layout.addWidget(tab.clear_filters_button, alignment=Qt.AlignmentFlag.AlignTop)

    for edit in (tab.license_filter_edit, tab.creator_filter_edit, tab.creator_exclude_edit):
        edit.returnPressed.connect(tab._apply_active_results_query)
        edit.textChanged.connect(lambda _text="": tab._update_filters_button())
    tab.format_filter_combo.currentIndexChanged.connect(lambda _index=0: tab._update_filters_button())
    tab.hide_downloaded_checkbox.toggled.connect(tab._handle_hide_downloaded_toggled)
    tab.local_texture_filter_combo.currentIndexChanged.connect(lambda _index=0: tab._handle_local_texture_filter_changed())
    tab.clear_filters_button.clicked.connect(lambda _checked=False: tab._clear_all_filters())
    return strip


def build_controls_panel(tab: object) -> QWidget:
    """The Sources lane: mirror catalogue settings or local folders."""

    panel = tab._model_library_controls_content = QWidget()
    panel.setMinimumWidth(0)
    panel.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Minimum)
    layout = tab._model_library_controls_layout = QVBoxLayout(panel)
    layout.setContentsMargins(0, 0, 4, 0)
    layout.setSpacing(8)

    mirror_group = tab.mirror_group = QGroupBox("Mirror Catalogue")
    mirror_layout = QVBoxLayout(mirror_group)
    mirror_layout.setContentsMargins(0, 4, 0, 0)
    mirror_layout.setSpacing(4)
    tab.mirror_url_edit = QLineEdit()
    tab.mirror_url_edit.setPlaceholderText(DEFAULT_MODEL_MIRROR_URL)
    mirror_layout.addWidget(_field_label("Mirror URL"))
    mirror_layout.addWidget(tab.mirror_url_edit)
    tab.catalogue_dir_edit = QLineEdit()
    tab.catalogue_dir_edit.setPlaceholderText("Local catalogue folder")
    tab.browse_catalogue_dir_button = _fixed_button("Browse")
    catalogue_row = QHBoxLayout()
    catalogue_row.setSpacing(4)
    catalogue_row.addWidget(tab.catalogue_dir_edit, stretch=1)
    catalogue_row.addWidget(tab.browse_catalogue_dir_button)
    mirror_layout.addWidget(_field_label("Catalogue"))
    mirror_layout.addLayout(catalogue_row)

    tab.max_shards_spin = QSpinBox()
    tab.max_shards_spin.setRange(0, 100_000)
    tab.max_shards_spin.setSpecialValueText("All")
    tab.max_shards_spin.setValue(int(tab.settings.value("model_library/max_shards", 1000) or 1000))
    tab.max_shards_spin.setKeyboardTracking(False)
    tab.result_limit_spin = QSpinBox()
    tab.result_limit_spin.setRange(1, 5000)
    tab.result_limit_spin.setValue(int(tab.settings.value("model_library/result_limit", 100) or 100))
    tab.result_limit_spin.setKeyboardTracking(False)
    limits_grid = QGridLayout()
    limits_grid.setHorizontalSpacing(6)
    limits_grid.setVerticalSpacing(2)
    limits_grid.addWidget(_field_label("Index pages"), 0, 0)
    limits_grid.addWidget(_field_label("Results"), 0, 1)
    limits_grid.addWidget(tab.max_shards_spin, 1, 0)
    limits_grid.addWidget(tab.result_limit_spin, 1, 1)
    mirror_layout.addLayout(limits_grid)

    tab.preferred_format_checks: dict[str, QCheckBox] = {}
    preferred_file_options = (
        ("gltf", "glTF ZIP", ""),
        ("glb", "GLB", ""),
        ("source", "Source ZIP", "Original source ZIP (OBJ/FBX/etc.)"),
        ("extra", "Extra ZIP", ""),
    )
    selected_preferred_files = set(tab._settings_string_list("model_library/preferred_formats_json", default=("gltf",)))
    if not selected_preferred_files:
        selected_preferred_files = {"gltf"}
    preferred_grid = QGridLayout()
    preferred_grid.setHorizontalSpacing(8)
    preferred_grid.setVerticalSpacing(2)
    for option_index, (format_key, label, tooltip) in enumerate(preferred_file_options):
        checkbox = QCheckBox(label)
        if tooltip:
            checkbox.setToolTip(tooltip)
        checkbox.setChecked(format_key in selected_preferred_files)
        checkbox.toggled.connect(lambda _checked=False: tab._save_preferred_format_settings())
        tab.preferred_format_checks[format_key] = checkbox
        preferred_grid.addWidget(checkbox, option_index // 2, option_index % 2)
    mirror_layout.addWidget(_field_label("Preferred files"))
    mirror_layout.addLayout(preferred_grid)

    tab.build_index_button = QPushButton("Build Search Index")
    tab.index_current_search_checkbox = QCheckBox("Current only")
    tab.index_current_search_checkbox.setChecked(bool(tab.settings.value("model_library/index_current_search", False, type=bool)))
    tab.index_current_search_checkbox.setToolTip(
        "Rebuilds the local metadata database with only records matching the Search, License, Creator, Exclude creators, and Format fields. "
        "Catalogue pages still need to be read, but cached shard files are reused."
    )
    mirror_layout.addSpacing(4)
    mirror_layout.addWidget(tab.build_index_button)
    mirror_layout.addWidget(tab.index_current_search_checkbox)
    tab.catalogue_status_label = QLabel("")
    tab.catalogue_status_label.setObjectName("HintLabel")
    tab.catalogue_status_label.setWordWrap(True)
    tab.catalogue_status_label.setMinimumWidth(0)
    tab.catalogue_status_label.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
    mirror_layout.addWidget(tab.catalogue_status_label)
    layout.addWidget(mirror_group)

    local_group = tab.local_group = QGroupBox("Local Folders")
    local_layout = QVBoxLayout(local_group)
    local_layout.setContentsMargins(0, 4, 0, 0)
    local_layout.setSpacing(4)
    tab.local_path_edit = QLineEdit()
    tab.local_path_edit.setPlaceholderText("Folder containing local models")
    tab.browse_local_button = _fixed_button("Browse")
    path_row = QHBoxLayout()
    path_row.setSpacing(4)
    path_row.addWidget(tab.local_path_edit, stretch=1)
    path_row.addWidget(tab.browse_local_button)
    local_layout.addLayout(path_row)
    tab.add_local_root_button = QPushButton("Add Folder")
    local_layout.addWidget(tab.add_local_root_button)
    tab.roots_tree = QTreeWidget()
    tab.roots_tree.setColumnCount(1)
    tab.roots_tree.setHeaderLabels(["Folders"])
    tab.roots_tree.setRootIsDecorated(False)
    tab.roots_tree.setUniformRowHeights(True)
    tab.roots_tree.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
    tab.roots_tree.setMinimumHeight(120)
    local_layout.addWidget(tab.roots_tree, stretch=1)
    tab.open_local_root_button = QPushButton("Open Folder")
    tab.remove_local_root_button = QPushButton("Remove")
    root_buttons = QWidget()
    root_buttons_layout = WrappingLayout(root_buttons, columns=2)
    root_buttons_layout.setSpacing(4)
    root_buttons_layout.addWidget(tab.open_local_root_button)
    root_buttons_layout.addWidget(tab.remove_local_root_button)
    local_layout.addWidget(root_buttons)
    layout.addWidget(local_group)
    layout.addStretch(1)

    tab.roots_tree.currentItemChanged.connect(lambda _current, _previous: tab._update_selection_state())
    tab.browse_local_button.clicked.connect(tab.browse_local_folder)
    tab.add_local_root_button.clicked.connect(tab.add_local_root)
    tab.remove_local_root_button.clicked.connect(tab.remove_selected_local_root)
    tab.open_local_root_button.clicked.connect(tab.open_selected_local_root)
    tab.browse_catalogue_dir_button.clicked.connect(tab.browse_catalogue_dir)
    tab.build_index_button.clicked.connect(tab.build_mirror_index)
    tab.index_current_search_checkbox.toggled.connect(
        lambda value: tab.settings.setValue("model_library/index_current_search", bool(value))
    )
    tab.max_shards_spin.valueChanged.connect(lambda value: tab.settings.setValue("model_library/max_shards", value))
    tab.result_limit_spin.valueChanged.connect(lambda value: tab.settings.setValue("model_library/result_limit", value))
    tab.mirror_url_edit.editingFinished.connect(tab._save_mirror_settings)
    tab.mirror_url_edit.textChanged.connect(lambda _value: tab._update_selection_state())
    tab.catalogue_dir_edit.editingFinished.connect(tab._save_mirror_settings)

    scroll = tab._model_library_controls_scroll = QScrollArea()
    scroll.setObjectName("ModelLibraryControlsScroll")
    scroll.setWidgetResizable(True)
    scroll.setFrameShape(QScrollArea.Shape.NoFrame)
    scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
    scroll.setWidget(panel)
    return scroll


def build_results_panel(tab: object) -> QWidget:
    panel = QWidget()
    layout = QVBoxLayout(panel)
    layout.setContentsMargins(0, 0, 0, 0)
    layout.setSpacing(4)

    tab.results_tree = QTreeWidget()
    tab.results_tree.setColumnCount(10)
    tab.results_tree.setHeaderLabels(["", "Name", "Source", "Local", "Textures", "Format", "Size", "License", "Creator", "Location"])
    tab.results_tree.setRootIsDecorated(False)
    tab.results_tree.setAlternatingRowColors(True)
    tab.results_tree.setUniformRowHeights(True)
    tab.results_tree.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
    tab.results_tree.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
    tab.results_tree.setSortingEnabled(False)
    tab.results_tree.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
    tab.results_tree.setHorizontalScrollMode(QAbstractItemView.ScrollMode.ScrollPerPixel)
    header = tab.results_tree.header()
    header.setStretchLastSection(False)
    header.setSectionsClickable(True)
    header.setSortIndicatorShown(True)
    header.setSortIndicator(tab._result_sort_column, tab._result_sort_order)
    header.setMinimumSectionSize(34)
    header.setSectionResizeMode(QHeaderView.ResizeMode.Interactive)
    header.setSectionResizeMode(0, QHeaderView.ResizeMode.Fixed)
    for column, width in enumerate((34, 260, 95, 110, 105, 90, 90, 150, 150, 280)):
        header.resizeSection(column, width)

    tab.results_column_filter_edits: dict[int, QLineEdit] = {}
    for column, label in MODEL_LIBRARY_FILTER_COLUMNS:
        edit = QLineEdit()
        edit.setPlaceholderText(label)
        edit.setClearButtonEnabled(True)
        tab.results_column_filter_edits[column] = edit
    tab.column_filter_row = ModelLibraryColumnFilterRow(tab.results_tree, tab.results_column_filter_edits)

    tab.empty_results_label = QLabel("")
    tab.empty_results_label.setObjectName("HintLabel")
    tab.empty_results_label.setWordWrap(True)
    tab.empty_results_label.setVisible(False)
    layout.addWidget(tab.column_filter_row)
    layout.addWidget(tab.empty_results_label)
    layout.addWidget(tab.results_tree, stretch=1)

    # Checked-row actions; the result counts live in the task row below.
    footer = QWidget()
    footer_layout = WrappingLayout(footer)
    footer_layout.setSpacing(6)
    tab.select_all_button = _fixed_button("All", tooltip="Select All")
    tab.select_none_button = _fixed_button("None", tooltip="Select None")
    tab.download_button = _fixed_button("Download Checked")
    footer_layout.addWidget(tab.select_all_button)
    footer_layout.addWidget(tab.select_none_button)
    footer_layout.addWidget(tab.download_button)
    layout.addWidget(footer)

    tab.results_tree.currentItemChanged.connect(tab._handle_results_current_item_changed)
    tab.results_tree.itemChanged.connect(tab._handle_result_item_changed)
    tab.results_tree.itemDoubleClicked.connect(lambda _item, _column: tab.use_selected_model_in_new_item_studio())
    tab.results_tree.customContextMenuRequested.connect(tab._show_results_context_menu)
    header.sectionClicked.connect(tab._handle_results_header_clicked)
    tab.select_all_button.clicked.connect(lambda _checked=False: tab._set_all_result_checks(True))
    tab.select_none_button.clicked.connect(lambda _checked=False: tab._set_all_result_checks(False))
    tab.download_button.clicked.connect(lambda _checked=False: tab.download_selected_models())
    for edit in tab.results_column_filter_edits.values():
        edit.textChanged.connect(lambda _text="", editor=edit: tab._handle_column_filter_changed(editor))
    return panel


def build_preview_panel(tab: object) -> QWidget:
    """The selection pane: name, preview, actions, and details."""

    panel = QWidget()
    layout = tab._model_library_preview_layout = QVBoxLayout(panel)
    layout.setContentsMargins(0, 0, 0, 0)
    layout.setSpacing(6)

    tab.details_edit = QLineEdit()
    tab.details_edit.setObjectName("ModelLibrarySelectionTitle")
    tab.details_edit.setReadOnly(True)
    tab.details_edit.setFrame(False)
    tab.details_edit.setPlaceholderText("Select a local file or mirror result.")
    tab.details_edit.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
    layout.addWidget(tab.details_edit)

    preview_group = tab.preview_group = QGroupBox()
    preview_group.setProperty("compactStructural", True)
    preview_layout = QVBoxLayout(preview_group)
    preview_layout.setContentsMargins(0, 0, 0, 0)
    preview_layout.setSpacing(4)
    # The inline preview is drawn by the resident Rust Preview host, so these are
    # preparation settings only: no preview widget owns them.
    inline_render_settings = ModelPreviewRenderSettings()
    inline_render_settings.visible_texture_mode = "sidecar_visible_first"
    inline_render_settings.render_diagnostic_mode = "base_direct"
    inline_render_settings.disable_tint = True
    inline_render_settings.disable_brightness = True
    inline_render_settings.disable_all_support_maps = True
    inline_render_settings.disable_normal_map = True
    inline_render_settings.disable_material_map = True
    inline_render_settings.disable_height_map = True
    inline_render_settings.low_quality_texture_max_dimension = 1024
    inline_render_settings.use_textures_by_default = True
    inline_render_settings.high_quality_by_default = True
    tab.inline_preview_render_settings = clamp_model_preview_render_settings(inline_render_settings)
    tab.inline_preview_stack = QStackedWidget()
    tab.inline_d3d11_preview_host = None
    tab.inline_preview_placeholder = QLabel(
        "Select a downloaded or local model to preview it here."
    )
    tab.inline_preview_placeholder.setObjectName("HintLabel")
    tab.inline_preview_placeholder.setAlignment(Qt.AlignCenter)
    tab.inline_preview_placeholder.setWordWrap(True)
    tab.inline_preview_placeholder.setMinimumHeight(180)
    tab.inline_preview_stack.addWidget(tab.inline_preview_placeholder)
    tab.inline_preview_stack.setCurrentWidget(tab.inline_preview_placeholder)
    preview_layout.addWidget(tab.inline_preview_stack, stretch=1)

    preview_controls = QHBoxLayout()
    preview_controls.setContentsMargins(0, 0, 0, 0)
    preview_controls.setSpacing(8)
    tab.auto_preview_checkbox = QCheckBox("Auto-preview")
    tab.auto_preview_checkbox.setToolTip(
        "Automatically previews local selections in the Model Library preview panel."
    )
    tab.auto_preview_checkbox.setChecked(bool(tab.settings.value("model_library/auto_preview", True, type=bool)))
    tab.inline_preview_flip_v_checkbox = QCheckBox("Flip V")
    tab.inline_preview_flip_v_checkbox.setToolTip(
        "Temporarily invert the texture V direction for the current Model Library preview only."
    )
    tab.inline_preview_reset_orientation_button = _fixed_button("Reset")
    tab.inline_preview_reset_orientation_button.setToolTip("Clear temporary Model Library texture orientation overrides.")
    tab.inline_preview_flip_v_checkbox.setEnabled(False)
    tab.inline_preview_reset_orientation_button.setEnabled(False)
    preview_controls.addWidget(tab.auto_preview_checkbox)
    preview_controls.addStretch(1)
    preview_controls.addWidget(tab.inline_preview_flip_v_checkbox)
    preview_controls.addWidget(tab.inline_preview_reset_orientation_button)
    preview_layout.addLayout(preview_controls)
    tab.inline_preview_status_label = _ElidedLabel(
        "Local preview resolves glTF/GLB/OBJ/DAE textures into the shared Preview renderer."
    )
    tab.inline_preview_status_label.setObjectName("HintLabel")
    preview_layout.addWidget(tab.inline_preview_status_label)
    layout.addWidget(preview_group, stretch=3)

    tab.use_in_new_item_studio_button = QPushButton("Use in Create New Item")
    tab.use_in_new_item_studio_button.setObjectName("EditorPrimaryButton")
    tab.use_in_new_item_studio_button.setToolTip("Open this resolved model in Create New Item's model step.")
    tab.preview_button = QPushButton("Preview")
    tab.generate_icon_button = QPushButton("Generate Icon")
    tab.more_actions_button = QPushButton("More")
    tab.more_actions_button.setToolTip("More Actions")
    tab.more_actions_menu = QMenu(tab.more_actions_button)
    tab.download_import_button = tab.more_actions_menu.addAction("Download + Create New Item")
    tab.open_file_url_button = tab.more_actions_menu.addAction("Open File URL")
    tab.open_location_button = tab.more_actions_menu.addAction("Open Location")
    tab.open_page_button = tab.more_actions_menu.addAction("Open Page")
    tab.more_actions_menu.addSeparator()
    tab.delete_local_button = tab.more_actions_menu.addAction("Delete Local")
    tab.delete_no_texture_downloads_button = tab.more_actions_menu.addAction("Delete No-Texture Downloads")
    tab.more_actions_button.setMenu(tab.more_actions_menu)
    layout.addWidget(tab.use_in_new_item_studio_button)
    secondary_actions = QWidget()
    secondary_layout = WrappingLayout(secondary_actions, columns=3)
    secondary_layout.setSpacing(4)
    secondary_layout.addWidget(tab.preview_button)
    secondary_layout.addWidget(tab.generate_icon_button)
    secondary_layout.addWidget(tab.more_actions_button)
    layout.addWidget(secondary_actions)

    selection_group = tab.selection_group = QGroupBox("Details")
    selection_group.setObjectName("ModelLibrarySelectionGroup")
    selection_layout = QVBoxLayout(selection_group)
    selection_layout.setContentsMargins(0, 4, 0, 0)
    selection_layout.setSpacing(4)
    tab.details_text = QPlainTextEdit()
    tab.details_text.setObjectName("ModelLibraryDetailsText")
    tab.details_text.setReadOnly(True)
    tab.details_text.setLineWrapMode(QPlainTextEdit.LineWrapMode.WidgetWidth)
    tab.details_text.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
    tab.details_text.setMinimumHeight(96)
    tab.details_text.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
    selection_layout.addWidget(tab.details_text, stretch=1)
    layout.addWidget(selection_group, stretch=2)

    tab.status_label = QLabel("")
    tab.status_label.setObjectName("HintLabel")
    tab.status_label.setWordWrap(True)
    tab.status_label.setVisible(False)
    layout.addWidget(tab.status_label)

    tab.inline_preview_flip_v_checkbox.toggled.connect(tab._handle_inline_preview_flip_v_toggled)
    tab.inline_preview_reset_orientation_button.clicked.connect(tab._handle_inline_preview_orientation_reset_clicked)
    tab.auto_preview_checkbox.toggled.connect(tab._handle_auto_preview_toggled)
    tab.preview_button.clicked.connect(tab.preview_selected_model_here)
    tab.use_in_new_item_studio_button.clicked.connect(tab.use_selected_model_in_new_item_studio)
    tab.generate_icon_button.clicked.connect(tab.generate_icon_from_preview)
    tab.download_import_button.triggered.connect(lambda _checked=False: tab.download_selected_model(import_after=True))
    tab.open_file_url_button.triggered.connect(tab.open_selected_file_url)
    tab.open_location_button.triggered.connect(tab.open_selected_location)
    tab.open_page_button.triggered.connect(tab.open_selected_page)
    tab.delete_local_button.triggered.connect(tab.delete_selected_local_models)
    tab.delete_no_texture_downloads_button.triggered.connect(tab.delete_no_texture_downloads)
    return panel


def build_task_row(tab: object) -> QWidget:
    """Latest status, with progress and Cancel while a task runs."""

    row = tab.task_row = QFrame()
    row.setObjectName("ModelLibraryTaskRow")
    row.setFrameShape(QFrame.Shape.NoFrame)
    row.setProperty("compactStructural", True)
    layout = QHBoxLayout(row)
    layout.setContentsMargins(0, 0, 0, 0)
    layout.setSpacing(6)
    tab.active_task_progress = QProgressBar()
    tab.active_task_progress.setRange(0, 0)
    tab.active_task_progress.setTextVisible(True)
    tab.active_task_progress.setFormat("Working...")
    tab.active_task_progress.setFixedWidth(160)
    tab.active_task_progress.setVisible(False)
    tab.active_task_label = _ElidedLabel("")
    tab.active_task_label.setObjectName("HintLabel")
    tab.results_status_label = QLabel("")
    tab.results_status_label.setObjectName("HintLabel")
    tab.cancel_task_button = _fixed_button("Cancel")
    tab.cancel_task_button.setEnabled(False)
    tab.cancel_task_button.setVisible(False)
    layout.addWidget(tab.active_task_progress)
    layout.addWidget(tab.active_task_label, stretch=1)
    layout.addWidget(tab.results_status_label)
    layout.addWidget(tab.cancel_task_button)
    tab.cancel_task_button.clicked.connect(tab.cancel_current_task)
    return row


def finish_model_library_layout(tab: object) -> None:
    """Apply tool-local styling and the remembered Sources/Filters state."""

    tab.setStyleSheet(
        tab.styleSheet()
        + "\nQLineEdit#ModelLibrarySelectionTitle {"
        " background: transparent; border: none; padding: 0; font-weight: 600; }"
    )
    tab._set_sources_panel_visible(
        bool(tab.settings.value("model_library/sources_visible", True, type=bool)), persist=False
    )
    tab._set_filters_visible(
        bool(tab.settings.value("model_library/filters_visible", False, type=bool)), persist=False
    )


__all__ = [
    "SOURCES_LANE_MAX_WIDTH",
    "SOURCES_LANE_MIN_WIDTH",
    "ModelLibraryColumnFilterRow",
    "build_command_strip",
    "build_controls_panel",
    "build_filters_strip",
    "build_preview_panel",
    "build_results_panel",
    "build_task_row",
    "finish_model_library_layout",
]
