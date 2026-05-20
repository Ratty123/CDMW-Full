from __future__ import annotations

import json
import os
import re
import shutil
import threading
import time
import zipfile
from collections import defaultdict
from pathlib import Path
from pathlib import PurePosixPath
from typing import Callable, Optional

from PySide6.QtCore import QObject, QProcess, QSettings, Qt, QThread, QTimer, QUrl, Signal, Slot
from PySide6.QtGui import QDesktopServices, QImage
from PySide6.QtWidgets import (
    QAbstractItemView,
    QButtonGroup,
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QFormLayout,
    QGridLayout,
    QGroupBox,
    QHeaderView,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMenu,
    QMessageBox,
    QPlainTextEdit,
    QProgressBar,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QSpinBox,
    QStackedWidget,
    QSplitter,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from cdmw.core.archive_modding import (
    SCENE_TEXTURE_SOURCE_EXTENSIONS,
    attach_scene_preview_textures,
    import_scene_mesh_with_report,
    parsed_mesh_to_preview_model,
)
from cdmw.core.model_catalogue import (
    DEFAULT_MODEL_MIRROR_URL,
    IMPORTABLE_MODEL_EXTENSIONS,
    MirrorDownloadCandidate,
    MirrorDownloadResult,
    build_mirror_catalogue_index,
    catalogue_stats,
    download_mirror_model_candidate,
    is_importable_model_path,
    mirror_download_candidates,
    normalize_mirror_base_url,
    resolve_importable_model_path,
    scan_local_model_files,
    search_catalogue_records,
    zip_contains_importable_model,
)
from cdmw.rendering.model_preview_prepare import prepare_model_preview
from cdmw.models import ModelPreviewData, ModelPreviewMesh
from cdmw.modding.scene_importer import SceneImportResult
from cdmw.rendering.material_channels import resolve_preview_batch_material_channels
from cdmw.rendering.native_preview_package import write_isolated_d3d11_preview_package
from cdmw.ui.native_d3d11_preview_host import NativeD3D11PreviewHostFrame, native_d3d11_renderer_command
from cdmw.ui.themes import get_theme
from cdmw.ui.widgets import responsive_sidebar_bounds
from cdmw.ui.widgets import NativePreviewPanel


class _ModelLibraryTaskWorker(QObject):
    completed = Signal(object)
    error = Signal(str)
    finished = Signal()
    progress = Signal(str)

    def __init__(self, task: Callable[[Callable[[str], None]], object]) -> None:
        super().__init__()
        self.task = task

    @Slot()
    def run(self) -> None:
        try:
            self.completed.emit(self.task(lambda message: self.progress.emit(str(message))))
        except Exception as exc:
            self.error.emit(str(exc))
        finally:
            self.finished.emit()


class ModelLibraryTab(QWidget):
    status_message_requested = Signal(str, bool)
    import_mesh_requested = Signal(str, object)
    preview_mesh_requested = Signal(str, object)
    item_icon_source_generated = Signal(str, object)
    RESULTS_FILTER_DEBOUNCE_MS = 140
    RESULTS_POPULATION_BATCH_SIZE = 200

    def __init__(
        self,
        *,
        settings: QSettings,
        base_dir: Path,
        theme_key: str = "graphite",
        parent: Optional[QWidget] = None,
    ) -> None:
        super().__init__(parent)
        self.settings = settings
        self.base_dir = Path(base_dir)
        self.theme_key = str(theme_key or "graphite")
        self.local_models: list[dict[str, object]] = []
        self.mirror_results: list[dict[str, object]] = []
        self._result_payloads_by_item: dict[int, dict[str, object]] = {}
        self._texture_status_cache: dict[tuple[str, str], int] = {}
        self._last_hidden_downloaded_count = 0
        self._active_results_view = "mirror"
        self._inline_preview_request_id = 0
        self._inline_preview_loaded_import_path: Optional[Path] = None
        self._inline_preview_loaded_payload: Optional[dict[str, object]] = None
        self._inline_d3d11_process: Optional[QProcess] = None
        self._inline_d3d11_active_package: Optional[Path] = None
        self._inline_d3d11_status_file: Optional[Path] = None
        self._inline_d3d11_status_mtime = 0.0
        self._inline_preview_loaded_texture_count = 0
        self._inline_preview_loaded_renderer_backend = ""
        self._pending_icon_generation_request_id = 0
        self._task_status_active = False
        self._result_sort_column = int(self.settings.value("model_library/result_sort_column", 1) or 1)
        self._result_sort_order = (
            Qt.SortOrder.DescendingOrder
            if str(self.settings.value("model_library/result_sort_order", "asc") or "asc") == "desc"
            else Qt.SortOrder.AscendingOrder
        )
        self._task_thread: Optional[QThread] = None
        self._task_worker: Optional[_ModelLibraryTaskWorker] = None
        self._task_complete_handler: Optional[Callable[[object], None]] = None
        self._task_error_handler: Optional[Callable[[str], None]] = None
        self._stop_event: Optional[threading.Event] = None
        self._auto_preview_timer = QTimer(self)
        self._auto_preview_timer.setSingleShot(True)
        self._auto_preview_timer.setInterval(350)
        self._auto_preview_timer.timeout.connect(self._preview_current_model_if_auto_enabled)
        self._results_filter_timer = QTimer(self)
        self._results_filter_timer.setSingleShot(True)
        self._results_filter_timer.setInterval(self.RESULTS_FILTER_DEBOUNCE_MS)
        self._results_filter_timer.timeout.connect(self._flush_debounced_results_filter)
        self._results_population_timer = QTimer(self)
        self._results_population_timer.setSingleShot(True)
        self._results_population_timer.setInterval(0)
        self._results_population_timer.timeout.connect(self._flush_results_population_batch)
        self._pending_results_rows: list[dict[str, object]] = []
        self._pending_results_total_count = 0
        self._pending_results_visible_count = 0
        self._pending_results_selected_payload: Optional[dict[str, object]] = None
        self._populating_results = False
        self._activation_preview_timer = QTimer(self)
        self._activation_preview_timer.setSingleShot(True)
        self._activation_preview_timer.setInterval(90)
        self._activation_preview_timer.timeout.connect(self._schedule_auto_inline_preview)
        self._inline_d3d11_status_timer = QTimer(self)
        self._inline_d3d11_status_timer.setInterval(200)
        self._inline_d3d11_status_timer.timeout.connect(self._poll_inline_d3d11_status)

        root_layout = QVBoxLayout(self)
        root_layout.setContentsMargins(10, 10, 10, 10)
        root_layout.setSpacing(8)

        header = QLabel("Model Library")
        header.setObjectName("SectionTitle")
        root_layout.addWidget(header)

        splitter = QSplitter(Qt.Orientation.Horizontal)
        splitter.setChildrenCollapsible(False)
        splitter.setHandleWidth(8)
        root_layout.addWidget(splitter, stretch=1)

        controls_panel = self._build_controls_panel()
        results_panel = self._build_results_panel()
        preview_panel = self._build_preview_panel()
        splitter.addWidget(controls_panel)
        splitter.addWidget(results_panel)
        splitter.addWidget(preview_panel)

        controls_min, _controls_pref, controls_max = responsive_sidebar_bounds(self, role="wide")
        preview_min, _preview_pref, _preview_max = responsive_sidebar_bounds(self, role="wide")
        controls_panel.setMinimumWidth(controls_min)
        controls_panel.setMaximumWidth(max(controls_max, 430))
        preview_panel.setMinimumWidth(preview_min)
        splitter.setStretchFactor(0, 0)
        splitter.setStretchFactor(1, 1)
        splitter.setStretchFactor(2, 1)
        splitter.setSizes([max(controls_min, 380), 760, preview_min])

        self._load_settings()
        self._refresh_roots_tree()
        self._update_catalogue_status()
        initial_results_loaded = self._load_initial_results_view()
        self._update_selection_state()
        if not initial_results_loaded:
            self._set_status("Choose Mirror Catalogue or Local Library. Use Refresh to reload the active view.")

    def _build_controls_panel(self) -> QWidget:
        panel = QWidget()
        panel.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Minimum)
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)

        self._updating_results_query = False
        local_group = QGroupBox("Local Folders")
        self.local_group = local_group
        local_layout = QVBoxLayout(local_group)
        local_layout.setContentsMargins(8, 8, 8, 8)
        local_layout.setSpacing(6)
        path_row = QHBoxLayout()
        self.local_path_edit = QLineEdit()
        self.local_path_edit.setPlaceholderText("Folder containing local models")
        self.browse_local_button = QPushButton("Browse")
        path_row.addWidget(self.local_path_edit, stretch=1)
        path_row.addWidget(self.browse_local_button)
        local_layout.addLayout(path_row)
        local_buttons = QGridLayout()
        self.add_local_root_button = QPushButton("Add Folder")
        self.remove_local_root_button = QPushButton("Remove")
        self.scan_local_button = QPushButton("Show Local Models")
        self.open_local_root_button = QPushButton("Open Folder")
        local_buttons.addWidget(self.add_local_root_button, 0, 0)
        local_buttons.addWidget(self.remove_local_root_button, 0, 1)
        local_buttons.addWidget(self.scan_local_button, 1, 0)
        local_buttons.addWidget(self.open_local_root_button, 1, 1)
        local_layout.addLayout(local_buttons)
        self.roots_tree = QTreeWidget()
        self.roots_tree.setColumnCount(1)
        self.roots_tree.setHeaderLabels(["Folders"])
        self.roots_tree.setRootIsDecorated(False)
        self.roots_tree.setUniformRowHeights(True)
        self.roots_tree.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.roots_tree.setMaximumHeight(120)
        local_layout.addWidget(self.roots_tree)
        self.roots_tree.currentItemChanged.connect(lambda _current, _previous: self._update_selection_state())
        layout.addWidget(local_group)

        mirror_group = QGroupBox("Mirror Index Source")
        self.mirror_group = mirror_group
        mirror_layout = QVBoxLayout(mirror_group)
        mirror_layout.setContentsMargins(8, 8, 8, 8)
        mirror_layout.setSpacing(6)
        mirror_form = QFormLayout()
        mirror_form.setContentsMargins(0, 0, 0, 0)
        mirror_form.setHorizontalSpacing(8)
        mirror_form.setVerticalSpacing(6)
        self.mirror_url_edit = QLineEdit()
        self.mirror_url_edit.setPlaceholderText(DEFAULT_MODEL_MIRROR_URL)
        mirror_form.addRow("Mirror URL", self.mirror_url_edit)
        catalogue_dir_row = QHBoxLayout()
        self.catalogue_dir_edit = QLineEdit()
        self.catalogue_dir_edit.setPlaceholderText("Local catalogue folder")
        self.browse_catalogue_dir_button = QPushButton("Browse")
        catalogue_dir_row.addWidget(self.catalogue_dir_edit, stretch=1)
        catalogue_dir_row.addWidget(self.browse_catalogue_dir_button)
        mirror_form.addRow("Catalogue", catalogue_dir_row)
        self.max_shards_spin = QSpinBox()
        self.max_shards_spin.setRange(0, 100_000)
        self.max_shards_spin.setSpecialValueText("All")
        self.max_shards_spin.setValue(int(self.settings.value("model_library/max_shards", 1000) or 1000))
        self.max_shards_spin.setKeyboardTracking(False)
        mirror_form.addRow("Index pages", self.max_shards_spin)
        self.result_limit_spin = QSpinBox()
        self.result_limit_spin.setRange(1, 5000)
        self.result_limit_spin.setValue(int(self.settings.value("model_library/result_limit", 100) or 100))
        self.result_limit_spin.setKeyboardTracking(False)
        mirror_form.addRow("Results", self.result_limit_spin)
        preferred_files_layout = QGridLayout()
        preferred_files_layout.setContentsMargins(0, 0, 0, 0)
        preferred_files_layout.setHorizontalSpacing(8)
        preferred_files_layout.setVerticalSpacing(4)
        self.preferred_format_checks: dict[str, QCheckBox] = {}
        preferred_file_options = (
            ("gltf", "glTF ZIP"),
            ("glb", "GLB"),
            ("source", "Original source ZIP (OBJ/FBX/etc.)"),
            ("extra", "Extra ZIP"),
        )
        selected_preferred_files = set(self._settings_string_list("model_library/preferred_formats_json", default=("gltf",)))
        if not selected_preferred_files:
            selected_preferred_files = {"gltf"}
        for option_index, (format_key, label) in enumerate(preferred_file_options):
            checkbox = QCheckBox(label)
            checkbox.setChecked(format_key in selected_preferred_files)
            checkbox.toggled.connect(lambda _checked=False: self._save_preferred_format_settings())
            self.preferred_format_checks[format_key] = checkbox
            preferred_files_layout.addWidget(checkbox, option_index // 2, option_index % 2)
        mirror_form.addRow("Preferred files", preferred_files_layout)
        mirror_layout.addLayout(mirror_form)
        build_buttons = QGridLayout()
        self.build_index_button = QPushButton("Build Search Index")
        self.cancel_task_button = QPushButton("Cancel")
        self.cancel_task_button.setEnabled(False)
        build_buttons.addWidget(self.build_index_button, 0, 0)
        build_buttons.addWidget(self.cancel_task_button, 0, 1)
        mirror_layout.addLayout(build_buttons)
        self.index_current_search_checkbox = QCheckBox("Build index from current search/filter only")
        self.index_current_search_checkbox.setChecked(bool(self.settings.value("model_library/index_current_search", False, type=bool)))
        self.index_current_search_checkbox.setToolTip(
            "Rebuilds the local metadata database with only records matching the Search, License, Creator, Exclude creators, and Format fields. "
            "Catalogue pages still need to be read, but cached shard files are reused."
        )
        mirror_layout.addWidget(self.index_current_search_checkbox)
        self.task_status_label = QLabel("Mirror catalogue is idle.")
        self.task_status_label.setObjectName("HintLabel")
        self.task_status_label.setWordWrap(True)
        mirror_layout.addWidget(self.task_status_label)
        self.search_edit = QLineEdit()
        self.search_edit.setPlaceholderText("Search by name, tag, creator, or UID")
        self.search_edit.setText(str(self.settings.value("model_library/search_query", "sword") or "sword"))
        filter_form = QFormLayout()
        filter_form.setContentsMargins(0, 0, 0, 0)
        filter_form.setHorizontalSpacing(8)
        filter_form.setVerticalSpacing(6)
        self.license_filter_edit = QLineEdit()
        self.license_filter_edit.setPlaceholderText("CC0, Attribution, NonCommercial")
        self.creator_filter_edit = QLineEdit()
        self.creator_filter_edit.setPlaceholderText("Creator name")
        self.creator_exclude_edit = QLineEdit()
        self.creator_exclude_edit.setPlaceholderText("Creator names/usernames, comma separated")
        self.format_filter_combo = QComboBox()
        self.format_filter_combo.addItem("Any format", "")
        self.format_filter_combo.addItem("glTF ZIP", "gltf")
        self.format_filter_combo.addItem("GLB", "glb")
        self.format_filter_combo.addItem("Original source", "source")
        filter_form.addRow("License", self.license_filter_edit)
        filter_form.addRow("Creator", self.creator_filter_edit)
        filter_form.addRow("Exclude creators", self.creator_exclude_edit)
        filter_form.addRow("Format", self.format_filter_combo)
        mirror_layout.addLayout(filter_form)
        self.hide_downloaded_checkbox = QCheckBox("Hide downloaded")
        self.hide_downloaded_checkbox.setChecked(bool(self.settings.value("model_library/hide_downloaded", False, type=bool)))
        mirror_layout.addWidget(self.hide_downloaded_checkbox)
        search_buttons = QGridLayout()
        self.search_mirror_button = QPushButton("Search Mirror")
        self.show_indexed_button = QPushButton("Popular")
        search_buttons.addWidget(self.search_mirror_button, 0, 0)
        search_buttons.addWidget(self.show_indexed_button, 0, 1)
        mirror_layout.addLayout(search_buttons)
        self.catalogue_status_label = QLabel("")
        self.catalogue_status_label.setObjectName("HintLabel")
        self.catalogue_status_label.setWordWrap(True)
        mirror_layout.addWidget(self.catalogue_status_label)
        layout.addWidget(mirror_group)

        actions_group = QGroupBox("Actions")
        actions_layout = QGridLayout(actions_group)
        actions_layout.setContentsMargins(8, 8, 8, 8)
        actions_layout.setSpacing(6)
        self.preview_button = QPushButton("Preview")
        self.import_mesh_button = QPushButton("Import Mesh")
        self.import_mesh_button.setToolTip("Replaces the mesh currently selected in Archive Browser.")
        self.download_button = QPushButton("Download Checked")
        self.generate_icon_button = QPushButton("Generate Icon")
        self.more_actions_button = QPushButton("More Actions")
        self.more_actions_menu = QMenu(self.more_actions_button)
        self.download_import_button = self.more_actions_menu.addAction("Download + Import")
        self.delete_local_button = self.more_actions_menu.addAction("Delete Local")
        self.open_file_url_button = self.more_actions_menu.addAction("Open File URL")
        self.open_location_button = self.more_actions_menu.addAction("Open Location")
        self.open_page_button = self.more_actions_menu.addAction("Open Page")
        self.more_actions_button.setMenu(self.more_actions_menu)
        actions_layout.addWidget(self.preview_button, 0, 0)
        actions_layout.addWidget(self.import_mesh_button, 0, 1)
        actions_layout.addWidget(self.download_button, 1, 0)
        actions_layout.addWidget(self.generate_icon_button, 1, 1)
        actions_layout.addWidget(self.more_actions_button, 2, 0, 1, 2)
        self.auto_preview_checkbox = QCheckBox("Auto preview local selection")
        self.auto_preview_checkbox.setChecked(bool(self.settings.value("model_library/auto_preview", True, type=bool)))
        actions_layout.addWidget(self.auto_preview_checkbox, 3, 0, 1, 2)
        layout.addWidget(actions_group)

        selection_group = QGroupBox("Selection")
        selection_layout = QVBoxLayout(selection_group)
        selection_layout.setContentsMargins(8, 8, 8, 8)
        selection_layout.setSpacing(6)
        self.details_edit = QLineEdit()
        self.details_edit.setReadOnly(True)
        self.details_edit.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        selection_layout.addWidget(self.details_edit)
        self.details_text = QLabel("")
        self.details_text.setObjectName("HintLabel")
        self.details_text.setWordWrap(True)
        self.details_text.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self.details_text.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        selection_layout.addWidget(self.details_text)
        layout.addWidget(selection_group)

        layout.addStretch(1)

        self.browse_local_button.clicked.connect(self.browse_local_folder)
        self.add_local_root_button.clicked.connect(self.add_local_root)
        self.remove_local_root_button.clicked.connect(self.remove_selected_local_root)
        self.scan_local_button.clicked.connect(self.scan_local_roots)
        self.open_local_root_button.clicked.connect(self.open_selected_local_root)
        self.browse_catalogue_dir_button.clicked.connect(self.browse_catalogue_dir)
        self.build_index_button.clicked.connect(self.build_mirror_index)
        self.cancel_task_button.clicked.connect(self.cancel_current_task)
        self.search_mirror_button.clicked.connect(self.search_mirror)
        self.show_indexed_button.clicked.connect(lambda _checked=False: self.search_mirror(query_override=""))
        self.search_edit.returnPressed.connect(self._apply_active_results_query)
        self.search_edit.textChanged.connect(self._handle_results_query_changed)
        self.hide_downloaded_checkbox.toggled.connect(self._handle_hide_downloaded_toggled)
        self.index_current_search_checkbox.toggled.connect(lambda value: self.settings.setValue("model_library/index_current_search", bool(value)))
        self.max_shards_spin.valueChanged.connect(lambda value: self.settings.setValue("model_library/max_shards", value))
        self.result_limit_spin.valueChanged.connect(lambda value: self.settings.setValue("model_library/result_limit", value))
        self.mirror_url_edit.editingFinished.connect(self._save_mirror_settings)
        self.mirror_url_edit.textChanged.connect(lambda _value: self._update_selection_state())
        self.catalogue_dir_edit.editingFinished.connect(self._save_mirror_settings)
        self.preview_button.clicked.connect(self.preview_selected_model_here)
        self.auto_preview_checkbox.toggled.connect(self._handle_auto_preview_toggled)
        self.import_mesh_button.clicked.connect(self.import_selected_model)
        self.download_button.clicked.connect(lambda _checked=False: self.download_selected_models())
        self.download_import_button.triggered.connect(lambda _checked=False: self.download_selected_model(import_after=True))
        self.generate_icon_button.clicked.connect(self.generate_icon_from_preview)
        self.open_file_url_button.triggered.connect(self.open_selected_file_url)
        self.open_location_button.triggered.connect(self.open_selected_location)
        self.open_page_button.triggered.connect(self.open_selected_page)
        self.delete_local_button.triggered.connect(self.delete_selected_local_models)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QScrollArea.Shape.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll.setWidget(panel)
        return scroll

    def _build_results_panel(self) -> QWidget:
        panel = QWidget()
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(6)
        view_row = QHBoxLayout()
        view_row.setContentsMargins(0, 0, 0, 0)
        view_row.setSpacing(6)
        self.mirror_results_view_button = QPushButton("Mirror Catalogue")
        self.local_results_view_button = QPushButton("Local Library")
        self.refresh_results_view_button = QPushButton("Refresh")
        self.mirror_results_view_button.setCheckable(True)
        self.local_results_view_button.setCheckable(True)
        self.results_view_button_group = QButtonGroup(self)
        self.results_view_button_group.setExclusive(True)
        self.results_view_button_group.addButton(self.mirror_results_view_button)
        self.results_view_button_group.addButton(self.local_results_view_button)
        view_row.addWidget(self.mirror_results_view_button)
        view_row.addWidget(self.local_results_view_button)
        view_row.addWidget(self.refresh_results_view_button)
        view_row.addStretch(1)
        layout.addLayout(view_row)
        filter_row = QHBoxLayout()
        filter_row.setContentsMargins(0, 0, 0, 0)
        filter_row.setSpacing(6)
        self.results_search_label = QLabel("Mirror search")
        self.results_filter_field_combo = QComboBox()
        self.results_filter_field_combo.addItem("All fields", "all")
        self.results_filter_field_combo.addItem("Name", "name")
        self.results_filter_field_combo.addItem("Creator", "creator")
        self.results_filter_field_combo.addItem("License", "license")
        self.results_filter_field_combo.addItem("Format", "format")
        self.results_filter_field_combo.addItem("Path / URL", "path")
        self.results_filter_field_combo.addItem("UID", "uid")
        self.apply_results_query_button = QPushButton("Search")
        self.clear_results_query_button = QPushButton("Clear")
        filter_row.addWidget(self.results_search_label)
        filter_row.addWidget(self.results_filter_field_combo)
        filter_row.addWidget(self.search_edit, stretch=1)
        filter_row.addWidget(self.apply_results_query_button)
        filter_row.addWidget(self.clear_results_query_button)
        layout.addLayout(filter_row)
        self.results_view_label = QLabel("")
        self.results_view_label.setObjectName("HintLabel")
        self.results_view_label.setWordWrap(True)
        layout.addWidget(self.results_view_label)
        self.empty_results_label = QLabel("")
        self.empty_results_label.setObjectName("HintLabel")
        self.empty_results_label.setWordWrap(True)
        self.empty_results_label.setVisible(False)
        layout.addWidget(self.empty_results_label)
        self.active_task_label = QLabel("")
        self.active_task_label.setObjectName("HintLabel")
        self.active_task_label.setWordWrap(True)
        self.active_task_label.setVisible(False)
        layout.addWidget(self.active_task_label)
        self.active_task_progress = QProgressBar()
        self.active_task_progress.setRange(0, 0)
        self.active_task_progress.setTextVisible(True)
        self.active_task_progress.setFormat("Working...")
        self.active_task_progress.setVisible(False)
        layout.addWidget(self.active_task_progress)
        self.results_tree = QTreeWidget()
        self.results_tree.setColumnCount(10)
        self.results_tree.setHeaderLabels(["", "Name", "Source", "Local", "Textures", "Format", "Size", "License", "Creator", "Location"])
        self.results_tree.setRootIsDecorated(False)
        self.results_tree.setAlternatingRowColors(True)
        self.results_tree.setUniformRowHeights(True)
        self.results_tree.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.results_tree.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.results_tree.setSortingEnabled(False)
        self.results_tree.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self.results_tree.setHorizontalScrollMode(QAbstractItemView.ScrollMode.ScrollPerPixel)
        self.results_tree.header().setStretchLastSection(False)
        self.results_tree.header().setSectionsClickable(True)
        self.results_tree.header().setSortIndicatorShown(True)
        self.results_tree.header().setSortIndicator(self._result_sort_column, self._result_sort_order)
        self.results_tree.header().setMinimumSectionSize(34)
        self.results_tree.header().setSectionResizeMode(QHeaderView.ResizeMode.Interactive)
        self.results_tree.header().setSectionResizeMode(0, QHeaderView.ResizeMode.Fixed)
        self.results_tree.header().resizeSection(0, 34)
        self.results_tree.header().resizeSection(1, 260)
        self.results_tree.header().resizeSection(2, 95)
        self.results_tree.header().resizeSection(3, 110)
        self.results_tree.header().resizeSection(4, 105)
        self.results_tree.header().resizeSection(5, 90)
        self.results_tree.header().resizeSection(6, 90)
        self.results_tree.header().resizeSection(7, 150)
        self.results_tree.header().resizeSection(8, 150)
        self.results_tree.header().resizeSection(9, 280)
        layout.addWidget(self.results_tree, stretch=1)
        selection_row = QHBoxLayout()
        selection_row.setContentsMargins(0, 0, 0, 0)
        selection_row.setSpacing(6)
        self.select_all_button = QPushButton("Select All")
        self.select_none_button = QPushButton("Select None")
        selection_row.addWidget(self.select_all_button)
        selection_row.addWidget(self.select_none_button)
        selection_row.addStretch(1)
        layout.addLayout(selection_row)
        self.results_status_label = QLabel("")
        self.results_status_label.setObjectName("HintLabel")
        self.results_status_label.setWordWrap(True)
        layout.addWidget(self.results_status_label)
        self.results_tree.currentItemChanged.connect(self._handle_results_current_item_changed)
        self.results_tree.itemChanged.connect(lambda _item, _column: self._update_selection_state())
        self.results_tree.itemDoubleClicked.connect(lambda _item, _column: self.import_selected_model())
        self.results_tree.customContextMenuRequested.connect(self._show_results_context_menu)
        self.results_tree.header().sectionClicked.connect(self._handle_results_header_clicked)
        self.select_all_button.clicked.connect(lambda _checked=False: self._set_all_result_checks(True))
        self.select_none_button.clicked.connect(lambda _checked=False: self._set_all_result_checks(False))
        self.mirror_results_view_button.clicked.connect(lambda _checked=False: self.show_mirror_catalogue_view())
        self.local_results_view_button.clicked.connect(lambda _checked=False: self.show_local_library_view())
        self.refresh_results_view_button.clicked.connect(lambda _checked=False: self.refresh_active_results_view())
        self.apply_results_query_button.clicked.connect(self._apply_active_results_query)
        self.clear_results_query_button.clicked.connect(self._clear_active_results_query)
        self.results_filter_field_combo.currentIndexChanged.connect(lambda _index=0: self._handle_results_filter_field_changed())
        return panel

    def _build_preview_panel(self) -> QWidget:
        panel = QWidget()
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(6)
        preview_group = QGroupBox("Model Preview")
        preview_layout = QVBoxLayout(preview_group)
        preview_layout.setContentsMargins(8, 8, 8, 8)
        preview_layout.setSpacing(6)
        self.inline_preview_widget = NativePreviewPanel(
            "Select a downloaded or local model to preview it here.",
            theme_key=self.theme_key,
        )
        inline_render_settings = self.inline_preview_widget.render_settings()
        inline_render_settings.visible_texture_mode = "sidecar_visible_first"
        inline_render_settings.render_diagnostic_mode = "base_direct"
        inline_render_settings.disable_tint = True
        inline_render_settings.disable_brightness = True
        inline_render_settings.disable_all_support_maps = True
        inline_render_settings.disable_normal_map = True
        inline_render_settings.disable_material_map = True
        inline_render_settings.disable_height_map = True
        self.inline_preview_widget.set_render_settings(inline_render_settings)
        self.inline_preview_widget.set_use_textures(True)
        self.inline_preview_widget.set_high_quality_textures(True)
        self.inline_preview_widget.setMinimumHeight(280)
        self.inline_preview_stack = QStackedWidget()
        self.inline_preview_stack.addWidget(self.inline_preview_widget)
        self.inline_d3d11_preview_host = NativeD3D11PreviewHostFrame()
        self.inline_d3d11_preview_host.setMinimumHeight(280)
        self.inline_preview_stack.addWidget(self.inline_d3d11_preview_host)
        preview_layout.addWidget(self.inline_preview_stack, stretch=1)
        orientation_controls_layout = QHBoxLayout()
        orientation_controls_layout.setContentsMargins(0, 0, 0, 0)
        orientation_controls_layout.setSpacing(8)
        self.inline_preview_flip_v_checkbox = QCheckBox("Flip V")
        self.inline_preview_flip_v_checkbox.setToolTip(
            "Temporarily invert the texture V direction for the current Model Library preview only."
        )
        self.inline_preview_reset_orientation_button = QPushButton("Reset")
        self.inline_preview_reset_orientation_button.setToolTip("Clear temporary Model Library texture orientation overrides.")
        self.inline_preview_flip_v_checkbox.setEnabled(False)
        self.inline_preview_reset_orientation_button.setEnabled(False)
        orientation_controls_layout.addWidget(self.inline_preview_flip_v_checkbox)
        orientation_controls_layout.addWidget(self.inline_preview_reset_orientation_button)
        orientation_controls_layout.addStretch(1)
        preview_layout.addLayout(orientation_controls_layout)
        self.inline_preview_status_label = QLabel("Local preview resolves glTF/GLB/OBJ/DAE textures from the model folder and uses native D3D11 when available.")
        self.inline_preview_status_label.setObjectName("HintLabel")
        self.inline_preview_status_label.setWordWrap(True)
        preview_layout.addWidget(self.inline_preview_status_label)
        self.inline_preview_flip_v_checkbox.toggled.connect(self._handle_inline_preview_flip_v_toggled)
        self.inline_preview_reset_orientation_button.clicked.connect(self._handle_inline_preview_orientation_reset_clicked)
        layout.addWidget(preview_group, stretch=1)
        self.status_label = QLabel("")
        self.status_label.setObjectName("HintLabel")
        self.status_label.setWordWrap(True)
        self.status_label.setVisible(False)
        layout.addWidget(self.status_label)
        return panel

    def _handle_results_current_item_changed(self, _current: Optional[QTreeWidgetItem], _previous: Optional[QTreeWidgetItem]) -> None:
        self._update_selection_state()
        if self._populating_results:
            return
        self._schedule_auto_inline_preview()

    def _handle_auto_preview_toggled(self, checked: bool) -> None:
        self.settings.setValue("model_library/auto_preview", bool(checked))
        if checked:
            self._schedule_auto_inline_preview()

    def _handle_hide_downloaded_toggled(self, checked: bool) -> None:
        self.settings.setValue("model_library/hide_downloaded", bool(checked))
        if self._active_results_view == "mirror":
            self._populate_results(self.mirror_results)
            hidden = int(getattr(self, "_last_hidden_downloaded_count", 0) or 0)
            if checked and hidden and self.results_tree.topLevelItemCount() == 0:
                self._set_status(
                    f"Hide downloaded is on. All {hidden:,} cached mirror result(s) are already downloaded, so the table is empty."
                )
            else:
                suffix = f" Hidden downloaded: {hidden:,}." if checked else ""
                self._set_status(f"Showing Mirror Catalogue with {self.results_tree.topLevelItemCount():,} visible result(s).{suffix}")

    def _handle_results_query_changed(self, text: str) -> None:
        if self._updating_results_query:
            return
        if self._active_results_view == "local":
            self.settings.setValue("model_library/local_search_query", str(text))
            self._schedule_results_filter()
            self._update_results_view_label()
            return
        self.settings.setValue("model_library/search_query", str(text))
        self._update_results_view_label()

    def _handle_results_filter_field_changed(self) -> None:
        key = "model_library/local_search_field" if self._active_results_view == "local" else "model_library/search_field"
        self.settings.setValue(key, str(self.results_filter_field_combo.currentData() or "all"))
        if self._active_results_view == "local":
            self._schedule_results_filter()
            self._update_results_view_label()

    def _schedule_results_filter(self) -> None:
        self._results_filter_timer.start()

    def _flush_debounced_results_filter(self) -> None:
        if self._active_results_view == "local":
            self._populate_results(self.local_models)

    def _set_results_query_text(self, text: str) -> None:
        self._updating_results_query = True
        try:
            self.search_edit.setText(str(text or ""))
        finally:
            self._updating_results_query = False

    def _set_results_filter_field(self, field: str) -> None:
        if not hasattr(self, "results_filter_field_combo"):
            return
        index = self.results_filter_field_combo.findData(str(field or "all"))
        self.results_filter_field_combo.setCurrentIndex(index if index >= 0 else 0)

    def _apply_active_results_query(self) -> None:
        if self._active_results_view == "local":
            self.settings.setValue("model_library/local_search_query", self.search_edit.text().strip())
            self._populate_results(self.local_models)
            self._update_results_view_label()
            self._set_status(
                f"Showing Local Library: {self._pending_results_visible_count:,}/{len(self.local_models):,} matching model file(s)."
            )
            return
        self.search_mirror()

    def _clear_active_results_query(self) -> None:
        self._set_results_query_text("")
        if self._active_results_view == "local":
            self.settings.setValue("model_library/local_search_query", "")
            self._populate_results(self.local_models)
            self._update_results_view_label()
            return
        self.settings.setValue("model_library/search_query", "")
        self.search_mirror(query_override="")

    def _handle_results_header_clicked(self, column: int) -> None:
        column = max(0, min(int(column), self.results_tree.columnCount() - 1))
        if column == self._result_sort_column:
            self._result_sort_order = (
                Qt.SortOrder.DescendingOrder
                if self._result_sort_order == Qt.SortOrder.AscendingOrder
                else Qt.SortOrder.AscendingOrder
            )
        else:
            self._result_sort_column = column
            self._result_sort_order = Qt.SortOrder.DescendingOrder if column == 6 else Qt.SortOrder.AscendingOrder
        self.settings.setValue("model_library/result_sort_column", self._result_sort_column)
        self.settings.setValue(
            "model_library/result_sort_order",
            "desc" if self._result_sort_order == Qt.SortOrder.DescendingOrder else "asc",
        )
        self.results_tree.header().setSortIndicatorShown(True)
        self.results_tree.header().setSortIndicator(self._result_sort_column, self._result_sort_order)
        if self._active_results_view == "local":
            self._populate_results(self.local_models)
        else:
            self._populate_results(self.mirror_results)

    def _use_result_source_order(self) -> None:
        self._result_sort_column = -1
        if hasattr(self, "results_tree"):
            self.results_tree.header().setSortIndicatorShown(False)

    def _schedule_auto_inline_preview(self) -> None:
        if not hasattr(self, "auto_preview_checkbox") or not self.auto_preview_checkbox.isChecked():
            return
        if not self.isVisible():
            return
        payload = self._selected_payload()
        if not self._payload_can_preview_here(payload):
            return
        self._auto_preview_timer.start()

    def handle_activated(self) -> None:
        self._activation_preview_timer.start()

    def _preview_current_model_if_auto_enabled(self) -> None:
        if hasattr(self, "auto_preview_checkbox") and self.auto_preview_checkbox.isChecked():
            self.preview_selected_model_here()

    def _load_settings(self) -> None:
        self.local_roots = self._settings_path_list("model_library/local_roots_json")
        default_catalogue_dir = Path("E:/ModelCatalogue") if Path("E:/").exists() else (self.base_dir / "model_catalogue")
        mirror_url = str(self.settings.value("model_library/mirror_url", "") or "")
        catalogue_dir = str(self.settings.value("model_library/catalogue_dir", str(default_catalogue_dir)) or str(default_catalogue_dir))
        self.mirror_url_edit.setText(mirror_url)
        self.catalogue_dir_edit.setText(catalogue_dir)
        self._set_active_results_view(str(self.settings.value("model_library/results_view", "mirror") or "mirror"), persist=False)

    def _set_active_results_view(self, view: str, *, persist: bool = True) -> None:
        previous_view = getattr(self, "_active_results_view", "mirror")
        if hasattr(self, "search_edit") and not self._updating_results_query:
            if previous_view == "local":
                self.settings.setValue("model_library/local_search_query", self.search_edit.text().strip())
            else:
                self.settings.setValue("model_library/search_query", self.search_edit.text().strip())
        self._active_results_view = "local" if str(view).strip().lower() == "local" else "mirror"
        if hasattr(self, "mirror_results_view_button"):
            self.mirror_results_view_button.setChecked(self._active_results_view == "mirror")
            self.local_results_view_button.setChecked(self._active_results_view == "local")
        if hasattr(self, "mirror_group"):
            self.mirror_group.setVisible(self._active_results_view == "mirror")
        if hasattr(self, "results_search_label"):
            if self._active_results_view == "local":
                self.results_search_label.setText("Filter local")
                self.apply_results_query_button.setText("Apply")
                self.search_edit.setPlaceholderText("Filter local models by name, creator, license, format, path, or source")
                self.results_filter_field_combo.setEnabled(True)
                self._set_results_filter_field(str(self.settings.value("model_library/local_search_field", "all") or "all"))
                self._set_results_query_text(str(self.settings.value("model_library/local_search_query", "") or ""))
            else:
                self.results_search_label.setText("Search mirror")
                self.apply_results_query_button.setText("Search")
                self.search_edit.setPlaceholderText("Search mirror by name, tag, creator, or UID")
                self.results_filter_field_combo.setEnabled(False)
                self._set_results_filter_field("all")
                self._set_results_query_text(str(self.settings.value("model_library/search_query", self.search_edit.text()) or ""))
        if persist:
            self.settings.setValue("model_library/results_view", self._active_results_view)
        self._update_results_view_label()

    def _update_results_view_label(self) -> None:
        if not hasattr(self, "results_view_label"):
            return
        if self._active_results_view == "local":
            roots = len(getattr(self, "local_roots", ()) or ())
            query = str(self.search_edit.text() if hasattr(self, "search_edit") else "").strip()
            field = str(
                self.results_filter_field_combo.currentText()
                if hasattr(self, "results_filter_field_combo")
                else "All fields"
            )
            filter_text = f" Filter: {query} ({field})." if query else ""
            self.results_view_label.setText(
                f"Local Library | {roots:,} folder(s), including downloaded mirror models when available.{filter_text}"
            )
            return
        query = str(self.search_edit.text() if hasattr(self, "search_edit") else "").strip()
        query_text = f" Search: {query}" if query else " Search: popular models"
        self.results_view_label.setText(f"Mirror Catalogue | Indexed metadata results from the mirror catalogue.{query_text}")

    def _load_initial_results_view(self) -> bool:
        self._populate_results([])
        if self._active_results_view == "local":
            if not self.local_roots:
                return False
            self._set_status("Loading local model library...")
            QTimer.singleShot(0, self.scan_local_roots)
            return True
        if not self.catalogue_db_path().is_file():
            return False
        self._set_status("Loading mirror catalogue results...")
        QTimer.singleShot(0, self.search_mirror)
        return True

    def show_mirror_catalogue_view(self) -> None:
        self._set_active_results_view("mirror")
        if self.mirror_results:
            self._use_result_source_order()
            self._populate_results(self.mirror_results)
            hidden = int(getattr(self, "_last_hidden_downloaded_count", 0) or 0)
            suffix = f" {hidden:,} downloaded result(s) hidden." if hidden else ""
            self._set_status(
                f"Showing {self.results_tree.topLevelItemCount():,}/{len(self.mirror_results):,} cached mirror catalogue result(s).{suffix} Use Refresh to search again."
            )
            return
        self.search_mirror()

    def show_local_library_view(self) -> None:
        self._set_active_results_view("local")
        if self.local_models:
            self._populate_results(self.local_models)
            visible_count = self.results_tree.topLevelItemCount()
            suffix = "" if visible_count == len(self.local_models) else f" ({visible_count:,} matching current filter)"
            self._set_status(f"Showing {len(self.local_models):,} cached local model file(s){suffix}. Use Refresh to scan again.")
            return
        self.scan_local_roots()

    def refresh_active_results_view(self) -> None:
        if self._active_results_view == "local":
            self.scan_local_roots()
            return
        self.search_mirror()

    def _settings_path_list(self, key: str) -> list[str]:
        return self._settings_string_list(key)

    def _settings_string_list(self, key: str, *, default: tuple[str, ...] = ()) -> list[str]:
        raw = self.settings.value(key, json.dumps(list(default)) if default else "")
        if isinstance(raw, list):
            return [str(item) for item in raw if str(item).strip()]
        text = str(raw or "").strip()
        if not text:
            return list(default)
        try:
            payload = json.loads(text)
        except json.JSONDecodeError:
            return [part for part in text.split(os.pathsep) if part.strip()]
        if isinstance(payload, list):
            return [str(item) for item in payload if str(item).strip()]
        return list(default)

    def _save_roots(self) -> None:
        self.settings.setValue("model_library/local_roots_json", json.dumps(self.local_roots))

    def _save_mirror_settings(self) -> None:
        try:
            mirror_url = self.mirror_url()
        except ValueError:
            mirror_url = self.mirror_url_edit.text().strip()
        self.settings.setValue("model_library/mirror_url", mirror_url)
        self.settings.setValue("model_library/catalogue_dir", str(self.catalogue_dir()))

    def _checked_preferred_formats(self) -> list[str]:
        selected: list[str] = []
        for format_key in ("gltf", "glb", "source", "extra"):
            checkbox = getattr(self, "preferred_format_checks", {}).get(format_key)
            if checkbox is not None and checkbox.isChecked():
                selected.append(format_key)
        return selected

    def _selected_preferred_formats(self, *, require_importable: bool = False, allow_empty: bool = False) -> list[str]:
        selected = self._checked_preferred_formats()
        if require_importable:
            selected = [format_key for format_key in selected if format_key in {"gltf", "glb"}]
        if not selected and not allow_empty:
            selected = ["gltf"]
        return selected

    def _primary_preferred_format(self, *, require_importable: bool = False) -> str:
        return self._selected_preferred_formats(require_importable=require_importable)[0]

    def _save_preferred_format_settings(self) -> None:
        if not hasattr(self, "preferred_format_checks"):
            return
        self.settings.setValue("model_library/preferred_formats_json", json.dumps(self._checked_preferred_formats()))

    def _refresh_roots_tree(self) -> None:
        self.roots_tree.clear()
        for root in self.local_roots:
            item = QTreeWidgetItem([root])
            self.roots_tree.addTopLevelItem(item)
        if self.local_roots and not self.local_path_edit.text().strip():
            self.local_path_edit.setText(self.local_roots[-1])

    def browse_local_folder(self) -> None:
        start_dir = self.local_path_edit.text().strip() or (self.local_roots[-1] if self.local_roots else str(Path.home()))
        folder = QFileDialog.getExistingDirectory(self, "Choose Model Folder", start_dir)
        if folder:
            self.local_path_edit.setText(folder)

    def add_local_root(self) -> None:
        folder = self.local_path_edit.text().strip()
        if not folder:
            self.browse_local_folder()
            folder = self.local_path_edit.text().strip()
        if not folder:
            return
        path = Path(folder).expanduser()
        if not path.is_dir():
            self._set_status(f"Local model folder does not exist: {path}", error=True)
            return
        try:
            normalized = str(path.resolve())
        except OSError:
            normalized = str(path.absolute())
        if normalized not in self.local_roots:
            self.local_roots.append(normalized)
            self._save_roots()
            self._refresh_roots_tree()
        self.scan_local_roots()

    def remove_selected_local_root(self) -> None:
        item = self.roots_tree.currentItem()
        if item is None:
            return
        root = item.text(0)
        self.local_roots = [value for value in self.local_roots if value != root]
        self._save_roots()
        self._refresh_roots_tree()

    def open_selected_local_root(self) -> None:
        item = self.roots_tree.currentItem()
        path = Path(item.text(0)) if item is not None else Path(self.local_path_edit.text().strip() or "")
        if path.is_dir():
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(path)))

    def scan_local_roots(self) -> None:
        self._set_active_results_view("local")
        roots = list(self.local_roots)
        if not roots:
            self.local_models = []
            self._populate_results([])
            self._set_status("Add at least one local model folder before scanning.", error=True)
            return

        def task(progress: Callable[[str], None]) -> object:
            progress("Scanning local model folders...")
            return [item.to_dict() for item in scan_local_model_files(roots)]

        def complete(result: object) -> None:
            models = result if isinstance(result, list) else []
            self._texture_status_cache.clear()
            self.local_models = self._normalize_local_model_rows([dict(item) for item in models if isinstance(item, dict)])
            self._populate_results(self.local_models)
            visible_count = self.results_tree.topLevelItemCount()
            suffix = "" if visible_count == len(self.local_models) else f" ({visible_count:,} matching current filter)"
            self._set_status(f"Showing Local Library: {len(self.local_models):,} model file(s){suffix}.")

        self._run_task("Scanning local model folders...", task, complete)

    def browse_catalogue_dir(self) -> None:
        start_dir = str(self.catalogue_dir())
        folder = QFileDialog.getExistingDirectory(self, "Choose Catalogue Folder", start_dir)
        if folder:
            self.catalogue_dir_edit.setText(folder)
            self._save_mirror_settings()
            self._update_catalogue_status()

    def build_mirror_index(self) -> None:
        self._save_mirror_settings()
        self._stop_event = threading.Event()
        try:
            mirror_url = self.mirror_url()
        except ValueError as exc:
            self._set_status(str(exc), error=True)
            self._stop_event = None
            return
        output_dir = self.catalogue_dir()
        max_shards = int(self.max_shards_spin.value())
        index_current_search = bool(self.index_current_search_checkbox.isChecked())
        index_query = self.search_edit.text().strip() if index_current_search else ""
        license_filter = self.license_filter_edit.text().strip() if index_current_search else ""
        creator_filter = self.creator_filter_edit.text().strip() if index_current_search else ""
        creator_excludes = self.creator_exclude_edit.text().strip() if index_current_search else ""
        format_filter = str(self.format_filter_combo.currentData() or "") if index_current_search else ""
        if index_current_search and not any((index_query, license_filter, creator_filter, creator_excludes, format_filter)):
            self._set_status("Enter a search term or filter before building a scoped mirror index.", error=True)
            self._stop_event = None
            return

        def task(progress: Callable[[str], None]) -> object:
            return build_mirror_catalogue_index(
                mirror_url=mirror_url,
                output_dir=output_dir,
                max_shards=max_shards,
                index_query=index_query,
                license_contains=license_filter,
                creator_contains=creator_filter,
                creator_excludes=creator_excludes,
                required_format=format_filter,
                clear_existing=index_current_search,
                stop_event=self._stop_event,
                on_progress=lambda _current, _total, message: progress(message),
            )

        def complete(result: object) -> None:
            self._stop_event = None
            self._update_catalogue_status()
            if isinstance(result, dict):
                scope_label = ""
                if bool(result.get("index_scoped")):
                    scope = str(result.get("index_query", "") or "current filters")
                    seen = int(result.get("seen_model_records_this_run", 0) or 0)
                    scope_label = f" Scoped to {scope!r}; scanned {seen:,} record(s)."
                self._set_status(
                    f"Indexed {int(result.get('indexed_model_records_this_run', 0)):,} model record(s) from "
                    f"{int(result.get('indexed_catalogue_pages', 0)):,} catalogue page(s) this run. "
                    f"Database now has {int(result.get('models_in_database', 0)):,} model(s) from "
                    f"{int(result.get('shards_in_database', 0)):,} cached page(s)."
                    f"{scope_label}"
                )
            else:
                self._set_status("Mirror catalogue index finished.")

        self._run_task("Building mirror metadata index...", task, complete)

    def cancel_current_task(self) -> None:
        if self._stop_event is not None:
            self._stop_event.set()
            self._set_status("Cancelling current model library task...")

    def search_mirror(self, *, query_override: Optional[str] = None) -> None:
        self._set_active_results_view("mirror")
        self._save_mirror_settings()
        query = self.search_edit.text().strip() if query_override is None else str(query_override)
        if query_override is None:
            self.settings.setValue("model_library/search_query", query)
        db_path = self.catalogue_db_path()
        if not db_path.is_file():
            self.mirror_results = []
            self._populate_results([])
            self._set_status("Build the mirror search index before searching.", error=True)
            return
        limit = int(self.result_limit_spin.value())
        license_filter = self.license_filter_edit.text().strip()
        creator_filter = self.creator_filter_edit.text().strip()
        creator_excludes = self.creator_exclude_edit.text().strip()
        format_filter = str(self.format_filter_combo.currentData() or "")

        def task(progress: Callable[[str], None]) -> object:
            progress("Searching mirror catalogue...")
            return list(
                search_catalogue_records(
                    db_path,
                    query,
                    limit=limit,
                    license_contains=license_filter,
                    creator_contains=creator_filter,
                    creator_excludes=creator_excludes,
                    required_format=format_filter,
                )
            )

        def complete(result: object) -> None:
            rows = result if isinstance(result, list) else []
            self.mirror_results = [dict(item) for item in rows if isinstance(item, dict)]
            self._use_result_source_order()
            self._populate_results(self.mirror_results)
            filters = [value for value in (license_filter, creator_filter, format_filter) if value]
            if creator_excludes:
                filters.append(f"excluding creators: {creator_excludes}")
            label = query or "popular models"
            if filters:
                label = f"{label} with filters: {', '.join(filters)}"
            hidden = int(getattr(self, "_last_hidden_downloaded_count", 0) or 0)
            suffix = f" {hidden:,} downloaded result(s) hidden." if hidden else ""
            self._update_results_view_label()
            self._set_status(
                f"Showing Mirror Catalogue: {self.results_tree.topLevelItemCount():,}/{len(self.mirror_results):,} result(s) for {label}.{suffix}"
            )

        self._run_task("Searching mirror catalogue...", task, complete)

    def show_selected_model_files(self) -> None:
        payloads = [payload for payload in self._batch_action_payloads() if payload.get("kind") == "mirror"]
        if not payloads:
            self._set_status("Check one or more mirror models to show file URLs.", error=True)
            return
        self._show_file_urls_for_payloads(payloads)

    def _show_file_urls_for_payloads(self, payloads: list[dict[str, object]]) -> None:
        text = self._selected_file_url_text(payloads)
        dialog = QDialog(self)
        dialog.setWindowTitle("Model File URLs")
        dialog.setMinimumSize(760, 460)
        layout = QVBoxLayout(dialog)
        note = QLabel(
            "Open these URLs in your browser or another download tool. "
            "After the files are on disk, add their folder under Local Folders, scan it, then preview or import the local model."
        )
        note.setWordWrap(True)
        layout.addWidget(note)
        text_edit = QPlainTextEdit()
        text_edit.setReadOnly(True)
        text_edit.setPlainText(text)
        layout.addWidget(text_edit, stretch=1)
        buttons = QDialogButtonBox(QDialogButtonBox.Close)
        buttons.rejected.connect(dialog.reject)
        layout.addWidget(buttons)
        dialog.exec()
        self._set_status(f"Showing file URLs for {len(payloads):,} mirror model(s).")

    def download_selected_models(self) -> None:
        payloads = [payload for payload in self._batch_action_payloads() if payload.get("kind") == "mirror"]
        if not payloads:
            self._set_status("Check one or more mirror models to download.", error=True)
            return
        self._download_mirror_payloads(payloads, import_after=False, preview_after=False)

    def download_selected_model(self, *, import_after: bool) -> None:
        payload = self._selected_payload()
        if not payload:
            self._set_status("Select a model first.", error=True)
            return
        if payload.get("kind") != "mirror":
            if import_after:
                self.import_selected_model()
            else:
                self._set_status("Local models are already on disk.", error=True)
            return
        self._download_mirror_payloads([payload], import_after=import_after, preview_after=False)

    def open_selected_file_url(self) -> None:
        payload = self._selected_payload()
        if not payload or payload.get("kind") != "mirror":
            self._set_status("Select one mirror model first.", error=True)
            return
        candidates = self._mirror_candidates_for_payload(payload)
        if not candidates:
            self._set_status("Selected mirror model has no file URL in the catalogue.", error=True)
            return
        preferred = self._primary_preferred_format()
        candidate = next((item for item in candidates if item.format == preferred), candidates[0])
        if not QDesktopServices.openUrl(QUrl(candidate.url)):
            self._set_status(f"Could not open file URL: {candidate.url}", error=True)
            return
        self._set_status(f"Opened {candidate.label} URL in your browser. Save it locally, then scan its folder from Local Folders.")

    def preview_selected_model(self) -> None:
        payload = self._selected_payload()
        if not payload:
            self._set_status("Select a model first.", error=True)
            return
        if payload.get("kind") == "mirror":
            import_path = self._resolve_payload_import_path(payload)
            if import_path is not None:
                self._set_status(f"Opening preview from local model file: {import_path}")
                self.preview_mesh_requested.emit(str(import_path), dict(payload))
                return
            self._set_status("Downloading and extracting model before preview...")
            self._download_mirror_payloads([payload], import_after=False, preview_after=True)
            return
        path = Path(str(payload.get("path", "") or ""))
        if not path.is_file():
            self._set_status(f"Local model file is missing: {path}", error=True)
            return
        import_path = self._resolve_payload_import_path(payload)
        if import_path is None:
            self._set_status(
                f"{path.suffix or 'This file'} can be browsed here, but preview currently accepts importable files or ZIPs containing: {', '.join(sorted(IMPORTABLE_MODEL_EXTENSIONS))}.",
                error=True,
            )
            return
        if import_path != path:
            self._set_status(f"Extracted ZIP and opening preview from: {import_path}")
        self.preview_mesh_requested.emit(str(import_path), dict(payload))

    def preview_selected_model_here(self) -> None:
        payload = self._selected_payload()
        if not payload:
            self._set_inline_preview_status("Select a model first.", error=True)
            return
        import_path = self._resolve_payload_import_path(payload)
        if import_path is None:
            if payload.get("kind") == "mirror":
                self._set_inline_preview_status("Download this mirror model first, then Preview Here.", error=True)
            else:
                self._set_inline_preview_status("This local item is not an importable model or ZIP.", error=True)
            return
        self._load_inline_model_preview(import_path, payload)

    def _inline_preview_renderer_backend(self) -> str:
        return "native_d3d11"

    def _inline_d3d11_theme_payload(self) -> dict[str, str]:
        theme = get_theme(self.theme_key)
        return {
            "background": str(theme.get("preview_bg", "#0d0f11")),
            "text": str(theme.get("text_muted", theme.get("text", "#c8d3df"))),
        }

    def _inline_d3d11_process_running(self) -> bool:
        process = self._inline_d3d11_process
        try:
            return process is not None and process.state() != QProcess.NotRunning
        except RuntimeError:
            return False

    def _start_inline_d3d11_process(self, package_dir: Path, *, render_settings: object) -> bool:
        package_dir = Path(package_dir)
        status_file = package_dir / "host_status.json"
        try:
            status_file.unlink(missing_ok=True)
        except OSError:
            pass
        self._inline_d3d11_active_package = package_dir
        self._inline_d3d11_status_file = status_file
        self._inline_d3d11_status_mtime = 0.0
        if self._inline_d3d11_process_running():
            self.inline_preview_stack.setCurrentWidget(self.inline_d3d11_preview_host)
            self.inline_d3d11_preview_host.clear_preview(status_file)
            if self.inline_d3d11_preview_host.load_package(package_dir, status_file, reset_view=True):
                self.inline_d3d11_preview_host.set_render_tuning(render_settings)
                self._inline_d3d11_status_timer.start()
                return True
            self._stop_inline_d3d11_process()
        try:
            program, arguments = native_d3d11_renderer_command(
                package_dir,
                status_file,
                host_widget=self.inline_d3d11_preview_host,
                theme_payload=self._inline_d3d11_theme_payload(),
            )
        except Exception as exc:
            self._set_inline_preview_status(f"Native D3D11 preview unavailable: {exc}", error=True)
            return False
        process = QProcess(self)
        process.setProgram(program)
        process.setArguments(arguments)
        try:
            process.setWorkingDirectory(str(Path(__file__).resolve().parents[2]))
        except Exception:
            pass
        process.setProcessChannelMode(QProcess.SeparateChannels)
        process.readyReadStandardError.connect(lambda process=process: self._handle_inline_d3d11_stderr(process))
        process.finished.connect(lambda _exit_code, _exit_status, process=process: self._handle_inline_d3d11_finished(process))
        process.errorOccurred.connect(lambda error, process=process: self._handle_inline_d3d11_error(process, error))
        self._inline_d3d11_process = process
        self.inline_preview_stack.setCurrentWidget(self.inline_d3d11_preview_host)
        self._inline_d3d11_status_timer.start()
        process.start()
        return True

    def _handle_inline_d3d11_stderr(self, process: QProcess) -> None:
        if process is not self._inline_d3d11_process:
            return
        try:
            message = bytes(process.readAllStandardError()).decode("utf-8", errors="replace").strip()
        except RuntimeError:
            return
        if message:
            self._set_inline_preview_status(f"Native D3D11 preview stderr: {message[-600:]}", error=True)

    def _handle_inline_d3d11_error(self, process: QProcess, error: object) -> None:
        if process is self._inline_d3d11_process:
            self._set_inline_preview_status(f"Native D3D11 preview process error: {error}", error=True)

    def _handle_inline_d3d11_finished(self, process: QProcess) -> None:
        if process is self._inline_d3d11_process:
            self._inline_d3d11_process = None
            self._inline_d3d11_status_timer.stop()

    def _poll_inline_d3d11_status(self) -> None:
        status_file = self._inline_d3d11_status_file
        if status_file is None:
            return
        try:
            stat = status_file.stat()
        except OSError:
            return
        mtime = float(getattr(stat, "st_mtime", 0.0) or 0.0)
        if mtime <= float(self._inline_d3d11_status_mtime):
            return
        self._inline_d3d11_status_mtime = mtime
        try:
            payload = json.loads(status_file.read_text(encoding="utf-8"))
        except Exception:
            return
        if not isinstance(payload, dict):
            return
        event = str(payload.get("event", "") or "").strip().lower()
        if event == "loaded":
            batch_count = int(payload.get("batch_count", 0) or 0)
            vertex_count = int(payload.get("vertex_count", 0) or 0)
            self._set_inline_preview_status(f"Native D3D11 Model Library preview ready: {batch_count:,} batch(es), {vertex_count:,} vertices.")
        elif event == "error":
            self._set_inline_preview_status(str(payload.get("message", "Native D3D11 preview failed.") or ""), error=True)

    def _stop_inline_d3d11_process(self) -> None:
        process = self._inline_d3d11_process
        self._inline_d3d11_process = None
        self._inline_d3d11_status_timer.stop()
        if process is None:
            return
        try:
            if process.state() != QProcess.NotRunning:
                process.terminate()
                QTimer.singleShot(1200, lambda process=process: process.kill() if process.state() != QProcess.NotRunning else None)
        except RuntimeError:
            return

    def _prepare_inline_preview_orientation_for_load(self, *, reset_orientation: bool) -> None:
        if reset_orientation:
            self._set_inline_preview_flip_v_checked(False)
            self._apply_inline_preview_flip_v_render_setting(False)
        self._inline_preview_loaded_texture_count = 0
        self._inline_preview_loaded_renderer_backend = ""
        self._sync_inline_preview_orientation_controls()

    def _set_inline_preview_flip_v_checked(self, checked: bool) -> None:
        if not hasattr(self, "inline_preview_flip_v_checkbox"):
            return
        self.inline_preview_flip_v_checkbox.blockSignals(True)
        self.inline_preview_flip_v_checkbox.setChecked(bool(checked))
        self.inline_preview_flip_v_checkbox.blockSignals(False)

    def _apply_inline_preview_flip_v_render_setting(self, checked: bool) -> None:
        settings = self.inline_preview_widget.render_settings()
        settings.flip_texture_v = bool(checked)
        self.inline_preview_widget.set_render_settings(settings)

    def _sync_inline_preview_orientation_controls(self) -> None:
        if not hasattr(self, "inline_preview_flip_v_checkbox"):
            return
        enabled = bool(
            self._inline_preview_loaded_import_path is not None
            and int(self._inline_preview_loaded_texture_count) > 0
        )
        self.inline_preview_flip_v_checkbox.setEnabled(enabled)
        self.inline_preview_reset_orientation_button.setEnabled(enabled)

    def _reload_inline_preview_for_orientation(self) -> None:
        loaded_path = self._inline_preview_loaded_import_path
        payload = dict(self._inline_preview_loaded_payload or {})
        if loaded_path is None or not payload:
            return
        self._load_inline_model_preview(loaded_path, payload, reset_orientation=False)

    def _handle_inline_preview_flip_v_toggled(self, checked: bool) -> None:
        self._apply_inline_preview_flip_v_render_setting(bool(checked))
        self._sync_inline_preview_orientation_controls()
        if int(self._inline_preview_loaded_texture_count) <= 0:
            return
        if str(self._inline_preview_loaded_renderer_backend or "").strip().lower() == "native_d3d11":
            self._reload_inline_preview_for_orientation()
            return
        self._set_inline_preview_status("Flip V preview override applied." if checked else "Texture orientation preview reset.")

    def _handle_inline_preview_orientation_reset_clicked(self) -> None:
        if hasattr(self, "inline_preview_flip_v_checkbox") and self.inline_preview_flip_v_checkbox.isChecked():
            self.inline_preview_flip_v_checkbox.setChecked(False)
            return
        self._handle_inline_preview_flip_v_toggled(False)

    def _load_inline_model_preview(
        self,
        import_path: Path,
        payload: dict[str, object],
        *,
        reset_orientation: bool = True,
    ) -> None:
        if self._task_thread is not None and self._task_thread.isRunning():
            self._set_inline_preview_status("A model library task is already running.", error=True)
            return
        self._inline_preview_request_id += 1
        request_id = self._inline_preview_request_id
        model_name = str(payload.get("name", "") or import_path.stem or "model")
        renderer_backend = self._inline_preview_renderer_backend()
        self._prepare_inline_preview_orientation_for_load(reset_orientation=reset_orientation)
        self._set_inline_preview_status(f"Preparing preview for {model_name}...")
        self.inline_preview_widget.clear_model(f"Preparing preview for {model_name}...")
        self.inline_preview_stack.setCurrentWidget(self.inline_preview_widget)
        self._inline_preview_loaded_import_path = None
        self._inline_preview_loaded_payload = None
        preview_render_settings = self.inline_preview_widget.render_settings()

        def task(progress: Callable[[str], None]) -> object:
            progress(f"Reading model file: {import_path}")
            scene_result = import_scene_mesh_with_report(import_path)
            preview_model = parsed_mesh_to_preview_model(scene_result.mesh)
            texture_count = self._attach_inline_preview_textures(preview_model, scene_result, import_path)
            prepared_model, prepared_preview = prepare_model_preview(
                preview_model,
                render_settings=preview_render_settings,
                enable_material_combiner=False,
            )
            package_dir = ""
            package_ms = 0.0
            if renderer_backend == "native_d3d11":
                package_started = time.perf_counter()
                package_dir = str(
                    write_isolated_d3d11_preview_package(
                        prepared_model,
                        prepared_preview,
                        render_settings=preview_render_settings,
                        use_textures=True,
                        high_quality_textures=True,
                        backend="d3d11",
                        enable_material_combiner=False,
                        prefer_direct_dds=True,
                        editor_workspace="model_library",
                    )
                )
                package_ms = max(0.0, (time.perf_counter() - package_started) * 1000.0)
            material_channel_summary = self._inline_preview_material_channel_summary(prepared_preview)
            mesh_count = len(getattr(preview_model, "meshes", ()) or ())
            audit = getattr(scene_result, "external_audit", None)
            return {
                "request_id": request_id,
                "model_name": model_name,
                "import_path": str(import_path),
                "renderer_backend": renderer_backend,
                "preview_model": prepared_model,
                "prepared_preview": prepared_preview,
                "d3d11_package_dir": package_dir,
                "d3d11_package_ms": package_ms,
                "vertices": int(scene_result.mesh.total_vertices),
                "faces": int(scene_result.mesh.total_faces),
                "meshes": int(mesh_count),
                "textures": int(texture_count),
                "material_channel_summary": material_channel_summary,
                "diagnostics": tuple(scene_result.diagnostics or ()),
                "audit_category": str(getattr(audit, "verified_category", "") or ""),
                "audit_confidence": float(getattr(audit, "confidence", 0.0) or 0.0),
                "audit_texture_slots": tuple(getattr(audit, "texture_slots", ()) or ()),
                "audit_workflows": tuple(getattr(audit, "pbr_workflows", ()) or ()),
                "audit_warnings": tuple(getattr(audit, "warnings", ()) or ()),
                "audit_false_positive": bool(getattr(audit, "false_positive", False)),
                "audit_mixed_model": bool(getattr(audit, "mixed_model", False)),
            }

        def complete(result: object) -> None:
            if not isinstance(result, dict):
                self._set_inline_preview_status("Preview finished with an unexpected response.", error=True)
                return
            if int(result.get("request_id", -1)) != int(self._inline_preview_request_id):
                return
            preview_model = result.get("preview_model")
            prepared_preview = result.get("prepared_preview")
            active_renderer = str(result.get("renderer_backend", "") or "").strip().lower()
            renderer_note = " | renderer: native D3D11"
            loaded_renderer_backend = "native_d3d11"
            if active_renderer == "native_d3d11" and str(result.get("d3d11_package_dir", "") or "").strip():
                package_dir = Path(str(result.get("d3d11_package_dir", "") or ""))
                if self._start_inline_d3d11_process(package_dir, render_settings=preview_render_settings):
                    loaded_renderer_backend = "native_d3d11"
                    renderer_note = f" | renderer: native D3D11 package ({float(result.get('d3d11_package_ms', 0.0) or 0.0):.1f} ms)"
                else:
                    self._set_inline_preview_status("Native D3D11 preview failed to start.", error=True)
                    return
            else:
                self._set_inline_preview_status("Native D3D11 preview package was not built.", error=True)
                return
            self._inline_preview_loaded_import_path = Path(str(result.get("import_path", "") or import_path))
            self._inline_preview_loaded_payload = dict(payload)
            self._inline_preview_loaded_renderer_backend = loaded_renderer_backend
            texture_count = int(result.get("textures", 0) or 0)
            self._inline_preview_loaded_texture_count = texture_count
            payload["texture_status"] = f"Resolved ({texture_count})" if texture_count > 0 else "None resolved"
            audit_category = str(result.get("audit_category", "") or "")
            if audit_category:
                payload["audit_category"] = audit_category
                payload["audit_confidence"] = float(result.get("audit_confidence", 0.0) or 0.0)
                payload["audit_texture_slots"] = tuple(result.get("audit_texture_slots", ()) or ())
                payload["audit_workflows"] = tuple(result.get("audit_workflows", ()) or ())
                payload["audit_warnings"] = tuple(result.get("audit_warnings", ()) or ())
                payload["audit_false_positive"] = bool(result.get("audit_false_positive", False))
                payload["audit_mixed_model"] = bool(result.get("audit_mixed_model", False))
            self._refresh_result_row_statuses()
            audit_text = ""
            if audit_category:
                audit_text = f" | audit: {audit_category} {float(result.get('audit_confidence', 0.0) or 0.0):.0%}"
            material_channel_summary = str(result.get("material_channel_summary", "") or "").strip()
            material_channel_text = f" | channels: {material_channel_summary}" if material_channel_summary else ""
            self._set_inline_preview_status(
                f"{result.get('model_name', 'Model')} | {int(result.get('meshes', 0)):,} mesh(es), "
                f"{int(result.get('vertices', 0)):,} vertices, {int(result.get('faces', 0)):,} faces, "
                f"{texture_count:,} resolved texture slot(s){audit_text}{material_channel_text}{renderer_note}."
            )
            self._sync_inline_preview_orientation_controls()
            self._update_selection_state()
            if int(self._pending_icon_generation_request_id) == int(request_id):
                self._pending_icon_generation_request_id = 0
                QTimer.singleShot(180, self._capture_inline_preview_icon)

        def handle_error(message: str) -> None:
            self._pending_icon_generation_request_id = 0
            self._sync_inline_preview_orientation_controls()
            self._set_inline_preview_status(f"Preview failed: {message}", error=True)

        self._run_task(
            f"Preparing model library preview for {model_name}...",
            task,
            complete,
            error_handler=handle_error,
        )

    def generate_icon_from_preview(self) -> None:
        payload = self._selected_payload()
        if not payload:
            self._set_inline_preview_status("Select a model first.", error=True)
            return
        import_path = self._resolve_payload_import_path(payload)
        if import_path is None:
            self._set_inline_preview_status("Preview a downloaded or local importable model before generating an icon.", error=True)
            return
        if not self._inline_preview_matches(import_path):
            if self._task_thread is not None and self._task_thread.isRunning():
                self._set_inline_preview_status("A model library task is already running.", error=True)
                return
            self._pending_icon_generation_request_id = self._inline_preview_request_id + 1
            self._load_inline_model_preview(import_path, payload)
            return
        self._capture_inline_preview_icon()

    def _inline_preview_matches(self, import_path: Path) -> bool:
        loaded = self._inline_preview_loaded_import_path
        if loaded is None:
            return False
        try:
            return loaded.resolve() == import_path.resolve()
        except OSError:
            return str(loaded.absolute()).casefold() == str(import_path.absolute()).casefold()

    def _capture_inline_preview_icon(self) -> None:
        payload = self._selected_payload()
        loaded_path = self._inline_preview_loaded_import_path
        if payload is None or loaded_path is None:
            self._set_inline_preview_status("Preview a model first, then generate an icon.", error=True)
            return
        current_import_path = self._resolve_payload_import_path(payload)
        if current_import_path is None or not self._inline_preview_matches(current_import_path):
            self._set_inline_preview_status("The selected model preview is no longer active.", error=True)
            return
        if self.inline_preview_stack.currentWidget() is self.inline_d3d11_preview_host:
            output_dir = self.catalogue_dir() / "generated_icons"
            output_dir.mkdir(parents=True, exist_ok=True)
            output_stem = self._generated_icon_stem(payload, loaded_path)
            output_path = output_dir / f"{output_stem}.png"
            counter = 1
            while output_path.exists():
                counter += 1
                output_path = output_dir / f"{output_stem}_{counter}.png"
            if not self.inline_d3d11_preview_host.capture_replacement_icon(output_path):
                self._set_inline_preview_status("Icon capture failed: native D3D11 preview framebuffer is empty.", error=True)
                return
            self._set_inline_preview_status(f"Generated native D3D11 model preview icon: {output_path.name}")
            self.item_icon_source_generated.emit(str(output_path), dict(self._inline_preview_loaded_payload or payload))
            return
        if int(getattr(self.inline_preview_widget, "_vertex_count", 0) or 0) <= 0:
            self._set_inline_preview_status("The preview is not render-ready yet.", error=True)
            return
        try:
            self.inline_preview_widget.repaint()
            pixmap = self.inline_preview_widget.grab()
            image = pixmap.toImage() if not pixmap.isNull() else QImage()
        except Exception as exc:
            self._set_inline_preview_status(f"Icon capture failed: {exc}", error=True)
            return
        if image.isNull() or image.width() <= 0 or image.height() <= 0:
            self._set_inline_preview_status("Icon capture failed: preview framebuffer is empty.", error=True)
            return
        icon_image = self._model_preview_icon_image(image)
        output_dir = self.catalogue_dir() / "generated_icons"
        output_dir.mkdir(parents=True, exist_ok=True)
        output_stem = self._generated_icon_stem(payload, loaded_path)
        output_path = output_dir / f"{output_stem}.png"
        counter = 1
        while output_path.exists():
            counter += 1
            output_path = output_dir / f"{output_stem}_{counter}.png"
        if not icon_image.save(str(output_path), "PNG"):
            self._set_inline_preview_status(f"Icon capture failed: could not write {output_path}.", error=True)
            return
        self._set_inline_preview_status(f"Generated model preview icon: {output_path.name}")
        self.item_icon_source_generated.emit(str(output_path), dict(self._inline_preview_loaded_payload or payload))

    def closeEvent(self, event: object) -> None:  # type: ignore[override]
        self._stop_inline_d3d11_process()
        try:
            super().closeEvent(event)  # type: ignore[arg-type]
        except TypeError:
            return

    def _model_preview_icon_image(self, image: QImage, *, size: int = 512) -> QImage:
        source = image.convertToFormat(QImage.Format.Format_RGBA8888)
        scaled = source.scaled(size, size, Qt.KeepAspectRatioByExpanding, Qt.SmoothTransformation)
        x = max(0, (scaled.width() - size) // 2)
        y = max(0, (scaled.height() - size) // 2)
        return scaled.copy(x, y, min(size, scaled.width()), min(size, scaled.height()))

    def _generated_icon_stem(self, payload: dict[str, object], import_path: Path) -> str:
        name = str(payload.get("name", "") or import_path.stem or "model_icon").strip()
        slug = re.sub(r"[^A-Za-z0-9._-]+", "-", name).strip("-._")
        if not slug:
            slug = "model_icon"
        slug = slug[:72].strip("-._") or "model_icon"
        uid = str(payload.get("uid", "") or "").strip()
        if uid:
            slug = f"{slug}-{re.sub(r'[^A-Za-z0-9]+', '', uid)[:12]}"
        return f"{slug}-{time.strftime('%Y%m%d-%H%M%S')}"

    def _download_mirror_payloads(
        self,
        payloads: list[dict[str, object]],
        *,
        import_after: bool,
        preview_after: bool,
    ) -> None:
        try:
            mirror_url = self.mirror_url()
        except ValueError as exc:
            self._set_status(str(exc), error=True)
            return
        output_root = self._download_output_root()
        require_importable = import_after or preview_after
        selected_formats = self._selected_preferred_formats(allow_empty=True)
        if not selected_formats:
            self._set_status("Select at least one preferred file type to download.", error=True)
            return
        if require_importable and not any(format_key in {"gltf", "glb"} for format_key in selected_formats):
            self._set_status("Select glTF ZIP or GLB under Preferred files before preview/import.", error=True)
            return
        payloads_by_uid = {str(payload.get("uid", "") or ""): payload for payload in payloads}
        candidate_jobs: list[tuple[dict[str, object], MirrorDownloadCandidate]] = []
        unavailable_results: list[tuple[str, object, str]] = []
        for payload in payloads:
            candidates = self._download_candidates_for_selected_formats(
                payload,
                selected_formats,
                require_importable=require_importable,
                mirror_url=mirror_url,
            )
            uid = str(payload.get("uid", "") or "")
            if not candidates:
                if require_importable:
                    unavailable_results.append((uid, None, "Selected model does not expose a glTF ZIP or GLB file."))
                else:
                    unavailable_results.append((uid, None, "Selected file types are not available for this model."))
                continue
            candidate_jobs.extend((payload, candidate) for candidate in candidates)

        def task(progress: Callable[[str], None]) -> object:
            results: list[tuple[str, object, str]] = list(unavailable_results)
            total = len(candidate_jobs)
            if total <= 0:
                return results
            for index, (payload, candidate) in enumerate(candidate_jobs, start=1):
                uid = str(payload.get("uid", "") or "")
                name = str(payload.get("name", "") or "selected model")
                progress(f"Downloading {index:,} / {total:,}: {name} ({candidate.label})...")
                try:
                    result = download_mirror_model_candidate(
                        payload,
                        candidate,
                        output_root=output_root,
                    )
                    results.append((uid, result, ""))
                    progress(f"Downloaded {index:,} / {total:,}: {name} ({candidate.label}).")
                except Exception as exc:
                    results.append((uid, None, str(exc)))
                    progress(f"Download failed {index:,} / {total:,}: {name} ({candidate.label}).")
            return results

        def complete(result: object) -> None:
            if not isinstance(result, list):
                self._set_status("Mirror download finished with an unexpected response.", error=True)
                return
            successes: list[tuple[dict[str, object], MirrorDownloadResult]] = []
            errors: list[str] = []
            for uid, download_result, error_text in result:
                payload = payloads_by_uid.get(str(uid))
                if isinstance(download_result, MirrorDownloadResult) and payload is not None:
                    payload["asset_dir"] = str(download_result.asset_dir)
                    downloaded_formats = {
                        part.strip()
                        for part in str(payload.get("download_format", "") or "").split(",")
                        if part.strip()
                    }
                    downloaded_formats.add(download_result.candidate.format)
                    payload["download_format"] = ", ".join(
                        format_key for format_key in ("gltf", "glb", "source", "extra") if format_key in downloaded_formats
                    )
                    if download_result.import_path is not None or not str(payload.get("archive_path", "") or "").strip():
                        payload["archive_path"] = str(download_result.archive_path)
                    if download_result.import_path is not None:
                        payload["import_path"] = str(download_result.import_path)
                    payload["local_status"] = self._mirror_local_status(payload)
                    successes.append((payload, download_result))
                elif str(error_text or "").strip():
                    errors.append(str(error_text))
            if successes:
                self._ensure_download_root_registered(output_root)
                self._texture_status_cache.clear()
            if self._active_results_view == "mirror" and self.hide_downloaded_checkbox.isChecked():
                self._populate_results(self.mirror_results)
            else:
                self._refresh_result_row_statuses()
                self._update_selection_state()
            if errors and not successes:
                self._set_status(f"Mirror download failed: {errors[0]}", error=True)
                return
            success_model_count = len({str(payload.get("uid", "") or id(payload)) for payload, _download_result in successes})
            if errors:
                self._set_status(
                    f"Downloaded {len(successes):,} file(s) for {success_model_count:,} model(s); "
                    f"{len(errors):,} failed. First error: {errors[0]}",
                    error=True,
                )
            else:
                self._set_status(
                    f"Downloaded {len(successes):,} file(s) for {success_model_count:,} mirror model(s) to {output_root}. "
                    "The downloads folder is now listed under Local Folders."
                )
            if import_after or preview_after:
                if not successes:
                    return
                importable_success = next(
                    (
                        (payload, download_result)
                        for payload, download_result in successes
                        if download_result.import_path is not None
                        and is_importable_model_path(download_result.import_path)
                    ),
                    None,
                )
                if importable_success is None:
                    self._set_status("Downloaded archive does not contain an importable glTF/GLB model.", error=True)
                    return
                payload, download_result = importable_success
                if download_result.import_path is None or not is_importable_model_path(download_result.import_path):
                    self._set_status("Downloaded archive does not contain an importable glTF/GLB model.", error=True)
                    return
                if import_after:
                    self._set_status(f"Downloaded and extracted model; opening import setup from {download_result.import_path}.")
                    self.import_mesh_requested.emit(str(download_result.import_path), dict(payload))
                elif preview_after:
                    self._set_status(f"Downloaded and extracted model; opening preview from {download_result.import_path}.")
                    self.preview_mesh_requested.emit(str(download_result.import_path), dict(payload))

        self._run_task("Downloading mirror model(s)...", task, complete)

    def delete_selected_local_models(self) -> None:
        self._delete_local_payloads(self._local_delete_payloads())

    def _delete_local_payloads(self, payloads: list[dict[str, object]]) -> None:
        targets = self._local_delete_targets_for_payloads(payloads)
        if not targets:
            self._set_status("No local file or downloaded model folder is available to delete.", error=True)
            return
        if not self._confirm_delete_local_targets(targets):
            self._set_status("Delete cancelled.")
            return

        deleted: list[Path] = []
        errors: list[str] = []
        for target, _label in targets:
            try:
                if target.is_dir():
                    shutil.rmtree(target)
                elif target.is_file():
                    target.unlink()
                deleted.append(target)
            except OSError as exc:
                errors.append(f"{target}: {exc}")

        if deleted:
            self._texture_status_cache.clear()
            self.inline_preview_widget.clear_model("Select a downloaded or local model to preview it here.")
            self.inline_preview_stack.setCurrentWidget(self.inline_preview_widget)
            self._inline_preview_loaded_import_path = None
            self._inline_preview_loaded_payload = None
            self._inline_preview_loaded_texture_count = 0
            self._inline_preview_loaded_renderer_backend = ""
            self._pending_icon_generation_request_id = 0
            self._prepare_inline_preview_orientation_for_load(reset_orientation=True)
            self._clear_deleted_local_state(deleted)
            if self._active_results_view == "local" and self.local_roots:
                self.scan_local_roots()
            elif self._active_results_view == "mirror" and self.hide_downloaded_checkbox.isChecked():
                self._populate_results(self.mirror_results)
            else:
                self._refresh_result_row_statuses()
                self._update_selection_state()
        if errors:
            self._set_status(f"Deleted {len(deleted):,} local item(s); {len(errors):,} failed. First error: {errors[0]}", error=True)
            return
        self._set_status(f"Deleted {len(deleted):,} local item(s) from disk.")

    def import_selected_model(self) -> None:
        payload = self._selected_payload()
        if not payload:
            self._set_status("Select a model first.", error=True)
            return
        if payload.get("kind") == "mirror":
            import_path = self._resolve_payload_import_path(payload)
            if import_path is not None:
                self._set_status(f"Opening import setup from local model file: {import_path}")
                self.import_mesh_requested.emit(str(import_path), dict(payload))
                return
            self._set_status("Downloading and extracting model before import setup...")
            self.download_selected_model(import_after=True)
            return
        path = Path(str(payload.get("path", "") or ""))
        if not path.is_file():
            self._set_status(f"Local model file is missing: {path}", error=True)
            return
        import_path = self._resolve_payload_import_path(payload)
        if import_path is None:
            self._set_status(
                f"{path.suffix or 'This file'} can be browsed here, but the mesh importer currently accepts importable files or ZIPs containing: {', '.join(sorted(IMPORTABLE_MODEL_EXTENSIONS))}.",
                error=True,
            )
            return
        if import_path != path:
            self._set_status(f"Extracted ZIP and opening import setup from: {import_path}")
        self.import_mesh_requested.emit(str(import_path), dict(payload))

    def open_selected_location(self) -> None:
        payload = self._selected_payload()
        if not payload:
            return
        candidates = [
            payload.get("asset_dir"),
            payload.get("archive_path"),
            payload.get("import_path"),
            payload.get("path"),
        ]
        for value in candidates:
            if not value:
                continue
            path = Path(str(value))
            if path.is_file():
                QDesktopServices.openUrl(QUrl.fromLocalFile(str(path.parent)))
                return
            if path.is_dir():
                QDesktopServices.openUrl(QUrl.fromLocalFile(str(path)))
                return

    def open_selected_page(self) -> None:
        payload = self._selected_payload()
        if not payload:
            return
        url = str(payload.get("viewer_url", "") or payload.get("metadata_url", "") or "")
        if url:
            QDesktopServices.openUrl(QUrl(url))
            return
        path = Path(str(payload.get("path", "") or ""))
        if path.is_file():
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(path)))

    def _show_results_context_menu(self, position) -> None:
        item = self.results_tree.itemAt(position)
        if item is None:
            return
        self.results_tree.setCurrentItem(item)
        payload = self._payload_from_item(item)
        if payload is None:
            return

        menu = QMenu(self)
        is_checked = item.checkState(0) == Qt.CheckState.Checked
        check_action = menu.addAction("Uncheck Row" if is_checked else "Check Row")
        check_action.triggered.connect(
            lambda _checked=False, row=item, state=not is_checked: row.setCheckState(
                0,
                Qt.CheckState.Checked if state else Qt.CheckState.Unchecked,
            )
        )

        menu.addSeparator()
        kind = str(payload.get("kind", "") or "")
        mirror_url_ready = bool(self.mirror_url_edit.text().strip())
        if kind == "mirror":
            preview_here_action = menu.addAction("Preview Here")
            preview_here_action.setEnabled(self._payload_can_preview_here(payload))
            preview_here_action.triggered.connect(self.preview_selected_model_here)
            icon_action = menu.addAction("Generate Icon From Preview")
            icon_action.setEnabled(self._payload_can_preview_here(payload))
            icon_action.triggered.connect(self.generate_icon_from_preview)
            delete_local_action = menu.addAction("Delete Local Copy")
            delete_local_action.setEnabled(self._local_delete_target_for_payload(payload) is not None)
            delete_local_action.triggered.connect(lambda _checked=False, row_payload=payload: self._delete_local_payloads([row_payload]))
            download_action = menu.addAction("Download This")
            download_action.setEnabled(mirror_url_ready)
            download_action.triggered.connect(
                lambda _checked=False, row_payload=payload: self._download_mirror_payloads(
                    [row_payload],
                    import_after=False,
                    preview_after=False,
                )
            )
            download_import_action = menu.addAction("Download + Import This")
            download_import_action.setEnabled(mirror_url_ready)
            download_import_action.triggered.connect(
                lambda _checked=False, row_payload=payload: self._download_mirror_payloads(
                    [row_payload],
                    import_after=True,
                    preview_after=False,
                )
            )
            preview_action = menu.addAction("D3D11 Preview This")
            preview_action.setEnabled(mirror_url_ready or bool(payload.get("import_path")))
            preview_action.triggered.connect(self.preview_selected_model)
            urls_action = menu.addAction("Show File URLs for This")
            urls_action.triggered.connect(lambda _checked=False, row_payload=payload: self._show_file_urls_for_payloads([row_payload]))
            open_url_action = menu.addAction("Open Preferred File URL")
            open_url_action.triggered.connect(self.open_selected_file_url)
            page_action = menu.addAction("Open Model Page")
            page_action.triggered.connect(self.open_selected_page)
        else:
            preview_here_action = menu.addAction("Preview Here")
            preview_here_action.setEnabled(self._payload_can_preview_here(payload))
            preview_here_action.triggered.connect(self.preview_selected_model_here)
            icon_action = menu.addAction("Generate Icon From Preview")
            icon_action.setEnabled(self._payload_can_preview_here(payload))
            icon_action.triggered.connect(self.generate_icon_from_preview)
            preview_action = menu.addAction("Preview In Archive Browser")
            preview_action.setEnabled(self._payload_can_import(payload))
            preview_action.triggered.connect(self.preview_selected_model)
            import_action = menu.addAction("Import Mesh")
            import_action.setEnabled(self._payload_can_import(payload))
            import_action.triggered.connect(self.import_selected_model)
            location_action = menu.addAction("Open Folder")
            location_action.triggered.connect(self.open_selected_location)
            delete_local_action = menu.addAction("Delete Local File / Folder")
            delete_local_action.setEnabled(self._local_delete_target_for_payload(payload) is not None)
            delete_local_action.triggered.connect(lambda _checked=False, row_payload=payload: self._delete_local_payloads([row_payload]))

        checked_mirrors = [row_payload for row_payload in self._checked_payloads() if row_payload.get("kind") == "mirror"]
        if checked_mirrors:
            menu.addSeparator()
            download_checked_action = menu.addAction(f"Download Checked ({len(checked_mirrors)})")
            download_checked_action.setEnabled(mirror_url_ready)
            download_checked_action.triggered.connect(
                lambda _checked=False, checked_payloads=checked_mirrors: self._download_mirror_payloads(
                    checked_payloads,
                    import_after=False,
                    preview_after=False,
                )
            )
            urls_checked_action = menu.addAction(f"Show Checked File URLs ({len(checked_mirrors)})")
            urls_checked_action.triggered.connect(
                lambda _checked=False, checked_payloads=checked_mirrors: self._show_file_urls_for_payloads(checked_payloads)
            )

        checked_deletable = [
            row_payload
            for row_payload in self._checked_payloads()
            if self._local_delete_target_for_payload(row_payload) is not None
        ]
        if checked_deletable:
            menu.addSeparator()
            delete_checked_action = menu.addAction(f"Delete Checked Local Copies ({len(checked_deletable)})")
            delete_checked_action.triggered.connect(
                lambda _checked=False, checked_payloads=checked_deletable: self._delete_local_payloads(checked_payloads)
            )

        menu.addSeparator()
        select_all_action = menu.addAction("Select All")
        select_all_action.setEnabled(self.results_tree.topLevelItemCount() > 0)
        select_all_action.triggered.connect(lambda _checked=False: self._set_all_result_checks(True))
        select_none_action = menu.addAction("Select None")
        select_none_action.setEnabled(bool(self._checked_payloads()))
        select_none_action.triggered.connect(lambda _checked=False: self._set_all_result_checks(False))
        menu.exec(self.results_tree.viewport().mapToGlobal(position))

    def _filtered_result_rows(self, rows: list[dict[str, object]]) -> list[dict[str, object]]:
        self._last_hidden_downloaded_count = 0
        if self._active_results_view == "local":
            query = str(self.search_edit.text() if hasattr(self, "search_edit") else "").strip()
            if not query:
                return rows
            field = str(
                self.results_filter_field_combo.currentData()
                if hasattr(self, "results_filter_field_combo")
                else "all"
            )
            terms = [term.casefold() for term in re.findall(r"[^\s,;]+", query) if term.strip()]
            if not terms:
                return rows
            return [payload for payload in rows if self._local_payload_matches_filter(payload, terms, field)]
        if self._active_results_view != "mirror" or not getattr(self, "hide_downloaded_checkbox", None):
            return rows
        if not self.hide_downloaded_checkbox.isChecked():
            return rows
        visible: list[dict[str, object]] = []
        for payload in rows:
            if not isinstance(payload, dict) or payload.get("kind") != "mirror":
                visible.append(payload)
                continue
            if self._mirror_payload_downloaded(payload):
                self._last_hidden_downloaded_count += 1
                continue
            visible.append(payload)
        return visible

    def _local_payload_filter_values(self, payload: dict[str, object], field: str) -> list[str]:
        if field == "name":
            keys = ("name",)
        elif field == "creator":
            keys = ("creator_name", "creator_username", "source")
        elif field == "license":
            keys = ("license_label", "license_slug")
        elif field == "format":
            keys = ("extension", "format", "source")
        elif field == "path":
            keys = ("relative_path", "path", "root", "asset_dir", "archive_path", "import_path")
        elif field == "uid":
            keys = ("uid", "id")
        else:
            keys = (
                "name",
                "creator_name",
                "creator_username",
                "license_label",
                "license_slug",
                "extension",
                "format",
                "source",
                "relative_path",
                "path",
                "root",
                "asset_dir",
                "archive_path",
                "import_path",
                "uid",
                "id",
            )
        values: list[str] = []
        for key in keys:
            value = payload.get(key)
            if isinstance(value, (list, tuple, set)):
                values.extend(str(item) for item in value if str(item).strip())
            elif value is not None and str(value).strip():
                values.append(str(value))
        return values

    def _local_payload_matches_filter(self, payload: dict[str, object], terms: list[str], field: str) -> bool:
        if not isinstance(payload, dict):
            return False
        haystack = " ".join(self._local_payload_filter_values(payload, field)).casefold()
        return bool(haystack) and all(term in haystack for term in terms)

    def _mirror_payload_downloaded(self, payload: dict[str, object]) -> bool:
        if payload.get("kind") != "mirror":
            return False
        if str(payload.get("local_status", "") or "").strip():
            return True
        self._apply_mirror_local_state(payload)
        if str(payload.get("local_status", "") or "").strip():
            return True
        for key in ("import_path", "archive_path"):
            path_text = str(payload.get(key, "") or "").strip()
            if path_text and Path(path_text).is_file():
                return True
        asset_dir_text = str(payload.get("asset_dir", "") or "").strip()
        return bool(asset_dir_text and Path(asset_dir_text).is_dir())

    def _result_size_bytes(self, payload: dict[str, object]) -> int:
        if payload.get("kind") == "mirror":
            return self._mirror_size_bytes(payload)
        try:
            return int(payload.get("size", 0) or 0)
        except (TypeError, ValueError):
            return 0

    def _result_sort_text(self, payload: dict[str, object], column: int) -> str:
        if payload.get("kind") == "mirror":
            if column == 2:
                return "Mirror"
            if column == 3:
                self._apply_mirror_local_state(payload)
                return self._mirror_local_status(payload)
            if column == 4:
                return self._texture_status_for_payload(payload)
            if column == 5:
                return ", ".join(candidate.format for candidate in self._mirror_candidates_for_payload(payload))
            if column == 7:
                return str(payload.get("license_label", "") or "")
            if column == 8:
                return str(payload.get("creator_name", "") or payload.get("creator_username", "") or "")
            if column == 9:
                return str(payload.get("viewer_url", "") or payload.get("metadata_url", "") or "")
            return str(payload.get("name", "") or "Untitled model")
        if column == 2:
            return str(payload.get("source", "") or "Local")
        if column == 3:
            return self._local_payload_status(payload)
        if column == 4:
            return self._texture_status_for_payload(payload)
        if column == 5:
            return str(payload.get("extension", "") or "")
        if column == 7:
            return str(payload.get("license_label", "") or "")
        if column == 8:
            return str(payload.get("creator_name", "") or payload.get("creator_username", "") or "")
        if column == 9:
            return str(payload.get("relative_path", "") or payload.get("path", "") or "")
        return str(payload.get("name", "") or "Untitled model")

    def _sort_result_rows(self, rows: list[dict[str, object]]) -> list[dict[str, object]]:
        if int(self._result_sort_column) < 0:
            return list(rows)
        column = max(0, min(int(self._result_sort_column), self.results_tree.columnCount() - 1))
        descending = self._result_sort_order == Qt.SortOrder.DescendingOrder

        def sort_key(payload: dict[str, object]) -> tuple[object, object, str]:
            name = str(payload.get("name", "") or "Untitled model").casefold()
            if column == 6:
                return (self._result_size_bytes(payload), 0, name)
            text = self._result_sort_text(payload, column).casefold()
            numeric_name_rank = 1 if column == 1 and text.strip().isdigit() else 0
            return (numeric_name_rank, text, name)

        return sorted(rows, key=sort_key, reverse=descending)

    def _update_empty_results_message(self, visible_count: int, total_count: int) -> None:
        if not hasattr(self, "empty_results_label"):
            return
        message = ""
        if visible_count <= 0:
            if self._active_results_view == "mirror":
                hidden = int(getattr(self, "_last_hidden_downloaded_count", 0) or 0)
                if hidden and getattr(self, "hide_downloaded_checkbox", None) and self.hide_downloaded_checkbox.isChecked():
                    message = (
                        f"All {hidden:,} mirror result(s) are hidden because they are already downloaded. "
                        "Turn off Hide downloaded, search a different term, or delete local copies to show them again."
                    )
                elif total_count <= 0:
                    query = str(self.search_edit.text() if hasattr(self, "search_edit") else "").strip()
                    message = f"No mirror results found for \"{query}\"." if query else "No mirror results loaded. Search the mirror catalogue or show popular models."
            else:
                query = str(self.search_edit.text() if hasattr(self, "search_edit") else "").strip()
                if total_count > 0 and query:
                    message = f"No local models match \"{query}\". Clear the local filter or choose another field."
                else:
                    message = "No local models are loaded. Add a folder, then show local models."
        self.empty_results_label.setText(message)
        self.empty_results_label.setVisible(bool(message))

    def _populate_results(self, rows: list[dict[str, object]]) -> None:
        self._results_filter_timer.stop()
        self._results_population_timer.stop()
        self._auto_preview_timer.stop()
        selected_payload = self._selected_payload()
        total_count = len(rows)
        visible_rows = self._sort_result_rows(self._filtered_result_rows(rows))
        self._pending_results_rows = list(visible_rows)
        self._pending_results_total_count = total_count
        self._pending_results_visible_count = len(visible_rows)
        self._pending_results_selected_payload = selected_payload
        self._populating_results = True
        self.results_tree.setSortingEnabled(False)
        self.results_tree.blockSignals(True)
        self.results_tree.setUpdatesEnabled(False)
        self.results_tree.clear()
        self._result_payloads_by_item.clear()
        self.results_tree.setUpdatesEnabled(True)
        self.results_tree.blockSignals(False)
        self._update_empty_results_message(len(visible_rows), total_count)
        if visible_rows:
            self.results_status_label.setText(
                f"Populating results... 0 / {len(visible_rows):,}"
            )
        self._flush_results_population_batch()

    def _build_result_item(self, payload: dict[str, object]) -> QTreeWidgetItem:
        kind = str(payload.get("kind", "") or "")
        if kind == "mirror":
            self._apply_mirror_local_state(payload)
            formats = ", ".join(candidate.format for candidate in self._mirror_candidates_for_payload(payload)) or "-"
            size_bytes = self._mirror_size_bytes(payload)
            size = self._format_size(size_bytes) if size_bytes > 0 else "-"
            location = str(payload.get("viewer_url", "") or payload.get("metadata_url", "") or "")
            source = "Mirror"
            local_status = self._mirror_local_status(payload)
            texture_status = self._texture_status_for_payload(payload)
            license_label = str(payload.get("license_label", "") or "")
            creator = str(payload.get("creator_name", "") or payload.get("creator_username", "") or "")
        else:
            formats = str(payload.get("extension", "") or "")
            size_bytes = int(payload.get("size", 0) or 0)
            size = self._format_size(size_bytes)
            location = str(payload.get("relative_path", "") or payload.get("path", "") or "")
            source = str(payload.get("source", "") or "Local")
            local_status = self._local_payload_status(payload)
            texture_status = self._texture_status_for_payload(payload)
            license_label = str(payload.get("license_label", "") or "")
            creator = str(payload.get("creator_name", "") or payload.get("creator_username", "") or "")
        item = QTreeWidgetItem(
            [
                "",
                str(payload.get("name", "") or "Untitled model"),
                source,
                local_status,
                texture_status,
                formats,
                size,
                license_label,
                creator,
                location,
            ]
        )
        item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
        item.setCheckState(0, Qt.CheckState.Unchecked)
        item.setData(0, Qt.ItemDataRole.UserRole, payload)
        item.setData(1, Qt.ItemDataRole.UserRole, payload)
        self._result_payloads_by_item[id(item)] = payload
        return item

    def _payload_population_key(self, payload: Optional[dict[str, object]]) -> tuple[str, str, str]:
        if not isinstance(payload, dict):
            return ("", "", "")
        return (
            str(payload.get("kind", "") or ""),
            str(payload.get("uid", "") or payload.get("id", "") or ""),
            str(payload.get("import_path", "") or payload.get("path", "") or payload.get("relative_path", "") or payload.get("name", "") or ""),
        )

    def _finish_results_population(self) -> None:
        self.results_tree.setSortingEnabled(False)
        target_item: Optional[QTreeWidgetItem] = None
        selected_key = self._payload_population_key(self._pending_results_selected_payload)
        if any(selected_key):
            for index in range(self.results_tree.topLevelItemCount()):
                item = self.results_tree.topLevelItem(index)
                payload = self._payload_from_item(item)
                if payload is self._pending_results_selected_payload or self._payload_population_key(payload) == selected_key:
                    target_item = item
                    break
        if target_item is None and self.results_tree.topLevelItemCount() > 0:
            target_item = self.results_tree.topLevelItem(0)
        if target_item is not None:
            self.results_tree.setCurrentItem(target_item)
        self._pending_results_rows = []
        self._pending_results_selected_payload = None
        self._populating_results = False
        self._update_selection_state()
        self._schedule_auto_inline_preview()

    def _flush_results_population_batch(self) -> None:
        if not self._pending_results_rows:
            self._finish_results_population()
            return
        batch = self._pending_results_rows[: self.RESULTS_POPULATION_BATCH_SIZE]
        del self._pending_results_rows[: self.RESULTS_POPULATION_BATCH_SIZE]
        items = [self._build_result_item(payload) for payload in batch]
        self.results_tree.setUpdatesEnabled(False)
        self.results_tree.addTopLevelItems(items)
        self.results_tree.setUpdatesEnabled(True)
        populated = self._pending_results_visible_count - len(self._pending_results_rows)
        self.results_status_label.setText(
            f"Populating results... {populated:,} / {self._pending_results_visible_count:,}"
        )
        if self._pending_results_rows:
            self._results_population_timer.start()
            return
        self._finish_results_population()

    def _update_selection_state(self) -> None:
        payload = self._selected_payload()
        checked_payloads = self._checked_payloads()
        batch_payloads = self._batch_action_payloads()
        batch_mirror_count = sum(1 for selected in batch_payloads if selected.get("kind") == "mirror")
        delete_payloads = self._local_delete_payloads()
        checked_count = len(checked_payloads)
        result_count = self.results_tree.topLevelItemCount()
        mirror_url_ready = bool(self.mirror_url_edit.text().strip())
        has_selection = bool(payload)
        is_mirror = bool(payload and payload.get("kind") == "mirror")
        is_local = bool(payload and payload.get("kind") == "local")
        local_importable = bool(is_local and self._payload_can_import(payload))
        mirror_importable = bool(is_mirror)
        can_preview_here = self._payload_can_preview_here(payload)
        self.import_mesh_button.setEnabled(has_selection and (local_importable or mirror_importable))
        self.preview_button.setEnabled(can_preview_here)
        self.generate_icon_button.setEnabled(can_preview_here)
        self.download_button.setEnabled(batch_mirror_count > 0 and mirror_url_ready)
        self.download_button.setText("Download Checked" if batch_mirror_count <= 1 else f"Download Checked ({batch_mirror_count})")
        self.download_import_button.setEnabled(is_mirror and mirror_url_ready)
        self.open_file_url_button.setEnabled(is_mirror)
        self.open_location_button.setEnabled(has_selection)
        self.open_page_button.setEnabled(has_selection)
        self.delete_local_button.setEnabled(bool(delete_payloads))
        self.delete_local_button.setText("Delete Local" if len(delete_payloads) <= 1 else f"Delete Local ({len(delete_payloads)})")
        self.more_actions_button.setEnabled(
            bool(
                (is_mirror and mirror_url_ready)
                or is_mirror
                or has_selection
                or delete_payloads
            )
        )
        self.select_all_button.setEnabled(result_count > 0)
        self.select_none_button.setEnabled(checked_count > 0)
        self.remove_local_root_button.setEnabled(self.roots_tree.currentItem() is not None)
        if result_count:
            view_name = "Local Library" if self._active_results_view == "local" else "Mirror Catalogue"
            self.results_status_label.setText(f"{view_name}: {result_count:,} result(s) | {checked_count:,} checked")
        else:
            view_name = "Local Library" if self._active_results_view == "local" else "Mirror Catalogue"
            hidden = int(getattr(self, "_last_hidden_downloaded_count", 0) or 0)
            if self._active_results_view == "mirror" and hidden and self.hide_downloaded_checkbox.isChecked():
                self.results_status_label.setText(f"{view_name}: 0 visible result(s) | {hidden:,} downloaded hidden")
            else:
                self.results_status_label.setText(f"{view_name}: 0 result(s)")
        self._show_details(payload)

    def _show_details(self, payload: Optional[dict[str, object]]) -> None:
        if not payload:
            self.details_edit.clear()
            self.details_text.setText("Select a local file or mirror result.")
            return
        name = str(payload.get("name", "") or "Untitled model")
        self.details_edit.setText(name)
        if payload.get("kind") == "mirror":
            candidates = self._mirror_candidates_for_payload(payload)
            lines = [
                f"UID: {payload.get('uid', '')}",
                f"Creator: {payload.get('creator_name', '') or payload.get('creator_username', '') or '-'}",
                f"License: {payload.get('license_label', '') or '-'}",
                f"Formats: {', '.join(candidate.label for candidate in candidates) or '-'}",
                f"Faces: {self._format_count(payload.get('face_count'))}",
                f"Vertices: {self._format_count(payload.get('vertex_count'))}",
                f"Views: {self._format_count(payload.get('view_count'))}",
                f"Likes: {self._format_count(payload.get('like_count'))}",
                f"Local status: {self._mirror_local_status(payload) or 'Not downloaded'}",
                f"Textures: {self._texture_status_for_payload(payload)}",
            ]
            if candidates:
                lines.append("")
                lines.append("File URLs:")
                lines.extend(f"- {candidate.label}: {candidate.url}" for candidate in candidates)
            lines.append("")
            lines.append("Downloads are enabled after you enter the mirror URL. Downloaded files are stored under the catalogue downloads folder.")
            if payload.get("asset_dir"):
                lines.append(f"Local: {payload.get('asset_dir')}")
            if payload.get("archive_path"):
                lines.append(f"Archive: {payload.get('archive_path')}")
            if payload.get("import_path"):
                lines.append(f"Resolved import file: {payload.get('import_path')}")
            if payload.get("viewer_url"):
                lines.append(f"Page: {payload.get('viewer_url')}")
            description = str(payload.get("description", "") or "").strip()
            if description:
                lines.append("")
                lines.append(description[:1600])
            self.details_text.setText("\n".join(lines))
            return
        path = Path(str(payload.get("path", "") or ""))
        lines = [
            f"Path: {path}",
            f"Root: {payload.get('root', '')}",
            f"Format: {payload.get('extension', '')}",
            f"Size: {self._format_size(int(payload.get('size', 0) or 0))}",
            f"Modified: {self._format_time(float(payload.get('modified_at', 0.0) or 0.0))}",
            f"Local status: {self._local_payload_status(payload)}",
            f"Textures: {self._texture_status_for_payload(payload)}",
            "Import: supported" if self._payload_can_import(payload) else "Import: browse only",
        ]
        if payload.get("creator_name") or payload.get("creator_username"):
            lines.append(f"Creator: {payload.get('creator_name', '') or payload.get('creator_username', '')}")
        if payload.get("license_label"):
            lines.append(f"License: {payload.get('license_label')}")
        if payload.get("viewer_url"):
            lines.append(f"Page: {payload.get('viewer_url')}")
        if payload.get("asset_dir"):
            lines.append(f"Asset folder: {payload.get('asset_dir')}")
        import_path = str(payload.get("import_path", "") or "")
        if import_path:
            lines.append(f"Resolved import file: {import_path}")
        audit_category = str(payload.get("audit_category", "") or "")
        if audit_category:
            confidence = float(payload.get("audit_confidence", 0.0) or 0.0)
            texture_slots = ", ".join(str(slot) for slot in tuple(payload.get("audit_texture_slots", ()) or ())) or "-"
            workflows = ", ".join(str(workflow) for workflow in tuple(payload.get("audit_workflows", ()) or ())) or "-"
            flags = []
            if payload.get("audit_false_positive"):
                flags.append("false-positive")
            if payload.get("audit_mixed_model"):
                flags.append("mixed")
            suffix = f" ({', '.join(flags)})" if flags else ""
            lines.append(f"Audit: {audit_category} {confidence:.0%}{suffix}; textures: {texture_slots}; PBR: {workflows}")
            for warning in tuple(payload.get("audit_warnings", ()) or ())[:3]:
                lines.append(f"Audit warning: {warning}")
        archive_path = str(payload.get("archive_path", "") or "")
        if archive_path:
            lines.append(f"Archive: {archive_path}")
        self.details_text.setText("\n".join(lines))

    def _selected_payload(self) -> Optional[dict[str, object]]:
        item = self.results_tree.currentItem()
        return self._payload_from_item(item)

    def _selected_payloads(self) -> list[dict[str, object]]:
        payloads: list[dict[str, object]] = []
        seen_items: set[int] = set()
        for item in self.results_tree.selectedItems():
            item_id = id(item)
            if item_id in seen_items:
                continue
            payload = self._payload_from_item(item)
            if isinstance(payload, dict):
                seen_items.add(item_id)
                payloads.append(payload)
        current_item = self.results_tree.currentItem()
        current = self._selected_payload()
        if current is not None and (current_item is None or id(current_item) not in seen_items):
            payloads.append(current)
        return payloads

    def _payload_from_item(self, item: Optional[QTreeWidgetItem]) -> Optional[dict[str, object]]:
        if item is None:
            return None
        mapped_payload = self._result_payloads_by_item.get(id(item))
        if mapped_payload is not None:
            return mapped_payload
        for column in (0, 1):
            payload = item.data(column, Qt.ItemDataRole.UserRole)
            if isinstance(payload, dict):
                return payload
        return None

    def _checked_payloads(self) -> list[dict[str, object]]:
        payloads: list[dict[str, object]] = []
        for index in range(self.results_tree.topLevelItemCount()):
            item = self.results_tree.topLevelItem(index)
            if item.checkState(0) != Qt.CheckState.Checked:
                continue
            payload = self._payload_from_item(item)
            if payload is not None:
                payloads.append(payload)
        return payloads

    def _batch_action_payloads(self) -> list[dict[str, object]]:
        return self._checked_payloads()

    def _set_all_result_checks(self, checked: bool) -> None:
        state = Qt.CheckState.Checked if checked else Qt.CheckState.Unchecked
        self.results_tree.blockSignals(True)
        try:
            for index in range(self.results_tree.topLevelItemCount()):
                self.results_tree.topLevelItem(index).setCheckState(0, state)
        finally:
            self.results_tree.blockSignals(False)
        self._update_selection_state()

    def _local_delete_payloads(self) -> list[dict[str, object]]:
        checked_payloads = [
            payload
            for payload in self._checked_payloads()
            if self._local_delete_target_for_payload(payload) is not None
        ]
        if checked_payloads:
            return checked_payloads
        current = self._selected_payload()
        if current is not None and self._local_delete_target_for_payload(current) is not None:
            return [current]
        return []

    def _local_delete_targets_for_payloads(self, payloads: list[dict[str, object]]) -> list[tuple[Path, str]]:
        targets: list[tuple[Path, str]] = []
        seen: set[str] = set()
        for payload in payloads:
            target = self._local_delete_target_for_payload(payload)
            if target is None:
                continue
            path, label = target
            try:
                resolved_key = str(path.resolve()).casefold()
            except OSError:
                resolved_key = str(path.absolute()).casefold()
            if resolved_key in seen:
                continue
            seen.add(resolved_key)
            targets.append((path, label))
        return targets

    def _local_delete_target_for_payload(self, payload: Optional[dict[str, object]]) -> Optional[tuple[Path, str]]:
        if not payload:
            return None
        asset_dir_text = str(payload.get("asset_dir", "") or "").strip()
        if asset_dir_text:
            asset_dir = Path(asset_dir_text)
            if asset_dir.is_dir() and (asset_dir / "model_metadata.json").is_file():
                return asset_dir, "downloaded model folder"
        archive_path = Path(str(payload.get("archive_path", "") or ""))
        try:
            download_root = self._download_output_root().resolve()
        except OSError:
            download_root = self._download_output_root().absolute()
        if archive_path.is_file() and self._download_metadata_path_for_local_path(archive_path, download_root) is not None:
            metadata_path = self._download_metadata_path_for_local_path(archive_path, download_root)
            if metadata_path is not None and metadata_path.parent.is_dir():
                return metadata_path.parent, "downloaded model folder"
        path = Path(str(payload.get("path", "") or ""))
        if payload.get("kind") == "local" and path.is_file():
            return path, "local model file"
        return None

    def _confirm_delete_local_targets(self, targets: list[tuple[Path, str]]) -> bool:
        if not targets:
            return False
        box = QMessageBox(self)
        box.setWindowTitle("Delete Local Models")
        box.setIcon(QMessageBox.Warning)
        box.setText(f"Delete {len(targets):,} local item(s) from disk?")
        listed = "\n".join(f"- {label}: {path}" for path, label in targets[:8])
        if len(targets) > 8:
            listed = f"{listed}\n- ... {len(targets) - 8:,} more"
        box.setInformativeText(
            "Downloaded mirror rows delete their whole downloaded model folder. "
            "Regular local rows delete only the selected model file.\n\n"
            f"{listed}"
        )
        delete_button = box.addButton("Delete", QMessageBox.DestructiveRole)
        box.addButton(QMessageBox.Cancel)
        box.setDefaultButton(QMessageBox.Cancel)
        box.exec()
        return box.clickedButton() == delete_button

    def _clear_deleted_local_state(self, deleted_targets: list[Path]) -> None:
        def is_deleted_path(value: object) -> bool:
            text = str(value or "").strip()
            if not text:
                return False
            path = Path(text)
            try:
                resolved_path = path.resolve()
            except OSError:
                resolved_path = path.absolute()
            for target in deleted_targets:
                try:
                    resolved_target = target.resolve()
                except OSError:
                    resolved_target = target.absolute()
                if resolved_path == resolved_target or resolved_target in resolved_path.parents:
                    return True
            return False

        for payload in self.mirror_results:
            if any(is_deleted_path(payload.get(key)) for key in ("asset_dir", "archive_path", "import_path")):
                for key in ("asset_dir", "archive_path", "import_path", "download_format", "local_status"):
                    payload.pop(key, None)
        self.local_models = [
            payload
            for payload in self.local_models
            if not any(is_deleted_path(payload.get(key)) for key in ("asset_dir", "archive_path", "import_path", "path"))
        ]

    def _download_output_root(self) -> Path:
        return self.catalogue_dir() / "downloads"

    def _normalize_local_model_rows(self, rows: list[dict[str, object]]) -> list[dict[str, object]]:
        download_root = self._download_output_root()
        try:
            resolved_download_root = download_root.resolve()
        except OSError:
            resolved_download_root = download_root.absolute()

        grouped: dict[str, list[dict[str, object]]] = {}
        grouped_metadata: dict[str, dict[str, object]] = {}
        passthrough: list[dict[str, object]] = []

        for row in rows:
            path = Path(str(row.get("path", "") or ""))
            metadata_path = self._download_metadata_path_for_local_path(path, resolved_download_root)
            if metadata_path is None:
                passthrough.append(row)
                continue
            asset_dir = metadata_path.parent
            key = str(asset_dir).casefold()
            grouped.setdefault(key, []).append(row)
            if key not in grouped_metadata:
                grouped_metadata[key] = self._read_download_metadata(metadata_path)

        normalized = list(passthrough)
        for key, group_rows in grouped.items():
            metadata = grouped_metadata.get(key) or {}
            metadata_path = self._metadata_path_from_group(group_rows, resolved_download_root)
            if metadata_path is None:
                normalized.extend(group_rows)
                continue
            normalized.append(self._download_group_local_row(metadata_path.parent, metadata, group_rows, resolved_download_root))

        normalized.sort(key=lambda item: (str(item.get("name", "") or "").lower(), str(item.get("path", "") or "").lower()))
        return normalized

    def _download_metadata_path_for_local_path(self, path: Path, download_root: Path) -> Optional[Path]:
        try:
            resolved_path = path.resolve()
        except OSError:
            resolved_path = path.absolute()
        if download_root != resolved_path and download_root not in resolved_path.parents:
            return None
        start = resolved_path.parent if resolved_path.is_file() else resolved_path
        for candidate_dir in (start, *start.parents):
            if candidate_dir == download_root.parent:
                break
            metadata_path = candidate_dir / "model_metadata.json"
            if metadata_path.is_file():
                return metadata_path
            if candidate_dir == download_root:
                break
        return None

    def _read_download_metadata(self, metadata_path: Path) -> dict[str, object]:
        try:
            payload = json.loads(metadata_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return {}
        return dict(payload) if isinstance(payload, dict) else {}

    def _metadata_path_from_group(self, group_rows: list[dict[str, object]], download_root: Path) -> Optional[Path]:
        for row in group_rows:
            metadata_path = self._download_metadata_path_for_local_path(Path(str(row.get("path", "") or "")), download_root)
            if metadata_path is not None:
                return metadata_path
        return None

    def _download_group_local_row(
        self,
        asset_dir: Path,
        metadata: dict[str, object],
        group_rows: list[dict[str, object]],
        download_root: Path,
    ) -> dict[str, object]:
        import_path = self._find_importable_file_under(asset_dir)
        archive_path = self._preferred_download_archive_path(asset_dir, metadata, group_rows)
        display_path = import_path or archive_path or Path(str(group_rows[0].get("path", "") or asset_dir))
        try:
            relative_path = str(display_path.relative_to(download_root))
        except ValueError:
            relative_path = str(display_path)
        size = 0
        for candidate in (archive_path, display_path):
            if candidate is not None and candidate.is_file():
                try:
                    size = int(candidate.stat().st_size)
                    break
                except OSError:
                    pass
        modified_at = 0.0
        for row in group_rows:
            try:
                modified_at = max(modified_at, float(row.get("modified_at", 0.0) or 0.0))
            except (TypeError, ValueError):
                pass
        creator_payload = metadata.get("user") if isinstance(metadata.get("user"), dict) else {}
        creator_name = str(metadata.get("creator_name", "") or creator_payload.get("displayName", "") or creator_payload.get("username", "") or "")
        creator_username = str(metadata.get("creator_username", "") or creator_payload.get("username", "") or "")
        license_payload = metadata.get("license") if isinstance(metadata.get("license"), dict) else {}
        license_label = str(metadata.get("license_label", "") or license_payload.get("label", "") or "")
        import_supported = bool(import_path and import_path.is_file())
        if not import_supported and display_path.suffix.lower() == ".zip":
            import_supported = zip_contains_importable_model(display_path)
        row = {
            "kind": "local",
            "name": str(metadata.get("name", "") or display_path.stem),
            "path": str(display_path),
            "root": str(download_root),
            "relative_path": relative_path,
            "extension": display_path.suffix.lower(),
            "size": size,
            "modified_at": modified_at,
            "import_supported": import_supported,
            "source": "Downloaded",
            "asset_dir": str(asset_dir),
            "archive_path": str(archive_path) if archive_path is not None else "",
            "import_path": str(import_path) if import_path is not None else "",
            "uid": str(metadata.get("uid", "") or metadata.get("id", "") or ""),
            "viewer_url": str(metadata.get("viewer_url", "") or metadata.get("viewerUrl", "") or ""),
            "license_label": license_label,
            "creator_name": creator_name,
            "creator_username": creator_username,
        }
        row["texture_status"] = self._texture_status_for_payload(row)
        return row

    def _preferred_download_archive_path(
        self,
        asset_dir: Path,
        metadata: dict[str, object],
        group_rows: list[dict[str, object]],
    ) -> Optional[Path]:
        uid = str(metadata.get("uid", "") or metadata.get("id", "") or "")
        candidates: list[Path] = []
        if uid:
            candidates.extend([asset_dir / f"{uid}.zip", asset_dir / f"{uid}.glb", asset_dir / f"{uid}.source.zip"])
        for row in group_rows:
            path = Path(str(row.get("path", "") or ""))
            if path.is_file() and path.suffix.lower() in {".zip", ".glb"}:
                candidates.append(path)
        for candidate in candidates:
            if candidate.is_file() and not candidate.name.lower().endswith(".source.zip"):
                return candidate
        for candidate in candidates:
            if candidate.is_file():
                return candidate
        return None

    def _ensure_download_root_registered(self, output_root: Path) -> None:
        output_root.mkdir(parents=True, exist_ok=True)
        try:
            normalized = str(output_root.resolve())
        except OSError:
            normalized = str(output_root.absolute())
        if normalized not in self.local_roots:
            self.local_roots.append(normalized)
            self._save_roots()
            self._refresh_roots_tree()
        if not self.local_path_edit.text().strip():
            self.local_path_edit.setText(normalized)

    def _payload_can_import(self, payload: Optional[dict[str, object]]) -> bool:
        if not payload:
            return False
        if payload.get("kind") == "mirror":
            return True
        if bool(payload.get("import_supported")):
            return True
        path = Path(str(payload.get("path", "") or ""))
        return path.suffix.lower() == ".zip" and zip_contains_importable_model(path)

    def _payload_can_preview_here(self, payload: Optional[dict[str, object]]) -> bool:
        if not payload:
            return False
        if payload.get("kind") == "mirror":
            self._apply_mirror_local_state(payload)
            return self._mirror_local_status(payload) in {"Ready", "ZIP ready"}
        return self._payload_can_import(payload)

    def _set_inline_preview_status(self, message: str, *, error: bool = False) -> None:
        if hasattr(self, "inline_preview_status_label"):
            self.inline_preview_status_label.setText(message)
        self.status_message_requested.emit(message, error)

    def _attach_inline_preview_textures(
        self,
        preview_model: object,
        scene_result: object,
        scene_path: Path,
    ) -> int:
        if not isinstance(scene_result, SceneImportResult):
            return 0
        return attach_scene_preview_textures(preview_model, scene_result, scene_path)

    def _inline_preview_material_channel_summary(self, prepared_preview: object) -> str:
        batches = tuple(getattr(prepared_preview, "batches", ()) or ())
        if not batches:
            return ""
        channel_counts: dict[str, int] = defaultdict(int)
        unresolved_counts: dict[str, int] = defaultdict(int)
        for batch in batches:
            textures = {
                "base": str(getattr(batch, "preview_texture_path", "") or ""),
                "normal": str(getattr(batch, "preview_normal_texture_path", "") or ""),
                "material": str(getattr(batch, "preview_material_texture_path", "") or ""),
                "height": str(getattr(batch, "preview_height_texture_path", "") or ""),
            }
            dds_textures = {
                "base": {"source_path": str(getattr(batch, "preview_texture_dds_path", "") or ""), "confidence": "exact"},
                "normal": {"source_path": str(getattr(batch, "preview_normal_texture_dds_path", "") or ""), "confidence": "exact"},
                "material": {"source_path": str(getattr(batch, "preview_material_texture_dds_path", "") or ""), "confidence": "unresolved"},
                "height": {"source_path": str(getattr(batch, "preview_height_texture_dds_path", "") or ""), "confidence": "unresolved"},
            }
            payload = {
                "material_name": str(getattr(batch, "material_name", "") or ""),
                "texture_name": str(getattr(batch, "texture_name", "") or ""),
                "textures": {slot: value for slot, value in textures.items() if value},
                "dds_textures": {slot: value for slot, value in dds_textures.items() if str(value.get("source_path", "") or "")},
                "material_contract": {
                    "texture_slots": {
                        slot: {
                            "confidence": dds_textures.get(slot, {}).get("confidence", "inferred"),
                            "diagnostic": "Model Library resolved preview texture",
                        }
                        for slot, value in textures.items()
                        if value or str(dds_textures.get(slot, {}).get("source_path", "") or "")
                    },
                    "packed_channels": tuple(getattr(batch, "preview_material_texture_packed_channels", ()) or ()),
                },
            }
            contract = resolve_preview_batch_material_channels(payload)
            for channel in contract.channels.values():
                channel_counts[channel.sketchfab_channel or channel.channel] += 1
            for unresolved in contract.unresolved:
                slot = str(unresolved.get("slot", "") or "").strip()
                if slot:
                    unresolved_counts[slot] += 1
        channel_text = ", ".join(f"{name}:{count}" for name, count in sorted(channel_counts.items())[:8]) or "none"
        unresolved_text = ", ".join(f"{name}:{count}" for name, count in sorted(unresolved_counts.items())[:6])
        return f"{channel_text}; unresolved {unresolved_text}" if unresolved_text else channel_text

    def _resolve_payload_import_path(self, payload: dict[str, object]) -> Optional[Path]:
        if payload.get("kind") == "mirror":
            self._apply_mirror_local_state(payload)
            import_path = Path(str(payload.get("import_path", "") or ""))
            if import_path.is_file() and is_importable_model_path(import_path):
                return import_path
            archive_path = Path(str(payload.get("archive_path", "") or ""))
            if archive_path.is_file():
                asset_dir = Path(str(payload.get("asset_dir", "") or archive_path.parent))
                extract_root = asset_dir / "gltf" if archive_path.suffix.lower() == ".zip" else None
                resolved = resolve_importable_model_path(archive_path, extract_root=extract_root)
                if resolved is not None:
                    payload["import_path"] = str(resolved)
                    payload["local_status"] = self._mirror_local_status(payload)
                    self._refresh_result_row_statuses()
                    return resolved
            return None
        import_path = Path(str(payload.get("import_path", "") or ""))
        if import_path.is_file() and is_importable_model_path(import_path):
            return import_path
        path = Path(str(payload.get("path", "") or ""))
        if not path.is_file():
            return None
        resolved = resolve_importable_model_path(path)
        if resolved is not None:
            payload["import_path"] = str(resolved)
            payload["import_supported"] = True
            self._refresh_result_row_statuses()
        return resolved

    def _apply_mirror_local_state(self, payload: dict[str, object]) -> None:
        if payload.get("kind") != "mirror":
            return
        asset_dir = self._existing_mirror_asset_dir(payload)
        if asset_dir is not None:
            payload["asset_dir"] = str(asset_dir)
        archive_path = self._existing_mirror_archive_path(payload, asset_dir)
        if archive_path is not None:
            payload["archive_path"] = str(archive_path)
        import_path = Path(str(payload.get("import_path", "") or ""))
        if not import_path.is_file():
            if archive_path is not None and archive_path.suffix.lower() == ".glb":
                payload["import_path"] = str(archive_path)
            elif asset_dir is not None:
                discovered = self._find_importable_file_under(asset_dir)
                if discovered is not None:
                    payload["import_path"] = str(discovered)
        payload["local_status"] = self._mirror_local_status(payload)

    def _existing_mirror_asset_dir(self, payload: dict[str, object]) -> Optional[Path]:
        asset_dir_text = str(payload.get("asset_dir", "") or "").strip()
        if asset_dir_text:
            asset_dir = Path(asset_dir_text)
            if asset_dir.is_dir():
                return asset_dir
        uid = str(payload.get("uid", "") or "").strip()
        if not uid:
            return None
        output_root = self._download_output_root()
        if not output_root.is_dir():
            return None
        matches = [path for path in output_root.glob(f"*-{uid}") if path.is_dir()]
        if not matches:
            return None
        matches.sort(key=lambda path: path.stat().st_mtime if path.exists() else 0.0, reverse=True)
        return matches[0]

    def _existing_mirror_archive_path(self, payload: dict[str, object], asset_dir: Optional[Path]) -> Optional[Path]:
        archive_path = Path(str(payload.get("archive_path", "") or ""))
        if archive_path.is_file():
            return archive_path
        if asset_dir is None or not asset_dir.is_dir():
            return None
        for candidate in self._mirror_candidates_for_payload(payload):
            path = asset_dir / str(getattr(candidate, "filename", "") or "")
            if path.is_file():
                return path
        archives = sorted(
            [path for path in asset_dir.iterdir() if path.is_file() and path.suffix.lower() in {".zip", ".glb"}],
            key=lambda path: path.name.lower(),
        )
        return archives[0] if archives else None

    def _find_importable_file_under(self, root: Path) -> Optional[Path]:
        priority = {".gltf": 0, ".glb": 1, ".obj": 2, ".dae": 3}
        candidates = [
            path
            for path in root.rglob("*")
            if path.is_file() and is_importable_model_path(path)
        ]
        if not candidates:
            return None
        candidates.sort(key=lambda path: (priority.get(path.suffix.lower(), 99), str(path).lower()))
        return candidates[0]

    def _mirror_local_status(self, payload: dict[str, object]) -> str:
        import_path = Path(str(payload.get("import_path", "") or ""))
        if import_path.is_file() and is_importable_model_path(import_path):
            return "Ready"
        archive_path = Path(str(payload.get("archive_path", "") or ""))
        if archive_path.is_file():
            if archive_path.suffix.lower() == ".zip" and zip_contains_importable_model(archive_path):
                return "ZIP ready"
            return "Downloaded"
        return ""

    def _local_payload_status(self, payload: dict[str, object]) -> str:
        if self._payload_can_import(payload):
            path = Path(str(payload.get("path", "") or ""))
            if path.suffix.lower() == ".zip":
                return "ZIP ready"
            return "Ready"
        if Path(str(payload.get("path", "") or "")).suffix.lower() == ".zip":
            return "ZIP"
        return "Browse"

    def _texture_status_for_payload(self, payload: dict[str, object]) -> str:
        existing = str(payload.get("texture_status", "") or "").strip()
        if existing:
            return existing
        if payload.get("kind") == "mirror":
            self._apply_mirror_local_state(payload)
            asset_dir_text = str(payload.get("asset_dir", "") or "").strip()
            asset_dir = Path(asset_dir_text) if asset_dir_text else None
            if asset_dir is not None and asset_dir.is_dir():
                count = self._count_texture_files(asset_dir, recursive=True)
                if count > 0:
                    return f"Found ({count})"
            archive_path_text = str(payload.get("archive_path", "") or "").strip()
            archive_path = Path(archive_path_text) if archive_path_text else None
            if archive_path is not None and archive_path.is_file():
                return self._texture_status_for_model_path(archive_path, payload)
            return "Download to check"
        asset_dir_text = str(payload.get("asset_dir", "") or "").strip()
        asset_dir = Path(asset_dir_text) if asset_dir_text else None
        if asset_dir is not None and asset_dir.is_dir():
            count = self._count_texture_files(asset_dir, recursive=True)
            if count > 0:
                return f"Found ({count})"
        archive_path_text = str(payload.get("archive_path", "") or "").strip()
        archive_path = Path(archive_path_text) if archive_path_text else None
        if archive_path is not None and archive_path.is_file():
            return self._texture_status_for_model_path(archive_path, payload)
        path_text = str(payload.get("path", "") or "").strip()
        path = Path(path_text) if path_text else None
        if path is not None and path.is_file():
            return self._texture_status_for_model_path(path, payload)
        return "Unknown"

    def _texture_status_for_model_path(self, path: Path, payload: Optional[dict[str, object]] = None) -> str:
        suffix = path.suffix.lower()
        if suffix == ".zip":
            count = self._count_zip_texture_members(path)
            return f"In ZIP ({count})" if count > 0 else "None found"
        if suffix == ".glb":
            return "Embedded/Unknown"
        import_path_text = str((payload or {}).get("import_path", "") or "").strip()
        import_path = Path(import_path_text) if import_path_text else path
        if import_path.is_file():
            if import_path.suffix.lower() == ".glb":
                return "Embedded/Unknown"
            count = self._nearby_texture_count(import_path)
            return f"Found ({count})" if count > 0 else "None found"
        return "Unknown"

    def _nearby_texture_count(self, scene_path: Path) -> int:
        roots: list[tuple[Path, bool]] = [
            (scene_path.parent, False),
            (scene_path.parent / "textures", True),
            (scene_path.parent / "texture", True),
            (scene_path.parent.parent / "textures", True),
            (scene_path.parent.parent / "texture", True),
        ]
        seen_roots: set[str] = set()
        total = 0
        for root, recursive in roots:
            if not root.is_dir():
                continue
            try:
                key = str(root.resolve()).casefold()
            except OSError:
                key = str(root.absolute()).casefold()
            if key in seen_roots:
                continue
            seen_roots.add(key)
            total += self._count_texture_files(root, recursive=recursive)
        return total

    def _count_texture_files(self, root: Path, *, recursive: bool, limit: int = 999) -> int:
        try:
            resolved = root.resolve()
        except OSError:
            resolved = root.absolute()
        cache_key = (str(resolved).casefold(), "r" if recursive else "flat")
        cached = self._texture_status_cache.get(cache_key)
        if cached is not None:
            return cached
        count = 0
        iterator = resolved.rglob("*") if recursive else resolved.iterdir()
        try:
            for candidate in iterator:
                if candidate.is_file() and candidate.suffix.lower() in SCENE_TEXTURE_SOURCE_EXTENSIONS:
                    count += 1
                    if count >= limit:
                        break
        except OSError:
            count = 0
        self._texture_status_cache[cache_key] = count
        return count

    def _count_zip_texture_members(self, archive_path: Path, limit: int = 999) -> int:
        try:
            resolved = archive_path.resolve()
        except OSError:
            resolved = archive_path.absolute()
        cache_key = (str(resolved).casefold(), "zip")
        cached = self._texture_status_cache.get(cache_key)
        if cached is not None:
            return cached
        count = 0
        try:
            with zipfile.ZipFile(resolved, "r") as zip_file:
                for member in zip_file.infolist():
                    member_name = member.filename.replace("\\", "/")
                    if member.is_dir() or not member_name or member_name.startswith("/") or "../" in f"/{member_name}":
                        continue
                    if Path(member_name).suffix.lower() in SCENE_TEXTURE_SOURCE_EXTENSIONS:
                        count += 1
                        if count >= limit:
                            break
        except (OSError, zipfile.BadZipFile):
            count = 0
        self._texture_status_cache[cache_key] = count
        return count

    def _refresh_result_row_statuses(self) -> None:
        for index in range(self.results_tree.topLevelItemCount()):
            item = self.results_tree.topLevelItem(index)
            payload = self._payload_from_item(item)
            if payload is None:
                continue
            if payload.get("kind") == "mirror":
                self._apply_mirror_local_state(payload)
                item.setText(3, self._mirror_local_status(payload))
                item.setText(4, self._texture_status_for_payload(payload))
            else:
                item.setText(3, self._local_payload_status(payload))
                item.setText(4, self._texture_status_for_payload(payload))

    def _mirror_candidates_for_payload(self, payload: dict[str, object]) -> tuple[MirrorDownloadCandidate, ...]:
        payload_mirror_url = str(payload.get("mirror_url", "") or "").strip()
        if not payload_mirror_url:
            try:
                payload_mirror_url = self.mirror_url()
            except ValueError:
                payload_mirror_url = DEFAULT_MODEL_MIRROR_URL
        return mirror_download_candidates(
            payload,
            payload_mirror_url,
            preferred_format=self._primary_preferred_format(),
        )

    def _download_candidates_for_selected_formats(
        self,
        payload: dict[str, object],
        selected_formats: list[str],
        *,
        require_importable: bool,
        mirror_url: str,
    ) -> list[MirrorDownloadCandidate]:
        payload_mirror_url = str(payload.get("mirror_url", "") or "").strip() or mirror_url
        candidates = mirror_download_candidates(
            payload,
            payload_mirror_url,
            preferred_format=selected_formats[0] if selected_formats else "gltf",
        )
        selected = set(selected_formats)
        filtered = [
            candidate
            for candidate in candidates
            if candidate.format in selected
        ]
        if require_importable and not any(candidate.import_supported for candidate in filtered):
            return []
        return sorted(filtered, key=lambda candidate: selected_formats.index(candidate.format))

    def _selected_file_url_text(self, payloads: list[dict[str, object]]) -> str:
        sections: list[str] = []
        for payload in payloads:
            name = str(payload.get("name", "") or "Untitled model")
            uid = str(payload.get("uid", "") or "")
            license_label = str(payload.get("license_label", "") or "")
            creator = str(payload.get("creator_name", "") or payload.get("creator_username", "") or "")
            sections.append(name)
            if uid:
                sections.append(f"UID: {uid}")
            if creator:
                sections.append(f"Creator: {creator}")
            if license_label:
                sections.append(f"License: {license_label}")
            for candidate in self._mirror_candidates_for_payload(payload):
                sections.append(f"{getattr(candidate, 'label', 'File')}: {getattr(candidate, 'url', '')}")
            viewer_url = str(payload.get("viewer_url", "") or "")
            if viewer_url:
                sections.append(f"Page: {viewer_url}")
            sections.append("")
        return "\n".join(sections).strip()

    def mirror_url(self) -> str:
        return normalize_mirror_base_url(self.mirror_url_edit.text().strip())

    def catalogue_dir(self) -> Path:
        return Path(self.catalogue_dir_edit.text().strip() or "E:/ModelCatalogue").expanduser()

    def catalogue_db_path(self) -> Path:
        return self.catalogue_dir() / "mirror_catalogue.sqlite"

    def _update_catalogue_status(self) -> None:
        stats = catalogue_stats(self.catalogue_db_path())
        self.catalogue_status_label.setText(
            f"Indexed metadata: {stats['models']:,} model(s), {stats['shards']:,} catalogue page(s). Downloads are stored under {self.catalogue_dir() / 'downloads'} after you enter the mirror URL."
        )

    def _run_task(
        self,
        status: str,
        task: Callable[[Callable[[str], None]], object],
        complete_handler: Callable[[object], None],
        *,
        error_handler: Optional[Callable[[str], None]] = None,
    ) -> None:
        if self._task_thread is not None and self._task_thread.isRunning():
            self._set_status("A model library task is already running.", error=True)
            return
        self._task_status_active = True
        self._set_status(status)
        self._task_complete_handler = complete_handler
        self._task_error_handler = error_handler
        thread = QThread(self)
        worker = _ModelLibraryTaskWorker(task)
        worker.moveToThread(thread)
        thread.started.connect(worker.run)
        worker.progress.connect(self._handle_task_progress)
        worker.completed.connect(self._handle_task_completed)
        worker.error.connect(self._handle_task_error)
        worker.finished.connect(thread.quit)
        worker.finished.connect(worker.deleteLater)
        thread.finished.connect(thread.deleteLater)
        thread.finished.connect(self._handle_task_finished)
        self._task_thread = thread
        self._task_worker = worker
        self.cancel_task_button.setEnabled(self._stop_event is not None)
        self.build_index_button.setEnabled(False)
        self.scan_local_button.setEnabled(False)
        self.search_mirror_button.setEnabled(False)
        self.show_indexed_button.setEnabled(False)
        self.mirror_results_view_button.setEnabled(False)
        self.local_results_view_button.setEnabled(False)
        self.refresh_results_view_button.setEnabled(False)
        self.download_button.setEnabled(False)
        self.download_import_button.setEnabled(False)
        self.open_file_url_button.setEnabled(False)
        self.preview_button.setEnabled(False)
        self.generate_icon_button.setEnabled(False)
        self.more_actions_button.setEnabled(False)
        self.delete_local_button.setEnabled(False)
        lower_status = status.lower()
        if "building" in lower_status or "index" in lower_status:
            self.build_index_button.setText("Building...")
        if "search" in lower_status:
            self.search_mirror_button.setText("Searching...")
        if "scanning" in lower_status:
            self.scan_local_button.setText("Scanning...")
        if "download" in lower_status:
            self.download_button.setText("Downloading...")
        thread.start()

    @Slot(str)
    def _handle_task_progress(self, message: str) -> None:
        self._set_status(str(message))

    @Slot(object)
    def _handle_task_completed(self, result: object) -> None:
        handler = self._task_complete_handler
        self._task_complete_handler = None
        if handler is not None:
            handler(result)

    @Slot(str)
    def _handle_task_error(self, message: str) -> None:
        handler = self._task_error_handler
        self._task_error_handler = None
        self._task_complete_handler = None
        if handler is not None:
            handler(str(message))
            return
        self._set_status(str(message), error=True)

    @Slot()
    def _handle_task_finished(self) -> None:
        self._task_thread = None
        self._task_worker = None
        self._task_error_handler = None
        self._stop_event = None
        self._task_status_active = False
        if hasattr(self, "task_status_label"):
            current_task_status = self.task_status_label.text()
            if current_task_status.startswith("Working: "):
                self.task_status_label.setText(f"Status: {current_task_status[len('Working: '):]}")
        if hasattr(self, "active_task_label"):
            current_active_status = self.active_task_label.text()
            if current_active_status.startswith("Working: "):
                self.active_task_label.setText(f"Status: {current_active_status[len('Working: '):]}")
        self.cancel_task_button.setEnabled(False)
        self.build_index_button.setText("Build Search Index")
        self.scan_local_button.setText("Show Local Models")
        self.search_mirror_button.setText("Search Mirror")
        self.show_indexed_button.setText("Popular")
        self.download_button.setText("Download Checked")
        if hasattr(self, "active_task_progress"):
            self.active_task_progress.setVisible(False)
        self.build_index_button.setEnabled(True)
        self.scan_local_button.setEnabled(True)
        self.search_mirror_button.setEnabled(True)
        self.show_indexed_button.setEnabled(True)
        self.mirror_results_view_button.setEnabled(True)
        self.local_results_view_button.setEnabled(True)
        self.refresh_results_view_button.setEnabled(True)
        self._update_selection_state()

    def _set_status(self, message: str, *, error: bool = False) -> None:
        self.status_label.setText(message)
        if hasattr(self, "task_status_label"):
            prefix = "Working: " if self._task_status_active else ("Error: " if error else "Status: ")
            self.task_status_label.setText(f"{prefix}{message}")
        self._update_active_task_progress(message, error=error)
        if self._task_status_active and hasattr(self, "results_status_label"):
            self.results_status_label.setText(f"Working: {message}")
        self.status_message_requested.emit(message, error)

    def _update_active_task_progress(self, message: str, *, error: bool = False) -> None:
        if not hasattr(self, "active_task_label") or not hasattr(self, "active_task_progress"):
            return
        text = str(message or "").strip()
        if not text:
            return
        if self._task_status_active:
            self.active_task_label.setText(f"Working: {text}")
            self.active_task_label.setVisible(True)
            self.active_task_progress.setVisible(True)
            match = re.search(r"(\d[\d,]*)\s*/\s*(\d[\d,]*)", text)
            if match:
                current = int(match.group(1).replace(",", ""))
                total = max(1, int(match.group(2).replace(",", "")))
                self.active_task_progress.setRange(0, total)
                self.active_task_progress.setValue(max(0, min(current, total)))
                self.active_task_progress.setFormat(f"{current:,} / {total:,}")
            else:
                self.active_task_progress.setRange(0, 0)
                self.active_task_progress.setFormat("Working...")
            return
        prefix = "Error: " if error else "Status: "
        self.active_task_label.setText(f"{prefix}{text}")
        self.active_task_label.setVisible(True)
        self.active_task_progress.setVisible(False)

    def _mirror_size_summary(self, payload: dict[str, object]) -> str:
        size = self._mirror_size_bytes(payload)
        return self._format_size(size) if size > 0 else "-"

    def _mirror_size_bytes(self, payload: dict[str, object]) -> int:
        archives = payload.get("archives") if isinstance(payload.get("archives"), dict) else {}
        sizes: list[int] = []
        for value in archives.values():
            if isinstance(value, dict):
                size = value.get("size")
                try:
                    sizes.append(int(size))
                except (TypeError, ValueError):
                    pass
        if not sizes:
            return 0
        return max(sizes)

    def _format_size(self, size: int) -> str:
        value = max(0, int(size))
        if value < 1024:
            return f"{value} B"
        if value < 1024 * 1024:
            return f"{value / 1024:.1f} KB"
        if value < 1024 * 1024 * 1024:
            return f"{value / (1024 * 1024):.1f} MB"
        return f"{value / (1024 * 1024 * 1024):.1f} GB"

    def _format_count(self, value: object) -> str:
        try:
            if value is None or value == "":
                return "-"
            return f"{int(value):,}"
        except (TypeError, ValueError):
            return "-"

    def _format_time(self, timestamp: float) -> str:
        if timestamp <= 0:
            return "-"
        return time.strftime("%Y-%m-%d %H:%M", time.localtime(timestamp))


__all__ = ["ModelLibraryTab"]
