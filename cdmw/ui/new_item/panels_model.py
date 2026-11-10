"""New Item Studio, panel 3: model, icon, and imported-model placement."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QEvent, QSettings, QSignalBlocker, QSize, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QPainter, QPen
from PySide6.QtWidgets import (
    QButtonGroup,
    QCheckBox,
    QComboBox,
    QDoubleSpinBox,
    QFormLayout,
    QFrame,
    QFileDialog,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QProgressBar,
    QPushButton,
    QRadioButton,
    QScrollArea,
    QSizePolicy,
    QSplitter,
    QTabWidget,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from cdmw.domain.new_item.spec import IconSource, MaterialRoute, ModelSource, SheathedModel
from cdmw.ui.mesh_editor.icons import mesh_editor_action_icon
from cdmw.ui.new_item.controller import NewItemStudioController
from cdmw.ui.new_item.item_preview import GIZMO_TOOLS, ItemPreviewFrame
from cdmw.ui.new_item.model_import import ModelPlacement
from cdmw.ui.new_item.panels_model_preview_mixin import (
    ModelPanelPreviewMixin,
)
from cdmw.ui.new_item.state import glow_choice
from cdmw.ui.new_item.ui_kit import BLOCK, EDIT, OK, WARN, NoteLabel, elided, note
from cdmw.ui.wrapping_layout import WrappingLayout

#: what a Blender looks like on each platform, for the dialog that points the studio at one
BLENDER_FILE_FILTER = "Blender (blender.exe blender);;All files (*)"
#: the folder Skeleton Edit JSON picks and rig GLB exports last used
RIG_DIR_SETTING = "ui/new_item_rig_dir"


def _spin(minimum: float, maximum: float, step: float, decimals: int, suffix: str = "") -> QDoubleSpinBox:
    spin = QDoubleSpinBox()
    spin.setRange(minimum, maximum)
    spin.setSingleStep(step)
    spin.setDecimals(decimals)
    if suffix:
        spin.setSuffix(suffix)
    spin.setKeyboardTracking(False)
    spin.setMinimumWidth(72)
    return spin


def _foldout(content: QWidget) -> QWidget:
    section = QWidget()
    layout = QVBoxLayout(section)
    layout.setContentsMargins(0, 0, 0, 0)
    layout.setSpacing(2)
    section.toggle = QToolButton()
    section.toggle.setCheckable(True)
    section.toggle.setArrowType(Qt.ArrowType.RightArrow)
    section.toggle.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
    section.contents = QWidget()
    content_layout = QVBoxLayout(section.contents)
    content_layout.setContentsMargins(0, 0, 0, 0)
    content_layout.addWidget(content)
    section.toggle.toggled.connect(section.contents.setVisible)
    section.toggle.toggled.connect(
        lambda opened: section.toggle.setArrowType(Qt.ArrowType.DownArrow if opened else Qt.ArrowType.RightArrow)
    )
    layout.addWidget(section.toggle, 0, Qt.AlignmentFlag.AlignLeft)
    layout.addWidget(section.contents)
    section.contents.hide()
    return section


class _InspectorTabs(QTabWidget):
    """Let the active form use its natural height inside the inspector scroll area."""

    def __init__(self) -> None:
        super().__init__()
        # Maximum can retain a collapsed page's cached height during expansion.
        # The inspector's trailing stretch already keeps these tabs compact.
        self.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Preferred)
        self.currentChanged.connect(lambda _index: self.updateGeometry())

    def sizeHint(self) -> QSize:
        size = super().sizeHint()
        if page := self.currentWidget():
            size.setHeight(page.sizeHint().height() + self.tabBar().sizeHint().height() + 6)
        return size

    def minimumSizeHint(self) -> QSize:
        size = super().minimumSizeHint()
        if page := self.currentWidget():
            size.setHeight(page.minimumSizeHint().height() + self.tabBar().sizeHint().height() + 6)
        return size


class _BusySpinner(QWidget):
    """Small timer-driven spinner whose paint cadence is also testable."""

    frame_advanced = Signal(int)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._frame = 0
        self._timer = QTimer(self)
        self._timer.setInterval(60)
        self._timer.timeout.connect(self._advance)
        self.setFixedSize(22, 22)

    def sizeHint(self) -> QSize:
        return QSize(22, 22)

    def set_running(self, running: bool) -> None:
        if running:
            if not self._timer.isActive():
                self._timer.start()
        else:
            self._timer.stop()
            self._frame = 0
            self.update()

    def _advance(self) -> None:
        self._frame = (self._frame + 1) % 12
        self.frame_advanced.emit(self._frame)
        self.update()

    def paintEvent(self, _event) -> None:  # noqa: N802 - Qt override
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        painter.translate(self.width() / 2.0, self.height() / 2.0)
        painter.rotate(float(self._frame * 30))
        base = QColor(self.palette().highlight().color())
        for index in range(12):
            colour = QColor(base)
            colour.setAlpha(45 + index * 17)
            painter.setPen(QPen(colour, 2.0, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
            painter.drawLine(0, -6, 0, -9)
            painter.rotate(30.0)
        painter.end()


class ModelPanel(ModelPanelPreviewMixin, QGroupBox):
    """Choose the model and icon beside the imported-model placement workspace."""

    #: a glow was pushed to the viewport at least once: only then does an all-unticked
    #: draft still need a restoring push
    _glow_preview_touched = False

    part_editor_open_requested = Signal()
    part_editor_apply_requested = Signal()

    def __init__(
        self,
        controller: NewItemStudioController,
        parent=None,
        *,
        native_preview_core_cache_root: Path | None = None,
    ) -> None:
        super().__init__("3. Model and placement", parent)
        self._controller = controller
        self._workspace_ready = False
        self._fitting_workspace = False
        self._placement_available = False
        self.setProperty("compactModelPanel", True)
        outer = QVBoxLayout(self)
        outer.setContentsMargins(8, 6, 8, 6)
        outer.setSpacing(4)
        self.setToolTip("Choose or import the model, place it, tune its appearance, and choose the inventory icon.")
        self.workspace_splitter = QSplitter(Qt.Orientation.Horizontal, self)
        self.workspace_splitter.setObjectName("new_item_model_workspace_splitter")
        self.workspace_splitter.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Expanding)
        self.workspace_splitter.setChildrenCollapsible(False)
        self.workspace_splitter.installEventFilter(self)
        # Components sit in their own column left of the viewport/inspector pair, which
        # alone turns vertical on a narrow window.
        self.model_outer_splitter = QSplitter(Qt.Orientation.Horizontal, self)
        self.model_outer_splitter.setObjectName("new_item_model_outer_splitter")
        self.model_outer_splitter.setChildrenCollapsible(False)
        outer.addWidget(self.model_outer_splitter, 1)

        self.model_icon_column = QWidget(self.workspace_splitter)
        self.model_icon_column.setObjectName("new_item_model_icon_column")
        self.model_icon_column.setMinimumWidth(320)
        model_icon_column_layout = QVBoxLayout(self.model_icon_column)
        model_icon_column_layout.setContentsMargins(0, 0, 0, 0)
        model_icon_column_layout.setSpacing(6)
        self.model_icon_scroll = QScrollArea(self.model_icon_column)
        self.model_icon_scroll.setObjectName("new_item_model_icon_scroll")
        self.model_icon_scroll.setWidgetResizable(True)
        self.model_icon_scroll.setFrameShape(QScrollArea.Shape.NoFrame)
        self.model_icon_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.model_icon_content = QWidget(self.model_icon_scroll)
        model_icon_content_layout = QVBoxLayout(self.model_icon_content)
        model_icon_content_layout.setContentsMargins(0, 0, 0, 0)
        model_icon_content_layout.setSpacing(2)
        self.model_icon_scroll.setWidget(self.model_icon_content)
        model_icon_column_layout.addWidget(self.model_icon_scroll, 1)

        self.preview_column = QWidget(self.workspace_splitter)
        self.preview_column.setMinimumWidth(440)
        preview_column_layout = QVBoxLayout(self.preview_column)
        preview_column_layout.setContentsMargins(0, 0, 0, 0)
        preview_column_layout.setSpacing(4)

        self.preview = ItemPreviewFrame(
            self,
            native_preview_core_cache_root=native_preview_core_cache_root,
        )
        self._syncing_numbers = False
        #: >0 while a component selection/inclusion change runs: the viewport is not rebuilt
        self._preview_hold = 0
        #: the viewport shows an older component state; Refresh preview brings it up to date
        self._preview_stale = False
        self._show_preview_timer = QTimer(self)
        self._show_preview_timer.setSingleShot(True)
        self._show_preview_timer.setInterval(0)
        self._show_preview_timer.timeout.connect(self.refresh_preview)
        self._appearance_preview_timer = QTimer(self)
        self._appearance_preview_timer.setSingleShot(True)
        self._appearance_preview_timer.setInterval(80)
        self._appearance_preview_timer.timeout.connect(self.refresh_preview)

        model, model_layout, import_row = self._build_model_source_controls()
        self.appearance_page = QWidget()
        appearance_layout = QVBoxLayout(self.appearance_page)
        appearance_layout.setContentsMargins(8, 8, 8, 8)
        appearance_layout.setSpacing(6)
        for widget in (self.plain_pbr, self.own_sheath):
            appearance_layout.addWidget(widget)
        self._build_model_appearance_controls(model, appearance_layout, import_row)
        self.blender_details.layout().insertWidget(0, self.blender_details.toggle)
        appearance_layout.addStretch(1)
        # Model section order: the file, then what prepares it (Mesh Editor, cloth,
        # weights), then the details to read when something needs attention.
        # Mesh Editor and cloth get a section of their own under Model.
        self.edit_group = QGroupBox("Mesh Editor and cloth")
        self.edit_group.setObjectName("new_item_edit_and_cloth")
        edit_layout = QVBoxLayout(self.edit_group)
        edit_layout.setContentsMargins(6, 4, 6, 4)
        edit_layout.setSpacing(4)
        for widget in (self.part_editor_holder, self.keep_physics, self.cloth_paint_note, self.cloth_guides_row):
            self.model_layout.removeWidget(widget)
            edit_layout.addWidget(widget)
        self.model_layout.removeWidget(self.busy_bar)
        self.model_layout.addWidget(self.busy_bar)

        self._build_placement_controls()

        self._build_preview_controls(controller)

        self._build_icon_controls()

        # The column follows the work: which component, its model (and any Mesh Editor
        # or cloth preparation), where it sits and how it looks, then what stays
        # visible underneath a worn item. Apply placement stays pinned below.
        from cdmw.ui.new_item.component_list import ComponentList
        # Components get their own column left of the viewport, so the inspector holds
        # only the selected component's settings.
        self.components_column = QWidget(self.model_outer_splitter)
        self.components_column.setObjectName("new_item_components_column")
        self.components_column.setMinimumWidth(190)
        self.components_column.setMaximumWidth(320)
        components_layout = QVBoxLayout(self.components_column)
        components_layout.setContentsMargins(0, 0, 0, 0)
        self.components = ComponentList(controller, self)
        self.components.compact()
        components_layout.addWidget(self.components)
        components_layout.addStretch(1)
        self.components.preview_out_of_date.connect(self.mark_preview_stale)
        model_icon_content_layout.addWidget(self.model_group)
        model_icon_content_layout.addWidget(self.edit_group)
        from cdmw.ui.new_item.dye_editor import DyeEditor
        self.dyes = DyeEditor(controller,self)
        self.inspector_tabs = _InspectorTabs()
        self.inspector_tabs.setObjectName("new_item_model_inspector_tabs")
        self.inspector_tabs.addTab(self.placement_group, "Placement")
        self.inspector_tabs.addTab(self.appearance_page, "Appearance")
        self.inspector_tabs.addTab(self.dyes, "Dyes")
        self.inspector_tabs.addTab(self.icon_group, "Icon")
        model_icon_content_layout.addWidget(self.inspector_tabs)
        self.body_details = _foldout(self.body_visibility_editor)
        self.body_details.setObjectName("new_item_body_underneath")
        self.body_details.toggle.setText("Body underneath")
        self.body_details.toggle.setToolTip(
            "What stays visible under this worn component: skin, hair and other clothing layers it would cut.")
        self.body_details.setVisible(controller.template_is_worn())
        model_icon_content_layout.addWidget(self.body_details)
        model_icon_content_layout.addStretch(1)
        preview_column_layout.addWidget(self.preview_group, 1)
        # View options and the fitting reference change only the picture: they sit
        # under it, not among the item's own settings.
        self.preview_options = QWidget(self.preview_column)
        self.preview_options.setObjectName("new_item_preview_options")
        preview_options_layout = QHBoxLayout(self.preview_options)
        preview_options_layout.setContentsMargins(0, 0, 0, 0)
        preview_options_layout.setSpacing(6)
        preview_options_layout.addWidget(self.preview_controls, 3)
        preview_options_layout.addWidget(self.reference_group, 2)
        preview_column_layout.addWidget(self.preview_options)
        self.reference_group.setVisible(controller.template_is_worn())
        self.material_warning = NoteLabel("", WARN)
        model_icon_column_layout.addWidget(self.material_warning)
        model_icon_column_layout.addWidget(self.operation_banner)
        model_icon_column_layout.addWidget(self.placement_actions)
        self.workspace_splitter.addWidget(self.preview_column)
        self.workspace_splitter.addWidget(self.model_icon_column)
        for index, factor in enumerate((1, 0)):
            self.workspace_splitter.setStretchFactor(index, factor)
        self.workspace_splitter.setSizes((720, 470))
        self.model_outer_splitter.addWidget(self.components_column)
        self.model_outer_splitter.addWidget(self.workspace_splitter)
        self.model_outer_splitter.setStretchFactor(0, 0)
        self.model_outer_splitter.setStretchFactor(1, 1)
        self.model_outer_splitter.setSizes((220, 1200))
        # The component list is the binding selector; it lives with the model, not the preview.
        self.variants = self.components
        self.preview_controls.layout().insertWidget(0, self.show_character)

        controller.model_changed.connect(self._show_model)
        controller.model_changed.connect(lambda _result: self.refresh_preview())
        controller.model_import_changed.connect(lambda _source: self._show_model(controller.model_result))
        controller.model_import_changed.connect(lambda _source: self.refresh_preview())
        # A model that arrived clears the note about an earlier failed import.
        controller.model_import_changed.connect(
            lambda source: self.import_problem.setVisible(False) if source is not None else None)
        controller.model_placement_changed.connect(self._placement_changed)
        controller.busy_changed.connect(self._busy_changed)
        controller.operation_progress.connect(self._operation_progress)
        controller.template_changed.connect(lambda _key: self._show_model(controller.model_result))
        controller.template_changed.connect(
            lambda key: self.show_character.setEnabled(key is not None)
        )
        controller.template_changed.connect(lambda _key: self.refresh_preview())
        # the parts a glow is chosen by are the template's, so the list follows it
        controller.template_changed.connect(lambda _key: self.refresh_glow_parts())
        # and the parts are the imported model's, so they follow it too -- from the moment
        # the file is read, not from Apply the placement. The result only exists after
        # Apply, and listening for it alone left the list empty until then.
        controller.model_changed.connect(lambda _result: self.refresh_glow_parts())
        controller.model_import_changed.connect(lambda _source: self.refresh_glow_parts())
        controller.model_import_failed.connect(self._import_failed)
        controller.model_apply_failed.connect(self._apply_failed)
        self.preview.ready.connect(lambda: self.capture_inline_button.setEnabled(
            not self._preview_stale
            and not (self.show_installed_reference.isChecked() and controller.installed_reference is not None)))
        self.preview.ready.connect(self._refresh_placement_enabled)
        self.preview.ready.connect(self._refresh_apply_status)
        # after every package (re)build: the session replays the last glow update as
        # stored, which is stale the moment the model changes, so a fresh full statement
        # for the mesh now showing lands right behind it
        self.preview.ready.connect(self._sync_glow_preview)
        self._icon_source_changed(True)
        self.plain_pbr.setEnabled(False)
        self.own_sheath.setEnabled(False)
        self._refresh_import_widgets()
        self._workspace_ready = True
        self._fit_model_workspace()

    def eventFilter(self, watched, event) -> bool:
        if watched is self.workspace_splitter and event.type() in (QEvent.Type.Resize, QEvent.Type.LayoutRequest):
            self._fit_model_workspace()
        return super().eventFilter(watched, event)

    def _set_placement_visible(self, visible: bool) -> None:
        newly_available = bool(visible) and not self._placement_available
        self._placement_available = bool(visible)
        self.placement_actions.setVisible(self._placement_available)
        self._fit_model_workspace()
        if newly_available and self.inspector_tabs.indexOf(self.placement_group) >= 0:
            self.inspector_tabs.setCurrentWidget(self.placement_group)

    def _fit_model_workspace(self) -> None:
        if not self._workspace_ready or self._fitting_workspace:
            return
        self._fitting_workspace = True
        try:
            scrollbar = self.model_icon_scroll.verticalScrollBar().sizeHint().width()
            for spin in (*self.offset_spins, *self.rotation_spins, *self.scale_spins):
                spin.setMinimumWidth(max(72, spin.minimumSizeHint().width()))
            inspector_content_width = max(
                self.inspector_tabs.tabBar().minimumSizeHint().width() + 6,
                *(page.minimumSizeHint().width() + 6
                  for page in (self.model_group, self.preview_controls, self.placement_group,
                               self.appearance_page, self.dyes, self.icon_group)),
            )
            # Wide enough that the Model section keeps its labels beside the values.
            inspector_width = max(470, inspector_content_width + scrollbar)
            preview_width = max(440, self.preview_group.minimumSizeHint().width())
            self.preview_column.setMinimumWidth(preview_width)
            available = self.workspace_splitter.width()
            handle = self.workspace_splitter.handleWidth()
            self.model_icon_column.setMinimumWidth(inspector_width)
            index = self.inspector_tabs.indexOf(self.placement_group)
            self.inspector_tabs.setTabVisible(index, self._placement_available)
            self.placement_actions.setVisible(self._placement_available)
            # Resizing changes only the splitter direction. Both the inspector and
            # the native preview retain their widget parents at every width.
            orientation = (Qt.Orientation.Vertical if available < inspector_width + preview_width + handle
                           else Qt.Orientation.Horizontal)
            sizes = self.workspace_splitter.sizes()
            squeezed = (orientation == Qt.Orientation.Horizontal and len(sizes) == 2
                        and sizes[1] < inspector_width and available >= inspector_width + preview_width + handle)
            if self.workspace_splitter.orientation() != orientation or squeezed:
                self.workspace_splitter.setOrientation(orientation)
                if orientation == Qt.Orientation.Vertical:
                    self.workspace_splitter.setSizes((max(360, self.height() - 250), 250))
                else:
                    self.workspace_splitter.setSizes((max(preview_width, available - inspector_width), inspector_width))
            self.inspector_tabs.updateGeometry()
        finally:
            self._fitting_workspace = False

    def _build_icon_controls(self) -> None:
        icon = QGroupBox("Icon")
        icon.setTitle("")
        icon.setAccessibleName("Icon")
        icon.setProperty("titlelessSection", True)
        icon_layout = QVBoxLayout(icon)
        icon_layout.setContentsMargins(8, 4, 8, 6)
        icon_layout.setSpacing(4)
        self.keep_icon = QRadioButton("Keep the template's icon")
        self.keep_icon.setChecked(True)
        self.keep_icon.toggled.connect(self._icon_source_changed)
        icon_layout.addWidget(self.keep_icon)
        self.generate_icon = QRadioButton("Use a custom icon")
        self.generate_icon.setToolTip("The icon is fitted and encoded against the template icon's DDS format, the way the Builder's Generate Icon does. Unproven in game until the first check.")
        icon_layout.addWidget(self.generate_icon)
        source_row = QHBoxLayout()
        self.icon_source = QLineEdit()
        self.icon_source.setPlaceholderText("Image file, or a folder the best-matching image is picked from")
        self.icon_source.textChanged.connect(self._store_icon_source)
        icon_layout.addWidget(self.icon_source)
        self.icon_file_button = QPushButton("Image...")
        self.icon_file_button.setToolTip("Take a picture you already have.")
        self.icon_file_button.clicked.connect(self._pick_icon_file)
        source_row.addWidget(self.icon_file_button)
        self.icon_folder_button = QPushButton("Folder...")
        self.icon_folder_button.setToolTip("Pick the best-matching image out of a folder.")
        self.icon_folder_button.clicked.connect(self._pick_icon_folder)
        source_row.addWidget(self.icon_folder_button)
        source_row.addStretch(1)
        icon_layout.addLayout(source_row)
        icon_layout.addWidget(self.icon_thumbnail, 0, Qt.AlignmentFlag.AlignLeft)
        icon_layout.addStretch(1)
        self.icon_group = icon


    def _build_preview_controls(self, controller) -> None:
        preview = QGroupBox()
        preview.setProperty("titlelessSection", True)
        preview.setAccessibleName("Preview")
        self.preview_group = preview
        preview.setMinimumWidth(440)
        preview_layout = QVBoxLayout(preview)
        preview_layout.setContentsMargins(0, 0, 0, 0)
        preview_layout.setSpacing(0)
        self.preview_layout = preview_layout
        self.preview_controls = QGroupBox("Preview")
        controls_layout = QVBoxLayout(self.preview_controls)
        controls_layout.setContentsMargins(8, 6, 8, 6)
        controls_layout.setSpacing(4)
        preview.setToolTip(
            "Your model over the template. Orbit, zoom, move it with the gizmo, and capture the icon from this view."
        )
        self.show_character = QCheckBox("Show the character")
        self.show_character.setObjectName("new_item_show_character")
        self.show_character.setToolTip(
            "The game's own character provides a size reference for the item and effect."
        )
        self.show_character.setEnabled(controller.draft.template_key is not None)
        self.show_character.toggled.connect(self._character_preview_changed)
        controls_layout.addWidget(self.view_toolbar)
        self.operation_banner = QFrame(self.model_icon_column)
        self.operation_banner.setObjectName("new_item_loading_card")
        self.operation_banner.setFrameShape(QFrame.Shape.StyledPanel)
        self.operation_banner.setSizePolicy(
            QSizePolicy.Policy.Expanding,
            QSizePolicy.Policy.Fixed,
        )
        self.operation_banner.setMinimumHeight(36)
        operation_layout = QVBoxLayout(self.operation_banner)
        operation_layout.setContentsMargins(8, 4, 8, 4)
        operation_layout.setSpacing(4)
        operation_row = QHBoxLayout()
        operation_row.setSpacing(6)
        self.operation_spinner = _BusySpinner(self.operation_banner)
        operation_row.addWidget(self.operation_spinner)
        self.operation_label = QLabel("")
        self.operation_label.setObjectName("new_item_intro")
        self.operation_label.setWordWrap(True)
        self.operation_label.setSizePolicy(QSizePolicy.Policy.Maximum, QSizePolicy.Policy.Preferred)
        self.operation_label.setMaximumWidth(260)
        operation_row.addWidget(self.operation_label)
        operation_row.addWidget(self.busy_bar)
        self.cancel_operation_button = QPushButton("Cancel")
        self.cancel_operation_button.clicked.connect(self._cancel_operation)
        operation_row.addWidget(self.cancel_operation_button)
        operation_row.addStretch(1)
        operation_layout.addLayout(operation_row)
        self.operation_banner.setVisible(False)
        self.preview.setMinimumHeight(300)
        self.preview.status_changed.connect(self._preview_status)
        self.preview.captured.connect(self._inline_capture_done)
        self.preview.placement_changed.connect(self._gizmo_moved)
        preview_layout.addWidget(self.preview, 1)
        self.capture_inline_button = QPushButton("Capture icon…")
        self.capture_inline_button.setToolTip(
            "Takes the view as it is (grid and gizmo hidden), then you drag the rectangle that becomes the 512 x 512 icon."
        )
        self.capture_inline_button.clicked.connect(self._capture_inline)
        self.capture_inline_button.setEnabled(False)
        self.refresh_preview_button = QPushButton("Refresh preview")
        self.refresh_preview_button.setObjectName("new_item_refresh_preview")
        self.refresh_preview_button.setToolTip("Show the current components. Selecting or ticking components does not reload "
                                               "the viewport by itself; the plan and export always use the current choices.")
        self.refresh_preview_button.clicked.connect(lambda: self.refresh_preview(force=True))
        self.preview_stale_label = QLabel("Preview out of date")
        self.preview_stale_label.setObjectName("new_item_preview_stale")
        self.preview_stale_label.setToolTip("Refresh preview before placing the model or capturing the icon.")
        self.preview_stale_label.setVisible(False)
        preview_actions = QHBoxLayout()
        preview_actions.setSpacing(6)
        preview_actions.addWidget(self.refresh_preview_button)
        preview_actions.addWidget(self.preview_stale_label)
        preview_actions.addStretch(1)
        preview_actions.addWidget(self.capture_inline_button)
        controls_layout.addLayout(preview_actions)
        self.preview_status = QLabel("")
        self.preview_status.setObjectName("new_item_intro")
        self.preview_status.setWordWrap(True)
        controls_layout.addWidget(self.preview_status)
        self.icon_thumbnail = QLabel("")
        self.icon_thumbnail.setFixedSize(72, 72)
        self.icon_thumbnail.setAlignment(Qt.AlignCenter)
        self.icon_thumbnail.setVisible(False)
        self._preview_mesh_token: object = None
        self._preview_busy = False

    def set_operation_status_host(self, host: QWidget) -> None:
        """Keep progress and cancellation together in the shell's status row."""
        banner = self.operation_banner
        if banner.parentWidget() is host:
            return
        hidden = banner.isHidden()
        self.model_icon_column.layout().removeWidget(banner)
        banner.setParent(host)
        banner.setFrameShape(QFrame.Shape.NoFrame)
        banner.setMinimumHeight(0)
        layout = banner.layout()
        layout.setContentsMargins(0, 0, 0, 0)
        self.busy_bar.setFixedWidth(92)
        self.operation_label.setWordWrap(False)
        self.operation_label.setSizePolicy(QSizePolicy.Policy.Maximum, QSizePolicy.Policy.Preferred)
        self.operation_label.setMaximumWidth(200)
        self.operation_label.setToolTip(self.operation_label.text())
        self.cancel_operation_button.setStyleSheet("padding: 2px 6px;")
        host.layout().addWidget(banner)
        banner.setVisible(not hidden)
        # The status bar presents this widget; the model panel retains its lifetime.
        self.destroyed.connect(banner.deleteLater)

    def _build_placement_controls(self) -> None:
        self.placement_group = QGroupBox("Placement")
        self.placement_group.setTitle("")
        self.placement_group.setProperty("titlelessSection", True)
        self.placement_group.setAccessibleName("Placement")
        placement_layout = QVBoxLayout(self.placement_group)
        placement_layout.setContentsMargins(8, 4, 8, 6)
        placement_layout.setSpacing(4)
        self.placement_group.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Maximum)
        self.placement_group.setToolTip(
            "The model starts fitted to the template. Move it with the gizmo or numbers, then apply the placement."
        )
        self.view_toolbar = QWidget()
        toolbar_layout = QVBoxLayout(self.view_toolbar)
        toolbar_layout.setContentsMargins(0, 0, 0, 0)
        toolbar_layout.setSpacing(4)
        view_row = QHBoxLayout()
        view_row.addWidget(QLabel("View:"))
        self.view_mode = QComboBox()
        self.view_mode.addItem("Overlay with template (not exported)", "overlay")
        self.view_mode.addItem("Side by side with template (not exported)", "side_by_side")
        self.view_mode.addItem("Selected component only", "replacement_only")
        self.view_mode.addItem("Template only (not exported)", "original_only")
        self.view_mode.setToolTip(
            "The template is drawn only for comparison and is never exported. Components hidden in export are not drawn "
            "in any view. Selected component only shows the model the selected component exports."
        )
        self.view_mode.currentIndexChanged.connect(
            lambda _i: self.preview.set_view_mode(str(self.view_mode.currentData() or "overlay"))
        )
        view_row.addWidget(self.view_mode, 1)
        self.grid_visible = QCheckBox("Grid")
        self.grid_visible.setChecked(True)
        self.grid_visible.toggled.connect(self.preview.set_grid_visible)
        view_row.addWidget(self.grid_visible)
        self.preview.set_lighting_preset("neutral_studio")
        self.dark_preview = QCheckBox("Dark mode")
        self.dark_preview.setToolTip("Dim the preview lighting and background to see emissive glow and its bloom. This changes only the viewport.")
        self.dark_preview.toggled.connect(self._preview_lighting_changed)
        view_row.addWidget(self.dark_preview)
        self.frame_view_button = QPushButton("Frame")
        self.frame_view_button.setToolTip("Bring the camera back onto the model where it sits now.")
        self.frame_view_button.clicked.connect(self.preview.fit_view)
        toolbar_layout.addLayout(view_row)
        self.gizmo_toolbar = QWidget(self.preview)
        gizmo_policy = QSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Preferred)
        gizmo_policy.setHeightForWidth(True)
        self.gizmo_toolbar.setSizePolicy(gizmo_policy)
        gizmo_row = WrappingLayout(self.gizmo_toolbar)
        gizmo_row.setSpacing(4)
        self.gizmo_button_group = QButtonGroup(self.gizmo_toolbar)
        self.gizmo_buttons = {
            "move": QPushButton("Move"),
            "rotate": QPushButton("Rotate"),
            "scale": QPushButton("Scale"),
        }
        for tool in GIZMO_TOOLS:
            button = self.gizmo_buttons[tool]
            button.setCheckable(True)
            button.setToolTip(button.text())
            button.setIcon(mesh_editor_action_icon(f"transform_{tool}", self.palette()))
            button.setIconSize(QSize(14, 14))
            button.setSizePolicy(QSizePolicy.Policy.Maximum, QSizePolicy.Policy.Fixed)
            self.gizmo_button_group.addButton(button)
            button.toggled.connect(
                lambda checked, t=tool: self.preview.set_gizmo_tool(t) if checked else None
            )
            gizmo_row.addWidget(button)
        self.gizmo_buttons["move"].setChecked(True)
        self.frame_view_button.setIcon(mesh_editor_action_icon("frame", self.palette()))
        self.frame_view_button.setIconSize(QSize(14, 14))
        self.frame_view_button.setSizePolicy(QSizePolicy.Policy.Maximum, QSizePolicy.Policy.Fixed)
        gizmo_row.addWidget(self.frame_view_button)
        self.preview.layout().removeWidget(self.preview.gizmo_visible)
        gizmo_row.addWidget(self.preview.gizmo_visible)
        self.preview.layout().insertWidget(0, self.gizmo_toolbar)
        numbers = QGridLayout()
        numbers.setHorizontalSpacing(6)
        numbers.setVerticalSpacing(4)
        self.offset_spins = tuple(_spin(-50.0, 50.0, 0.01, 3, " m") for _ in range(3))
        self.rotation_spins = tuple(_spin(-360.0, 360.0, 1.0, 1, "°") for _ in range(3))
        self.scale_spins = tuple(_spin(0.0001, 1000.0, 0.01, 4) for _ in range(3))
        groups = (
            ("Position (m)", self.offset_spins),
            ("Rotation (°)", self.rotation_spins),
            ("Scale", self.scale_spins),
        )
        row = 0
        for title, spins in groups:
            numbers.addWidget(QLabel(title), row, 0, 1, 3)
            row += 1
            if spins is self.scale_spins:
                for axis, direction in enumerate(("Width", "Height", "Depth")):
                    numbers.addWidget(QLabel(direction), row, axis)
                row += 1
            for axis, (spin, prefix) in enumerate(zip(spins, ("X: ", "Y: ", "Z: "))):
                spin.setPrefix(prefix)
                spin.setAccessibleName(f"{title} {'XYZ'[axis]}")
                if spins is self.scale_spins:
                    spin.setToolTip(
                        "Scale along this model axis before rotation. 1.0 is the fitted size; 2.0 doubles it."
                    )
                spin.valueChanged.connect(self._numbers_changed)
                numbers.addWidget(spin, row, axis)
                numbers.setColumnStretch(axis, 1)
            row += 1
        self.uniform_scale = QCheckBox("Uniform scale")
        self.uniform_scale.setToolTip(
            "Keep the current proportions when editing a scale value. Doubling X also doubles Y and Z."
        )
        numbers.addWidget(self.uniform_scale, row, 0, 1, 3)
        placement_layout.addLayout(numbers)
        quick_turn_content = QWidget()
        quick_turns = QGridLayout(quick_turn_content)
        quick_turns.setContentsMargins(0, 0, 0, 0)
        quick_turns.setHorizontalSpacing(3)
        quick_turns.setVerticalSpacing(4)
        self.quick_turn_buttons = {}
        for axis, name in enumerate("XYZ"):
            quick_turns.addWidget(QLabel(name), axis, 0)
            turns = ((-90, QPushButton("−90°")), (90, QPushButton("+90°")), (180, QPushButton("180°")))
            for column, (degrees, button) in enumerate(turns, start=1):
                button.setToolTip(f"Turn the model {degrees:+d}° around {name}, keeping its position and scale.")
                button.setAccessibleName(f"Turn {name} {degrees:+d}°")
                button.clicked.connect(lambda _checked=False, a=axis, d=degrees: self._quick_turn(a, d))
                quick_turns.addWidget(button, axis, column)
                self.quick_turn_buttons[axis, degrees] = button
        self.quick_turn_section = _foldout(quick_turn_content)
        self.quick_turn_section.toggle.setText("Quick turn")
        placement_layout.addWidget(self.quick_turn_section)
        action_row = QHBoxLayout()
        self.fit_button = QPushButton("Fit to template")
        self.fit_button.setToolTip(
            "Scale and align the geometry to the template. Imported weights stay attached to their vertices; this does not retarget the rig. The placement numbers return to zero."
        )
        self.fit_button.clicked.connect(self._fit_to_template)
        action_row.addWidget(self.fit_button)
        self.reset_rotation_button = QPushButton("Reset rotation")
        self.reset_rotation_button.setToolTip("Restore the fitted orientation, keeping the current position and scale.")
        self.reset_rotation_button.clicked.connect(self._reset_rotation)
        action_row.addWidget(self.reset_rotation_button)
        self.apply_button = QPushButton("Apply placement")
        self.apply_button.setProperty("newItemPrimary", True)
        self.apply_button.setToolTip(
            "Build the item's mesh from the model at this placement (the Builder's import over the template's mesh, a few seconds)."
        )
        self.apply_button.clicked.connect(self._controller.start_model_apply)
        placement_layout.addLayout(action_row)
        self.placement_actions = QWidget()
        placement_actions_layout = QVBoxLayout(self.placement_actions)
        placement_actions_layout.setContentsMargins(8, 4, 8, 6)
        placement_actions_layout.setSpacing(4)
        self.apply_status = NoteLabel("", None)
        placement_actions_layout.addWidget(self.apply_status)
        placement_actions_layout.addWidget(self.apply_button)
        self.placement_actions.hide()
        self.placement_group.setVisible(False)

    def _build_model_appearance_controls(self, model, model_layout, import_row) -> None:
        self.glow_box = QGroupBox("Glow")
        self.glow_box.setCheckable(True)
        self.glow_box.setChecked(False)
        self.glow_box.setToolTip(
            "Choose glowing parts, colour, strength and animation. Source glow maps are retained; "
            "parts without a glow map use a solid map. Off restores the source emission."
        )
        glow_layout = QVBoxLayout(self.glow_box)
        glow_layout.setContentsMargins(8, 6, 8, 6)
        glow_layout.setSpacing(4)
        self.glow_parts = QListWidget()
        self.glow_parts.setToolTip(
            "The item's material parts, as its model names them. Tick the ones that glow."
        )
        self.glow_parts.setMaximumHeight(110)
        self.glow_parts.itemChanged.connect(lambda _item: self._glow_changed())
        glow_layout.addWidget(self.glow_parts)
        glow_row = QHBoxLayout()
        self.glow_color_button = QPushButton("Colour")
        self.glow_color_button.setToolTip("The colour the chosen parts glow in.")
        self.glow_color_button.clicked.connect(self._pick_glow_color)
        glow_row.addWidget(self.glow_color_button)
        self.glow_strength_label = QLabel("Strength")
        glow_row.addWidget(self.glow_strength_label)
        from cdmw.ui.wheel_guard import enable_focused_wheel
        self.glow_intensity = enable_focused_wheel(QDoubleSpinBox())
        self.glow_intensity.setRange(0.1, 20.0)
        self.glow_intensity.setSingleStep(0.5)
        self.glow_intensity.setDecimals(1)
        self.glow_intensity.setValue(4.0)
        self.glow_intensity.setToolTip(
            "How strongly the selected parts glow. Shipped emissive equipment commonly uses 1 to 10; the format limit is 20."
        )
        self.glow_intensity.valueChanged.connect(lambda _value: self._glow_changed())
        glow_row.addWidget(self.glow_intensity)
        glow_row.addStretch(1)
        glow_layout.addLayout(glow_row)
        from cdmw.ui.new_item.glow_animation_editor import GlowAnimationEditor
        self.glow_animation = GlowAnimationEditor(self.glow_box)
        self.glow_animation.refresh(self._controller.draft.glow_animation, self._controller.draft.glow_rgb)
        self.glow_animation.changed.connect(self._glow_changed)
        glow_layout.addWidget(self.glow_animation)
        self._glow_detail_widgets = (
            self.glow_parts,
            self.glow_color_button,
            self.glow_strength_label,
            self.glow_intensity,
            self.glow_animation,
        )
        self.glow_box.toggled.connect(self._set_glow_details_visible)
        self.glow_box.toggled.connect(lambda _on: self._glow_changed())
        self._set_glow_details_visible(False)
        model_layout.addWidget(self.glow_box)
        self._set_glow_swatch()
        from cdmw.ui.new_item.translucency_editor import TranslucencyEditor

        self.translucency_editor = TranslucencyEditor(self)
        self.translucency_editor.changed.connect(self._translucency_changed)
        self.translucency_editor.paint_requested.connect(lambda part: self._paint_transparency(part, "translucency"))
        self.translucency_editor.restore_mask_requested.connect(lambda part: self._restore_transparency_mask(part, "translucency"))
        self.translucency_editor.refresh(self._controller.material_parts(), self._controller.draft.translucency,
                                         authored=self._controller.material_authored_translucency())
        model_layout.addWidget(self.translucency_editor)
        from cdmw.ui.new_item.surface_editor import SurfaceEditor
        self.surface_editor = SurfaceEditor(self)
        self.surface_editor.changed.connect(self._surface_changed)
        model_layout.addWidget(self.surface_editor)
        from cdmw.ui.new_item.body_visibility_editor import BodyVisibilityEditor
        self.body_visibility_editor = BodyVisibilityEditor(self)
        self._refresh_body_visibility()
        self.body_visibility_editor.changed.connect(self._body_visibility_changed)
        self.body_visibility_editor.layers_requested.connect(self._find_visibility_layers)
        self.body_visibility_editor.apply_to_worn_requested.connect(self._body_visibility_to_worn)
        from cdmw.ui.new_item.shader_controls_editor import ShaderControlsEditor
        self.shader_controls_editor = ShaderControlsEditor(self)
        self.shader_controls_editor.refresh(self._controller.material_parts(), self._controller.draft.shader_controls,
                                            self._controller.material_shader_options())
        self.shader_controls_editor.changed.connect(self._shader_controls_changed)
        self.shader_controls_editor.paint_requested.connect(lambda part: self._paint_transparency(part, "blending"))
        self.shader_controls_editor.restore_mask_requested.connect(lambda part: self._restore_transparency_mask(part, "blending"))
        self.shader_controls_editor.restore_surface_mask_requested.connect(
            lambda part: self._restore_transparency_mask(part, "blending", target="surface"))
        self._controller.transparency_mask_changed.connect(self._transparency_mask_changed)
        model_layout.addWidget(self.shader_controls_editor)
        self.flip_texture_v = QCheckBox("Flip texture V")
        self.flip_texture_v.setToolTip(
            "glTF, GLB, OBJ and DAE put V's origin at the bottom and the game samples it from the top, so their textures need the "
            "flip or they draw mirrored along the model. Ticked for those formats; untick it if your source is already in the "
            "game's convention (a mesh taken from the archives)."
        )
        self.flip_texture_v.setVisible(False)
        self.flip_texture_v.toggled.connect(self._flip_texture_v_changed)
        model_layout.addWidget(self.flip_texture_v)
        self._import_widgets = (
            import_row,
            self.import_summary,
            self.import_details,
            self.part_editor_holder,
            self.blender_details,
            self.plain_pbr,
            self.own_sheath,
        )
        self.model_group = model

    def _add_model_row(self, label: str, field: QWidget, tooltip: str = "") -> None:
        """One label/value row of the Model section; the label follows its field's visibility."""

        caption = QLabel(label)
        caption.setObjectName("new_item_model_row_label")
        caption.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop)
        if tooltip:
            caption.setToolTip(tooltip)
        self.model_grid.addRow(caption, field)
        self._model_rows.append((caption, field))

    def _sync_model_row_labels(self) -> None:
        for caption, field in getattr(self, "_model_rows", ()):
            caption.setVisible(not field.isHidden())

    def _build_model_source_controls(self):
        model = QGroupBox("Model")
        model.setAccessibleName("Model")
        model.setObjectName("new_item_selected_component")
        model_layout = QVBoxLayout(model)
        model_layout.setContentsMargins(6, 4, 6, 4)
        model_layout.setSpacing(3)
        self.model_layout = model_layout
        self.editing_label = QLabel("")
        self.editing_label.setObjectName("new_item_editing_label")
        self.editing_label.setTextFormat(Qt.TextFormat.PlainText)
        self.editing_label.setWordWrap(True)
        editing_font = self.editing_label.font()
        editing_font.setBold(True)
        self.editing_label.setFont(editing_font)
        # The section title names the component; the label stays for its text.
        self.editing_label.setVisible(False)
        model_layout.addWidget(self.editing_label)
        source_label = QLabel("Exported model:")
        self.keep_model = QRadioButton("Template model")
        self.keep_model.setToolTip("Export the game's own model for the selected component.")
        self.keep_model.setChecked(True)
        self.keep_model.toggled.connect(self._model_source_changed)
        source_choices = QHBoxLayout()
        source_choices.addWidget(source_label)
        source_choices.addWidget(self.keep_model)
        self.import_model = QRadioButton("Imported model")
        self.import_model.setToolTip(
            "Supports glTF, GLB, OBJ, DAE, FBX through Blender, and zip files containing one model."
        )
        source_choices.addWidget(self.import_model)
        # The radio pair stays the model-source state; the visible actions below drive it.
        self.source_radio_row = QWidget()
        self.source_radio_row.setLayout(source_choices)
        self.source_radio_row.setVisible(False)
        model_layout.addWidget(self.source_radio_row)
        row = QHBoxLayout()
        row.setContentsMargins(0,0,0,0)
        picker_row = QHBoxLayout()
        picker_row.setContentsMargins(0, 0, 0, 0)
        self.import_button = QPushButton("Import model…")
        self.import_button.setToolTip(
            "Replace only the selected component with a glTF, GLB, OBJ, DAE or FBX (through Blender) model, or a zip with "
            "one inside. Other ticked components keep their own models."
        )
        self.import_button.clicked.connect(self._pick_model_file)
        picker_row.addWidget(self.import_button)
        self.use_template_button = QPushButton("Use template model")
        self.use_template_button.setToolTip("Export the game's own model for the selected component. An import is kept for switching back.")
        self.use_template_button.clicked.connect(lambda: self.keep_model.setChecked(True))
        picker_row.addWidget(self.use_template_button)
        self.use_import_button = QPushButton("Use imported model")
        self.use_import_button.setToolTip("Export the model already imported for the selected component.")
        self.use_import_button.clicked.connect(lambda: self.import_model.setChecked(True))
        picker_row.addWidget(self.use_import_button)
        picker_row.addStretch(1)
        # Label/value rows: what the model is, where it comes from, how it is weighted.
        self.model_grid = QFormLayout()
        self.model_grid.setContentsMargins(0, 2, 0, 2)
        self.model_grid.setHorizontalSpacing(10)
        self.model_grid.setVerticalSpacing(6)
        self._model_rows = []
        self.source_field = QWidget()
        source_layout = QVBoxLayout(self.source_field)
        source_layout.setContentsMargins(0, 0, 0, 0)
        source_layout.setSpacing(4)
        source_layout.addLayout(picker_row)
        # A failed import says why right here, not only in the window's status line,
        # and offers the usual way out when the model's bones do not fit the template.
        self.import_problem = QWidget()
        self.import_problem.setObjectName("new_item_import_problem")
        problem_layout = QVBoxLayout(self.import_problem)
        problem_layout.setContentsMargins(0, 2, 0, 2)
        problem_layout.setSpacing(4)
        self.import_problem_note = NoteLabel("", WARN)
        problem_layout.addWidget(self.import_problem_note)
        self.retry_transfer_button = QPushButton("Import again with Transfer from template")
        self.retry_transfer_button.setObjectName("new_item_retry_transfer")
        self.retry_transfer_button.setToolTip(
            "Read the same file again, replacing its weights with the template's. Use Export rig GLB… instead "
            "to keep your own weights: weight the model to that rig in Blender and import it again.")
        self.retry_transfer_button.clicked.connect(self._retry_import_with_transfer)
        problem_layout.addWidget(self.retry_transfer_button, 0, Qt.AlignmentFlag.AlignLeft)
        self.import_problem.setVisible(False)
        self._last_import_path = None
        from cdmw.ui.new_item.installed_character_models import InstalledCharacterModels
        self.installed_models = InstalledCharacterModels(self._controller, self)
        self.installed_models.loaded.connect(self._installed_model_loaded)
        reference_group = QGroupBox("Fitting reference — preview only")
        reference_layout = QVBoxLayout(reference_group)
        reference_layout.setContentsMargins(6, 4, 6, 4)
        reference_layout.setSpacing(3)
        reference_group.setToolTip("Compare installed refits with your own model. The reference is never exported.")
        reference_row = QHBoxLayout()
        self.installed_model_button = QPushButton("Browse installed models…")
        self.installed_model_button.clicked.connect(self.installed_models.open)
        reference_row.addWidget(self.installed_model_button)
        reference_row.addStretch(1)
        reference_layout.addLayout(reference_row)
        reference_row = QHBoxLayout()
        self.show_installed_reference = QCheckBox("Show fitting reference")
        self.show_installed_reference.setEnabled(False)
        self.show_installed_reference.toggled.connect(self._installed_reference_changed)
        reference_row.addWidget(self.show_installed_reference)
        self.clear_reference_button = QPushButton("Clear reference")
        self.clear_reference_button.setEnabled(False)
        self.clear_reference_button.clicked.connect(self._controller.clear_installed_reference)
        reference_row.addWidget(self.clear_reference_button)
        reference_layout.addLayout(reference_row)
        self.reference_name = QLabel()
        self.reference_name.setWordWrap(True)
        reference_layout.addWidget(self.reference_name)
        self.reference_group = reference_group
        self._controller.installed_reference_changed.connect(self._installed_reference_changed)
        self.clear_button = QPushButton("Discard")
        self.clear_button.setToolTip("Discard the imported model.")
        self.clear_button.clicked.connect(self._controller.discard_model)
        row.addWidget(self.clear_button)
        self.skinning_button = QPushButton("Skin weights…")
        self.skinning_button.setToolTip("Keep, reduce or deliberately transfer weights for each imported part. Review losses in Import details.")
        self.skinning_button.clicked.connect(self._edit_skinning)
        self.skinning_button.setEnabled(False)
        row.addWidget(self.skinning_button)
        row.addStretch(1)
        import_row = QWidget()
        import_row.setLayout(row)
        source_layout.addWidget(import_row)
        self.weights_rig_group = QWidget()
        self.weights_rig_group.setObjectName("new_item_weights_rig")
        weights_rig_layout = QVBoxLayout(self.weights_rig_group)
        weights_rig_layout.setContentsMargins(12, 0, 0, 2)
        weights_rig_layout.setSpacing(4)
        self.import_skin_policy = QComboBox()
        self.import_skin_policy.addItem("Keep imported weights", "preserve")
        self.import_skin_policy.addItem("Transfer from template", "transfer")
        self.import_skin_policy.addItem("Reduce to six influences", "reduce")
        self.import_skin_policy.setToolTip("Used when importing a rigged model. Keeping weights refuses missing bones or excess influences. "
                                         "Transfer deliberately replaces authored weights; reduction reports removed weights before Apply placement.")
        self.rig_field = QWidget()
        rig_row = QHBoxLayout(self.rig_field)
        rig_row.setContentsMargins(0, 0, 0, 0)
        rig_label = QLabel("Rig")
        rig_label.setToolTip(
            "Weight a model to new bones, for capes, tails or long hair:\n"
            "1. Choose Add bones… and add child bones or a chain to this variant's skeleton.\n"
            "2. Choose Export rig GLB… and weight your model to the new bones in Blender.\n"
            "3. Import the model here. The item ships the added bones.")
        self._rig_tooltip = rig_label.toolTip()
        self.rig_summary = QLabel("Template skeleton")
        self.rig_summary.setTextFormat(Qt.TextFormat.PlainText)
        self.rig_summary.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        rig_row.addWidget(self.rig_summary, 1)
        self.add_bones_button = QPushButton("Add bones…")
        self.add_bones_button.setToolTip(
            "Add child bones or chains to this variant's skeleton, or open a Skeleton Edit JSON draft. Imported weights "
            "can then use those bones; the item ships the edited skeleton, and Send to DMM combines bones that other "
            "items add. Added bones follow their parent rigidly and are not proven in game. Male and female variants "
            "use different skeletons; add bones to each.")
        self.add_bones_button.clicked.connect(self._controller.start_add_bones)
        rig_row.addWidget(self.add_bones_button)
        self.clear_skeleton_edit_button = QPushButton("Clear")
        self.clear_skeleton_edit_button.setToolTip("Forget the skeleton edits and weight the model against the template's own skeleton.")
        self.clear_skeleton_edit_button.clicked.connect(self._controller.clear_skeleton_edit)
        self.clear_skeleton_edit_button.setVisible(False)
        rig_row.addWidget(self.clear_skeleton_edit_button)
        self.export_rig_button = QPushButton("Export rig GLB…")
        self.export_rig_button.setToolTip(
            "Write the template mesh skinned to its skeleton, with any added bones, as GLB to weight a model against in Blender.")
        self.export_rig_button.clicked.connect(self._pick_rig_export_folder)
        rig_row.addWidget(self.export_rig_button)
        # Kept for callers that look the old foldout up; it no longer holds the controls.
        self.weights_rig_details = self.weights_rig_group
        self.weights_rig_group.setVisible(False)
        self._controller.skeleton_edit_changed.connect(self._show_skeleton_edit)
        # Open the dialog after the reading task has finished, not inside its callback.
        self._controller.rig_source_ready.connect(
            lambda source: QTimer.singleShot(0, lambda: self._open_bone_editor(source)))
        self.import_summary = QLabel("No imported model.")
        self.import_summary.setWordWrap(True)
        self.import_summary.setTextFormat(Qt.TextFormat.PlainText)
        self.import_summary.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        source_choices.addStretch(1)
        self.model_status = NoteLabel("No imported model.", None)
        self.import_details = _foldout(self.model_status)
        self.import_details.toggle.setText("Import details")
        self.part_editor_holder = QWidget()
        part_editor_layout = QVBoxLayout(self.part_editor_holder)
        part_editor_layout.setContentsMargins(0, 0, 0, 0)
        part_editor_buttons = QVBoxLayout()
        part_editor_buttons.setSpacing(4)
        self.open_part_editor_button = QPushButton("Open in Mesh Editor")
        self.open_part_editor_button.setToolTip(
            "Open this imported model in Mesh Editor to split it into parts or paint cloth. Finish and return to "
            "Create New Item brings the edit back here and applies the placement again if it was applied."
        )
        self.open_part_editor_button.clicked.connect(self.part_editor_open_requested.emit)
        part_editor_buttons.addWidget(self.open_part_editor_button, 0, Qt.AlignmentFlag.AlignLeft)
        self.use_part_editor_button = QPushButton("Use Mesh Editor changes")
        self.use_part_editor_button.setToolTip(
            "Use the edit accepted in Mesh Editor, if it did not come back by itself. It rebuilds this preview and "
            "becomes the model Apply placement builds."
        )
        self.use_part_editor_button.clicked.connect(self.part_editor_apply_requested.emit)
        part_editor_buttons.addWidget(self.use_part_editor_button, 0, Qt.AlignmentFlag.AlignLeft)
        part_editor_layout.addLayout(part_editor_buttons)
        self.part_editor_status = NoteLabel("", None)
        part_editor_layout.addWidget(self.part_editor_status)
        model_layout.addWidget(self.part_editor_holder)
        self._part_editor_active = False
        self.set_part_editor_state(False)
        self.blender_holder = QWidget()
        blender_row = QVBoxLayout(self.blender_holder)
        blender_row.setContentsMargins(0, 0, 0, 0)
        self.blender_label = QLabel("")
        self.blender_label.setWordWrap(True)
        blender_row.addWidget(self.blender_label)
        blender_buttons = QHBoxLayout()
        self.blender_button = QPushButton("Choose blender.exe...")
        self.blender_button.setToolTip(
            "FBX is the one format the studio does not read itself: an FBX arrives rotated, mirrored or a hundred times "
            "too large unless its transform stack, layer mappings and units are read exactly, and Blender is what reads "
            "them correctly. Point the studio at a Blender and an FBX is converted to glTF on import; leave it unset and "
            "an FBX is refused before anything is read."
        )
        self.blender_button.clicked.connect(self._choose_blender)
        blender_buttons.addWidget(self.blender_button)
        self.blender_forget = QPushButton("Forget it")
        self.blender_forget.clicked.connect(lambda: self._set_blender(""))
        blender_buttons.addWidget(self.blender_forget)
        blender_buttons.addStretch(1)
        blender_row.addLayout(blender_buttons)
        self.blender_details = _foldout(self.blender_holder)
        self.blender_details.toggle.setText("FBX setup")
        for label, field, tip in (
            ("File", self.import_summary, ""),
            ("Source", self.source_field, ""),
            ("Weights", self.import_skin_policy, "How the next import of a rigged model is weighted."),
            ("Rig", self.rig_field, self._rig_tooltip),
            ("Notes", self.import_details, ""),
            ("FBX", self.blender_details, ""),
        ):
            self._add_model_row(label, field, tip)
        model_layout.insertLayout(model_layout.indexOf(self.source_radio_row) + 1, self.model_grid)
        self._refresh_blender_label()
        model_layout.addWidget(self.import_problem)
        self.busy_bar = QProgressBar()
        self.busy_bar.setObjectName("new_item_model_progress")
        self.busy_bar.setRange(0, 0)
        self.busy_bar.setTextVisible(True)
        self.busy_bar.setFormat("%p%")
        self.busy_bar.setFixedWidth(92)
        self.busy_bar.setMinimumHeight(20)
        self.busy_bar.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        self.busy_bar.setVisible(False)
        model_layout.addWidget(self.busy_bar)
        self.plain_pbr = QCheckBox("Plain PBR materials")
        self.plain_pbr.setChecked(True)
        self.plain_pbr.setToolTip(
            "SkinnedMeshStandard: base colour, normal and roughness/metal, the material route used by shipped texture-driven equipment, "
            "with a real _sp map from the source. Off: the Builder's layered material goes in as it came, and the game draws "
            "its own detail layers over the imported textures."
        )
        self.plain_pbr.toggled.connect(self._material_route_changed)
        model_layout.addWidget(self.plain_pbr)
        self.own_sheath = QCheckBox("Use import when sheathed")
        self.own_sheath.setChecked(True)
        self.own_sheath.setToolTip(
            "Shown only when the template exposes an alternate _IN visual part. On: that borrowed record is cloned under the "
            "new item's stem and pointed at the imported mesh. Off: the template's alternate visual remains borrowed."
        )
        self.own_sheath.toggled.connect(self._sheath_changed)
        model_layout.addWidget(self.own_sheath)
        self.keep_physics = QCheckBox("Template cloth / physics")
        self.keep_physics.setToolTip(
            "A template's cloth and jiggle bindings are tied to that template's own vertices. On a model of your own "
            "those indices land wherever they land, which is how a handle ends up swinging like a cape. Off, those bindings "
            "are removed and the item keeps only the template's collision shape. On for a template whose cloth you want and "
            "whose shape yours follows closely."
        )
        self.keep_physics.toggled.connect(self._keep_physics_changed)
        model_layout.addWidget(self.keep_physics)
        self.cloth_paint_note = NoteLabel("", None)
        self.cloth_paint_note.setObjectName("new_item_cloth_paint_note")
        self.cloth_paint_note.setVisible(False)
        model_layout.addWidget(self.cloth_paint_note)
        # How painted cloth moves: with the template's guides, or with guides of its own.
        self.cloth_guides_row = QWidget()
        self.cloth_guides_row.setObjectName("new_item_cloth_guides_row")
        guides_form = QFormLayout(self.cloth_guides_row)
        guides_form.setContentsMargins(0, 0, 0, 0)
        self.cloth_guides_mode = QComboBox()
        self.cloth_guides_mode.setObjectName("new_item_cloth_guides_mode")
        self.cloth_guides_mode.addItem("Follows the template's cloth", "template")
        self.cloth_guides_mode.addItem("Gets cloth guides of its own (experimental)", "own")
        self.cloth_guides_mode.setToolTip(
            "Template's cloth: painted areas follow the template's own cloth guides, which suits a garment shaped like "
            "the template's. Own guides: the template's guides are removed and new ones are built from the painted area, "
            "held where the paint meets unpainted areas and at painted pins."
        )
        self.cloth_guides_mode.currentIndexChanged.connect(self._cloth_guides_mode_changed)
        guides_form.addRow("Painted cloth", self.cloth_guides_mode)
        self.cloth_profile = QComboBox()
        self.cloth_profile.setObjectName("new_item_cloth_profile")
        self.cloth_profile.setToolTip(
            "The cloth profile sets how the new cloth moves (stiffness, weight, damping). The template's profile is kept "
            "unless you choose another one from the game's profile catalogue."
        )
        self.cloth_profile.currentIndexChanged.connect(self._cloth_profile_changed)
        self._cloth_profile_snapshot = None
        guides_form.addRow("Cloth profile", self.cloth_profile)
        self.cloth_guides_row.setVisible(False)
        model_layout.addWidget(self.cloth_guides_row)
        return model, model_layout, import_row

    def mount_preview(self) -> None:
        """Move the shared resident viewport back into Model & Placement."""

        parent = self.preview.parentWidget()
        if parent is not self.preview_group:
            if parent is not None and parent.layout() is not None:
                parent.layout().removeWidget(self.preview)
            self.preview_layout.insertWidget(0, self.preview, 1)
        self.set_preview_editable(True)

    def set_preview_editable(self, editable: bool) -> None:
        """Model & Placement moves the item with the gizmo; the steps that borrow the
        viewport only show it, so their copy has no handles. Frame stays for both."""

        editable = bool(editable)
        for button in self.gizmo_buttons.values():
            button.setVisible(editable)
        self.preview.gizmo_visible.setVisible(editable)
        if editable == self.preview.placement_editable:
            return
        self.preview.set_placement_editable(editable)
        # Only Model & Placement shows the template's own model as a placement scene.
        self.refresh_preview()

    def _model_source_changed(self, keep: bool) -> None:
        draft = self._controller.draft
        draft.model_source = ModelSource.TEMPLATE if keep else ModelSource.IMPORTED
        for lane in ("model_skinning", "model_hide"):
            self._controller.cancel_operation(lane)
        self.plain_pbr.setEnabled(not keep)
        self.own_sheath.setEnabled(not keep)
        self._refresh_import_widgets()
        self._controller.invalidate_plan()
        self._refresh_apply_status()
        self._refresh_source_actions()

    def _refresh_import_widgets(self) -> None:
        keep = self.keep_model.isChecked()
        for widget in self._import_widgets:
            widget.setVisible(not keep)
        has_sheathed_variant = self._controller.template_has_sheathed_variant()
        self.own_sheath.setVisible(not keep and has_sheathed_variant)
        self.own_sheath.setEnabled(not keep and has_sheathed_variant)
        if self._controller.snapshot and self._controller.snapshot.sources and self._controller.snapshot.sources.static_layout:
            self.own_sheath.setVisible(False)
            self.own_sheath.setEnabled(False)
        self.clear_button.setVisible(self._controller.model_import is not None)
        has_source = self._controller.model_import is not None
        has_import = has_source or self._controller.model_result is not None
        from cdmw.services.new_item_cloth_paint import mesh_has_cloth_paint

        mesh = getattr(getattr(self._controller.model_import, "scene", None), "mesh", None)
        painted = mesh is not None and mesh_has_cloth_paint(mesh)
        # Painted cloth can build guides of its own, so a template without physics offers it too.
        self.keep_physics.setVisible(has_import and (self._controller.template_has_model_physics() or painted))
        self._refresh_cloth_paint_note()
        self._sync_model_row_labels()
        if keep:
            self.flip_texture_v.setVisible(False)

    def _refresh_cloth_paint_note(self) -> None:
        """Say beside Template cloth / physics whether the model carries cloth paint."""

        from cdmw.services.new_item_cloth_paint import mesh_has_cloth_paint

        source = self._controller.model_import
        mesh = getattr(getattr(source, "scene", None), "mesh", None)
        painted = mesh is not None and mesh_has_cloth_paint(mesh)
        shown = (self.keep_physics.isVisibleTo(self) and not self.keep_model.isChecked() and mesh is not None
                 and (painted or self.keep_physics.isChecked()))
        self.cloth_paint_note.setVisible(shown)
        own = bool(getattr(source, "own_cloth_guides", False))
        self.cloth_guides_row.setVisible(shown and painted and self.keep_physics.isChecked())
        if self.cloth_guides_row.isVisibleTo(self):
            self._sync_cloth_guide_controls(source)
        if not shown:
            return
        if painted and self.keep_physics.isChecked() and own:
            self.cloth_paint_note.set_note(
                "Cloth paint: painted areas get cloth guides of their own, held where they meet unpainted areas "
                "and at painted pins.", OK)
        elif painted and self.keep_physics.isChecked():
            self.cloth_paint_note.set_note("Cloth paint: painted areas move with the template's cloth.", OK)
        elif painted:
            self.cloth_paint_note.set_note("This model has cloth paint. Turn on Template cloth / physics to use it.", WARN)
        else:
            self.cloth_paint_note.set_note(
                "No cloth paint. To choose what swings, open the model in Mesh Editor and use the Cloth page.", None)

    def set_part_editor_state(self, active: bool, message: str = "") -> None:
        """Show the two ends of the cross-tab part-edit handoff."""

        self._part_editor_active = bool(active)
        #: the note as last set here, so its author can tell whether it is still showing
        self.part_editor_message = str(message or "")
        self.open_part_editor_button.setText("Return to Mesh Editor" if active else "Open in Mesh Editor")
        self.use_part_editor_button.setVisible(active)
        self.part_editor_status.setVisible(bool(message))
        if message:
            self.part_editor_status.set_note(str(message), EDIT if active else WARN)

    def _refresh_blender_label(self) -> None:
        """Say which Blender the studio will use for an FBX, or that there is none."""

        from cdmw.ui.new_item.blender_setting import blender_for_fbx

        chosen = blender_for_fbx()
        if chosen:
            self.blender_label.setText(f"FBX support: on, converted with {chosen}")
        else:
            self.blender_label.setText(
                "For FBX support, Blender is required: the studio converts an FBX with it, and will not import one "
                "until it is pointed at a Blender. glTF, GLB, OBJ and DAE need none of this."
            )
        self.blender_forget.setVisible(bool(chosen))

    def _choose_blender(self) -> None:
        from cdmw.ui.new_item.blender_setting import suggested_blender

        suggestion = suggested_blender()
        start = str(suggestion) if suggestion is not None else ""
        path, _selected = QFileDialog.getOpenFileName(
            self, "Choose the Blender that reads FBX", start, BLENDER_FILE_FILTER,
        )
        if path:
            self._set_blender(path)

    def _set_blender(self, path: str) -> None:
        """Remember `path` (or forget it), and say what it turned out to be."""

        from cdmw.services.fbx_blender_conversion import describe_blender
        from cdmw.ui.new_item.blender_setting import remember_blender

        stored = remember_blender(path)
        self._refresh_blender_label()
        if not path:
            self._controller.status_message.emit("The studio will not convert FBX until it is pointed at a Blender again.", False)
            return
        if not stored:
            self._controller.status_message.emit(f"{Path(path).name} is not a Blender the studio can run.", True)
            return
        version = describe_blender(stored)
        self._controller.status_message.emit(
            f"FBX will be converted with {version or Path(stored).name}.", False
        )

    def _material_route_changed(self, plain: bool) -> None:
        self._controller.draft.material_route = MaterialRoute.PLAIN_PBR if plain else MaterialRoute.BUILDER
        self._controller.invalidate_plan()
        self.shader_controls_editor.refresh(self._controller.material_parts(), self._controller.draft.shader_controls,
                                            self._controller.material_shader_options())
        self._sync_glow_preview()

    def refresh_glow_parts(self) -> None:
        """Fill the part list from the chosen template, keeping what was already ticked."""

        chosen = set(self._controller.draft.glow_parts)
        self.glow_animation.refresh(self._controller.draft.glow_animation, self._controller.draft.glow_rgb)
        self.glow_intensity.blockSignals(True)
        self.glow_intensity.setValue(self._controller.draft.glow_intensity)
        self.glow_intensity.blockSignals(False)
        self._set_glow_swatch()
        parts = self._controller.material_parts()
        self.translucency_editor.refresh(parts, self._controller.draft.translucency,
                                         authored=self._controller.material_authored_translucency())
        source = self._controller.model_import
        mesh = getattr(getattr(source, "scene", None), "mesh", None)
        self.surface_editor.refresh(parts, self._controller.draft.surface_settings,
            enabled=source is not None, mesh=mesh, glow=glow_choice(self._controller.draft))
        self._refresh_body_visibility()
        self.shader_controls_editor.refresh(parts, self._controller.draft.shader_controls,
                                            self._controller.material_shader_options())
        self.glow_parts.blockSignals(True)
        self.glow_parts.clear()
        for name, label in parts:
            item = QListWidgetItem(label)
            # the label is the reader's own material; the wrapper name is what the file
            # keys it by, and what the plan has to be given
            item.setData(Qt.ItemDataRole.UserRole, name)
            item.setToolTip(name)
            item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            item.setCheckState(Qt.CheckState.Checked if name in chosen else Qt.CheckState.Unchecked)
            self.glow_parts.addItem(item)
        self.glow_parts.blockSignals(False)
        self.glow_box.setEnabled(bool(parts))
        self.glow_box.blockSignals(True)
        self.glow_box.setChecked(bool(chosen) and bool(parts))
        self.glow_box.blockSignals(False)
        self._set_glow_details_visible(self.glow_box.isChecked())
        if not parts:
            self.glow_box.setChecked(False)
            self.glow_box.setToolTip("Choose a template or import a model to edit its material parts.")
        self._update_material_overlap_warning()

    def _update_material_overlap_warning(self) -> None:
        draft = self._controller.draft
        translucent = {name.casefold() for name in draft.translucency.parts} if draft.translucency else set()
        overlap = tuple(name for name in draft.glow_parts if name.casefold() in translucent)
        message = ""
        tone = WARN
        if overlap:
            labels = {
                str(self.glow_parts.item(row).data(Qt.ItemDataRole.UserRole)).casefold(): self.glow_parts.item(row).text()
                for row in range(self.glow_parts.count())
            }
            parts = ", ".join(labels.get(name.casefold(), name) for name in overlap)
            if draft.glow_animation.active or draft.glow_rgb is not None:
                tone = BLOCK
                message = (
                    f"Warning: Animated or RGB Glow cannot share a part with Translucency: {parts}. "
                    "This combination cannot be exported. Disable Glow animation and RGB, "
                    "or deselect these parts in Glow or Translucency."
                )
            else:
                message = (
                    f"Warning: Glow and Translucency overlap on: {parts}. "
                    "The game does not draw glow on translucent parts, so these parts will not glow in game. "
                    "Animated and RGB glow cannot be used on the same part."
                )
        self.material_warning.set_note(message, tone)

    def _ticked_glow_parts(self) -> tuple:
        return tuple(
            str(self.glow_parts.item(row).data(Qt.ItemDataRole.UserRole) or self.glow_parts.item(row).text())
            for row in range(self.glow_parts.count())
            if self.glow_parts.item(row).checkState() == Qt.CheckState.Checked
        )

    def _set_glow_details_visible(self, visible: bool) -> None:
        """Keep the inactive Glow choice to one compact row."""

        for widget in self._glow_detail_widgets:
            widget.setVisible(bool(visible))

    def _glow_changed(self) -> None:
        draft = self._controller.draft
        draft.glow_parts = self._ticked_glow_parts() if self.glow_box.isChecked() else ()
        draft.glow_intensity = float(self.glow_intensity.value())
        draft.glow_animation = self.glow_animation.value()
        draft.glow_rgb = self.glow_animation.rgb_value()
        self._controller.invalidate_plan()
        self._sync_glow_preview()

    def _preview_lighting_changed(self, dark: bool) -> None:
        self.preview.set_lighting_preset("dark" if dark else "neutral_studio")

    def _translucency_changed(self, choice) -> None:
        previous = self._controller.draft.translucency
        self._controller.draft.translucency = choice
        if choice is not None:
            self.plain_pbr.setChecked(True)
        self._controller.invalidate_plan()
        self._sync_glow_preview()
        if (previous.masks if previous else ()) != (choice.masks if choice else ()):
            self._appearance_preview_timer.start()

    def _paint_transparency(self, part, mode):
        if mode == "blending" and dict(self._controller.draft.shader_controls)[part].shader == "SkinnedMeshWing":
            mode = "cutout"
        self._controller.start_transparency_paint(part, mode, self._show_transparency_painter)

    def _show_transparency_painter(self, session, prepared):
        from cdmw.ui.new_item.transparency_painter import TransparencyPaintDialog
        dialog = TransparencyPaintDialog(prepared, lambda mask: self._controller.apply_transparency_paint(session, mask),
            part=session[-2], glass=session[-1] == "translucency", parent=self,
            run_file_task=lambda task, done, failed: self._controller.start_transparency_mask_io(session, task, done, failed),
            cancel_file_task=lambda: self._controller.cancel_operation("transparency_mask"))
        dialog.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
        # The controller owns cancellable file I/O; closing discards draft paint
        # and cancels that lane without destroying a running worker.
        self._transparency_painter = dialog
        dialog.open()

    def _restore_transparency_mask(self, part, mode, *, target="colour"):
        controller = self._controller
        if mode == "blending" and dict(controller.draft.shader_controls)[part].shader == "SkinnedMeshWing":
            mode = "cutout"
        session = (controller.snapshot, controller.current_variant_identity(), controller.model_import,
                   controller.model_result, controller._draft_revision, part, mode)
        controller.apply_transparency_paint(session, None, target=target)

    def _transparency_mask_changed(self):
        self.refresh_glow_parts()
        self._appearance_preview_timer.start()

    def _surface_changed(self, choices) -> None:
        self._controller.draft.surface_settings = choices
        if choices:
            self.plain_pbr.setChecked(True)
        self._controller.invalidate_plan()
        self._sync_glow_preview()

    def _body_visibility_changed(self, choice) -> None:
        self._controller.draft.body_visibility = choice
        self._controller.invalidate_plan()

    def _body_visibility_to_worn(self, choice) -> None:
        from cdmw.services.active_ui_translation import translate_active_ui_text
        count = self._controller.set_worn_body_visibility(choice)
        self._refresh_body_visibility()
        self.components.note.setText(
            translate_active_ui_text("Body underneath updated for {count} worn component(s).").format(count=count))

    def _refresh_body_visibility(self, *, looking=False) -> None:
        from cdmw.ui.new_item.component_list import component_name
        row = next((value for value in self._controller.component_rows() if value.selected), None)
        # Only a worn item cuts the body or other clothing; a weapon has nothing underneath.
        details = getattr(self, "body_details", None)  # absent while the panel is still being built
        if details is not None:
            worn = self._controller.template_is_worn()
            details.setVisible(worn)
            # Installed character models are worn gear: a reference only helps a worn item.
            self.reference_group.setVisible(worn or self._controller.installed_reference is not None)
        self.body_visibility_editor.refresh(
            self._controller.draft.body_visibility,
            enabled=self._controller.current_variant_identity() is not None,
            layers=self._controller.visibility_layers(), looking=looking,
            component=component_name(row) if row is not None else "",
            # An unread prefab keeps the choice available; the plan then reports what it could change.
            applicable=row is None or row.cuts_body or not row.component_name,
            hidden=row is not None and not row.included,
        )
        from cdmw.services.active_ui_translation import translate_active_ui_text
        group = getattr(self, "model_group", None)  # absent while the panel is still being built
        if group is not None:
            group.setTitle(translate_active_ui_text("Model for {name}").format(name=component_name(row))
                           if row is not None else translate_active_ui_text("Model"))
        if row is None:
            self.editing_label.setText("")
        elif row.included:
            self.editing_label.setText(translate_active_ui_text("Model for {name}").format(name=component_name(row)))
        else:
            self.editing_label.setText(translate_active_ui_text("Model for {name} (left out of the export)").format(
                name=component_name(row)))
        self._refresh_source_actions()

    def _refresh_source_actions(self) -> None:
        controller = self._controller
        has_import = controller.model_import is not None or (
            controller.model_result is not None and controller.model_import is None
            and controller.draft.model_source is ModelSource.IMPORTED)
        keep = self.keep_model.isChecked()
        self.use_template_button.setVisible(not keep)
        self.use_import_button.setVisible(keep and controller.model_import is not None)
        self.import_button.setText("Replace import…" if has_import and not keep else "Import model…")

    def _find_visibility_layers(self) -> None:
        from shiboken6 import isValid

        def done(identity):
            if isValid(self.body_visibility_editor) and identity == self._controller.current_variant_identity():
                self._refresh_body_visibility()

        def failed(message):
            if not isValid(self.body_visibility_editor):
                return
            self._refresh_body_visibility()
            self.body_visibility_editor.layers_status.setText(f"Could not read the layers: {message}")
            self.body_visibility_editor.layers_status.setVisible(True)

        # Show the wait first: a synchronous controller finishes inside the call.
        self._refresh_body_visibility(looking=True)
        def cancelled():
            if isValid(self.body_visibility_editor):
                self._refresh_body_visibility()

        if not self._controller.start_visibility_layer_lookup(done, failed, cancelled):
            self._refresh_body_visibility()

    def _shader_controls_changed(self, choices) -> None:
        previous = self._controller.draft.shader_controls
        self._controller.draft.shader_controls = choices
        self._controller.invalidate_plan()
        def texture_state(items):
            return tuple((n, c.shader, c.transparency_mask, c.surface_response_mask, c.cutout_mask,
                          c.coverage_mapping, c.colour_coverage) for n, c in items)
        if texture_state(previous) != texture_state(choices):
            self._appearance_preview_timer.start()
        else:
            self._sync_glow_preview()

    def _sync_glow_preview(self) -> None:
        """Replay the draft's Glow and translucency choices together.

        Template choices rebuild from cached native materials. Imports use the live
        parameter channel. Its groups cover the model's submeshes, so un-ticking a
        part restores the import's own emissive without remembering what was sent.
        Experimental glass requires a selected part, as in export. An untouched
        import sends no material overrides.
        """

        self._update_material_overlap_warning()
        preview = self.preview
        source = self._controller.model_import
        if source is None:
            if self._controller.draft.template_key is not None:
                self._appearance_preview_timer.start()
            return
        sender = getattr(preview.host, "apply_material_parameter_groups", None)
        if source is None or not callable(sender) or not preview.showing_placement:
            return
        glow = glow_choice(self._controller.draft)
        translucency = self._controller.draft.translucency
        from cdmw.services.new_item_translucency import translucency_preview_parameter_groups

        source_mesh = getattr(getattr(source, "scene", None), "mesh", None)
        surface = self._controller.draft.surface_settings
        self.surface_editor.update_glow(source_mesh, glow)
        if glow is None and translucency is None and not surface and not self._controller.draft.shader_controls and not self._glow_preview_touched:
            return
        # Material names and factors do not depend on baked vertex positions.
        mesh = getattr(source, "preview_mesh", None) or source_mesh
        if mesh is None:
            return
        from cdmw.services.new_item_materials import glow_preview_parameter_groups
        groups = glow_preview_parameter_groups(mesh, glow) + translucency_preview_parameter_groups(
            mesh, translucency,
        )
        from cdmw.services.new_item_surface import surface_preview_groups
        groups += surface_preview_groups(mesh, surface, translucency=translucency)
        from cdmw.services.shader_controls_preview import shader_preview_groups
        groups += shader_preview_groups(mesh, self._controller.draft.shader_controls,
                                        plain_pbr=self._controller.draft.material_route is MaterialRoute.PLAIN_PBR)
        if groups and sender(groups):
            self._glow_preview_touched = self._glow_preview_touched or glow is not None or translucency is not None or bool(surface) or bool(self._controller.draft.shader_controls)

    def _pick_glow_color(self) -> None:
        from PySide6.QtGui import QColor
        from PySide6.QtWidgets import QColorDialog

        current = self._controller.draft.glow_color
        start = QColor.fromRgbF(*(max(0.0, min(1.0, float(channel))) for channel in current))
        chosen = QColorDialog.getColor(start, self, "The colour the parts glow in")
        if not chosen.isValid():
            return
        self._controller.draft.glow_color = (chosen.redF(), chosen.greenF(), chosen.blueF())
        self._set_glow_swatch()
        self._controller.invalidate_plan()
        self._sync_glow_preview()

    def _set_glow_swatch(self) -> None:
        red, green, blue = (int(round(max(0.0, min(1.0, float(c))) * 255)) for c in self._controller.draft.glow_color)
        self.glow_color_button.setText(f"Colour: #{red:02x}{green:02x}{blue:02x}")
        self.glow_color_button.setStyleSheet(
            f"background-color: rgb({red},{green},{blue}); color: {'black' if (red + green + blue) > 380 else 'white'};"
        )

    def _keep_physics_changed(self, keep: bool) -> None:
        self._controller.draft.keep_template_physics = bool(keep)
        self._controller.invalidate_plan()
        self._refresh_cloth_paint_note()

    def _sync_cloth_guide_controls(self, source) -> None:
        """Show the source's own-guides choice; list the catalogue's profiles once per snapshot."""

        snapshot = self._controller.snapshot
        if snapshot is not self._cloth_profile_snapshot:
            from cdmw.services.new_item_cloth_guides import CATALOGUE_PATH, cloth_profile_names

            names: tuple[str, ...] = ()
            try:
                # One small, cached archive file.
                if snapshot is not None and snapshot.has_entry(CATALOGUE_PATH):
                    names = cloth_profile_names(snapshot.payload(CATALOGUE_PATH))
            except Exception:  # noqa: BLE001 - an unreadable catalogue offers the template's profile only
                names = ()
            with QSignalBlocker(self.cloth_profile):
                self.cloth_profile.clear()
                self.cloth_profile.addItem("The template's profile", "")
                for name in names:
                    self.cloth_profile.addItem(name, name)
            self._cloth_profile_snapshot = snapshot
        own = bool(getattr(source, "own_cloth_guides", False))
        profile = str(getattr(source, "cloth_profile", "") or "")
        with QSignalBlocker(self.cloth_guides_mode):
            self.cloth_guides_mode.setCurrentIndex(1 if own else 0)
        with QSignalBlocker(self.cloth_profile):
            index = self.cloth_profile.findData(profile)
            if index < 0:
                self.cloth_profile.addItem(profile, profile)
                index = self.cloth_profile.count() - 1
            self.cloth_profile.setCurrentIndex(index)
        self.cloth_profile.setEnabled(own)

    def _cloth_guides_mode_changed(self, _index: int) -> None:
        source = self._controller.model_import
        own = self.cloth_guides_mode.currentData() == "own"
        if source is None or bool(getattr(source, "own_cloth_guides", False)) == own:
            return
        source.own_cloth_guides = own
        self._drop_built_model()
        self._refresh_cloth_paint_note()

    def _cloth_profile_changed(self, _index: int) -> None:
        source = self._controller.model_import
        profile = str(self.cloth_profile.currentData() or "")
        if source is None or str(getattr(source, "cloth_profile", "") or "") == profile:
            return
        source.cloth_profile = profile
        self._drop_built_model()

    def _drop_built_model(self) -> None:
        # The build differs, so a result from before this change is no longer the item's.
        if self._controller.model_result is not None:
            self._controller.set_imported_model(None, None)
        self._controller.invalidate_plan()
        self._refresh_apply_status()

    def _flip_texture_v_changed(self, flip: bool) -> None:
        source = self._controller.model_import
        if source is None or bool(source.flip_texture_v) == bool(flip):
            return
        source.flip_texture_v = bool(flip)
        # the build differs, so a result from before this switch is no longer the item's
        if self._controller.model_result is not None:
            self._controller.set_imported_model(None, None)
        self._controller.invalidate_plan()
        self._refresh_apply_status()

    def show_draft(self) -> None:
        """Show the draft's sheath and icon choices; the rest follows the model signals."""

        draft = self._controller.draft
        sheath, icon, icon_path = draft.sheathed_model, draft.icon, draft.icon_source_path
        self.own_sheath.setChecked(sheath is SheathedModel.OWN_MODEL)
        (self.keep_icon if icon is IconSource.TEMPLATE else self.generate_icon).setChecked(True)
        self._icon_source_changed(icon is IconSource.TEMPLATE)
        self.icon_source.setText(icon_path)

    def _sheath_changed(self, own: bool) -> None:
        self._controller.draft.sheathed_model = SheathedModel.OWN_MODEL if own else SheathedModel.TEMPLATE
        self._controller.invalidate_plan()

    def _rig_folder(self) -> str:
        settings = QSettings("CrimsonDesertModWorkbench", "CrimsonDesertModWorkbench")
        folder = str(settings.value(RIG_DIR_SETTING, "") or "")
        return folder if folder and Path(folder).is_dir() else str(Path.home())

    def _remember_rig_folder(self, folder: Path) -> None:
        QSettings("CrimsonDesertModWorkbench", "CrimsonDesertModWorkbench").setValue(RIG_DIR_SETTING, str(folder))

    def _open_bone_editor(self, source) -> None:
        from PySide6.QtWidgets import QDialog
        from cdmw.ui.archive_browser.pab_bone_editor_dialog import PabBoneEditorDialog
        data, pab_path = source
        current = next((edit for edit in self._controller.skeleton_edits if edit.path == pab_path), None)
        dialog = PabBoneEditorDialog(
            data, pab_path, self, initial_edits=current.add_bones if current is not None else (),
            accept_text=self.tr("Use These Bones"),
            accept_tooltip=self.tr("Weight imported models to these bones. The item ships them in this skeleton."),
            # Default names start with the item's name, so two items' chains do not share names.
            name_stem=self._controller.draft.internal_name,
            draft_directory=Path(self._rig_folder()))
        self._bone_editor = dialog
        try:
            if dialog.exec() == QDialog.DialogCode.Accepted:
                self._controller.set_skeleton_edit(pab_path, dialog.edits())
        finally:
            self._bone_editor = None
            dialog.deleteLater()

    def _pick_rig_export_folder(self) -> None:
        folder = QFileDialog.getExistingDirectory(self, "Export the template rig as GLB", self._rig_folder())
        if folder:
            self._remember_rig_folder(Path(folder))
            self._controller.start_rig_export(Path(folder))

    def _show_skeleton_edit(self, edits) -> None:
        edits = tuple(edits or ())
        if not edits:
            self.rig_summary.setText("Template skeleton")
            self.rig_summary.setToolTip("")
        else:
            self.rig_summary.setText("; ".join(
                f"{edit.path.rsplit('/', 1)[-1]} + {len(edit.bone_names)} added bone(s)" for edit in edits))
            self.rig_summary.setToolTip("\n".join(
                f"{edit.path}: {', '.join(edit.bone_names)}" for edit in edits))
        self.clear_skeleton_edit_button.setVisible(bool(edits))

    def _edit_skinning(self):
        from cdmw.ui.new_item.skinning_dialog import SkinningDialog
        source = self._controller.model_import
        if source is not None and source.skinning_target:
            self._skinning_dialog = SkinningDialog(source, self._controller.start_model_skinning, self)
            self._skinning_dialog.open()

    def _show_model(self, result: object) -> None:
        self._apply_error = ""
        source = self._controller.model_import
        # Only a model with its own bone weights has weights to choose; hide it otherwise.
        self.skinning_button.setVisible(bool(source is not None and source.skinning_target))
        self.skinning_button.setEnabled(bool(source is not None and source.skinning_target
            and source.mesh_generation == source.skinning_generation and not self._controller.busy))
        keep = self._controller.draft.model_source is ModelSource.TEMPLATE
        # Retained imports are available for switching back; their presence does not
        # override the selected source or mutate the variant while projecting its state.
        with QSignalBlocker(self.keep_model), QSignalBlocker(self.import_model):
            self.keep_model.setChecked(keep)
            self.import_model.setChecked(not keep)
        self.plain_pbr.setEnabled(not keep)
        self.own_sheath.setEnabled(not keep)
        self._set_placement_visible(source is not None or self._controller.draft.template_key is not None)
        self.fit_button.setText("Fit to template" if source is not None else "Reset placement")
        self.flip_texture_v.setVisible(source is not None)
        self.clear_button.setVisible(source is not None)
        self.open_part_editor_button.setEnabled(source is not None and not self._controller.busy)
        self.use_part_editor_button.setEnabled(source is not None and not self._controller.busy)
        if source is not None and self.flip_texture_v.isChecked() != bool(source.flip_texture_v):
            self.flip_texture_v.blockSignals(True)
            self.flip_texture_v.setChecked(bool(source.flip_texture_v))
            self.flip_texture_v.blockSignals(False)
        if result is None and source is None:
            self.model_status.set_note("No imported model.", None)
            self.import_summary.setText("No imported model.")
            self.import_summary.setToolTip("")
            self.plain_pbr.setEnabled(False)
            self.own_sheath.setEnabled(False)
            self._refresh_import_widgets()
            self._refresh_apply_status()
            return
        self._refresh_import_widgets()
        lines = []
        if source is not None:
            mesh = getattr(source.scene, "mesh", None)
            vertices = int(getattr(mesh, "total_vertices", 0) or 0)
            parts = len(tuple(getattr(mesh, "submeshes", ()) or ()))
            textures = f"{source.texture_count} texture(s) of its own" if source.texture_count else "no textures of its own found beside it"
            lines.append(note(f"{source.label}: {vertices:,} vertices, {parts} part(s), {textures}", OK))
            self.import_summary.setText(f"{elided(source.label, 42)}\n{vertices:,} vertices · {parts} parts · {source.texture_count} textures")
            self.import_summary.setToolTip(source.label)
            from cdmw.ui.new_item.import_details import import_detail_lines
            lines.extend(import_detail_lines(source))
        if result is not None:
            entry = self._controller.model_entry
            head = f"Placed over {entry.basename}" if entry is not None else "Placed"
            size = len(getattr(result, "rebuilt_data", getattr(result, "pac_data", b"")) or b"")
            extras = len(tuple(getattr(result, "supplemental_file_specs", ()) or ()))
            if source is None:
                self.import_summary.setText(f"{head}\n{size:,} bytes · {extras} side files")
                self.import_summary.setToolTip(head)
            lines.append(note(f"{head}: the rebuilt mesh is {size:,} bytes, {extras} side file(s)", OK))
            from cdmw.ui.new_item.import_details import build_note_lines
            lines.extend(build_note_lines(getattr(result, "notes", ())))
            self.apply_status.set_note("Applied: the plan will write this mesh.", OK)
        elif source is not None:
            self.apply_status.set_note("Placement not applied yet. Apply placement builds the mesh the item exports.", WARN)
        self.model_status.set_lines(lines)
        self._sync_placement_numbers(self._controller.model_placement)
        self._refresh_apply_status()

__all__ = ["ModelPanel"]
