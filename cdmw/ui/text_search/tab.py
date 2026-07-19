from __future__ import annotations

from pathlib import Path
from typing import List, Optional, Sequence

from PySide6.QtCore import QThread, Qt, QTimer, Signal
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QComboBox,
    QGridLayout,
    QGroupBox,
    QHeaderView,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPlainTextEdit,
    QProgressBar,
    QPushButton,
    QSplitter,
    QSizePolicy,
    QStackedWidget,
    QTreeWidget,
    QVBoxLayout,
    QWidget,
)

from cdmw.services.text_search_service import (
    DEFAULT_TEXT_SEARCH_EXTENSIONS,
    TextSearchResult,
    TextSearchRunStats,
)
from cdmw.services.archive_catalogue_service import ArchiveCatalogueService
from cdmw.models import ArchiveEntry
from cdmw.services.workspace_layout import workspace_paths
from cdmw.ui.text_search.controller import TextSearchControllerMixin, TextSearchSettingsMixin
from cdmw.ui.text_search.export_actions import TextSearchExportMixin
from cdmw.ui.text_search.preview_panel import TextSearchPreviewMixin
from cdmw.ui.text_search.remote_catalogue import TextSearchArchiveCatalogueMixin
from cdmw.ui.text_search.workers import TextSearchExportWorker, TextSearchPreviewWorker, TextSearchWorker
from cdmw.ui.widgets import (
    CodePreviewEditor,
    EmptyStatePanel,
    FlatSectionPanel,
    LogHighlighter,
    build_responsive_splitter_sizes,
    clamp_splitter_sizes,
    has_persistent_tree_column_widths,
    make_tree_columns_persistent,
    responsive_sidebar_bounds,
)


