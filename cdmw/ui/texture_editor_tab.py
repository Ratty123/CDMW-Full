from __future__ import annotations

import dataclasses
from pathlib import Path
from typing import Callable, Dict, List, Optional, Sequence, Tuple

import numpy as np
from PySide6.QtCore import QEvent, QPoint, QRect, QRectF, QSettings, QSize, Qt, QThread, QTimer, Signal
from PySide6.QtGui import (
    QAction,
    QBrush,
    QColor,
    QIcon,
    QImage,
    QMouseEvent,
    QPalette,
    QPainter,
    QPainterPath,
    QPen,
    QPixmap,
)
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QFrame,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMenu,
    QPushButton,
    QKeySequenceEdit,
    QScrollArea,
    QSizePolicy,
    QSpinBox,
    QSlider,
    QSplitter,
    QTabBar,
    QTextBrowser,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from cdmw.domain.textures.editor_presets import texture_editor_dds_presets
from cdmw.services.texture_editor_service import native_texture_editor_backend_status_text
from cdmw.ui.texture_workflow.editor_action_state import (
    texture_editor_guide_action_state,
    texture_editor_image_action_state,
    texture_editor_layer_action_state,
    texture_editor_main_action_state,
    texture_editor_tool_action_state,
)
from cdmw.ui.texture_workflow.editor_adjustment_ui import TextureEditorAdjustmentUiMixin
from cdmw.ui.texture_workflow.editor_canvas import TextureEditorCanvas
from cdmw.ui.texture_workflow.editor_brush_presets import (
    normalize_texture_editor_custom_brush_presets,
    texture_editor_brush_preset_combo_state,
)
from cdmw.ui.texture_workflow.editor_async_task_ui import TextureEditorAsyncTaskUiMixin
from cdmw.ui.texture_workflow.editor_brush_preset_ui import TextureEditorBrushPresetUiMixin
from cdmw.ui.texture_workflow.editor_document_ui import TextureEditorDocumentUiMixin
from cdmw.ui.texture_workflow.editor_floating_state import texture_editor_floating_canvas_transform_state
from cdmw.ui.texture_workflow.editor_export_state import texture_editor_default_workspace_root
from cdmw.ui.texture_workflow.editor_file_io_ui import TextureEditorFileIoUiMixin
from cdmw.ui.texture_workflow.editor_history_ui import TextureEditorHistoryUiMixin
from cdmw.ui.texture_workflow.editor_floating_ui import TextureEditorFloatingUiMixin
from cdmw.ui.texture_workflow.editor_images import (
    _create_tool_icon,
    _rgba_array_to_qimage,
    texture_editor_layer_thumbnail_preview_pixels,
    texture_editor_quick_mask_overlay_image,
)
from cdmw.ui.texture_workflow.editor_channel_ui import TextureEditorChannelUiMixin
from cdmw.ui.texture_workflow.editor_layer_ui import TextureEditorLayerUiMixin
from cdmw.ui.texture_workflow.editor_layer_state import (
    texture_editor_current_layer_id,
    texture_editor_layer_by_id,
    texture_editor_layer_list_label,
    texture_editor_layer_pixel_target_state,
    texture_editor_layer_refresh_selection_id,
)
from cdmw.ui.texture_workflow.editor_session import (
    _TextureEditorSession,
    texture_editor_document_composite_revision,
)
from cdmw.ui.texture_workflow.editor_shortcuts_ui import TextureEditorShortcutsUiMixin
from cdmw.ui.texture_workflow.editor_selection_ui import TextureEditorSelectionUiMixin
from cdmw.ui.texture_workflow.editor_session_ui import TextureEditorSessionUiMixin
from cdmw.ui.texture_workflow.editor_refresh_ui import TextureEditorRefreshUiMixin
from cdmw.ui.texture_workflow.editor_resident_texture import TextureEditorResidentTextureMixin
from cdmw.ui.texture_workflow.editor_source_binding import (
    texture_editor_metadata_display_state,
)
from cdmw.ui.texture_workflow.editor_status_state import (
    texture_editor_canvas_status_state,
)
from cdmw.ui.texture_workflow.editor_tool_coordination import TextureEditorToolCoordinationMixin
from cdmw.ui.texture_workflow.editor_tool_operation_ui import TextureEditorToolOperationUiMixin
from cdmw.ui.texture_workflow.editor_settings_persistence import TextureEditorSettingsPersistenceMixin
from cdmw.ui.texture_workflow.editor_status_cache_ui import TextureEditorStatusCacheUiMixin
from cdmw.ui.texture_workflow.editor_ui_shell import TextureEditorUiShellMixin
from cdmw.ui.texture_workflow.editor_ui_constraints import (
    texture_editor_ui_constraint_lookup_start_state,
    texture_editor_ui_constraint_ready_state,
    texture_editor_ui_constraint_warning_state,
)
from cdmw.ui.texture_workflow.editor_view_state import (
    texture_editor_composite_render_state,
    texture_editor_guides_from_view_state,
    texture_editor_grid_control_state,
    texture_editor_grid_color_hex,
    texture_editor_view_controls_state,
    texture_editor_view_mode_key,
)
from cdmw.ui.texture_workflow.editor_view_coordination import TextureEditorViewCoordinationMixin
from cdmw.ui.texture_workflow.editor_widgets import CollapsibleSection, TextureEditorNavigator, TextureEditorRuler
from cdmw.ui.texture_workflow.editor_workers import TextureEditorUIConstraintWorker
from cdmw.ui.texture_workflow.editor_worker_lifecycle import TextureEditorWorkerLifecycleMixin
from cdmw.models import (
    TextureEditorDocument,
    TextureEditorToolSettings,
    TextureEditorWorkspace,
)
from cdmw.ui.layout_utils import build_responsive_splitter_sizes, responsive_sidebar_bounds


