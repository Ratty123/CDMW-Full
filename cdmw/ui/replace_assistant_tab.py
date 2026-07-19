from __future__ import annotations

import dataclasses
from html import escape
from pathlib import Path, PurePosixPath
from typing import Callable, Dict, List, Optional, Sequence

from PySide6.QtCore import QSettings, Qt, QThread, QTimer, QUrl, Signal
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QComboBox,
    QDialog,
    QFileDialog,
    QGridLayout,
    QGroupBox,
    QHeaderView,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPlainTextEdit,
    QProgressBar,
    QPushButton,
    QScrollArea,
    QSplitter,
    QSpinBox,
    QStackedWidget,
    QTextBrowser,
    QToolButton,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from cdmw.constants import (
    APP_TITLE,
    DEFAULT_UPSCALE_POST_CORRECTION,
    DEFAULT_UPSCALE_TEXTURE_PRESET,
    REALESRGAN_NCNN_EXTRA_ARGS,
    REALESRGAN_NCNN_MODEL_DIR,
    REALESRGAN_NCNN_MODEL_NAME,
    REALESRGAN_NCNN_SCALE,
    REALESRGAN_NCNN_TILE_SIZE,
    UPSCALE_POST_CORRECTION_MATCH_HISTOGRAM,
    UPSCALE_POST_CORRECTION_MATCH_LEVELS,
    UPSCALE_POST_CORRECTION_MATCH_MEAN_LUMA,
    UPSCALE_POST_CORRECTION_NONE,
    UPSCALE_POST_CORRECTION_SOURCE_MATCH_BALANCED,
    UPSCALE_POST_CORRECTION_SOURCE_MATCH_EXPERIMENTAL,
    UPSCALE_POST_CORRECTION_SOURCE_MATCH_EXTENDED,
    UPSCALE_TEXTURE_PRESET_ALL,
    UPSCALE_TEXTURE_PRESET_BALANCED,
    UPSCALE_TEXTURE_PRESET_COLOR_UI,
    UPSCALE_TEXTURE_PRESET_COLOR_UI_EMISSIVE,
)
from cdmw.models import ArchiveEntry
from cdmw.domain.packages.export_policy import (
    MOD_PACKAGE_METADATA_ARTIFACTS_BY_KEY,
    MOD_PACKAGE_MANAGER_PROFILE_LABELS,
    MOD_PACKAGE_MANAGER_PROFILES,
    ModPackageExportOptions,
    mod_package_export_options_for_profiles,
    mod_package_export_options_for_manager,
    mod_package_profile_uses_manager_metadata,
)
from cdmw.services.replace_assistant_service import (
    ReplaceAssistantArchiveIndex,
    build_replace_assistant_archive_index,
    build_replace_assistant_items,
    build_replace_assistant_package,
    build_replace_assistant_preview_assets,
    match_replace_assistant_item_to_archive_entry,
    match_replace_assistant_item_to_local_original,
    match_replace_assistant_original,
)
from cdmw.services.texture_workflow_service import discover_realesrgan_ncnn_models
from cdmw.models import (
    ArchivePreviewResult,
    MatchedOriginalTexture,
    ModPackageInfo,
    ReplaceAssistantBuildOptions,
    ReplaceAssistantBuildSummary,
    ReplaceAssistantItem,
    ReplaceAssistantReviewItem,
    TextureEditorSourceBinding,
)
from cdmw.services.workspace_layout import workspace_paths
from cdmw.ui.widgets import (
    EmptyStatePanel,
    FlatSectionPanel,
    PreviewLabel,
    PreviewScrollArea,
    build_bounded_splitter_sizes,
    build_responsive_splitter_sizes,
    has_persistent_tree_column_widths,
    make_tree_columns_persistent,
    responsive_sidebar_bounds,
    set_sidebar_width_policy,
)
from cdmw.ui.replace_assistant.review_dialog import ReplaceAssistantReviewDialog
from cdmw.ui.replace_assistant.build import ReplaceAssistantBuildMixin
from cdmw.ui.replace_assistant.controls import ReplaceAssistantControlMixin
from cdmw.ui.replace_assistant.preview import ReplaceAssistantPreviewMixin
from cdmw.ui.replace_assistant.queue import ReplaceAssistantQueueMixin
from cdmw.ui.replace_assistant.remote_catalogue import ReplaceAssistantArchiveCatalogueMixin
from cdmw.ui.replace_assistant.settings import ReplaceAssistantSettingsMixin
from cdmw.services.archive_catalogue_service import ArchiveCatalogueService
from cdmw.ui.replace_assistant.workers import (
    ReplaceAssistantAutoMatchWorker,
    ReplaceAssistantBuildWorker,
    ReplaceAssistantImportWorker,
    ReplaceAssistantPreviewWorker,
    ReplaceAssistantUIConstraintWorker,
)


def _shutdown_thread(thread: Optional[QThread], *, grace_ms: int = 1200) -> None:
    del grace_ms
    if thread is None:
        return
    try:
        thread.requestInterruption()
    except Exception:
        pass
    thread.quit()


def _wrapped_help_tooltip(text: str, *, width: int = 360) -> str:
    tooltip_html = escape(str(text)).replace("\n", "<br>")
    return f"<qt><div style='width: {width}px; white-space: normal;'>{tooltip_html}</div></qt>"


def _make_help_button(text: str) -> QToolButton:
    button = QToolButton()
    button.setText("?")
    button.setToolTip(_wrapped_help_tooltip(text))
    button.setCursor(Qt.WhatsThisCursor)
    button.setAutoRaise(True)
    button.setFixedSize(22, 22)
    return button