class TextSearchTab(
    TextSearchSettingsMixin,
    TextSearchArchiveCatalogueMixin,
    TextSearchControllerMixin,
    TextSearchExportMixin,
    TextSearchPreviewMixin,
    QWidget,
):
    status_message_requested = Signal(str, bool)
    PREVIEW_DISPLAY_CHAR_LIMIT = 750_000
    SYNTAX_HIGHLIGHT_CHAR_LIMIT = 250_000
    MATCH_HIGHLIGHT_CHAR_LIMIT = 250_000
    AUTO_PREVIEW_RESULT_LIMIT = 4000
    RESULT_POPULATION_BATCH_SIZE = 300

    def resizeEvent(self, event: object) -> None:
        super().resizeEvent(event)  # type: ignore[arg-type]
        if hasattr(self, "_column_autofit_timer"):
            self._column_autofit_timer.start()

    def __init__(
        self,
        *,
        settings,
        base_dir: Path,
        theme_key: str,
        archive_catalogue_service: ArchiveCatalogueService | None = None,
        parent: Optional[QWidget] = None,
    ) -> None:
        super().__init__(parent)
        self.settings = settings
        self.base_dir = base_dir
        self.archive_entries: List[ArchiveEntry] = []
        self.archive_package_root_text = ""
        self.external_busy = False
        self._settings_ready = False
        self.current_theme_key = theme_key
        self.search_thread: Optional[QThread] = None
        self.search_worker: Optional[TextSearchWorker] = None
        self.search_request_id = 0
        self.preview_thread: Optional[QThread] = None
        self.preview_worker: Optional[TextSearchPreviewWorker] = None
        self.preview_request_id = 0
        self.export_thread: Optional[QThread] = None
        self.export_worker: Optional[TextSearchExportWorker] = None
        self.export_request_id = 0
        self.pending_preview_result: Optional[TextSearchResult] = None
        self.scheduled_preview_result: Optional[TextSearchResult] = None
        self.search_results: List[TextSearchResult] = []
        self.current_preview_result: Optional[TextSearchResult] = None
        self._pending_result_indexes: List[int] = []
        self._pending_result_total = 0
        self._pending_auto_preview_enabled = False
        self.last_search_query = ""
        self.last_search_case_sensitive = False
        self.last_search_regex_enabled = False
        self.last_search_stats = TextSearchRunStats(source_kind="archive", candidate_count=0, searched_count=0)
        self.preview_search_spans: List[tuple[int, int]] = []
        self.preview_find_spans: List[tuple[int, int]] = []
        self.preview_find_active_index = -1
        self.preview_text_cache = ""
        self._settings_save_timer = QTimer(self)
        self._settings_save_timer.setSingleShot(True)
        self._settings_save_timer.setInterval(250)
        self._settings_save_timer.timeout.connect(self._save_settings)
        self._preview_debounce_timer = QTimer(self)
        self._preview_debounce_timer.setSingleShot(True)
        self._preview_debounce_timer.setInterval(90)
        self._preview_debounce_timer.timeout.connect(self._flush_scheduled_preview_request)
        self._results_population_timer = QTimer(self)
        self._results_population_timer.setSingleShot(True)
        self._results_population_timer.setInterval(0)
        self._results_population_timer.timeout.connect(self._flush_result_population_batch)
        self._column_autofit_timer = QTimer(self)
        self._column_autofit_timer.setSingleShot(True)
        self._column_autofit_timer.setInterval(80)
        self._column_autofit_timer.timeout.connect(self.auto_fit_columns)

        root_layout = QVBoxLayout(self)
        root_layout.setContentsMargins(10, 10, 10, 10)
        root_layout.setSpacing(10)

        self.main_splitter = QSplitter(Qt.Horizontal)
        self.main_splitter.setChildrenCollapsible(False)
        self.main_splitter.setHandleWidth(8)
        root_layout.addWidget(self.main_splitter, stretch=1)

        controls_group = FlatSectionPanel("Text Search")
        controls_layout = controls_group.body_layout
        controls_layout.setSpacing(8)

        summary_label = QLabel(
            "Read-only search across archive or loose text-like files. Search for strings or regex patterns, preview "
            "the matched file with highlights, and export matches while preserving folder structure."
        )
        summary_label.setWordWrap(True)
        summary_label.setObjectName("HintLabel")
        controls_layout.addWidget(summary_label)

        grid = QGridLayout()
        grid.setHorizontalSpacing(8)
        grid.setVerticalSpacing(8)

        self.source_combo = QComboBox()
        self.source_combo.addItem("Archive files", "archive")
        self.source_combo.addItem("Loose folder", "loose")

        self.query_edit = QLineEdit()
        self.query_edit.setPlaceholderText("Search string or regex, e.g. material or <Texture")
        self.path_filter_edit = QLineEdit()
        self.path_filter_edit.setPlaceholderText("Optional path filter, e.g. object/ or *.xml naming fragment")
        self.extensions_edit = QLineEdit(DEFAULT_TEXT_SEARCH_EXTENSIONS)
        self.extensions_edit.setPlaceholderText(".xml;.txt;.json")
        self.case_sensitive_checkbox = QCheckBox("Case sensitive")
        self.regex_checkbox = QCheckBox("Regex")

        self.loose_root_edit = QLineEdit()
        self.loose_root_edit.setPlaceholderText("Loose root folder for non-archive text search")
        self.loose_root_browse_button = QPushButton("Browse")

        self.export_root_edit = QLineEdit(str(workspace_paths(base_dir)["text_search_export_root"].resolve()))
        self.export_root_browse_button = QPushButton("Browse")

        grid.addWidget(QLabel("Source"), 0, 0)
        grid.addWidget(self.source_combo, 0, 1)
        grid.addWidget(QLabel("Extensions"), 0, 2)
        grid.addWidget(self.extensions_edit, 0, 3)

        grid.addWidget(QLabel("Search"), 1, 0)
        grid.addWidget(self.query_edit, 1, 1, 1, 3)

        grid.addWidget(QLabel("Path filter"), 2, 0)
        grid.addWidget(self.path_filter_edit, 2, 1, 1, 3)

        self.loose_root_label = QLabel("Loose root")
        grid.addWidget(self.loose_root_label, 3, 0)
        grid.addWidget(self.loose_root_edit, 3, 1, 1, 2)
        grid.addWidget(self.loose_root_browse_button, 3, 3)

        grid.addWidget(QLabel("Export root"), 4, 0)
        grid.addWidget(self.export_root_edit, 4, 1, 1, 2)
        grid.addWidget(self.export_root_browse_button, 4, 3)

        option_row = QHBoxLayout()
        option_row.setSpacing(8)
        option_row.addWidget(self.case_sensitive_checkbox)
        option_row.addWidget(self.regex_checkbox)
        option_row.addStretch(1)
        grid.addLayout(option_row, 5, 1, 1, 3)

        grid.setColumnStretch(1, 1)
        grid.setColumnStretch(2, 0)
        grid.setColumnStretch(3, 1)
        controls_layout.addLayout(grid)

        button_row = QGridLayout()
        button_row.setHorizontalSpacing(8)
        button_row.setVerticalSpacing(8)
        self.search_button = QPushButton("Search")
        self.stop_button = QPushButton("Stop")
        self.stop_button.setEnabled(False)
        self.export_selected_button = QPushButton("Export Selected")
        self.export_all_button = QPushButton("Export Results")
        self.clear_log_button = QPushButton("Clear Log")
        for button in (
            self.search_button,
            self.stop_button,
            self.export_selected_button,
            self.export_all_button,
            self.clear_log_button,
        ):
            button.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        button_row.addWidget(self.search_button, 0, 0)
        button_row.addWidget(self.stop_button, 0, 1)
        button_row.addWidget(self.export_selected_button, 0, 2)
        button_row.addWidget(self.export_all_button, 1, 0, 1, 2)
        button_row.addWidget(self.clear_log_button, 1, 2)
        controls_layout.addLayout(button_row)

        self.results_summary_label = QLabel("No text search has been run yet.")
        self.results_summary_label.setObjectName("HintLabel")
        self.search_progress_label = QLabel("Ready.")
        self.search_progress_label.setObjectName("HintLabel")
        self.search_progress_bar = QProgressBar()
        self.search_progress_bar.setRange(0, 1)
        self.search_progress_bar.setValue(0)
        self.search_progress_bar.setFormat("Ready")
        controls_layout.addWidget(self.results_summary_label)
        controls_layout.addWidget(self.search_progress_label)
        controls_layout.addWidget(self.search_progress_bar)
        controls_layout.addSpacing(8)
        log_group = FlatSectionPanel("Search Log")
        log_layout = log_group.body_layout
        log_layout.setSpacing(8)
        self.log_view = QPlainTextEdit()
        self.log_view.setReadOnly(True)
        self.log_view.document().setMaximumBlockCount(5000)
        log_layout.addWidget(self.log_view)
        controls_layout.addWidget(log_group, stretch=1)
        self.main_splitter.addWidget(controls_group)

        results_group = FlatSectionPanel("Results")
        results_layout = results_group.body_layout
        results_layout.setSpacing(8)
        self.results_tree = QTreeWidget()
        self.results_tree.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self.results_tree.setAlternatingRowColors(True)
        self.results_tree.setRootIsDecorated(False)
        self.results_tree.setUniformRowHeights(True)
        self.results_tree.setHeaderLabels(["File Name", "Matches", "Package", "Path", "Ext"])
        self.results_tree.header().setStretchLastSection(False)
        self.results_tree.header().setSectionResizeMode(0, QHeaderView.Interactive)
        self.results_tree.header().setSectionResizeMode(1, QHeaderView.ResizeToContents)
        self.results_tree.header().setSectionResizeMode(2, QHeaderView.ResizeToContents)
        self.results_tree.header().setSectionResizeMode(3, QHeaderView.Stretch)
        self.results_tree.header().setSectionResizeMode(4, QHeaderView.ResizeToContents)
        self.results_tree.header().resizeSection(0, 260)
        self.results_tree.header().resizeSection(3, 360)
        make_tree_columns_persistent(
            self.results_tree,
            self.settings,
            "text_search/results",
            minimum_width=56,
            save_callback=self.schedule_settings_save,
        )
        self.results_stack = QStackedWidget()
        self.results_empty_state = EmptyStatePanel(
            "Ready to search",
            "Enter a string or regex, then run Search. Matching files will appear here with package and path context.",
        )
        self.results_stack.addWidget(self.results_empty_state)
        self.results_stack.addWidget(self.results_tree)
        results_layout.addWidget(self.results_stack, stretch=1)
        self.main_splitter.addWidget(results_group)

        preview_group = FlatSectionPanel("Preview")
        preview_layout = preview_group.body_layout
        preview_layout.setSpacing(8)
        self.preview_title_label = QLabel("Select a matching file")
        self.preview_title_label.setWordWrap(True)
        self.preview_meta_label = QLabel("Matched files will be previewed here with highlights.")
        self.preview_meta_label.setObjectName("HintLabel")
        self.preview_meta_label.setWordWrap(True)
        self.preview_detail_label = QLabel("")
        self.preview_detail_label.setObjectName("HintLabel")
        self.preview_detail_label.setWordWrap(True)
        preview_toolbar = QVBoxLayout()
        preview_toolbar.setSpacing(6)
        preview_search_row = QHBoxLayout()
        preview_search_row.setSpacing(8)
        preview_options_row = QHBoxLayout()
        preview_options_row.setSpacing(8)
        self.preview_find_edit = QLineEdit()
        self.preview_find_edit.setPlaceholderText("Find in preview")
        self.preview_find_prev_button = QPushButton("Prev")
        self.preview_find_next_button = QPushButton("Next")
        self.preview_find_case_checkbox = QCheckBox("Aa")
        self.preview_find_case_checkbox.setToolTip("Case-sensitive preview search")
        self.preview_wrap_checkbox = QCheckBox("Wrap")
        self.preview_wrap_checkbox.setToolTip("Wrap long lines in the preview editor")
        self.preview_font_smaller_button = QPushButton("A-")
        self.preview_font_larger_button = QPushButton("A+")
        self.preview_find_status_label = QLabel("No preview loaded.")
        self.preview_find_status_label.setObjectName("HintLabel")
        self.preview_find_status_label.setWordWrap(True)
        for button in (
            self.preview_find_prev_button,
            self.preview_find_next_button,
            self.preview_font_smaller_button,
            self.preview_font_larger_button,
        ):
            button.setMinimumWidth(42)
        preview_search_row.addWidget(self.preview_find_edit, stretch=1)
        preview_search_row.addWidget(self.preview_find_prev_button)
        preview_search_row.addWidget(self.preview_find_next_button)
        preview_options_row.addWidget(self.preview_find_case_checkbox)
        preview_options_row.addWidget(self.preview_wrap_checkbox)
        preview_options_row.addWidget(self.preview_font_smaller_button)
        preview_options_row.addWidget(self.preview_font_larger_button)
        preview_options_row.addWidget(self.preview_find_status_label, stretch=1)
        preview_toolbar.addLayout(preview_search_row)
        preview_toolbar.addLayout(preview_options_row)
        self.preview_text_edit = CodePreviewEditor(theme_key=theme_key)
        preview_layout.addWidget(self.preview_title_label)
        preview_layout.addWidget(self.preview_meta_label)
        preview_layout.addWidget(self.preview_detail_label)
        preview_layout.addLayout(preview_toolbar)
        preview_layout.addWidget(self.preview_text_edit, stretch=1)
        self.main_splitter.addWidget(preview_group)
        controls_min, _controls_pref, controls_max = responsive_sidebar_bounds(self, role="wide")
        results_min, _results_pref, _results_max = responsive_sidebar_bounds(self, role="narrow")
        preview_min, _preview_pref, _preview_max = responsive_sidebar_bounds(self, role="wide")
        controls_group.setMinimumWidth(controls_min)
        controls_group.setMaximumWidth(controls_max)
        results_group.setMinimumWidth(results_min)
        preview_group.setMinimumWidth(preview_min)
        self.main_splitter.setStretchFactor(0, 2)
        self.main_splitter.setStretchFactor(1, 2)
        self.main_splitter.setStretchFactor(2, 4)
        self.main_splitter.setSizes(
            build_responsive_splitter_sizes(1670, [24, 24, 52], [controls_min, results_min, preview_min])
        )
        self._column_autofit_timer.start()

        self.log_highlighter = LogHighlighter(self.log_view.document(), theme_key)
        log_font = QFont(self.font())
        log_font.setStyleHint(QFont.StyleHint.Monospace)
        inherited_size = self.font().pointSize()
        if inherited_size > 0:
            log_font.setPointSize(inherited_size)
        self.log_view.setFont(log_font)

        self.loose_root_browse_button.clicked.connect(self._browse_loose_root)
        self.export_root_browse_button.clicked.connect(self._browse_export_root)
        self.search_button.clicked.connect(self.start_search)
        self.stop_button.clicked.connect(self.stop_search)
        self.export_selected_button.clicked.connect(self.export_selected_results)
        self.export_all_button.clicked.connect(self.export_all_results)
        self.clear_log_button.clicked.connect(self.clear_log)
        self.results_tree.currentItemChanged.connect(self._handle_result_selection_changed)
        self.query_edit.returnPressed.connect(self.start_search)
        self.path_filter_edit.returnPressed.connect(self.start_search)
        self.source_combo.currentIndexChanged.connect(self._handle_source_changed)
        self.preview_find_edit.textChanged.connect(self._handle_preview_find_changed)
        self.preview_find_edit.returnPressed.connect(self._jump_to_next_preview_find_match)
        self.preview_find_prev_button.clicked.connect(self._jump_to_previous_preview_find_match)
        self.preview_find_next_button.clicked.connect(self._jump_to_next_preview_find_match)
        self.preview_find_case_checkbox.toggled.connect(self._handle_preview_find_changed)
        self.preview_wrap_checkbox.toggled.connect(self._handle_preview_wrap_changed)
        self.preview_font_smaller_button.clicked.connect(lambda: self._adjust_preview_font(-1))
        self.preview_font_larger_button.clicked.connect(lambda: self._adjust_preview_font(1))

        for widget in (
            self.query_edit,
            self.path_filter_edit,
            self.extensions_edit,
            self.loose_root_edit,
            self.export_root_edit,
            self.preview_find_edit,
        ):
            widget.textChanged.connect(self.schedule_settings_save)
        self.source_combo.currentIndexChanged.connect(self.schedule_settings_save)
        self.case_sensitive_checkbox.toggled.connect(self.schedule_settings_save)
        self.regex_checkbox.toggled.connect(self.schedule_settings_save)
        self.preview_wrap_checkbox.toggled.connect(self.schedule_settings_save)
        self.preview_find_case_checkbox.toggled.connect(self.schedule_settings_save)

        self._initialize_archive_catalogue(archive_catalogue_service)
        self._load_settings()
        self._settings_ready = True
        self._apply_source_state()
        self._update_controls()

    def set_theme(self, theme_key: str) -> None:
        self.current_theme_key = theme_key
        self.log_highlighter.set_theme(theme_key)
        self.preview_text_edit.set_theme(theme_key)
        self._refresh_preview_selections(focus_current=False)

    def set_splitter_sizes(self, sizes: Sequence[int]) -> None:
        if sizes:
            controls_min, _controls_pref, _controls_max = responsive_sidebar_bounds(self, role="wide")
            results_min, _results_pref, _results_max = responsive_sidebar_bounds(self, role="narrow")
            preview_min, _preview_pref, _preview_max = responsive_sidebar_bounds(self, role="wide")
            total_width = max(self.width() - 32, sum([controls_min, results_min, preview_min]))
            self.main_splitter.setSizes(
                clamp_splitter_sizes(
                    total_width,
                    sizes,
                    [controls_min, results_min, preview_min],
                    fallback_weights=[24, 24, 52],
                )
            )

    def splitter_sizes(self) -> List[int]:
        return self.main_splitter.sizes()

    def apply_responsive_splitter_sizes(self, total_width: Optional[int] = None) -> None:
        controls_min, _controls_pref, _controls_max = responsive_sidebar_bounds(self, role="wide")
        results_min, _results_pref, _results_max = responsive_sidebar_bounds(self, role="narrow")
        preview_min, _preview_pref, _preview_max = responsive_sidebar_bounds(self, role="wide")
        available_width = total_width or max(self.width() - 32, sum([controls_min, results_min, preview_min]))
        self.main_splitter.setSizes(
            build_responsive_splitter_sizes(available_width, [24, 24, 52], [controls_min, results_min, preview_min])
        )
        self._column_autofit_timer.start()

    def auto_fit_columns(self) -> None:
        header = self.results_tree.header()
        if header is None or self.results_tree.columnCount() <= 0:
            return
        header.setStretchLastSection(False)
        viewport_width = max(self.results_tree.viewport().width(), self.results_tree.width() - 24, 0)
        if viewport_width <= 0:
            return
        if has_persistent_tree_column_widths(self.settings, "text_search/results", self.results_tree.columnCount(), minimum_width=56):
            saved_total = sum(
                header.sectionSize(column)
                for column in range(self.results_tree.columnCount())
                if not self.results_tree.isColumnHidden(column)
            )
            if saved_total >= viewport_width - 24:
                return
        minimums = {
            0: 220,
            1: 74,
            2: 96,
            3: 280,
            4: 60,
        }
        self.results_tree.setUpdatesEnabled(False)
        try:
            for column in (1, 2, 4):
                self.results_tree.resizeColumnToContents(column)
                header.resizeSection(column, max(minimums[column], header.sectionSize(column)))
            reserved = sum(header.sectionSize(column) for column in (1, 2, 4))
            remaining = max(0, viewport_width - reserved - 12)
            file_width = max(minimums[0], int(remaining * 0.38))
            path_width = max(minimums[3], remaining - file_width)
            header.resizeSection(0, file_width)
            header.resizeSection(3, path_width)
        finally:
            self.results_tree.setUpdatesEnabled(True)