class TextureEditorTab(
    TextureEditorSettingsPersistenceMixin,
    TextureEditorBrushPresetUiMixin,
    TextureEditorShortcutsUiMixin,
    TextureEditorWorkerLifecycleMixin,
    TextureEditorAsyncTaskUiMixin,
    TextureEditorSessionUiMixin,
    TextureEditorChannelUiMixin,
    TextureEditorDocumentUiMixin,
    TextureEditorFloatingUiMixin,
    TextureEditorHistoryUiMixin,
    TextureEditorLayerUiMixin,
    TextureEditorSelectionUiMixin,
    TextureEditorAdjustmentUiMixin,
    TextureEditorFileIoUiMixin,
    TextureEditorResidentTextureMixin,
    TextureEditorStatusCacheUiMixin,
    TextureEditorRefreshUiMixin,
    TextureEditorToolCoordinationMixin,
    TextureEditorToolOperationUiMixin,
    TextureEditorViewCoordinationMixin,
    TextureEditorUiShellMixin,
    QWidget,
):
    status_message_requested = Signal(str, bool)
    send_to_replace_assistant_requested = Signal(str, object)
    send_to_texture_workflow_requested = Signal(str, object)
    send_to_item_icons_requested = Signal(str, object)
    native_dds_ready = Signal(str, object)
    resident_texture_patch_ready = Signal(object)
    browse_archive_requested = Signal(str)
    open_in_compare_requested = Signal(str, object)
    _task_completed_on_ui = Signal(object)
    _task_error_on_ui = Signal(str)
    _task_finished_on_ui = Signal()
    _ui_constraint_ready_on_ui = Signal(str, str)
    _ui_constraint_finished_on_ui = Signal()

    def __init__(
        self, *,
        settings: QSettings,
        base_dir: Path,
        get_png_root,
        get_original_dds_root=None,
        get_archive_entries=None,
        get_current_config=None,
        parent: Optional[QWidget] = None,
    ) -> None:
        super().__init__(parent)
        self.settings = settings
        self.base_dir = base_dir
        self.get_png_root = get_png_root
        self.get_original_dds_root = get_original_dds_root or (lambda: "")
        self.get_archive_entries = get_archive_entries or (lambda: [])
        self.get_current_config = get_current_config or (lambda: None)
        self._translate_ui_text: Callable[[str], str] = lambda text: str(text or "")
        self.workspace_root = texture_editor_default_workspace_root(base_dir)
        self.document: Optional[TextureEditorDocument] = None
        self.layer_pixels: Dict[str, np.ndarray] = {}
        self.history_snapshots: List[Dict[str, object]] = []
        self.history_index = -1
        self._layer_property_dirty = False
        self._floating_pixels: Optional[np.ndarray] = None
        self._floating_mask: Optional[np.ndarray] = None
        self._composite_cache: Optional[np.ndarray] = None
        self._composite_cache_revision = -1
        self._composite_dirty_bounds: Optional[Tuple[int, int, int, int]] = None
        self._thumbnail_cache: Dict[Tuple[str, int], QIcon] = {}
        self._pending_layer_property_before_document: Optional[TextureEditorDocument] = None
        self._pending_layer_property_before_pixels: Dict[str, np.ndarray] = {}
        self._adjustment_property_dirty = False
        self._pending_adjustment_before_document: Optional[TextureEditorDocument] = None
        self._refreshing_adjustments = False
        self._refreshing_layers_list = False
        self._editing_mask_target = False
        self._floating_transform_before_document: Optional[TextureEditorDocument] = None
        self._floating_transform_before_floating_pixels: Optional[np.ndarray] = None
        self._floating_transform_label = ""
        self.layer_clipboard: Optional[Tuple[np.ndarray, str, int, int, str]] = None
        self.selection_clipboard: Optional[Tuple[np.ndarray, str, int, int]] = None
        self.channel_clipboard: Optional[Tuple[np.ndarray, str]] = None
        self._sessions: List[_TextureEditorSession] = []
        self._active_session_index = -1
        self._switching_session = False
        self.workspace = TextureEditorWorkspace()
        self._shortcut_objects: List[object] = []
        self._task_thread: Optional[QThread] = None
        self._task_worker: Optional[object] = None
        self._ui_constraint_thread: Optional[QThread] = None
        self._ui_constraint_worker: Optional[TextureEditorUIConstraintWorker] = None
        self._pending_ui_constraint_key = ""
        self._task_success_callback: Optional[Callable[[object], None]] = None
        self._busy_task_label = ""
        self._adjustment_preview_timer = QTimer(self)
        self._adjustment_preview_timer.setSingleShot(True)
        self._adjustment_preview_timer.setInterval(16)
        self._adjustment_preview_timer.timeout.connect(self.preview_selected_adjustment_properties)
        self._coalesced_ui_refresh_timer = QTimer(self)
        self._coalesced_ui_refresh_timer.setSingleShot(True)
        self._coalesced_ui_refresh_timer.setInterval(16)
        self._coalesced_ui_refresh_timer.timeout.connect(self._flush_coalesced_ui_refresh)
        self._initialize_resident_texture_patch_state()
        self._applying_brush_preset = False
        raw_custom_brush_presets = str(self.settings.value("texture_editor/custom_brush_presets", "{}") or "{}").strip() or "{}"
        self._custom_brush_presets: Dict[str, Dict[str, object]] = normalize_texture_editor_custom_brush_presets(raw_custom_brush_presets)
        self.current_tool_settings = TextureEditorToolSettings()
        self._settings_ready = False
        self._texture_editor_splitter_restoring = False
        self._last_open_dir = str(base_dir)
        self._last_save_dir = str(base_dir)
        self._grid_color = QColor("#74C1FF")
        self._hover_pixel_info: Optional[Dict[str, object]] = None
        self._show_rulers = True
        self._show_guides = False
        self._vertical_guides: Tuple[int, ...] = ()
        self._horizontal_guides: Tuple[int, ...] = ()
        self._tool_setting_rows: Dict[str, Tuple[Optional[QWidget], QWidget]] = {}
        self._ui_constraint_warning_cache: Dict[str, str] = {}
        self.setStyleSheet(
            """
            QGroupBox {
                border: 1px solid rgba(128, 146, 179, 0.08);
                border-radius: 10px;
                margin-top: 10px;
                padding-top: 10px;
                font-weight: 600;
                background-color: rgba(255, 255, 255, 0.01);
            }
            QPushButton#EditorPanelButton {
                background-color: rgba(255, 255, 255, 0.02);
                border: 1px solid rgba(128, 146, 179, 0.12);
                color: #E7EDF7;
            }
            QPushButton#EditorPanelButton:hover {
                background-color: rgba(255, 255, 255, 0.04);
                border: 1px solid rgba(128, 146, 179, 0.2);
            }
            QPushButton#EditorPrimaryButton {
                background-color: rgba(116, 193, 255, 0.14);
                border: 1px solid rgba(116, 193, 255, 0.34);
                color: #EAF5FF;
            }
            QPushButton#EditorPrimaryButton:hover {
                background-color: rgba(116, 193, 255, 0.2);
                border: 1px solid rgba(116, 193, 255, 0.5);
            }
            QLineEdit, QComboBox, QTextBrowser, QListWidget {
                border-radius: 6px;
                border: 1px solid rgba(128, 146, 179, 0.12);
                background-color: rgba(255, 255, 255, 0.02);
            }
            QToolButton#EditorToolButton {
                background-color: rgba(255, 255, 255, 0.012);
                border: 1px solid rgba(255, 255, 255, 0.04);
            }
            QToolButton#EditorToolButton:checked {
                background-color: rgba(116, 193, 255, 0.18);
                border: 1px solid rgba(116, 193, 255, 0.45);
            }
            QFrame#EditorSectionBody {
                border: 1px solid rgba(128, 146, 179, 0.08);
                border-radius: 10px;
                background-color: rgba(255, 255, 255, 0.016);
            }
            QFrame#EditorActionPane {
                border: 1px solid rgba(128, 146, 179, 0.08);
                border-radius: 10px;
                background-color: rgba(255, 255, 255, 0.012);
            }
            QWidget#EditorLeftSidebar, QWidget#EditorInspectorSidebar {
                background-color: rgba(255, 255, 255, 0.012);
                border: 1px solid rgba(128, 146, 179, 0.08);
                border-radius: 12px;
            }
            QWidget#EditorCanvasPane {
                background-color: rgba(255, 255, 255, 0.008);
                border: 1px solid rgba(128, 146, 179, 0.06);
                border-radius: 12px;
            }
            QScrollArea#EditorSidebarScroll {
                border: none;
                background: transparent;
            }
            QSplitter::handle {
                background-color: transparent;
            }
            """
        )

        root_layout = QVBoxLayout(self)
        root_layout.setContentsMargins(10, 10, 10, 10)
        root_layout.setSpacing(0)

        self.document_tab_bar = QTabBar()
        self.document_tab_bar.setDocumentMode(True)
        self.document_tab_bar.setMovable(True)
        self.document_tab_bar.setTabsClosable(True)
        self.document_tab_bar.setDrawBase(False)
        self.document_tab_bar.setExpanding(False)
        self.document_tab_bar.hide()
        self._apply_document_tab_bar_style(self.font())
        self.open_file_button = QPushButton("Open Image...")
        self.open_archive_button = QPushButton("Browse Archive")
        self.open_compare_button = QPushButton("Open In Compare")
        self.open_project_button = QPushButton("Open Project...")
        self.save_project_button = QPushButton("Save Project")
        self.save_png_button = QPushButton("Export PNG")
        self.export_dds_button = QPushButton("Export DDS...")
        self.preview_compressed_button = QPushButton("Preview Compressed")
        self.send_replace_button = QPushButton("To Replace")
        self.send_workflow_button = QPushButton("To Workflow")
        self.send_item_icons_button = QPushButton("To Icon Creator")
        self.undo_button = QPushButton("Undo")
        self.redo_button = QPushButton("Redo")
        self.shortcuts_button = QPushButton("Shortcuts")
        self.save_png_button.setObjectName("EditorPrimaryButton")
        self.export_dds_button.setObjectName("EditorPrimaryButton")
        self.preview_compressed_button.setObjectName("EditorPanelButton")
        self.send_replace_button.setObjectName("EditorPrimaryButton")
        self.send_workflow_button.setObjectName("EditorPrimaryButton")
        self.send_item_icons_button.setObjectName("EditorPrimaryButton")
        self.open_archive_button.setObjectName("EditorPanelButton")
        self.open_compare_button.setObjectName("EditorPanelButton")
        self.open_project_button.setObjectName("EditorPanelButton")
        self.shortcuts_button.setObjectName("EditorPanelButton")
        self.open_compare_button.hide()

        self.warning_label = QLabel("")
        self.warning_label.setObjectName("WarningText")
        self.warning_label.setWordWrap(True)
        self.warning_label.setVisible(False)

        self.status_label = QLabel("Open a PNG, DDS, or project to start editing.")
        self.status_label.setObjectName("StatusLabel")
        self.status_label.setWordWrap(True)
        self.status_label.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Minimum)
        self.status_label.setMinimumHeight(36)
        self.native_dds_preset_combo = QComboBox()
        for preset in texture_editor_dds_presets():
            self.native_dds_preset_combo.addItem(preset.label, preset.key)
        self.native_dds_format_combo = QComboBox()
        self.native_dds_mip_combo = QComboBox()
        self.native_dds_mip_combo.addItem("Preset Mips", "")
        self.native_dds_mip_combo.addItem("Full Mips", "full")
        self.native_dds_mip_combo.addItem("Single Mip", "single")
        self.native_dds_status_label = QLabel(native_texture_editor_backend_status_text())
        self.native_dds_status_label.setObjectName("HintLabel")
        self.native_dds_status_label.setWordWrap(True)

        self.main_splitter = QSplitter(Qt.Horizontal)
        self.main_splitter.setChildrenCollapsible(False)
        self.main_splitter.setHandleWidth(10)
        root_layout.addWidget(self.main_splitter, stretch=1)

        self.tool_panel = QWidget()
        self.tool_panel.setObjectName("EditorLeftSidebar")
        editor_tool_min, _editor_tool_pref, editor_tool_max = self._texture_editor_tool_sidebar_bounds()
        self.tool_panel.setMinimumWidth(editor_tool_min)
        self.tool_panel.setMaximumWidth(editor_tool_max)
        tool_layout = QVBoxLayout(self.tool_panel)
        tool_layout.setContentsMargins(12, 12, 12, 12)
        tool_layout.setSpacing(8)
        left_actions_body = QFrame()
        left_actions_body.setObjectName("EditorActionPane")
        left_actions_layout = QVBoxLayout(left_actions_body)
        left_actions_layout.setContentsMargins(8, 8, 8, 8)
        left_actions_layout.setSpacing(6)
        self.actions_menu_button = QToolButton()
        self.actions_menu_button.setText("Actions")
        self.actions_menu_button.setToolButtonStyle(Qt.ToolButtonTextOnly)
        self.actions_menu_button.setPopupMode(QToolButton.InstantPopup)
        self.actions_menu_button.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.actions_menu_button.setObjectName("EditorPanelButton")
        self.actions_menu = QMenu(self.actions_menu_button)
        self.action_open_file = QAction("Open Image...", self)
        self.action_open_archive = QAction("Browse Archive", self)
        self.action_open_project = QAction("Open Project...", self)
        self.action_save_project = QAction("Save Project", self)
        self.action_export_png = QAction("Export PNG", self)
        self.action_export_dds = QAction("Export DDS...", self)
        self.action_preview_compressed = QAction("Preview Compressed", self)
        self.action_send_replace = QAction("Send To Texture Replacer", self)
        self.action_send_workflow = QAction("Send To Texture Workflow", self)
        self.action_send_item_icons = QAction("Send To Icon Creator", self)
        for action in (
            self.action_open_file,
            self.action_open_archive,
            self.action_open_project,
        ):
            self.actions_menu.addAction(action)
        self.actions_menu.addSeparator()
        for action in (
            self.action_save_project,
            self.action_export_png,
            self.action_export_dds,
            self.action_preview_compressed,
            self.action_send_replace,
            self.action_send_workflow,
            self.action_send_item_icons,
        ):
            self.actions_menu.addAction(action)
        self.actions_menu_button.setMenu(self.actions_menu)
        left_actions_layout.addWidget(self.actions_menu_button)
        edit_actions = QGridLayout()
        edit_actions.setHorizontalSpacing(8)
        edit_actions.setVerticalSpacing(6)
        edit_label = QLabel("Edit")
        edit_label.setObjectName("HintLabel")
        self.shortcuts_button.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        edit_actions.addWidget(edit_label, 0, 0, 1, 2)
        edit_actions.addWidget(self.undo_button, 1, 0)
        edit_actions.addWidget(self.redo_button, 1, 1)
        edit_actions.addWidget(self.shortcuts_button, 2, 0, 1, 2)
        left_actions_layout.addLayout(edit_actions)
        native_export_layout = QGridLayout()
        native_export_layout.setHorizontalSpacing(6)
        native_export_layout.setVerticalSpacing(6)
        native_export_label = QLabel("DDS")
        native_export_label.setObjectName("HintLabel")
        native_export_layout.addWidget(native_export_label, 0, 0, 1, 2)
        native_export_layout.addWidget(self.native_dds_preset_combo, 1, 0, 1, 2)
        native_export_layout.addWidget(self.native_dds_format_combo, 2, 0, 1, 2)
        native_export_layout.addWidget(self.native_dds_mip_combo, 3, 0, 1, 2)
        native_export_layout.addWidget(self.export_dds_button, 4, 0, 1, 2)
        native_export_layout.addWidget(self.preview_compressed_button, 5, 0, 1, 2)
        native_export_layout.addWidget(self.native_dds_status_label, 6, 0, 1, 2)
        left_actions_layout.addLayout(native_export_layout)
        left_actions_layout.addWidget(self.warning_label)
        left_actions_layout.addWidget(self.status_label)
        tool_layout.addWidget(left_actions_body)
        self.tool_buttons: Dict[str, QToolButton] = {}
        tool_group = QGroupBox("Tools")
        tool_group.setObjectName("EditorToolGroup")
        tool_group_layout = QVBoxLayout(tool_group)
        tool_group_layout.setContentsMargins(8, 12, 8, 8)
        tool_group_layout.setSpacing(4)
        for tool_key, label in (
            ("paint", "Paint"),
            ("erase", "Erase"),
            ("fill", "Fill"),
            ("gradient", "Gradient"),
            ("sharpen", "Sharpen"),
            ("soften", "Soften"),
            ("smudge", "Smudge"),
            ("dodge_burn", "Dodge/Burn"),
            ("clone", "Clone"),
            ("heal", "Heal"),
            ("patch", "Patch"),
            ("move", "Move"),
            ("select_rect", "Rect Select"),
            ("lasso", "Lasso"),
            ("recolor", "Recolor"),
        ):
            button = QToolButton()
            button.setText(label)
            button.setIcon(_create_tool_icon(tool_key))
            button.setCheckable(True)
            button.setObjectName("EditorToolButton")
            button.setToolButtonStyle(Qt.ToolButtonTextBesideIcon)
            button.setIconSize(QSize(16, 16))
            button.setMinimumHeight(22)
            button.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
            button.setAutoRaise(False)
            button.setToolTip(label)
            self.tool_buttons[tool_key] = button
            tool_group_layout.addWidget(button)
        tool_group_layout.addStretch(1)
        tool_layout.addWidget(tool_group)
        tool_layout.addStretch(1)
        self.left_scroll = QScrollArea()
        self.left_scroll.setObjectName("EditorSidebarScroll")
        self.left_scroll.setWidgetResizable(True)
        self.left_scroll.setFrameShape(QFrame.NoFrame)
        self.left_scroll.setMinimumWidth(editor_tool_min)
        self.left_scroll.setMaximumWidth(editor_tool_max)
        self.left_scroll.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Expanding)
        self.left_scroll.setWidget(self.tool_panel)
        self.main_splitter.addWidget(self.left_scroll)

        self.canvas_panel = QWidget()
        self.canvas_panel.setObjectName("EditorCanvasPane")
        self.canvas_panel.setMinimumWidth(480)
        canvas_layout = QVBoxLayout(self.canvas_panel)
        canvas_layout.setContentsMargins(12, 12, 12, 12)
        canvas_layout.setSpacing(10)
        canvas_layout.addWidget(self.document_tab_bar)
        self.canvas_toolbar = QFrame()
        self.canvas_toolbar.setObjectName("EditorActionPane")
        zoom_row = QHBoxLayout(self.canvas_toolbar)
        zoom_row.setContentsMargins(8, 6, 8, 4)
        zoom_row.setSpacing(6)
        self.zoom_out_button = QPushButton("-")
        self.zoom_fit_button = QPushButton("Fit")
        self.zoom_100_button = QPushButton("100%")
        self.zoom_in_button = QPushButton("+")
        self.zoom_label = QLabel("Fit")
        self.zoom_label.setObjectName("HintLabel")
        self.zoom_label.setMinimumWidth(44)
        self.zoom_label.setAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        self.view_mode_combo = QComboBox()
        self.view_mode_combo.addItem("Edited", "edited")
        self.view_mode_combo.addItem("Original", "original")
        self.view_mode_combo.addItem("Split", "split")
        self.view_mode_combo.addItem("Red", "red")
        self.view_mode_combo.addItem("Green", "green")
        self.view_mode_combo.addItem("Blue", "blue")
        self.view_mode_combo.addItem("Alpha", "alpha")
        self.view_mode_combo.setMinimumWidth(96)
        self.view_mode_label = QLabel("View")
        self.view_mode_label.setObjectName("HintLabel")
        self.compare_split_slider = QSlider(Qt.Horizontal)
        self.compare_split_slider.setRange(5, 95)
        self.compare_split_slider.setValue(50)
        self.compare_split_slider.setMinimumWidth(72)
        self.compare_split_slider.setMaximumWidth(110)
        self.compare_split_slider.setVisible(False)
        self.grid_checkbox = QCheckBox("Grid")
        self.grid_size_spin = QSpinBox()
        self.grid_size_spin.setRange(4, 1024)
        self.grid_size_spin.setSingleStep(4)
        self.grid_size_spin.setValue(64)
        self.grid_size_spin.setMinimumWidth(60)
        self.grid_size_spin.setMaximumWidth(80)
        self.grid_color_button = QToolButton()
        self.grid_color_button.setFixedSize(24, 24)
        self.grid_color_button.setToolTip("Grid color")
        self.grid_color_button.setAutoRaise(False)
        self.grid_opacity_spin = QSpinBox()
        self.grid_opacity_spin.setRange(5, 100)
        self.grid_opacity_spin.setSuffix("%")
        self.grid_opacity_spin.setValue(42)
        self.grid_opacity_spin.setToolTip("Grid opacity")
        self.grid_opacity_spin.setMinimumWidth(64)
        self.grid_opacity_spin.setMaximumWidth(72)
        self.zoom_out_button.setMinimumSize(32, 28)
        self.zoom_fit_button.setMinimumSize(42, 28)
        self.zoom_100_button.setMinimumSize(52, 28)
        self.zoom_in_button.setMinimumSize(32, 28)
        zoom_row.addWidget(self.zoom_out_button)
        zoom_row.addWidget(self.zoom_fit_button)
        zoom_row.addWidget(self.zoom_100_button)
        zoom_row.addWidget(self.zoom_in_button)
        zoom_row.addWidget(self.zoom_label)
        zoom_row.addSpacing(8)
        zoom_row.addWidget(self.view_mode_label)
        zoom_row.addWidget(self.view_mode_combo)
        zoom_row.addWidget(self.compare_split_slider)
        zoom_row.addSpacing(6)
        zoom_row.addWidget(self.grid_checkbox)
        zoom_row.addWidget(self.grid_size_spin)
        zoom_row.addWidget(self.grid_color_button)
        zoom_row.addWidget(self.grid_opacity_spin)
        zoom_row.addStretch(1)
        canvas_layout.addWidget(self.canvas_toolbar)
        self.canvas = TextureEditorCanvas()
        self.canvas_scroll = QScrollArea()
        self.canvas_scroll.setWidgetResizable(False)
        self.canvas_scroll.setAlignment(Qt.AlignCenter)
        self.canvas_scroll.setWidget(self.canvas)
        self.canvas.attach_scroll_area(self.canvas_scroll)
        self.ruler_corner = QFrame()
        self.ruler_corner.setFixedSize(22, 22)
        self.ruler_corner.setObjectName("EditorRulerCorner")
        self.top_ruler = TextureEditorRuler(Qt.Horizontal)
        self.left_ruler = TextureEditorRuler(Qt.Vertical)
        canvas_view_grid = QGridLayout()
        canvas_view_grid.setContentsMargins(0, 0, 0, 0)
        canvas_view_grid.setHorizontalSpacing(0)
        canvas_view_grid.setVerticalSpacing(0)
        canvas_view_grid.addWidget(self.ruler_corner, 0, 0)
        canvas_view_grid.addWidget(self.top_ruler, 0, 1)
        canvas_view_grid.addWidget(self.left_ruler, 1, 0)
        canvas_view_grid.addWidget(self.canvas_scroll, 1, 1)
        canvas_view_grid.setColumnStretch(1, 1)
        canvas_view_grid.setRowStretch(1, 1)
        canvas_layout.addLayout(canvas_view_grid, stretch=1)
        self.canvas_status_strip = QFrame()
        self.canvas_status_strip.setObjectName("EditorActionPane")
        canvas_status_layout = QHBoxLayout(self.canvas_status_strip)
        canvas_status_layout.setContentsMargins(8, 4, 8, 4)
        canvas_status_layout.setSpacing(10)
        self.canvas_status_zoom_label = QLabel("100%")
        self.canvas_status_tool_label = QLabel("Paint")
        self.canvas_status_layer_label = QLabel("Layer")
        self.canvas_status_selection_label = QLabel("No selection")
        self.canvas_status_state_label = QLabel("Ready")
        self.canvas_status_document_label = QLabel("No document")
        self.canvas_status_pixel_label = QLabel("XY -, -  RGBA -")
        self.canvas_status_source_label = QLabel("")
        self.canvas_status_source_label.setObjectName("HintLabel")
        for label_widget in (
            self.canvas_status_zoom_label,
            self.canvas_status_tool_label,
            self.canvas_status_layer_label,
            self.canvas_status_selection_label,
            self.canvas_status_state_label,
            self.canvas_status_document_label,
            self.canvas_status_pixel_label,
        ):
            label_widget.setObjectName("HintLabel")
            canvas_status_layout.addWidget(label_widget)
        canvas_status_layout.addWidget(self.canvas_status_source_label, stretch=1)
        canvas_layout.addWidget(self.canvas_status_strip)
        self.main_splitter.addWidget(self.canvas_panel)

        self.right_panel = QWidget()
        self.right_panel.setObjectName("EditorInspectorSidebar")
        self.right_panel.setMinimumWidth(210)
        right_layout = QVBoxLayout(self.right_panel)
        right_layout.setContentsMargins(12, 12, 12, 12)
        right_layout.setSpacing(10)
        settings_title = QLabel("Settings")
        settings_title.setStyleSheet("font-weight: 600;")
        right_layout.addWidget(settings_title)
        self.metadata_browser = QTextBrowser()
        self.metadata_browser.setOpenExternalLinks(False)
        self.metadata_browser.setMinimumHeight(120)
        self.metadata_browser.setFrameShape(QFrame.NoFrame)
        self.metadata_browser.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        self.metadata_browser.setStyleSheet("background: transparent; border: none;")
        metadata_body = QFrame()
        metadata_body.setObjectName("EditorSectionBody")
        metadata_layout = QVBoxLayout(metadata_body)
        metadata_layout.setContentsMargins(10, 10, 10, 10)
        metadata_layout.addWidget(self.metadata_browser)
        self.metadata_section = CollapsibleSection("Document", metadata_body, expanded=False)
        right_layout.addWidget(self.metadata_section)

        navigator_body = QFrame()
        navigator_body.setObjectName("EditorSectionBody")
        navigator_layout = QVBoxLayout(navigator_body)
        navigator_layout.setContentsMargins(10, 10, 10, 10)
        navigator_layout.setSpacing(8)
        self.navigator_widget = TextureEditorNavigator()
        navigator_layout.addWidget(self.navigator_widget)
        self.show_rulers_checkbox = QCheckBox("Show rulers")
        self.show_rulers_checkbox.setChecked(True)
        self.show_guides_checkbox = QCheckBox("Show guides")
        self.show_guides_checkbox.setChecked(False)
        navigator_layout.addWidget(self.show_rulers_checkbox)
        navigator_layout.addWidget(self.show_guides_checkbox)
        navigator_layout.addWidget(QLabel("Vertical guides"))
        self.vertical_guides_edit = QLineEdit()
        self.vertical_guides_edit.setPlaceholderText("e.g. 128, 256, 512")
        navigator_layout.addWidget(self.vertical_guides_edit)
        navigator_layout.addWidget(QLabel("Horizontal guides"))
        self.horizontal_guides_edit = QLineEdit()
        self.horizontal_guides_edit.setPlaceholderText("e.g. 64, 128")
        navigator_layout.addWidget(self.horizontal_guides_edit)
        guide_actions = QHBoxLayout()
        self.apply_guides_button = QPushButton("Apply Guides")
        self.clear_guides_button = QPushButton("Clear Guides")
        for button in (self.apply_guides_button, self.clear_guides_button):
            button.setObjectName("EditorPanelButton")
        guide_actions.addWidget(self.apply_guides_button)
        guide_actions.addWidget(self.clear_guides_button)
        navigator_layout.addLayout(guide_actions)
        self.navigator_section = CollapsibleSection("Navigator", navigator_body, expanded=True)
        right_layout.addWidget(self.navigator_section)

        tool_settings_body = QFrame()
        tool_settings_body.setObjectName("EditorSectionBody")
        self.tool_settings_layout = QFormLayout(tool_settings_body)
        self.tool_settings_layout.setContentsMargins(10, 10, 10, 10)
        self.tool_settings_layout.setFieldGrowthPolicy(QFormLayout.ExpandingFieldsGrow)
        self.tool_settings_layout.setRowWrapPolicy(QFormLayout.DontWrapRows)
        self.tool_settings_layout.setHorizontalSpacing(12)
        self.tool_settings_layout.setVerticalSpacing(8)
        self.tool_settings_layout.setLabelAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        self.paint_color_edit = QLineEdit("#C85A30")
        self.paint_color_button = QPushButton("Pick")
        self.paint_color_sample_button = QPushButton("Sample")
        self.paint_color_row = QWidget()
        paint_color_row_layout = QHBoxLayout(self.paint_color_row)
        paint_color_row_layout.setContentsMargins(0, 0, 0, 0)
        paint_color_row_layout.setSpacing(6)
        paint_color_row_layout.addWidget(self.paint_color_edit, stretch=1)
        paint_color_row_layout.addWidget(self.paint_color_button)
        paint_color_row_layout.addWidget(self.paint_color_sample_button)
        self.secondary_color_edit = QLineEdit("#FFFFFF")
        self.secondary_color_button = QPushButton("Pick")
        self.secondary_color_sample_button = QPushButton("Sample")
        self.secondary_color_row = QWidget()
        secondary_color_row_layout = QHBoxLayout(self.secondary_color_row)
        secondary_color_row_layout.setContentsMargins(0, 0, 0, 0)
        secondary_color_row_layout.setSpacing(6)
        secondary_color_row_layout.addWidget(self.secondary_color_edit, stretch=1)
        secondary_color_row_layout.addWidget(self.secondary_color_button)
        secondary_color_row_layout.addWidget(self.secondary_color_sample_button)
        self.brush_preset_combo = QComboBox()
        for entry in texture_editor_brush_preset_combo_state(
            self._custom_brush_presets,
            preserve_key="custom",
            current_key="custom",
        ).entries:
            self.brush_preset_combo.addItem(entry.label, entry.key)
        self.save_brush_preset_button = QPushButton("Save Preset")
        self.save_brush_preset_button.setObjectName("EditorPanelButton")
        self.brush_preset_row = QWidget()
        brush_preset_row_layout = QHBoxLayout(self.brush_preset_row)
        brush_preset_row_layout.setContentsMargins(0, 0, 0, 0)
        brush_preset_row_layout.setSpacing(6)
        brush_preset_row_layout.addWidget(self.brush_preset_combo, stretch=1)
        brush_preset_row_layout.addWidget(self.save_brush_preset_button)
        self.brush_tip_combo = QComboBox()
        self.brush_tip_combo.addItem("Round", "round")
        self.brush_tip_combo.addItem("Square", "square")
        self.brush_tip_combo.addItem("Diamond", "diamond")
        self.brush_tip_combo.addItem("Flat", "flat")
        self.brush_tip_combo.addItem("Image Stamp", "image_stamp")
        self.brush_pattern_combo = QComboBox()
        self.brush_pattern_combo.addItem("Solid", "solid")
        self.brush_pattern_combo.addItem("Speckle", "speckle")
        self.brush_pattern_combo.addItem("Hatch", "hatch")
        self.brush_pattern_combo.addItem("Crosshatch", "crosshatch")
        self.brush_pattern_combo.addItem("Grain", "grain")
        self.custom_brush_tip_path_edit = QLineEdit()
        self.custom_brush_tip_path_edit.setReadOnly(True)
        self.custom_brush_tip_path_edit.setPlaceholderText("No image stamp loaded")
        self.load_custom_brush_tip_button = QPushButton("Load...")
        self.clear_custom_brush_tip_button = QPushButton("Clear")
        self.custom_brush_tip_row = QWidget()
        custom_brush_tip_row_layout = QHBoxLayout(self.custom_brush_tip_row)
        custom_brush_tip_row_layout.setContentsMargins(0, 0, 0, 0)
        custom_brush_tip_row_layout.setSpacing(6)
        custom_brush_tip_row_layout.addWidget(self.custom_brush_tip_path_edit, stretch=1)
        custom_brush_tip_row_layout.addWidget(self.load_custom_brush_tip_button)
        custom_brush_tip_row_layout.addWidget(self.clear_custom_brush_tip_button)
        self.symmetry_mode_combo = QComboBox()
        self.symmetry_mode_combo.addItem("Off", "off")
        self.symmetry_mode_combo.addItem("Horizontal mirror", "horizontal")
        self.symmetry_mode_combo.addItem("Vertical mirror", "vertical")
        self.symmetry_mode_combo.addItem("Both axes", "both")
        self.brush_size_slider = QSlider(Qt.Horizontal)
        self.brush_size_slider.setRange(1, 256)
        self.brush_size_slider.setValue(32)
        self.size_step_mode_combo = QComboBox()
        self.size_step_mode_combo.addItem("Normal", "normal")
        self.size_step_mode_combo.addItem("Fine detail", "fine")
        self.hardness_slider = QSlider(Qt.Horizontal)
        self.hardness_slider.setRange(0, 100)
        self.hardness_slider.setValue(80)
        self.roundness_slider = QSlider(Qt.Horizontal)
        self.roundness_slider.setRange(10, 100)
        self.roundness_slider.setValue(100)
        self.angle_slider = QSlider(Qt.Horizontal)
        self.angle_slider.setRange(-180, 180)
        self.angle_slider.setValue(0)
        self.smoothing_slider = QSlider(Qt.Horizontal)
        self.smoothing_slider.setRange(0, 100)
        self.smoothing_slider.setValue(0)
        self.opacity_slider = QSlider(Qt.Horizontal)
        self.opacity_slider.setRange(1, 100)
        self.opacity_slider.setValue(100)
        self.flow_slider = QSlider(Qt.Horizontal)
        self.flow_slider.setRange(1, 100)
        self.flow_slider.setValue(100)
        self.spacing_slider = QSlider(Qt.Horizontal)
        self.spacing_slider.setRange(1, 100)
        self.spacing_slider.setValue(20)
        self.fill_tolerance_slider = QSlider(Qt.Horizontal)
        self.fill_tolerance_slider.setRange(0, 255)
        self.fill_tolerance_slider.setValue(24)
        self.fill_contiguous_checkbox = QCheckBox("Contiguous fill only")
        self.fill_contiguous_checkbox.setChecked(True)
        self.strength_slider = QSlider(Qt.Horizontal)
        self.strength_slider.setRange(0, 100)
        self.strength_slider.setValue(25)
        self.paint_blend_mode_combo = QComboBox()
        self.paint_blend_mode_combo.addItem("Normal", "normal")
        self.paint_blend_mode_combo.addItem("Multiply", "multiply")
        self.paint_blend_mode_combo.addItem("Screen", "screen")
        self.paint_blend_mode_combo.addItem("Overlay", "overlay")
        self.sharpen_mode_combo = QComboBox()
        self.sharpen_mode_combo.addItem("Unsharp Mask", "unsharp_mask")
        self.sharpen_mode_combo.addItem("Local Contrast", "local_contrast")
        self.sharpen_mode_combo.addItem("High Pass", "high_pass")
        self.soften_mode_combo = QComboBox()
        self.soften_mode_combo.addItem("Gaussian Blur", "gaussian")
        self.soften_mode_combo.addItem("Median Blur", "median")
        self.soften_mode_combo.addItem("Surface Blur", "surface")
        self.sample_visible_layers_checkbox = QCheckBox("Sample visible layers")
        self.sample_visible_layers_checkbox.setChecked(True)
        self.clone_aligned_checkbox = QCheckBox("Aligned sampling")
        self.clone_aligned_checkbox.setChecked(True)
        self.clear_clone_source_button = QPushButton("Clear Source")
        self.clear_clone_source_button.setObjectName("EditorPanelButton")
        self.lasso_snap_checkbox = QCheckBox("Snap lasso to edges")
        self.lasso_snap_checkbox.setChecked(False)
        self.lasso_snap_radius_slider = QSlider(Qt.Horizontal)
        self.lasso_snap_radius_slider.setRange(2, 24)
        self.lasso_snap_radius_slider.setValue(10)
        self.lasso_snap_sensitivity_slider = QSlider(Qt.Horizontal)
        self.lasso_snap_sensitivity_slider.setRange(1, 100)
        self.lasso_snap_sensitivity_slider.setValue(55)
        self.clone_source_label = QLabel("Ctrl+right-click sets the source point. Right-drag pans the canvas. Turn off aligned sampling to keep stamping from one fixed source.")
        self.clone_source_label.setWordWrap(True)
        self.smudge_strength_slider = QSlider(Qt.Horizontal)
        self.smudge_strength_slider.setRange(1, 100)
        self.smudge_strength_slider.setValue(45)
        self.dodge_burn_mode_combo = QComboBox()
        self.dodge_burn_mode_combo.addItem("Dodge Midtones", "dodge_midtones")
        self.dodge_burn_mode_combo.addItem("Dodge Highlights", "dodge_highlights")
        self.dodge_burn_mode_combo.addItem("Dodge Shadows", "dodge_shadows")
        self.dodge_burn_mode_combo.addItem("Burn Midtones", "burn_midtones")
        self.dodge_burn_mode_combo.addItem("Burn Highlights", "burn_highlights")
        self.dodge_burn_mode_combo.addItem("Burn Shadows", "burn_shadows")
        self.dodge_burn_exposure_slider = QSlider(Qt.Horizontal)
        self.dodge_burn_exposure_slider.setRange(1, 100)
        self.dodge_burn_exposure_slider.setValue(20)
        self.patch_blend_slider = QSlider(Qt.Horizontal)
        self.patch_blend_slider.setRange(1, 100)
        self.patch_blend_slider.setValue(70)
        self.gradient_type_combo = QComboBox()
        self.gradient_type_combo.addItem("Linear", "linear")
        self.gradient_type_combo.addItem("Radial", "radial")
        self.recolor_mode_combo = QComboBox()
        self.recolor_mode_combo.addItem("Tint whole texture", "tint")
        self.recolor_mode_combo.addItem("Replace selected color", "replace_color")
        self.recolor_source_edit = QLineEdit("#808080")
        self.recolor_source_pick_button = QPushButton("Pick")
        self.recolor_source_sample_button = QPushButton("Sample")
        self.recolor_target_edit = QLineEdit("#C85A30")
        self.recolor_target_pick_button = QPushButton("Pick")
        self.recolor_target_sample_button = QPushButton("Sample")
        self.recolor_tolerance_slider = QSlider(Qt.Horizontal)
        self.recolor_tolerance_slider.setRange(0, 255)
        self.recolor_tolerance_slider.setValue(48)
        self.recolor_strength_slider = QSlider(Qt.Horizontal)
        self.recolor_strength_slider.setRange(1, 100)
        self.recolor_strength_slider.setValue(100)
        self.recolor_preserve_luma_checkbox = QCheckBox("Preserve shading / luminance")
        self.recolor_preserve_luma_checkbox.setChecked(True)
        self.apply_recolor_button = QPushButton("Apply Recolor To Active Layer")
        recolor_source_row = QWidget()
        recolor_source_row_layout = QHBoxLayout(recolor_source_row)
        recolor_source_row_layout.setContentsMargins(0, 0, 0, 0)
        recolor_source_row_layout.setSpacing(6)
        recolor_source_row_layout.addWidget(self.recolor_source_edit, stretch=1)
        recolor_source_row_layout.addWidget(self.recolor_source_pick_button)
        recolor_source_row_layout.addWidget(self.recolor_source_sample_button)
        recolor_target_row = QWidget()
        recolor_target_row_layout = QHBoxLayout(recolor_target_row)
        recolor_target_row_layout.setContentsMargins(0, 0, 0, 0)
        recolor_target_row_layout.setSpacing(6)
        recolor_target_row_layout.addWidget(self.recolor_target_edit, stretch=1)
        recolor_target_row_layout.addWidget(self.recolor_target_pick_button)
        recolor_target_row_layout.addWidget(self.recolor_target_sample_button)
        self._add_tool_setting_row("brush_preset", "Preset", self.brush_preset_row)
        self._add_tool_setting_row("brush_tip", "Brush tip", self.brush_tip_combo)
        self._add_tool_setting_row("custom_brush_tip", "Stamp", self.custom_brush_tip_row)
        self._add_tool_setting_row("brush_pattern", "Pattern", self.brush_pattern_combo)
        self._add_tool_setting_row("symmetry_mode", "Symmetry", self.symmetry_mode_combo)
        self._add_tool_setting_row("paint_color", "Color", self.paint_color_row)
        self._add_tool_setting_row("secondary_color", "Secondary", self.secondary_color_row)
        self._add_tool_setting_row("brush_size", "Brush size", self.brush_size_slider)
        self._add_tool_setting_row("size_step_mode", "Size mode", self.size_step_mode_combo)
        self._add_tool_setting_row("hardness", "Hardness", self.hardness_slider)
        self._add_tool_setting_row("roundness", "Roundness", self.roundness_slider)
        self._add_tool_setting_row("angle_degrees", "Angle", self.angle_slider)
        self._add_tool_setting_row("smoothing", "Smoothing", self.smoothing_slider)
        self._add_tool_setting_row("opacity", "Opacity", self.opacity_slider)
        self._add_tool_setting_row("flow", "Flow", self.flow_slider)
        self._add_tool_setting_row("spacing", "Spacing", self.spacing_slider)
        self._add_tool_setting_row("paint_blend_mode", "Blend mode", self.paint_blend_mode_combo)
        self._add_tool_setting_row("fill_tolerance", "Fill tolerance", self.fill_tolerance_slider)
        self._add_tool_setting_row("fill_contiguous", "", self.fill_contiguous_checkbox)
        self._add_tool_setting_row("strength", "Strength", self.strength_slider)
        self._add_tool_setting_row("smudge_strength", "Smudge", self.smudge_strength_slider)
        self._add_tool_setting_row("dodge_burn_mode", "Tone mode", self.dodge_burn_mode_combo)
        self._add_tool_setting_row("dodge_burn_exposure", "Exposure", self.dodge_burn_exposure_slider)
        self._add_tool_setting_row("patch_blend", "Patch blend", self.patch_blend_slider)
        self._add_tool_setting_row("gradient_type", "Gradient", self.gradient_type_combo)
        self._add_tool_setting_row("sharpen_mode", "Sharpen mode", self.sharpen_mode_combo)
        self._add_tool_setting_row("soften_mode", "Soften mode", self.soften_mode_combo)
        self._add_tool_setting_row("sample_visible_layers", "", self.sample_visible_layers_checkbox)
        self._add_tool_setting_row("clone_aligned", "", self.clone_aligned_checkbox)
        self._add_tool_setting_row("clone_clear_source", "", self.clear_clone_source_button)
        self._add_tool_setting_row("lasso_snap_to_edges", "", self.lasso_snap_checkbox)
        self._add_tool_setting_row("lasso_snap_radius", "Snap radius", self.lasso_snap_radius_slider)
        self._add_tool_setting_row("lasso_snap_sensitivity", "Edge sensitivity", self.lasso_snap_sensitivity_slider)
        self._add_tool_setting_row("clone_hint", "Clone / Heal", self.clone_source_label)
        self._add_tool_setting_row("recolor_mode", "Recolor mode", self.recolor_mode_combo)
        self._add_tool_setting_row("recolor_source", "Recolor source", recolor_source_row)
        self._add_tool_setting_row("recolor_target", "Recolor target", recolor_target_row)
        self._add_tool_setting_row("recolor_tolerance", "Recolor tolerance", self.recolor_tolerance_slider)
        self._add_tool_setting_row("recolor_strength", "Recolor strength", self.recolor_strength_slider)
        self._add_tool_setting_row("recolor_preserve_luma", "", self.recolor_preserve_luma_checkbox)
        self._add_tool_setting_row("recolor_apply", "", self.apply_recolor_button)
        self.tool_settings_section = CollapsibleSection("Tool Settings", tool_settings_body, expanded=True)
        right_layout.addWidget(self.tool_settings_section)

        selection_body = QFrame()
        selection_body.setObjectName("EditorSectionBody")
        selection_layout = QVBoxLayout(selection_body)
        selection_layout.setContentsMargins(10, 10, 10, 10)
        selection_layout.setSpacing(8)
        self.selection_help_label = QLabel(
            "Selections limit paint, erase, fill, clone, heal, sharpen, soften, and recolor to the selected area. Quick Mask now lets Paint, Erase, and Fill edit the selection directly."
        )
        self.selection_help_label.setWordWrap(True)
        selection_layout.addWidget(self.selection_help_label)
        selection_form = QFormLayout()
        selection_form.setContentsMargins(0, 0, 0, 0)
        selection_form.setHorizontalSpacing(10)
        selection_form.setVerticalSpacing(8)
        self.selection_mode_combo = QComboBox()
        self.selection_mode_combo.addItem("Replace", "replace")
        self.selection_mode_combo.addItem("Add", "add")
        self.selection_mode_combo.addItem("Subtract", "subtract")
        self.selection_mode_combo.addItem("Intersect", "intersect")
        selection_form.addRow("Mode", self.selection_mode_combo)
        self.selection_feather_slider = QSlider(Qt.Horizontal)
        self.selection_feather_slider.setRange(0, 32)
        self.selection_feather_slider.setValue(0)
        selection_form.addRow("Feather", self.selection_feather_slider)
        self.selection_refine_spin = QSpinBox()
        self.selection_refine_spin.setRange(1, 64)
        self.selection_refine_spin.setValue(4)
        selection_form.addRow("Grow/Shrink", self.selection_refine_spin)
        selection_layout.addLayout(selection_form)
        self.selection_invert_checkbox = QCheckBox("Invert current selection")
        self.selection_quick_mask_checkbox = QCheckBox("Quick mask overlay")
        selection_layout.addWidget(self.selection_invert_checkbox)
        selection_layout.addWidget(self.selection_quick_mask_checkbox)
        selection_actions = QGridLayout()
        selection_actions.setHorizontalSpacing(8)
        selection_actions.setVerticalSpacing(8)
        self.selection_copy_layer_button = QPushButton("Copy To New Layer")
        self.selection_select_all_button = QPushButton("Select All")
        self.selection_clear_button = QPushButton("Clear Selection")
        self.selection_grow_button = QPushButton("Grow +4")
        self.selection_shrink_button = QPushButton("Shrink -4")
        self.selection_to_mask_button = QPushButton("Selection To Mask")
        self.selection_from_mask_button = QPushButton("Mask To Selection")
        for button in (
            self.selection_copy_layer_button,
            self.selection_select_all_button,
            self.selection_clear_button,
            self.selection_grow_button,
            self.selection_shrink_button,
            self.selection_to_mask_button,
            self.selection_from_mask_button,
        ):
            button.setObjectName("EditorPanelButton")
            button.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        selection_actions.addWidget(self.selection_copy_layer_button, 0, 0, 1, 2)
        selection_actions.addWidget(self.selection_select_all_button, 1, 0)
        selection_actions.addWidget(self.selection_clear_button, 1, 1)
        selection_actions.addWidget(self.selection_grow_button, 2, 0)
        selection_actions.addWidget(self.selection_shrink_button, 2, 1)
        selection_actions.addWidget(self.selection_to_mask_button, 3, 0)
        selection_actions.addWidget(self.selection_from_mask_button, 3, 1)
        selection_layout.addLayout(selection_actions)
        self.selection_section = CollapsibleSection("Selection", selection_body, expanded=False)
        right_layout.addWidget(self.selection_section)

        channels_body = QFrame()
        channels_body.setObjectName("EditorSectionBody")
        channels_layout = QVBoxLayout(channels_body)
        channels_layout.setContentsMargins(10, 10, 10, 10)
        channels_layout.setSpacing(8)
        self.channel_help_label = QLabel("Choose which channels paint, fill, gradient, recolor, and retouch tools are allowed to modify.")
        self.channel_help_label.setWordWrap(True)
        channels_layout.addWidget(self.channel_help_label)
        channel_grid = QGridLayout()
        channel_grid.setHorizontalSpacing(8)
        channel_grid.setVerticalSpacing(6)
        self.channel_red_checkbox = QCheckBox("R")
        self.channel_green_checkbox = QCheckBox("G")
        self.channel_blue_checkbox = QCheckBox("B")
        self.channel_alpha_checkbox = QCheckBox("A")
        self.channel_red_checkbox.setChecked(True)
        self.channel_green_checkbox.setChecked(True)
        self.channel_blue_checkbox.setChecked(True)
        self.channel_alpha_checkbox.setChecked(True)
        channel_grid.addWidget(self.channel_red_checkbox, 0, 0)
        channel_grid.addWidget(self.channel_green_checkbox, 0, 1)
        channel_grid.addWidget(self.channel_blue_checkbox, 0, 2)
        channel_grid.addWidget(self.channel_alpha_checkbox, 0, 3)
        channels_layout.addLayout(channel_grid)
        channel_actions = QGridLayout()
        channel_actions.setHorizontalSpacing(8)
        channel_actions.setVerticalSpacing(8)
        self.channel_all_button = QPushButton("All")
        self.channel_rgb_button = QPushButton("RGB")
        self.channel_alpha_only_button = QPushButton("Alpha Only")
        for button in (
            self.channel_all_button,
            self.channel_rgb_button,
            self.channel_alpha_only_button,
        ):
            button.setObjectName("EditorPanelButton")
            button.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        channel_actions.addWidget(self.channel_all_button, 0, 0)
        channel_actions.addWidget(self.channel_rgb_button, 0, 1)
        channel_actions.addWidget(self.channel_alpha_only_button, 0, 2)
        channels_layout.addLayout(channel_actions)
        packed_actions = QGridLayout()
        packed_actions.setHorizontalSpacing(8)
        packed_actions.setVerticalSpacing(8)
        self.channel_extract_combo = QComboBox()
        self.channel_extract_combo.addItem("Extract Red", "red")
        self.channel_extract_combo.addItem("Extract Green", "green")
        self.channel_extract_combo.addItem("Extract Blue", "blue")
        self.channel_extract_combo.addItem("Extract Alpha", "alpha")
        self.channel_extract_button = QPushButton("Extract To Layer")
        self.channel_pack_combo = QComboBox()
        self.channel_pack_combo.addItem("Pack Luma To Red", "red")
        self.channel_pack_combo.addItem("Pack Luma To Green", "green")
        self.channel_pack_combo.addItem("Pack Luma To Blue", "blue")
        self.channel_pack_combo.addItem("Pack Luma To Alpha", "alpha")
        self.channel_pack_button = QPushButton("Apply")
        self.channel_selection_combo = QComboBox()
        self.channel_selection_combo.addItem("Load Red As Selection", "red")
        self.channel_selection_combo.addItem("Load Green As Selection", "green")
        self.channel_selection_combo.addItem("Load Blue As Selection", "blue")
        self.channel_selection_combo.addItem("Load Alpha As Selection", "alpha")
        self.channel_selection_from_button = QPushButton("From Channel")
        self.channel_selection_to_combo = QComboBox()
        self.channel_selection_to_combo.addItem("Write Selection To Red", "red")
        self.channel_selection_to_combo.addItem("Write Selection To Green", "green")
        self.channel_selection_to_combo.addItem("Write Selection To Blue", "blue")
        self.channel_selection_to_combo.addItem("Write Selection To Alpha", "alpha")
        self.channel_selection_to_button = QPushButton("To Channel")
        self.channel_copy_combo = QComboBox()
        self.channel_copy_combo.addItem("Copy Red", "red")
        self.channel_copy_combo.addItem("Copy Green", "green")
        self.channel_copy_combo.addItem("Copy Blue", "blue")
        self.channel_copy_combo.addItem("Copy Alpha", "alpha")
        self.channel_copy_button = QPushButton("Copy")
        self.channel_paste_combo = QComboBox()
        self.channel_paste_combo.addItem("Paste To Red", "red")
        self.channel_paste_combo.addItem("Paste To Green", "green")
        self.channel_paste_combo.addItem("Paste To Blue", "blue")
        self.channel_paste_combo.addItem("Paste To Alpha", "alpha")
        self.channel_paste_button = QPushButton("Paste")
        self.channel_swap_a_combo = QComboBox()
        self.channel_swap_b_combo = QComboBox()
        for combo in (self.channel_swap_a_combo, self.channel_swap_b_combo):
            combo.addItem("Red", "red")
            combo.addItem("Green", "green")
            combo.addItem("Blue", "blue")
            combo.addItem("Alpha", "alpha")
        self.channel_swap_b_combo.setCurrentIndex(2)
        self.channel_swap_button = QPushButton("Swap")
        for button in (
            self.channel_extract_button,
            self.channel_pack_button,
            self.channel_selection_from_button,
            self.channel_selection_to_button,
            self.channel_copy_button,
            self.channel_paste_button,
            self.channel_swap_button,
        ):
            button.setObjectName("EditorPanelButton")
            button.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
            button.setMinimumWidth(0)
        packed_actions.addWidget(self.channel_extract_combo, 0, 0)
        packed_actions.addWidget(self.channel_extract_button, 0, 1)
        packed_actions.addWidget(self.channel_pack_combo, 1, 0)
        packed_actions.addWidget(self.channel_pack_button, 1, 1)
        packed_actions.addWidget(self.channel_selection_combo, 2, 0)
        packed_actions.addWidget(self.channel_selection_from_button, 2, 1)
        packed_actions.addWidget(self.channel_selection_to_combo, 3, 0)
        packed_actions.addWidget(self.channel_selection_to_button, 3, 1)
        packed_actions.addWidget(self.channel_copy_combo, 4, 0)
        packed_actions.addWidget(self.channel_copy_button, 4, 1)
        packed_actions.addWidget(self.channel_paste_combo, 5, 0)
        packed_actions.addWidget(self.channel_paste_button, 5, 1)
        swap_row = QWidget()
        swap_row_layout = QHBoxLayout(swap_row)
        swap_row_layout.setContentsMargins(0, 0, 0, 0)
        swap_row_layout.setSpacing(6)
        swap_row_layout.addWidget(self.channel_swap_a_combo, stretch=1)
        swap_row_layout.addWidget(QLabel("â†”"))
        swap_row_layout.addWidget(self.channel_swap_b_combo, stretch=1)
        packed_actions.addWidget(swap_row, 6, 0)
        packed_actions.addWidget(self.channel_swap_button, 6, 1)
        channels_layout.addLayout(packed_actions)
        self.channels_section = CollapsibleSection("Channels", channels_body, expanded=False)
        right_layout.addWidget(self.channels_section)

        transform_body = QFrame()
        transform_body.setObjectName("EditorSectionBody")
        transform_layout = QVBoxLayout(transform_body)
        transform_layout.setContentsMargins(10, 10, 10, 10)
        transform_layout.setSpacing(8)
        self.transform_help_label = QLabel("Float the active layer or a copied selection, then move, scale, rotate, flip, and commit it as an isolated layer.")
        self.transform_help_label.setWordWrap(True)
        transform_layout.addWidget(self.transform_help_label)
        transform_grid = QGridLayout()
        transform_grid.setHorizontalSpacing(8)
        transform_grid.setVerticalSpacing(8)
        self.transform_scale_spin = QSpinBox()
        self.transform_scale_spin.setRange(10, 400)
        self.transform_scale_spin.setValue(100)
        self.transform_rotation_spin = QSpinBox()
        self.transform_rotation_spin.setRange(-180, 180)
        self.transform_rotation_spin.setValue(0)
        self.transform_float_layer_button = QPushButton("Float Active Layer Copy")
        self.transform_apply_button = QPushButton("Apply")
        self.transform_flip_h_button = QPushButton("Flip H")
        self.transform_flip_v_button = QPushButton("Flip V")
        self.transform_rotate_left_button = QPushButton("Rotate -90")
        self.transform_rotate_right_button = QPushButton("Rotate +90")
        self.transform_commit_button = QPushButton("Commit")
        self.transform_cancel_button = QPushButton("Cancel")
        transform_grid.addWidget(QLabel("Scale %"), 0, 0)
        transform_grid.addWidget(self.transform_scale_spin, 0, 1)
        transform_grid.addWidget(QLabel("Rotation"), 1, 0)
        transform_grid.addWidget(self.transform_rotation_spin, 1, 1)
        transform_grid.addWidget(self.transform_float_layer_button, 2, 0, 1, 2)
        transform_grid.addWidget(self.transform_apply_button, 3, 0, 1, 2)
        transform_grid.addWidget(self.transform_flip_h_button, 4, 0)
        transform_grid.addWidget(self.transform_flip_v_button, 4, 1)
        transform_grid.addWidget(self.transform_rotate_left_button, 5, 0)
        transform_grid.addWidget(self.transform_rotate_right_button, 5, 1)
        transform_grid.addWidget(self.transform_commit_button, 6, 0)
        transform_grid.addWidget(self.transform_cancel_button, 6, 1)
        transform_layout.addLayout(transform_grid)
        self.transform_section = CollapsibleSection("Transform", transform_body, expanded=False)
        right_layout.addWidget(self.transform_section)

        image_body = QFrame()
        image_body.setObjectName("EditorSectionBody")
        image_layout = QVBoxLayout(image_body)
        image_layout.setContentsMargins(10, 10, 10, 10)
        image_layout.setSpacing(8)
        self.image_help_label = QLabel("Crop, resize, trim, flip, or rotate the current document while keeping layer positions aligned.")
        self.image_help_label.setWordWrap(True)
        image_layout.addWidget(self.image_help_label)
        image_actions = QVBoxLayout()
        image_actions.setContentsMargins(0, 0, 0, 0)
        image_actions.setSpacing(8)
        self.image_crop_selection_button = QPushButton("Crop To Selection")
        self.image_trim_button = QPushButton("Trim Transparent")
        self.image_resize_button = QPushButton("Image Size...")
        self.canvas_resize_button = QPushButton("Canvas Size...")
        self.image_flip_h_button = QPushButton("Flip H")
        self.image_flip_v_button = QPushButton("Flip V")
        self.image_rotate_left_button = QPushButton("Rotate -90")
        self.image_rotate_right_button = QPushButton("Rotate +90")
        for button in (
            self.image_crop_selection_button,
            self.image_trim_button,
            self.image_resize_button,
            self.canvas_resize_button,
            self.image_flip_h_button,
            self.image_flip_v_button,
            self.image_rotate_left_button,
            self.image_rotate_right_button,
        ):
            button.setObjectName("EditorPanelButton")
            button.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
            button.setMinimumWidth(0)
        image_actions.addWidget(self.image_crop_selection_button)
        image_actions.addWidget(self.image_trim_button)
        image_grid = QGridLayout()
        image_grid.setContentsMargins(0, 0, 0, 0)
        image_grid.setHorizontalSpacing(8)
        image_grid.setVerticalSpacing(8)
        image_grid.addWidget(self.image_resize_button, 0, 0)
        image_grid.addWidget(self.canvas_resize_button, 0, 1)
        image_grid.addWidget(self.image_flip_h_button, 1, 0)
        image_grid.addWidget(self.image_flip_v_button, 1, 1)
        image_grid.addWidget(self.image_rotate_left_button, 2, 0)
        image_grid.addWidget(self.image_rotate_right_button, 2, 1)
        image_actions.addLayout(image_grid)
        image_layout.addLayout(image_actions)
        self.image_section = CollapsibleSection("Image", image_body, expanded=False)
        right_layout.addWidget(self.image_section)

        atlas_body = QFrame()
        atlas_body.setObjectName("EditorSectionBody")
        atlas_layout = QVBoxLayout(atlas_body)
        atlas_layout.setContentsMargins(10, 10, 10, 10)
        atlas_layout.setSpacing(8)
        self.atlas_help_label = QLabel("Use the current grid size for atlas slicing, or export the current selection as a padded region.")
        self.atlas_help_label.setWordWrap(True)
        self.atlas_help_label.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Minimum)
        self.atlas_help_label.setMinimumHeight((self.atlas_help_label.fontMetrics().lineSpacing() * 3) + 6)
        atlas_layout.addWidget(self.atlas_help_label)
        atlas_form = QFormLayout()
        atlas_form.setContentsMargins(0, 0, 0, 0)
        atlas_form.setHorizontalSpacing(10)
        atlas_form.setVerticalSpacing(8)
        self.atlas_padding_spin = QSpinBox()
        self.atlas_padding_spin.setRange(0, 256)
        self.atlas_padding_spin.setValue(0)
        atlas_form.addRow("Padding", self.atlas_padding_spin)
        atlas_layout.addLayout(atlas_form)
        self.atlas_trim_checkbox = QCheckBox("Trim transparent bounds on export")
        self.atlas_skip_empty_checkbox = QCheckBox("Skip empty atlas slices")
        self.atlas_skip_empty_checkbox.setChecked(True)
        atlas_layout.addWidget(self.atlas_trim_checkbox)
        atlas_layout.addWidget(self.atlas_skip_empty_checkbox)
        atlas_actions = QVBoxLayout()
        atlas_actions.setContentsMargins(0, 0, 0, 0)
        atlas_actions.setSpacing(8)
        self.atlas_export_selection_button = QPushButton("Export Selection...")
        self.atlas_export_grid_button = QPushButton("Export Grid Slices...")
        for button in (self.atlas_export_selection_button, self.atlas_export_grid_button):
            button.setObjectName("EditorPanelButton")
            button.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        atlas_actions.addWidget(self.atlas_export_selection_button)
        atlas_actions.addWidget(self.atlas_export_grid_button)
        atlas_layout.addLayout(atlas_actions)
        self.atlas_section = CollapsibleSection("Atlas", atlas_body, expanded=False)
        right_layout.addWidget(self.atlas_section)

        layers_body = QFrame()
        layers_body.setObjectName("EditorSectionBody")
        layers_layout = QVBoxLayout(layers_body)
        layers_layout.setContentsMargins(10, 10, 10, 10)
        self.layers_list = QListWidget()
        self.layers_list.setMinimumHeight(140)
        self.layers_list.setFrameShape(QFrame.NoFrame)
        self.layers_list.setIconSize(QSize(28, 28))
        self.layers_list.setSelectionMode(QListWidget.SingleSelection)
        self.layers_list.setDragDropMode(QListWidget.InternalMove)
        self.layers_list.setDefaultDropAction(Qt.MoveAction)
        self.layers_list.setDragEnabled(True)
        self.layers_list.setAcceptDrops(True)
        self.layers_list.setDropIndicatorShown(True)
        layers_layout.addWidget(self.layers_list)
        layer_actions = QGridLayout()
        layer_actions.setHorizontalSpacing(8)
        layer_actions.setVerticalSpacing(8)
        self.add_layer_button = QPushButton("Add")
        self.duplicate_layer_button = QPushButton("Duplicate")
        self.remove_layer_button = QPushButton("Remove")
        self.merge_layer_button = QPushButton("Merge Down")
        self.layer_up_button = QPushButton("Up")
        self.layer_down_button = QPushButton("Down")
        for button in (
            self.add_layer_button,
            self.duplicate_layer_button,
            self.remove_layer_button,
            self.merge_layer_button,
            self.layer_up_button,
            self.layer_down_button,
        ):
            button.setObjectName("EditorPanelButton")
            button.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
            button.setMinimumWidth(0)
        layer_actions.addWidget(self.add_layer_button, 0, 0)
        layer_actions.addWidget(self.duplicate_layer_button, 0, 1)
        layer_actions.addWidget(self.remove_layer_button, 1, 0)
        layer_actions.addWidget(self.merge_layer_button, 1, 1)
        layer_actions.addWidget(self.layer_up_button, 2, 0)
        layer_actions.addWidget(self.layer_down_button, 2, 1)
        layers_layout.addLayout(layer_actions)
        self.layer_name_edit = QLineEdit()
        self.layer_visible_checkbox = QCheckBox("Visible")
        self.layer_visible_checkbox.setChecked(True)
        self.layer_locked_checkbox = QCheckBox("Lock layer")
        self.layer_alpha_locked_checkbox = QCheckBox("Lock alpha")
        self.layer_mask_enabled_checkbox = QCheckBox("Enable mask")
        self.layer_edit_mask_checkbox = QCheckBox("Edit mask")
        self.layer_blend_mode_combo = QComboBox()
        self.layer_blend_mode_combo.addItem("Normal", "normal")
        self.layer_blend_mode_combo.addItem("Multiply", "multiply")
        self.layer_blend_mode_combo.addItem("Screen", "screen")
        self.layer_blend_mode_combo.addItem("Overlay", "overlay")
        self.layer_opacity_slider = QSlider(Qt.Horizontal)
        self.layer_opacity_slider.setRange(0, 100)
        self.layer_opacity_slider.setValue(100)
        layers_layout.addWidget(QLabel("Layer name"))
        layers_layout.addWidget(self.layer_name_edit)
        layers_layout.addWidget(QLabel("Blend mode"))
        layers_layout.addWidget(self.layer_blend_mode_combo)
        layers_layout.addWidget(self.layer_visible_checkbox)
        layers_layout.addWidget(self.layer_locked_checkbox)
        layers_layout.addWidget(self.layer_alpha_locked_checkbox)
        layers_layout.addWidget(self.layer_mask_enabled_checkbox)
        layers_layout.addWidget(self.layer_edit_mask_checkbox)
        mask_actions = QGridLayout()
        mask_actions.setHorizontalSpacing(8)
        mask_actions.setVerticalSpacing(8)
        self.layer_add_mask_button = QPushButton("Add Mask")
        self.layer_invert_mask_button = QPushButton("Invert Mask")
        self.layer_delete_mask_button = QPushButton("Delete Mask")
        mask_actions.addWidget(self.layer_add_mask_button, 0, 0)
        mask_actions.addWidget(self.layer_invert_mask_button, 0, 1)
        mask_actions.addWidget(self.layer_delete_mask_button, 1, 0, 1, 2)
        layers_layout.addLayout(mask_actions)
        layers_layout.addWidget(QLabel("Layer opacity"))
        layers_layout.addWidget(self.layer_opacity_slider)
        self.layers_section = CollapsibleSection("Layers", layers_body, expanded=False)
        right_layout.addWidget(self.layers_section)

        adjustments_body = QFrame()
        adjustments_body.setObjectName("EditorSectionBody")
        adjustments_layout = QVBoxLayout(adjustments_body)
        adjustments_layout.setContentsMargins(10, 10, 10, 10)
        adjustments_layout.setSpacing(8)
        self.adjustments_list = QListWidget()
        self.adjustments_list.setMinimumHeight(100)
        self.adjustments_list.setFrameShape(QFrame.NoFrame)
        adjustments_layout.addWidget(self.adjustments_list)
        adjustments_actions = QGridLayout()
        adjustments_actions.setHorizontalSpacing(8)
        adjustments_actions.setVerticalSpacing(8)
        self.adjustment_add_combo = QComboBox()
        self.adjustment_add_combo.addItem("Hue / Saturation", "hue_saturation")
        self.adjustment_add_combo.addItem("Brightness / Contrast", "brightness_contrast")
        self.adjustment_add_combo.addItem("Exposure", "exposure")
        self.adjustment_add_combo.addItem("Vibrance", "vibrance")
        self.adjustment_add_combo.addItem("Color Balance", "color_balance")
        self.adjustment_add_combo.addItem("Selective Color", "selective_color")
        self.adjustment_add_combo.addItem("Levels", "levels")
        self.adjustment_add_combo.addItem("Curves", "curves")
        self.adjustment_add_button = QPushButton("Add")
        self.adjustment_duplicate_button = QPushButton("Duplicate")
        self.adjustment_remove_button = QPushButton("Remove")
        self.adjustment_reset_button = QPushButton("Reset")
        self.adjustment_up_button = QPushButton("Up")
        self.adjustment_down_button = QPushButton("Down")
        self.adjustment_solo_button = QPushButton("Solo")
        for button in (
            self.adjustment_add_button,
            self.adjustment_duplicate_button,
            self.adjustment_remove_button,
            self.adjustment_reset_button,
            self.adjustment_up_button,
            self.adjustment_down_button,
            self.adjustment_solo_button,
        ):
            button.setObjectName("EditorPanelButton")
            button.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
            button.setMinimumWidth(0)
        adjustments_actions.addWidget(self.adjustment_add_combo, 0, 0)
        adjustments_actions.addWidget(self.adjustment_add_button, 0, 1)
        adjustments_actions.addWidget(self.adjustment_duplicate_button, 1, 0)
        adjustments_actions.addWidget(self.adjustment_solo_button, 1, 1)
        adjustments_actions.addWidget(self.adjustment_remove_button, 2, 0)
        adjustments_actions.addWidget(self.adjustment_reset_button, 2, 1)
        adjustments_actions.addWidget(self.adjustment_up_button, 3, 0)
        adjustments_actions.addWidget(self.adjustment_down_button, 3, 1)
        adjustments_layout.addLayout(adjustments_actions)
        self.adjustment_enabled_checkbox = QCheckBox("Enabled")
        adjustments_layout.addWidget(self.adjustment_enabled_checkbox)
        self.adjustment_opacity_slider = QSlider(Qt.Horizontal)
        self.adjustment_opacity_slider.setRange(0, 100)
        self.adjustment_opacity_slider.setValue(100)
        adjustments_layout.addWidget(QLabel("Adjustment opacity"))
        adjustments_layout.addWidget(self.adjustment_opacity_slider)
        self.adjustment_mode_label = QLabel("Target")
        self.adjustment_mode_combo = QComboBox()
        self.adjustment_mode_combo.addItem("Reds", "reds")
        self.adjustment_mode_combo.addItem("Greens", "greens")
        self.adjustment_mode_combo.addItem("Blues", "blues")
        self.adjustment_mode_combo.addItem("Cyans", "cyans")
        self.adjustment_mode_combo.addItem("Magentas", "magentas")
        self.adjustment_mode_combo.addItem("Yellows", "yellows")
        self.adjustment_mode_combo.addItem("Neutrals", "neutrals")
        self.adjustment_mode_combo.addItem("Whites", "whites")
        self.adjustment_mode_combo.addItem("Blacks", "blacks")
        adjustments_layout.addWidget(self.adjustment_mode_label)
        adjustments_layout.addWidget(self.adjustment_mode_combo)
        self.adjustment_param_a_label = QLabel("Param A")
        self.adjustment_param_a_slider = QSlider(Qt.Horizontal)
        self.adjustment_param_a_slider.setRange(-100, 100)
        self.adjustment_param_b_label = QLabel("Param B")
        self.adjustment_param_b_slider = QSlider(Qt.Horizontal)
        self.adjustment_param_b_slider.setRange(-100, 100)
        self.adjustment_param_c_label = QLabel("Param C")
        self.adjustment_param_c_slider = QSlider(Qt.Horizontal)
        self.adjustment_param_c_slider.setRange(-100, 100)
        adjustments_layout.addWidget(self.adjustment_param_a_label)
        adjustments_layout.addWidget(self.adjustment_param_a_slider)
        adjustments_layout.addWidget(self.adjustment_param_b_label)
        adjustments_layout.addWidget(self.adjustment_param_b_slider)
        adjustments_layout.addWidget(self.adjustment_param_c_label)
        adjustments_layout.addWidget(self.adjustment_param_c_slider)
        adjustment_mask_actions = QGridLayout()
        adjustment_mask_actions.setHorizontalSpacing(8)
        adjustment_mask_actions.setVerticalSpacing(8)
        self.adjustment_use_active_mask_button = QPushButton("Mask Active Layer")
        self.adjustment_clear_mask_button = QPushButton("Clear Mask")
        for button in (
            self.adjustment_use_active_mask_button,
            self.adjustment_clear_mask_button,
        ):
            button.setObjectName("EditorPanelButton")
            button.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
            button.setMinimumWidth(0)
        adjustment_mask_actions.addWidget(self.adjustment_use_active_mask_button, 0, 0)
        adjustment_mask_actions.addWidget(self.adjustment_clear_mask_button, 0, 1)
        adjustments_layout.addLayout(adjustment_mask_actions)
        self.adjustments_section = CollapsibleSection("Adjustments", adjustments_body, expanded=False)
        right_layout.addWidget(self.adjustments_section)

        history_body = QFrame()
        history_body.setObjectName("EditorSectionBody")
        history_layout = QVBoxLayout(history_body)
        history_layout.setContentsMargins(10, 10, 10, 10)
        self.history_list = QListWidget()
        self.history_list.setMinimumHeight(120)
        self.history_list.setFrameShape(QFrame.NoFrame)
        history_layout.addWidget(self.history_list)
        history_actions = QHBoxLayout()
        self.history_restore_button = QPushButton("Restore Selected")
        self.history_clear_button = QPushButton("Clear History")
        history_actions.addWidget(self.history_restore_button)
        history_actions.addWidget(self.history_clear_button)
        history_actions.addStretch(1)
        history_layout.addLayout(history_actions)
        self.history_section = CollapsibleSection("History", history_body, expanded=False)
        right_layout.addWidget(self.history_section)

        right_layout.addStretch(1)
        self.right_scroll = QScrollArea()
        self.right_scroll.setWidgetResizable(True)
        self.right_scroll.setFrameShape(QFrame.NoFrame)
        editor_inspector_min, _editor_inspector_pref, editor_inspector_max = responsive_sidebar_bounds(self, role="narrow")
        self.right_scroll.setMinimumWidth(editor_inspector_min)
        self.right_scroll.setMaximumWidth(editor_inspector_max)
        self.right_scroll.setWidget(self.right_panel)
        self.main_splitter.addWidget(self.right_scroll)
        self.main_splitter.setStretchFactor(0, 0)
        self.main_splitter.setStretchFactor(1, 8)
        self.main_splitter.setStretchFactor(2, 2)
        self.main_splitter.setSizes(
            build_responsive_splitter_sizes(2040, [12, 70, 18], [editor_tool_min, 520, editor_inspector_min])
        )
        self._task_completed_on_ui.connect(self._handle_async_task_completed)
        self._task_error_on_ui.connect(self._handle_async_task_error)
        self._task_finished_on_ui.connect(self._handle_async_task_finished)
        self._ui_constraint_ready_on_ui.connect(self._handle_ui_constraint_ready)
        self._ui_constraint_finished_on_ui.connect(self._cleanup_ui_constraint_refs)

        self._connect_signals()
        self._refresh_native_dds_format_options()
        self._rebuild_brush_preset_combo(preserve_key="custom")
        self._set_active_tool("paint")
        self._load_settings()
        self._settings_ready = True
        self._rebuild_shortcuts()
        self._refresh_ui()
        self._apply_font_sensitive_metrics(self.font())
        QTimer.singleShot(0, self._apply_responsive_splitter_defaults)