class ReplaceAssistantTab(
    ReplaceAssistantBuildMixin,
    ReplaceAssistantPreviewMixin,
    ReplaceAssistantQueueMixin,
    ReplaceAssistantArchiveCatalogueMixin,
    ReplaceAssistantControlMixin,
    ReplaceAssistantSettingsMixin,
    QWidget,
):
    status_message_requested = Signal(str, bool)
    open_in_texture_editor_requested = Signal(str, object)

    def __init__(
        self,
        *,
        settings: QSettings,
        base_dir: Path,
        get_archive_entries: Callable[[], Sequence[ArchiveEntry]],
        get_original_root: Callable[[], str],
        get_current_config: Callable[[], object],
        archive_catalogue_service: ArchiveCatalogueService | None = None,
        parent: Optional[QWidget] = None,
    ) -> None:
        super().__init__(parent)
        self.settings = settings
        self.base_dir = base_dir
        self.get_archive_entries = get_archive_entries
        self.get_original_root = get_original_root
        self.get_current_config = get_current_config

        self.archive_entries: List[ArchiveEntry] = []
        self.archive_index: ReplaceAssistantArchiveIndex = build_replace_assistant_archive_index([])
        self.archive_index_original_root: Optional[Path] = None
        self.items: List[ReplaceAssistantItem] = []
        self.last_built_output_root: Optional[Path] = None
        self.review_dialog: Optional[ReplaceAssistantReviewDialog] = None
        self.external_busy = False
        self._settings_ready = False
        self._settings_save_timer = QTimer(self)
        self._settings_save_timer.setSingleShot(True)
        self._settings_save_timer.setInterval(250)
        self._settings_save_timer.timeout.connect(self._save_settings)
        self.preview_thread: Optional[QThread] = None
        self.preview_worker: Optional[ReplaceAssistantPreviewWorker] = None
        self.preview_request_id = 0
        self.pending_preview_item: Optional[ReplaceAssistantItem] = None
        self.preview_refresh_suspended = False
        self._pending_import_select_path: str = ""
        self.import_thread: Optional[QThread] = None
        self.import_worker: Optional[ReplaceAssistantImportWorker] = None
        self.match_thread: Optional[QThread] = None
        self.match_worker: Optional[ReplaceAssistantAutoMatchWorker] = None
        self.ui_constraint_thread: Optional[QThread] = None
        self.ui_constraint_worker: Optional[ReplaceAssistantUIConstraintWorker] = None
        self.ui_constraint_request_id = 0
        self._active_ui_constraint_target: str = ""
        self._pending_ui_constraint_target: str = ""
        self.build_thread: Optional[QThread] = None
        self.build_worker: Optional[ReplaceAssistantBuildWorker] = None
        self.pending_review_items: Optional[tuple[ReplaceAssistantReviewItem, ...]] = None
        self._ui_constraint_warning_cache: Dict[str, str] = {}
        self._initialize_archive_catalogue(archive_catalogue_service)

        root_layout = QVBoxLayout(self)
        root_layout.setContentsMargins(10, 10, 10, 10)
        root_layout.setSpacing(6)

        self.summary_label = QLabel("No files imported yet.")
        self.summary_label.setWordWrap(True)
        self.summary_label.setObjectName("HintLabel")

        button_row = QHBoxLayout()
        button_row.setSpacing(8)
        self.add_files_button = QPushButton("Add Files")
        self.add_folder_button = QPushButton("Add Folder")
        self.auto_match_button = QPushButton("Auto-Match")
        self.open_in_editor_button = QPushButton("Open In Texture Editor")
        self.choose_local_original_button = QPushButton("Choose Local Original")
        self.choose_archive_original_button = QPushButton("Choose Archive Original")
        self.remove_selected_button = QPushButton("Remove Selected")
        self.clear_all_button = QPushButton("Clear All")
        button_row.addWidget(self.add_files_button)
        button_row.addWidget(self.add_folder_button)
        button_row.addWidget(self.auto_match_button)
        button_row.addWidget(self.open_in_editor_button)
        button_row.addWidget(self.choose_local_original_button)
        button_row.addWidget(self.choose_archive_original_button)
        button_row.addWidget(self.remove_selected_button)
        button_row.addWidget(self.clear_all_button)
        button_row.addStretch(1)
        root_layout.addLayout(button_row)
        root_layout.addWidget(self.summary_label)

        self.main_splitter = QSplitter(Qt.Horizontal)
        self.main_splitter.setChildrenCollapsible(False)
        self.main_splitter.setHandleWidth(8)
        root_layout.addWidget(self.main_splitter, stretch=1)

        self.queue_panel = QWidget()
        queue_layout = QVBoxLayout(self.queue_panel)
        queue_layout.setContentsMargins(0, 0, 0, 0)
        queue_layout.setSpacing(8)
        queue_group = FlatSectionPanel("Replace Queue")
        queue_group_layout = queue_group.body_layout
        self.queue_tree = QTreeWidget()
        self.queue_tree.setRootIsDecorated(False)
        self.queue_tree.setAlternatingRowColors(True)
        self.queue_tree.setUniformRowHeights(True)
        self.queue_tree.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self.queue_tree.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.queue_tree.setHorizontalScrollMode(QAbstractItemView.ScrollPerPixel)
        self.queue_tree.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOn)
        self.queue_tree.setTextElideMode(Qt.ElideMiddle)
        self.queue_tree.setHeaderLabels(["Edited File", "Original", "Package", "Kind", "Status"])
        queue_header = self.queue_tree.header()
        queue_header.setStretchLastSection(False)
        queue_header.setSectionsMovable(True)
        queue_header.setSectionsClickable(True)
        queue_header.setMinimumSectionSize(72)
        queue_header.setSectionResizeMode(0, QHeaderView.Interactive)
        queue_header.setSectionResizeMode(1, QHeaderView.Interactive)
        queue_header.setSectionResizeMode(2, QHeaderView.ResizeToContents)
        queue_header.setSectionResizeMode(3, QHeaderView.ResizeToContents)
        queue_header.setSectionResizeMode(4, QHeaderView.Interactive)
        queue_header.resizeSection(0, 320)
        queue_header.resizeSection(1, 260)
        queue_header.resizeSection(2, 90)
        queue_header.resizeSection(3, 70)
        queue_header.resizeSection(4, 220)
        make_tree_columns_persistent(
            self.queue_tree,
            self.settings,
            "replace_assistant/queue",
            minimum_width=72,
            save_callback=self.schedule_settings_save,
        )
        self.queue_tree.setToolTip(
            "Columns can be resized or reordered. Use the horizontal scrollbar when the queue is narrower than the full column set."
        )
        self.queue_stack = QStackedWidget()
        self.queue_empty_state = EmptyStatePanel(
            "Import edited textures",
            "Add PNG or DDS files to build a replacement package. The queue will show matched originals, package targets, and any unresolved items.",
        )
        self.queue_stack.addWidget(self.queue_empty_state)
        self.queue_stack.addWidget(self.queue_tree)
        queue_group_layout.addWidget(self.queue_stack, stretch=1)
        queue_layout.addWidget(queue_group)
        self.main_splitter.addWidget(self.queue_panel)

        self.preview_panel = QWidget()
        preview_layout = QVBoxLayout(self.preview_panel)
        preview_layout.setContentsMargins(0, 0, 0, 0)
        preview_layout.setSpacing(8)
        preview_group = FlatSectionPanel("Preview")
        preview_group_layout = preview_group.body_layout
        preview_title_row = QHBoxLayout()
        preview_title_row.setSpacing(8)
        self.preview_title_label = QLabel("Select an imported file")
        self.preview_title_label.setWordWrap(True)
        self.preview_zoom_out_button = QPushButton("-")
        self.preview_zoom_fit_button = QPushButton("Fit")
        self.preview_zoom_100_button = QPushButton("100%")
        self.preview_zoom_in_button = QPushButton("+")
        self.preview_zoom_value = QLabel("-")
        self.preview_zoom_value.setObjectName("HintLabel")
        preview_title_row.addWidget(self.preview_title_label, stretch=1)
        preview_title_row.addWidget(self.preview_zoom_out_button)
        preview_title_row.addWidget(self.preview_zoom_fit_button)
        preview_title_row.addWidget(self.preview_zoom_100_button)
        preview_title_row.addWidget(self.preview_zoom_in_button)
        preview_title_row.addWidget(self.preview_zoom_value)
        preview_group_layout.addLayout(preview_title_row)
        self.preview_meta_label = QLabel("Select a file to preview it here.")
        self.preview_meta_label.setWordWrap(True)
        self.preview_meta_label.setObjectName("HintLabel")
        preview_group_layout.addWidget(self.preview_meta_label)
        self.preview_warning_label = QLabel("")
        self.preview_warning_label.setWordWrap(True)
        self.preview_warning_label.setObjectName("WarningText")
        self.preview_warning_label.setVisible(False)
        preview_group_layout.addWidget(self.preview_warning_label)
        self.preview_label = PreviewLabel("Select a file to preview it here.")
        self.preview_label.setMinimumHeight(320)
        self.preview_label.setMinimumWidth(320)
        self.preview_scroll = PreviewScrollArea()
        self.preview_scroll.setWidgetResizable(False)
        self.preview_scroll.setAlignment(Qt.AlignCenter)
        self.preview_scroll.setWidget(self.preview_label)
        self.preview_label.attach_scroll_area(self.preview_scroll)
        self.preview_label.set_wheel_zoom_handler(self._adjust_preview_zoom)
        preview_group_layout.addWidget(self.preview_scroll, stretch=1)
        self.preview_details_edit = QPlainTextEdit()
        self.preview_details_edit.setReadOnly(True)
        self.preview_details_edit.setPlaceholderText("Selected item details appear here.")
        preview_group_layout.addWidget(self.preview_details_edit)
        preview_layout.addWidget(preview_group, stretch=1)
        self.main_splitter.addWidget(self.preview_panel)

        self.settings_panel = QWidget()
        set_sidebar_width_policy(self.settings_panel, role="wide")
        settings_layout = QVBoxLayout(self.settings_panel)
        settings_layout.setContentsMargins(0, 0, 0, 0)
        settings_layout.setSpacing(8)

        build_group = FlatSectionPanel("Build Settings", body_margins=(10, 10, 10, 10), body_spacing=0)
        build_layout = QGridLayout()
        build_layout.setHorizontalSpacing(10)
        build_layout.setVerticalSpacing(8)
        build_layout.setColumnMinimumWidth(0, 136)
        build_layout.setColumnStretch(1, 1)

        self.build_mode_combo = QComboBox()
        self.build_mode_combo.addItem("Rebuild only", "rebuild_only")
        self.build_mode_combo.addItem("Upscale with NCNN, then rebuild", "upscale_then_rebuild")
        self.size_mode_combo = QComboBox()
        self.size_mode_combo.addItem("Use edited size", "use_edited_size")
        self.size_mode_combo.addItem("Match original size", "match_original")
        self.package_output_root_edit = QLineEdit(str((workspace_paths(self.base_dir)["workspace_root"] / "outputs" / "texture_replacer").resolve()))
        self.package_output_browse_button = QPushButton("Browse")
        self.overwrite_package_checkbox = QCheckBox("Clear existing output package before build")
        self.overwrite_package_checkbox.setChecked(True)
        overwrite_help_text = (
            "Deletes files in the generated package folder before writing the new output. "
            "This is local output cleanup, not a mod-manager conflict setting."
        )
        self.overwrite_package_checkbox.setToolTip(
            _wrapped_help_tooltip(overwrite_help_text)
        )
        default_package_options = mod_package_export_options_for_manager("dmm")
        self.create_no_encrypt_checkbox = QCheckBox(MOD_PACKAGE_METADATA_ARTIFACTS_BY_KEY["no_encrypt"].label)
        self.create_no_encrypt_checkbox.setChecked(default_package_options.create_no_encrypt_file)
        self.build_package_button = QPushButton("Build Package")
        self.open_output_folder_button = QPushButton("Open Output Folder")
        self.mirror_workflow_button = QPushButton("Mirror Texture Workflow")

        build_layout.addWidget(QLabel("Build mode"), 0, 0)
        build_layout.addWidget(self.build_mode_combo, 0, 1)
        build_layout.addWidget(QLabel("Size mode"), 1, 0)
        build_layout.addWidget(self.size_mode_combo, 1, 1)
        build_layout.addWidget(QLabel("Package parent root"), 2, 0)
        output_row = QHBoxLayout()
        output_row.setContentsMargins(0, 0, 0, 0)
        output_row.setSpacing(8)
        output_row.addWidget(self.package_output_root_edit, stretch=1)
        output_row.addWidget(self.package_output_browse_button)
        build_layout.addLayout(output_row, 2, 1)
        build_layout.addWidget(self.overwrite_package_checkbox, 3, 0, 1, 2)
        build_layout.addWidget(_make_help_button(overwrite_help_text), 3, 2)
        build_layout.addWidget(self.mirror_workflow_button, 4, 0)
        build_layout.addWidget(self.build_package_button, 4, 1)
        build_layout.addWidget(self.open_output_folder_button, 5, 0, 1, 2)
        build_group.body_layout.addLayout(build_layout)
        settings_layout.addWidget(build_group)

        package_group = FlatSectionPanel("Package Info", body_margins=(10, 10, 10, 10), body_spacing=0)
        package_layout = QGridLayout()
        package_layout.setHorizontalSpacing(10)
        package_layout.setVerticalSpacing(8)
        package_layout.setColumnMinimumWidth(0, 110)
        package_layout.setColumnStretch(1, 1)
        self.package_title_edit = QLineEdit("Crimson Desert Mod Workbench Mod")
        self.package_version_edit = QLineEdit("1.0")
        self.package_author_edit = QLineEdit("")
        self.package_description_edit = QLineEdit("")
        self.package_nexus_edit = QLineEdit("")
        self.package_manager_combo = QComboBox()
        self.package_manager_combo.addItem("Definitive Mod Manager", "dmm")
        self.package_manager_combo.addItem("JMM JSON", "jmm")
        self.package_manager_combo.addItem("CDUMM", "cdumm")
        self.package_manager_combo.addItem("Crimson Sharp / Crimson Browser", "crimson_sharp")
        self.package_manager_combo.addItem("Field-JSON v3.1", "field_json")
        self.package_profile_checkboxes: Dict[str, QCheckBox] = {}
        self.package_profiles_widget = QWidget()
        package_profiles_layout = QVBoxLayout(self.package_profiles_widget)
        package_profiles_layout.setContentsMargins(0, 0, 0, 0)
        package_profiles_layout.setSpacing(4)
        for profile in MOD_PACKAGE_MANAGER_PROFILES:
            label = MOD_PACKAGE_MANAGER_PROFILE_LABELS.get(profile, profile)
            checkbox = QCheckBox(label)
            checkbox.setToolTip(label)
            checkbox.setChecked(profile == "dmm")
            package_profiles_layout.addWidget(checkbox)
            self.package_profile_checkboxes[profile] = checkbox
        package_profiles_layout.addStretch(1)
        self.package_structure_combo = QComboBox()
        self.package_structure_combo.addItem("Game-relative folders", "game_relative")
        self.package_structure_combo.addItem("files/ wrapper", "files_wrapper")
        self.package_structure_combo.addItem("Custom compact paths", "custom_compact_paths")
        self.package_structure_combo.addItem("DMM texture folder", "dmm_texture")
        self.package_structure_combo.addItem("Field-JSON v3.1 assets", "field_json_v31")
        self.package_manifest_checkbox = QCheckBox(MOD_PACKAGE_METADATA_ARTIFACTS_BY_KEY["manifest_json"].label)
        self.package_manifest_checkbox.setChecked(default_package_options.create_manifest_json)
        self.package_mod_json_checkbox = QCheckBox(MOD_PACKAGE_METADATA_ARTIFACTS_BY_KEY["mod_json"].label)
        self.package_mod_json_checkbox.setChecked(default_package_options.create_mod_json)
        self.package_modinfo_checkbox = QCheckBox(MOD_PACKAGE_METADATA_ARTIFACTS_BY_KEY["modinfo_json"].label)
        self.package_modinfo_checkbox.setChecked(default_package_options.create_modinfo_json)
        self.package_info_json_checkbox = QCheckBox(MOD_PACKAGE_METADATA_ARTIFACTS_BY_KEY["info_json"].label)
        self.package_info_json_checkbox.setChecked(default_package_options.create_info_json)
        self.package_zip_checkbox = QCheckBox(MOD_PACKAGE_METADATA_ARTIFACTS_BY_KEY["ready_zip"].label)
        self.package_conflict_mode_combo = QComboBox()
        self.package_conflict_mode_combo.addItem("Normal", "")
        self.package_conflict_mode_combo.addItem("Override wins", "override")
        self.package_target_language_edit = QLineEdit("")
        self.package_target_language_edit.setPlaceholderText("Optional, for language-specific managers")
        package_layout.addWidget(QLabel("Title"), 0, 0)
        package_layout.addWidget(self.package_title_edit, 0, 1)
        package_layout.addWidget(QLabel("Version"), 1, 0)
        package_layout.addWidget(self.package_version_edit, 1, 1)
        package_layout.addWidget(QLabel("Author"), 2, 0)
        package_layout.addWidget(self.package_author_edit, 2, 1)
        package_layout.addWidget(QLabel("Description"), 3, 0)
        package_layout.addWidget(self.package_description_edit, 3, 1)
        package_layout.addWidget(QLabel("Target Mod Managers"), 4, 0)
        target_managers_label_item = package_layout.itemAtPosition(4, 0)
        if target_managers_label_item is not None:
            target_managers_label_item.setAlignment(Qt.AlignTop)
        package_layout.addWidget(self.package_profiles_widget, 4, 1, 1, 2)
        package_layout.addWidget(QLabel("Package output"), 5, 0)
        package_layout.addWidget(self.package_zip_checkbox, 5, 1, 1, 2)
        self.package_conflict_mode_label = QLabel("Conflict mode")
        self.package_target_language_label = QLabel("Target language")
        self.package_conflict_mode_help = _make_help_button("CDUMM compatibility metadata. Normal leaves manager conflict behavior unchanged; Override asks compatible managers to prefer this mod when conflicts are detected.")
        self.package_target_language_help = _make_help_button("Optional CDUMM compatibility metadata for language-specific packages. Leave empty for general packages.")
        package_layout.addWidget(self.package_conflict_mode_label, 6, 0)
        package_layout.addWidget(self.package_conflict_mode_combo, 6, 1)
        package_layout.addWidget(self.package_conflict_mode_help, 6, 2)
        package_layout.addWidget(self.package_target_language_label, 7, 0)
        package_layout.addWidget(self.package_target_language_edit, 7, 1)
        package_layout.addWidget(self.package_target_language_help, 7, 2)
        package_group.body_layout.addLayout(package_layout)
        settings_layout.addWidget(package_group)

        def _apply_package_manager_profile() -> None:
            profile_options = mod_package_export_options_for_manager(str(self.package_manager_combo.currentData() or "dmm"))
            index = self.package_structure_combo.findData(profile_options.structure)
            if index >= 0:
                self.package_structure_combo.setCurrentIndex(index)
            self.package_manifest_checkbox.setChecked(profile_options.create_manifest_json)
            self.package_mod_json_checkbox.setChecked(profile_options.create_mod_json)
            self.package_modinfo_checkbox.setChecked(profile_options.create_modinfo_json)
            self.package_info_json_checkbox.setChecked(profile_options.create_info_json)
            self.create_no_encrypt_checkbox.setChecked(profile_options.create_no_encrypt_file)
            self.package_zip_checkbox.setChecked(profile_options.create_zip)
            self._sync_package_manager_field_visibility()

        self.package_manager_combo.currentIndexChanged.connect(_apply_package_manager_profile)
        for checkbox in self.package_profile_checkboxes.values():
            checkbox.toggled.connect(lambda _checked=False: self._sync_package_manager_field_visibility())
            checkbox.toggled.connect(self.schedule_settings_save)

        self.ncnn_group = FlatSectionPanel("Direct Upscale Controls (NCNN only)", body_margins=(10, 10, 10, 10), body_spacing=0)
        ncnn_layout = QGridLayout()
        ncnn_layout.setHorizontalSpacing(10)
        ncnn_layout.setVerticalSpacing(8)
        ncnn_layout.setColumnMinimumWidth(0, 136)
        ncnn_layout.setColumnStretch(1, 1)
        self.ncnn_exe_path_edit = QLineEdit()
        self.ncnn_model_dir_edit = QLineEdit(str(workspace_paths(self.base_dir)["ncnn_model_dir"].resolve()))
        self.ncnn_model_combo = QComboBox()
        self.ncnn_refresh_models_button = QPushButton("Refresh Models")
        self.ncnn_scale_spin = QSpinBox()
        self.ncnn_scale_spin.setRange(1, 8)
        self.ncnn_scale_spin.setValue(REALESRGAN_NCNN_SCALE)
        self.ncnn_tile_size_spin = QSpinBox()
        self.ncnn_tile_size_spin.setRange(0, 32768)
        self.ncnn_tile_size_spin.setSingleStep(32)
        self.ncnn_tile_size_spin.setValue(REALESRGAN_NCNN_TILE_SIZE)
        self.ncnn_extra_args_edit = QLineEdit(REALESRGAN_NCNN_EXTRA_ARGS)
        self.upscale_post_correction_combo = QComboBox()
        self._add_combo_choice(self.upscale_post_correction_combo, "Off", UPSCALE_POST_CORRECTION_NONE)
        self._add_combo_choice(self.upscale_post_correction_combo, "Match Mean Luma", UPSCALE_POST_CORRECTION_MATCH_MEAN_LUMA)
        self._add_combo_choice(self.upscale_post_correction_combo, "Match Levels", UPSCALE_POST_CORRECTION_MATCH_LEVELS)
        self._add_combo_choice(self.upscale_post_correction_combo, "Match Histogram", UPSCALE_POST_CORRECTION_MATCH_HISTOGRAM)
        self._add_combo_choice(
            self.upscale_post_correction_combo,
            "Source Match Balanced (recommended)",
            UPSCALE_POST_CORRECTION_SOURCE_MATCH_BALANCED,
        )
        self._add_combo_choice(self.upscale_post_correction_combo, "Source Match Extended", UPSCALE_POST_CORRECTION_SOURCE_MATCH_EXTENDED)
        self._add_combo_choice(self.upscale_post_correction_combo, "Source Match Experimental", UPSCALE_POST_CORRECTION_SOURCE_MATCH_EXPERIMENTAL)
        self.upscale_texture_preset_combo = QComboBox()
        self._add_combo_choice(self.upscale_texture_preset_combo, "Balanced mixed textures (recommended)", UPSCALE_TEXTURE_PRESET_BALANCED)
        self._add_combo_choice(self.upscale_texture_preset_combo, "Color + UI only (safer)", UPSCALE_TEXTURE_PRESET_COLOR_UI)
        self._add_combo_choice(self.upscale_texture_preset_combo, "Color + UI + emissive", UPSCALE_TEXTURE_PRESET_COLOR_UI_EMISSIVE)
        self._add_combo_choice(self.upscale_texture_preset_combo, "All textures (advanced)", UPSCALE_TEXTURE_PRESET_ALL)
        self.enable_automatic_texture_rules_checkbox = QCheckBox("Use automatic texture safety rules")
        self.enable_unsafe_technical_override_checkbox = QCheckBox(
            "Expert override: force technical maps through PNG/upscale path (unsafe)"
        )
        self.retry_smaller_tile_checkbox = QCheckBox("Retry with smaller tile on failure")

        ncnn_layout.addWidget(QLabel("NCNN exe path"), 0, 0)
        exe_row = QHBoxLayout()
        exe_row.setContentsMargins(0, 0, 0, 0)
        exe_row.setSpacing(8)
        self.ncnn_exe_browse_button = QPushButton("Browse")
        exe_row.addWidget(self.ncnn_exe_path_edit, stretch=1)
        exe_row.addWidget(self.ncnn_exe_browse_button)
        ncnn_layout.addLayout(exe_row, 0, 1)
        ncnn_layout.addWidget(QLabel("Model folder"), 1, 0)
        model_dir_row = QHBoxLayout()
        model_dir_row.setContentsMargins(0, 0, 0, 0)
        model_dir_row.setSpacing(8)
        self.ncnn_model_dir_browse_button = QPushButton("Browse")
        model_dir_row.addWidget(self.ncnn_model_dir_edit, stretch=1)
        model_dir_row.addWidget(self.ncnn_model_dir_browse_button)
        ncnn_layout.addLayout(model_dir_row, 1, 1)
        ncnn_layout.addWidget(QLabel("Model"), 2, 0)
        model_row = QHBoxLayout()
        model_row.setContentsMargins(0, 0, 0, 0)
        model_row.setSpacing(8)
        model_row.addWidget(self.ncnn_model_combo, stretch=1)
        model_row.addWidget(self.ncnn_refresh_models_button)
        ncnn_layout.addLayout(model_row, 2, 1)
        ncnn_layout.addWidget(QLabel("Scale"), 3, 0)
        ncnn_layout.addWidget(self.ncnn_scale_spin, 3, 1)
        ncnn_layout.addWidget(QLabel("Tile size"), 4, 0)
        ncnn_layout.addWidget(self.ncnn_tile_size_spin, 4, 1)
        ncnn_layout.addWidget(QLabel("NCNN extra args"), 5, 0)
        ncnn_layout.addWidget(self.ncnn_extra_args_edit, 5, 1)
        ncnn_layout.addWidget(QLabel("Post correction"), 6, 0)
        ncnn_layout.addWidget(self.upscale_post_correction_combo, 6, 1)
        ncnn_layout.addWidget(QLabel("Texture preset"), 7, 0)
        ncnn_layout.addWidget(self.upscale_texture_preset_combo, 7, 1)
        ncnn_layout.addWidget(self.enable_automatic_texture_rules_checkbox, 8, 0, 1, 2)
        ncnn_layout.addWidget(self.enable_unsafe_technical_override_checkbox, 9, 0, 1, 2)
        ncnn_layout.addWidget(self.retry_smaller_tile_checkbox, 10, 0, 1, 2)
        self.ncnn_group.body_layout.addLayout(ncnn_layout)
        settings_layout.addWidget(self.ncnn_group)

        self.progress_bar = QProgressBar()
        self.progress_bar.setRange(0, 1)
        self.progress_bar.setValue(0)
        self.progress_bar.setFormat("Idle")
        self.progress_bar.setMaximumHeight(18)
        self.status_label = QLabel("Ready.")
        self.status_label.setObjectName("StatusLabel")
        self.status_label.setWordWrap(True)
        settings_layout.addWidget(self.progress_bar)
        settings_layout.addWidget(self.status_label)

        self.log_view = QPlainTextEdit()
        self.log_view.setReadOnly(True)
        self.log_view.setMaximumBlockCount(2000)
        self.log_view.setPlaceholderText("Texture Replacer log will appear here.")
        settings_layout.addWidget(self.log_view, stretch=1)
        self.settings_scroll = QScrollArea()
        self.settings_scroll.setWidgetResizable(True)
        self.settings_scroll.setWidget(self.settings_panel)
        self.settings_scroll.setAlignment(Qt.AlignTop | Qt.AlignLeft)
        self.settings_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        settings_min, _settings_pref, settings_max = responsive_sidebar_bounds(self, role="wide")
        self.settings_scroll.setMinimumWidth(settings_min)
        self.settings_scroll.setMaximumWidth(settings_max)
        self.main_splitter.addWidget(self.settings_scroll)
        queue_min, _queue_pref, queue_max = responsive_sidebar_bounds(self, role="normal")
        preview_min, _preview_pref, _preview_max = responsive_sidebar_bounds(self, role="wide")
        self.queue_panel.setMinimumWidth(queue_min)
        self.queue_panel.setMaximumWidth(queue_max)
        self.preview_panel.setMinimumWidth(preview_min)
        self.main_splitter.setStretchFactor(0, 0)
        self.main_splitter.setStretchFactor(1, 1)
        self.main_splitter.setStretchFactor(2, 0)
        self.main_splitter.setSizes(
            build_bounded_splitter_sizes(
                1800,
                [22, 58, 20],
                [queue_min, preview_min, settings_min],
                [queue_max, None, settings_max],
            )
        )

        self.add_files_button.clicked.connect(self.import_files)
        self.add_folder_button.clicked.connect(self.import_folder)
        self.auto_match_button.clicked.connect(self.auto_match_all_items)
        self.open_in_editor_button.clicked.connect(self.open_current_item_in_texture_editor)
        self.choose_local_original_button.clicked.connect(self.choose_local_original_for_selected)
        self.choose_archive_original_button.clicked.connect(self.choose_archive_original_for_selected)
        self.remove_selected_button.clicked.connect(self.remove_selected_items)
        self.clear_all_button.clicked.connect(self.clear_all_items)
        self.build_package_button.clicked.connect(self.start_build)
        self.open_output_folder_button.clicked.connect(self.open_output_folder)
        self.package_output_browse_button.clicked.connect(self._browse_package_output_root)
        self.mirror_workflow_button.clicked.connect(self.mirror_texture_workflow_settings)
        self.queue_tree.currentItemChanged.connect(self._handle_selection_changed)
        self.queue_tree.itemSelectionChanged.connect(self._update_controls)
        self.preview_zoom_out_button.clicked.connect(lambda: self._adjust_preview_zoom(-1))
        self.preview_zoom_fit_button.clicked.connect(lambda: self._set_preview_fit(True))
        self.preview_zoom_100_button.clicked.connect(lambda: self._set_preview_zoom_factor(1.0))
        self.preview_zoom_in_button.clicked.connect(lambda: self._adjust_preview_zoom(1))
        self.ncnn_exe_browse_button.clicked.connect(self._browse_ncnn_exe)
        self.ncnn_model_dir_browse_button.clicked.connect(self._browse_ncnn_model_dir)
        self.ncnn_refresh_models_button.clicked.connect(self.refresh_ncnn_models)
        self.build_mode_combo.currentIndexChanged.connect(self._sync_build_mode_visibility)
        for widget in (
            self.build_mode_combo,
            self.size_mode_combo,
            self.package_output_root_edit,
            self.overwrite_package_checkbox,
            self.create_no_encrypt_checkbox,
            self.package_title_edit,
            self.package_version_edit,
            self.package_author_edit,
            self.package_description_edit,
            self.package_nexus_edit,
            self.package_manager_combo,
            self.package_structure_combo,
            self.package_manifest_checkbox,
            self.package_mod_json_checkbox,
            self.package_modinfo_checkbox,
            self.package_info_json_checkbox,
            self.package_zip_checkbox,
            self.package_conflict_mode_combo,
            self.package_target_language_edit,
            self.ncnn_exe_path_edit,
            self.ncnn_model_dir_edit,
            self.ncnn_scale_spin,
            self.ncnn_tile_size_spin,
            self.ncnn_extra_args_edit,
            self.upscale_post_correction_combo,
            self.upscale_texture_preset_combo,
            self.enable_automatic_texture_rules_checkbox,
            self.enable_unsafe_technical_override_checkbox,
            self.retry_smaller_tile_checkbox,
        ):
            if hasattr(widget, "textChanged"):
                widget.textChanged.connect(self.schedule_settings_save)  # type: ignore[attr-defined]
            elif hasattr(widget, "valueChanged"):
                widget.valueChanged.connect(self.schedule_settings_save)  # type: ignore[attr-defined]
            elif hasattr(widget, "currentIndexChanged"):
                widget.currentIndexChanged.connect(self.schedule_settings_save)  # type: ignore[attr-defined]
            elif hasattr(widget, "toggled"):
                widget.toggled.connect(self.schedule_settings_save)  # type: ignore[attr-defined]

        self._refresh_ncnn_models()
        self._load_settings()
        self._settings_ready = True
        self._sync_build_mode_visibility()
        self._sync_package_manager_field_visibility()
        self._update_summary()
        self._update_controls()
        QTimer.singleShot(0, self._apply_responsive_splitter_defaults)

    def _apply_responsive_splitter_defaults(self) -> None:
        queue_min, _queue_pref, queue_max = responsive_sidebar_bounds(self, role="normal")
        preview_min, _preview_pref, _preview_max = responsive_sidebar_bounds(self, role="wide")
        settings_min, _settings_pref, settings_max = responsive_sidebar_bounds(self, role="wide")
        total_width = max(1, self.width() - 32)
        self.main_splitter.setSizes(
            build_bounded_splitter_sizes(
                total_width,
                [22, 58, 20],
                [queue_min, preview_min, settings_min],
                [queue_max, None, settings_max],
            )
        )

    def set_splitter_sizes(self, sizes: Sequence[int], *, total_width: Optional[int] = None) -> None:
        if not sizes:
            return
        queue_min, _queue_pref, queue_max = responsive_sidebar_bounds(self, role="normal")
        preview_min, _preview_pref, _preview_max = responsive_sidebar_bounds(self, role="wide")
        settings_min, _settings_pref, settings_max = responsive_sidebar_bounds(self, role="wide")
        available_width = total_width or max(1, self.width() - 32)
        self.main_splitter.setSizes(
            build_bounded_splitter_sizes(
                available_width,
                sizes,
                [queue_min, preview_min, settings_min],
                [queue_max, None, settings_max],
            )
        )

    def splitter_sizes(self) -> List[int]:
        return self.main_splitter.sizes()

    def apply_responsive_splitter_sizes(self, total_width: Optional[int] = None) -> None:
        queue_min, _queue_pref, queue_max = responsive_sidebar_bounds(self, role="normal")
        preview_min, _preview_pref, _preview_max = responsive_sidebar_bounds(self, role="wide")
        settings_min, _settings_pref, settings_max = responsive_sidebar_bounds(self, role="wide")
        available_width = total_width or max(1, self.width() - 32)
        self.main_splitter.setSizes(
            build_bounded_splitter_sizes(
                available_width,
                [22, 58, 20],
                [queue_min, preview_min, settings_min],
                [queue_max, None, settings_max],
            )
        )

    def auto_fit_columns(self) -> None:
        header = self.queue_tree.header()
        if header is None or self.queue_tree.columnCount() <= 0:
            return
        if has_persistent_tree_column_widths(self.settings, "replace_assistant/queue", self.queue_tree.columnCount(), minimum_width=72):
            return
        viewport_width = max(self.queue_tree.viewport().width(), self.queue_tree.width() - 24, 0)
        if viewport_width <= 0:
            return
        minimums = {
            0: 260,
            1: 220,
            2: 96,
            3: 72,
            4: 160,
        }
        self.queue_tree.setUpdatesEnabled(False)
        try:
            for column in (2, 3):
                self.queue_tree.resizeColumnToContents(column)
                header.resizeSection(column, max(minimums[column], header.sectionSize(column)))
            reserved = header.sectionSize(2) + header.sectionSize(3)
            remaining = max(0, viewport_width - reserved - 12)
            preferred = {
                0: max(minimums[0], int(remaining * 0.42)),
                1: max(minimums[1], int(remaining * 0.31)),
                4: max(minimums[4], remaining - int(remaining * 0.42) - int(remaining * 0.31)),
            }
            for column in (0, 1, 4):
                header.resizeSection(column, preferred[column])
        finally:
            self.queue_tree.setUpdatesEnabled(True)

    def _add_combo_choice(self, combo: QComboBox, label: str, value: str) -> None:
        combo.addItem(label, value)

    def _combo_value(self, combo: QComboBox) -> str:
        data = combo.currentData()
        return str(data) if data is not None else ""

    def _set_combo_by_value(self, combo: QComboBox, value: str) -> None:
        for index in range(combo.count()):
            if combo.itemData(index) == value:
                combo.setCurrentIndex(index)
                return

    def _current_original_root_path(self) -> Optional[Path]:
        original_root_text = self.get_original_root().strip()
        return Path(original_root_text).expanduser() if original_root_text else None

    def _ensure_archive_index_current(self) -> ReplaceAssistantArchiveIndex:
        current_original_root = self._current_original_root_path()
        active_entries = [] if self._catalogue_archive_ready() else (self.archive_entries or list(self.get_archive_entries()))
        self.archive_entries = list(active_entries)
        entries_missing_from_index = bool(active_entries) and not self.archive_index.entries_by_relative_path
        root_changed = self.archive_index_original_root != current_original_root
        if entries_missing_from_index or root_changed:
            self.archive_entries = list(active_entries)
            self.archive_index = build_replace_assistant_archive_index(
                self.archive_entries,
                original_dds_root=current_original_root,
            )
            self.archive_index_original_root = current_original_root
        return self.archive_index

    def set_archive_entries(self, entries: Sequence[ArchiveEntry], package_root_text: str = "") -> None:
        if self._catalogue_archive_ready():
            self.archive_entries = []
            return
        self.archive_entries = entries if isinstance(entries, list) else list(entries)
        del package_root_text
        self.archive_index = build_replace_assistant_archive_index([])
        self.archive_index_original_root = None
        self._update_summary()

    def set_external_busy(self, busy: bool) -> None:
        self.external_busy = busy
        self._update_controls()

    def is_busy(self) -> bool:
        return (
            self.preview_thread is not None
            or self.import_thread is not None
            or self.match_thread is not None
            or self.build_thread is not None
            or self._catalogue_request_busy()
        )

    def iter_shutdown_workers(self) -> tuple[tuple[str, Optional[QThread], Optional[object]], ...]:
        return (
            ("preview_thread", self.preview_thread, self.preview_worker),
            ("import_thread", self.import_thread, self.import_worker),
            ("match_thread", self.match_thread, self.match_worker),
            ("ui_constraint_thread", self.ui_constraint_thread, self.ui_constraint_worker),
            ("build_thread", self.build_thread, self.build_worker),
        )

    def request_shutdown(self) -> None:
        if self.review_dialog is not None:
            self.review_dialog.close()
            self.review_dialog = None
        if self.preview_worker is not None:
            self.preview_worker.stop()
        if self.import_worker is not None:
            self.import_worker.stop()
        if self.match_worker is not None:
            self.match_worker.stop()
        if self.ui_constraint_worker is not None:
            self.ui_constraint_worker.stop()
        if self.build_worker is not None:
            self.build_worker.stop()
        self._cancel_all_catalogue_requests(clear=True)
        for _name, thread, _worker in self.iter_shutdown_workers():
            _shutdown_thread(thread)

    def shutdown(self) -> None:
        self.request_shutdown()
