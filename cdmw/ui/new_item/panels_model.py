"""New Item Studio, panel 3: model, icon, and imported-model placement."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QSettings, QSize, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QPainter, QPen
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDoubleSpinBox,
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
    QVBoxLayout,
    QWidget,
)

from cdmw.domain.new_item.spec import IconSource, MaterialRoute, ModelSource, SheathedModel
from cdmw.ui.new_item.controller import NewItemStudioController
from cdmw.ui.new_item.item_preview import GIZMO_TOOLS, ItemPreviewFrame
from cdmw.ui.new_item.model_import import ModelPlacement
from cdmw.ui.new_item.state import glow_choice
from cdmw.ui.new_item.ui_kit import EDIT, OK, WARN, NoteLabel, note

IMPORT_FILE_FILTER = (
    "Model files (*.gltf *.glb *.obj *.dae *.fbx *.zip);;glTF / GLB (*.gltf *.glb);;Wavefront OBJ (*.obj);;"
    "Collada DAE (*.dae);;FBX, converted with Blender (*.fbx);;Zip with a model inside (*.zip);;All files (*)"
)
#: what a Blender looks like on each platform, for the dialog that points the studio at one
BLENDER_FILE_FILTER = "Blender (blender.exe blender);;All files (*)"
IMPORT_DIR_SETTING = "ui/new_item_import_dir"


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


class ModelPanel(QGroupBox):
    """Choose the model and icon beside the imported-model placement workspace."""

    #: a glow was pushed to the viewport at least once: only then does an all-unticked
    #: draft still need a restoring push
    _glow_preview_touched = False

    part_editor_open_requested = Signal()
    part_editor_apply_requested = Signal()

    def __init__(self, controller: NewItemStudioController, parent=None) -> None:
        super().__init__("3. Model and placement", parent)
        self._controller = controller
        outer = QVBoxLayout(self)
        outer.setContentsMargins(8, 6, 8, 6)
        outer.setSpacing(6)
        self.setToolTip("Choose or import the model, place it, tune its appearance, and choose the inventory icon.")
        self.workspace_splitter = QSplitter(Qt.Orientation.Horizontal, self)
        self.workspace_splitter.setObjectName("new_item_model_workspace_splitter")
        self.workspace_splitter.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Expanding)
        outer.addWidget(self.workspace_splitter, 1)

        self.model_icon_column = QWidget(self.workspace_splitter)
        self.model_icon_column.setObjectName("new_item_model_icon_column")
        self.model_icon_column.setMinimumWidth(620)
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
        model_icon_content_layout.setSpacing(6)
        self.model_icon_scroll.setWidget(self.model_icon_content)
        model_icon_column_layout.addWidget(self.model_icon_scroll, 1)

        self.placement_column = QWidget(self.workspace_splitter)
        self.placement_column.setObjectName("new_item_placement_column")
        self.placement_column.setMinimumWidth(520)
        placement_column_layout = QVBoxLayout(self.placement_column)
        placement_column_layout.setContentsMargins(0, 0, 0, 0)
        placement_column_layout.setSpacing(6)

        self.preview = ItemPreviewFrame(self)
        self._syncing_numbers = False
        self._show_preview_timer = QTimer(self)
        self._show_preview_timer.setSingleShot(True)
        self._show_preview_timer.setInterval(0)
        self._show_preview_timer.timeout.connect(self.refresh_preview)

        model = QGroupBox("Model")
        model.setTitle("")
        model.setAccessibleName("Model")
        model.setProperty("titlelessSection", True)
        model_layout = QVBoxLayout(model)
        model_layout.setContentsMargins(8, 4, 8, 6)
        model_layout.setSpacing(4)
        self.keep_model = QRadioButton("Keep the template's model (no new model files)")
        self.keep_model.setChecked(True)
        self.keep_model.toggled.connect(self._model_source_changed)
        model_layout.addWidget(self.keep_model)
        self.import_model = QRadioButton("Use an imported model")
        self.import_model.setToolTip("Supports glTF, GLB, OBJ, DAE, FBX through Blender, and zip files containing one model.")
        model_layout.addWidget(self.import_model)
        row = QHBoxLayout()
        self.import_button = QPushButton("Import a model file...")
        self.import_button.setToolTip(
            "Pick a glTF, GLB, OBJ or DAE file, or a zip with one inside, from anywhere on disk. It is read the way the Model "
            "Library reads it (its own textures too) and shown over the template below, where you place it. An FBX is read too "
            "once the studio has been pointed at a Blender, which converts it first."
        )
        self.import_button.clicked.connect(self._pick_model_file)
        row.addWidget(self.import_button)
        self.clear_button = QPushButton("Discard imported model")
        self.clear_button.clicked.connect(self._controller.discard_model)
        row.addWidget(self.clear_button)
        row.addStretch(1)
        import_row = QWidget()
        import_row.setLayout(row)
        model_layout.addWidget(import_row)
        self.model_status = NoteLabel("No imported model.", None)
        model_layout.addWidget(self.model_status)
        self.part_editor_holder = QWidget()
        part_editor_layout = QVBoxLayout(self.part_editor_holder)
        part_editor_layout.setContentsMargins(0, 0, 0, 0)
        part_editor_buttons = QHBoxLayout()
        self.open_part_editor_button = QPushButton("Open in Mesh Editor")
        self.open_part_editor_button.setToolTip(
            "Open this imported model in Mesh Editor. Select faces with Click, Brush, Rectangle or Lasso, choose Create Part "
            "from Selection, then return here and choose Use Mesh Editor changes."
        )
        self.open_part_editor_button.clicked.connect(self.part_editor_open_requested.emit)
        part_editor_buttons.addWidget(self.open_part_editor_button)
        self.use_part_editor_button = QPushButton("Use Mesh Editor changes")
        self.use_part_editor_button.setToolTip(
            "Capture the current Mesh Editor revision, rebuild this textured preview, and make its parts the source for Apply the placement."
        )
        self.use_part_editor_button.clicked.connect(self.part_editor_apply_requested.emit)
        part_editor_buttons.addWidget(self.use_part_editor_button)
        part_editor_buttons.addStretch(1)
        part_editor_layout.addLayout(part_editor_buttons)
        self.part_editor_status = NoteLabel("", None)
        part_editor_layout.addWidget(self.part_editor_status)
        model_layout.addWidget(self.part_editor_holder)
        self._part_editor_active = False
        self.set_part_editor_state(False)
        # FBX is read by converting it with Blender, and only with a Blender the reader
        # pointed at. That is a requirement of the format, not a tip about it, so it says
        # so on the step: buried under a toggle, the one refusal that names it has nowhere
        # to send anyone.
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
        model_layout.addWidget(self.blender_holder)
        self._refresh_blender_label()
        self.busy_bar = QProgressBar()
        self.busy_bar.setRange(0, 0)
        self.busy_bar.setTextVisible(False)
        self.busy_bar.setFixedHeight(6)
        self.busy_bar.setVisible(False)
        model_layout.addWidget(self.busy_bar)
        self.plain_pbr = QCheckBox("Plain PBR materials (recommended)")
        self.plain_pbr.setChecked(True)
        self.plain_pbr.setToolTip(
            "SkinnedMeshStandard: base colour, normal and roughness/metal, the material route used by shipped texture-driven equipment, "
            "with a real _sp map from the source. Off: the Builder's layered material goes in as it came, and the game draws "
            "its own detail layers over the imported textures."
        )
        self.plain_pbr.toggled.connect(self._material_route_changed)
        model_layout.addWidget(self.plain_pbr)
        self.own_sheath = QCheckBox("Use imported model when sheathed or holstered")
        self.own_sheath.setChecked(True)
        self.own_sheath.setToolTip(
            "Shown only when the template exposes an alternate _IN visual part. On: that borrowed record is cloned under the "
            "new item's stem and pointed at the imported mesh. Off: the template's alternate visual remains borrowed."
        )
        self.own_sheath.toggled.connect(self._sheath_changed)
        model_layout.addWidget(self.own_sheath)
        self.keep_physics = QCheckBox("Keep template cloth and physics")
        self.keep_physics.setToolTip(
            "A template's mesh physics file binds cloth and collision to that template's own vertices. On a model of your own "
            "those indices land wherever they land, which is how a handle ends up swinging like a cape. Off, the item is written "
            "without a physics file and the game gives it none. On for a template whose cloth you want and whose shape yours "
            "follows closely."
        )
        self.keep_physics.toggled.connect(self._keep_physics_changed)
        model_layout.addWidget(self.keep_physics)
        # Glow. The template's own emissive is not inherited -- its mask is cut for the
        # template's mesh and the importer's stand-in is flat, which lights the whole model
        # -- so a glow is something the reader asks for, part by part.
        self.glow_box = QGroupBox("Glow")
        self.glow_box.setCheckable(True)
        self.glow_box.setChecked(False)
        self.glow_box.setToolTip(
            "Make parts of the item give off light. The game's emissive is one colour and one strength per part, so a part "
            "either glows or it does not; pick the parts, the colour and how strongly. Off, the item glows only where your "
            "own model brought an emissive map."
        )
        glow_layout = QVBoxLayout(self.glow_box)
        glow_layout.setContentsMargins(8, 6, 8, 6)
        glow_layout.setSpacing(4)
        self.glow_parts = QListWidget()
        self.glow_parts.setToolTip("The item's material parts, as its model names them. Tick the ones that glow.")
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
        self.glow_intensity = QDoubleSpinBox()
        self.glow_intensity.setRange(0.1, 20.0)
        self.glow_intensity.setSingleStep(0.5)
        self.glow_intensity.setDecimals(1)
        self.glow_intensity.setValue(4.0)
        self.glow_intensity.setToolTip("How strongly the selected parts glow. Shipped emissive equipment commonly uses 1 to 10; the format limit is 20.")
        self.glow_intensity.valueChanged.connect(lambda _value: self._glow_changed())
        glow_row.addWidget(self.glow_intensity)
        glow_row.addStretch(1)
        glow_layout.addLayout(glow_row)
        self._glow_detail_widgets = (
            self.glow_parts,
            self.glow_color_button,
            self.glow_strength_label,
            self.glow_intensity,
        )
        self.glow_box.toggled.connect(self._set_glow_details_visible)
        self.glow_box.toggled.connect(lambda _on: self._glow_changed())
        self._set_glow_details_visible(False)
        model_layout.addWidget(self.glow_box)
        self._set_glow_swatch()
        self.flip_texture_v = QCheckBox("Flip textures vertically (V)")
        self.flip_texture_v.setToolTip(
            "glTF, GLB, OBJ and DAE put V's origin at the bottom and the game samples it from the top, so their textures need the "
            "flip or they draw mirrored along the model. Ticked for those formats; untick it if your source is already in the "
            "game's convention (a mesh taken from the archives)."
        )
        self.flip_texture_v.setVisible(False)
        self.flip_texture_v.toggled.connect(self._flip_texture_v_changed)
        model_layout.addWidget(self.flip_texture_v)
        #: the import's own controls: shown once a model of your own is asked for, so the
        #: step is two radio buttons while the template's model is kept
        self._import_widgets = (
            import_row,
            self.model_status,
            self.part_editor_holder,
            self.blender_holder,
            self.plain_pbr,
            self.own_sheath,
        )
        self.model_group = model

        # ---- placement: the model over the template, beside its resident viewport
        self.placement_group = QGroupBox("Place the model over the template")
        self.placement_group.setTitle("")
        self.placement_group.setAccessibleName("Placement")
        self.placement_group.setProperty("titlelessSection", True)
        placement_layout = QVBoxLayout(self.placement_group)
        placement_layout.setContentsMargins(8, 4, 8, 6)
        placement_layout.setSpacing(4)
        self.placement_group.setToolTip(
            "The model starts fitted to the template. Move it with the gizmo or numbers, then apply the placement."
        )
        view_row = QHBoxLayout()
        view_row.addWidget(QLabel("View:"))
        self.view_mode = QComboBox()
        self.view_mode.addItem("Overlay", "overlay")
        self.view_mode.addItem("Side by side", "side_by_side")
        self.view_mode.addItem("Your model only", "replacement_only")
        self.view_mode.addItem("Template only", "original_only")
        self.view_mode.setToolTip("Overlay: your model over the template. Side by side: the template left, your model right. Or one of them alone.")
        self.view_mode.currentIndexChanged.connect(lambda _i: self.preview.set_view_mode(str(self.view_mode.currentData() or "overlay")))
        view_row.addWidget(self.view_mode)
        self.grid_visible = QCheckBox("Grid")
        self.grid_visible.setChecked(True)
        self.grid_visible.toggled.connect(self.preview.set_grid_visible)
        view_row.addWidget(self.grid_visible)
        view_row.addStretch(1)
        self.frame_view_button = QPushButton("Frame")
        self.frame_view_button.setToolTip("Bring the camera back onto the model where it sits now.")
        self.frame_view_button.clicked.connect(self.preview.fit_view)
        view_row.addWidget(self.frame_view_button)
        placement_layout.addLayout(view_row)
        gizmo_row = QHBoxLayout()
        gizmo_row.addWidget(QLabel("Gizmo:"))
        self.gizmo_buttons = {"move": QRadioButton("Move"), "rotate": QRadioButton("Rotate"), "scale": QRadioButton("Scale")}
        for tool in GIZMO_TOOLS:
            button = self.gizmo_buttons[tool]
            button.toggled.connect(lambda checked, t=tool: self.preview.set_gizmo_tool(t) if checked else None)
            gizmo_row.addWidget(button)
        self.gizmo_buttons["move"].setChecked(True)
        gizmo_row.addStretch(1)
        placement_layout.addLayout(gizmo_row)
        numbers = QGridLayout()
        numbers.setHorizontalSpacing(6)
        numbers.setVerticalSpacing(4)
        self.offset_spins = tuple(_spin(-50.0, 50.0, 0.01, 3, " m") for _ in range(3))
        self.rotation_spins = tuple(_spin(-360.0, 360.0, 1.0, 1, "\u00b0") for _ in range(3))
        self.scale_spins = tuple(_spin(0.0001, 1000.0, 0.01, 4) for _ in range(3))
        for axis, title in enumerate(("X", "Y", "Z")):
            axis_label = QLabel(title)
            axis_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
            numbers.addWidget(axis_label, 0, axis + 1)
        for row, (title, spins) in enumerate(
            (
                ("Position X / Y / Z (m)", self.offset_spins),
                ("Rotation X / Y / Z (\u00b0)", self.rotation_spins),
                ("Scale X / Y / Z", self.scale_spins),
            ),
            start=1,
        ):
            numbers.addWidget(QLabel(title), row, 0)
            for axis, spin in enumerate(spins):
                spin.valueChanged.connect(self._numbers_changed)
                numbers.addWidget(spin, row, axis + 1)
                numbers.setColumnStretch(axis + 1, 1)
        placement_layout.addLayout(numbers)
        action_row = QHBoxLayout()
        self.fit_button = QPushButton("Fit to the template")
        self.fit_button.setToolTip("Back to the first guess: the model scaled to the template's length, turned onto its axes, centred on it; the numbers go back to zero.")
        self.fit_button.clicked.connect(self._fit_to_template)
        action_row.addWidget(self.fit_button)
        self.apply_button = QPushButton("Apply the placement")
        self.apply_button.setToolTip("Build the item's mesh from the model at this placement (the Builder's import over the template's mesh, a few seconds).")
        self.apply_button.clicked.connect(self._controller.start_model_apply)
        action_row.addWidget(self.apply_button)
        action_row.addStretch(1)
        placement_layout.addLayout(action_row)
        self.apply_status = NoteLabel("", None)
        placement_layout.addWidget(self.apply_status)
        self.placement_group.setVisible(False)

        preview = QGroupBox("Preview: the item as it will be")
        self.preview_group = preview
        preview.setMinimumWidth(520)
        preview_layout = QVBoxLayout(preview)
        self.preview_layout = preview_layout
        preview.setToolTip("Your model over the template. Orbit, zoom, move it with the gizmo, and capture the icon from this view.")
        self.operation_banner = QWidget(self.placement_column)
        operation_layout = QVBoxLayout(self.operation_banner)
        operation_layout.setContentsMargins(0, 0, 0, 0)
        operation_layout.setSpacing(3)
        operation_row = QHBoxLayout()
        operation_row.setSpacing(6)
        self.operation_spinner = _BusySpinner(self.operation_banner)
        operation_row.addWidget(self.operation_spinner)
        self.operation_label = QLabel("")
        self.operation_label.setObjectName("new_item_intro")
        operation_row.addWidget(self.operation_label, 1)
        self.cancel_operation_button = QPushButton("Cancel")
        self.cancel_operation_button.clicked.connect(self._cancel_operation)
        operation_row.addWidget(self.cancel_operation_button)
        operation_layout.addLayout(operation_row)
        operation_layout.addWidget(self.busy_bar)
        self.operation_banner.setVisible(False)
        self.preview.setMinimumHeight(300)
        self.preview.status_changed.connect(self._preview_status)
        self.preview.captured.connect(self._inline_capture_done)
        self.preview.placement_changed.connect(self._gizmo_moved)
        preview_layout.addWidget(self.preview, 1)
        preview_row = QHBoxLayout()
        self.capture_inline_button = QPushButton("Take the icon from this view...")
        self.capture_inline_button.setToolTip("Takes the view as it is (grid and gizmo hidden), then you drag the rectangle that becomes the 512 x 512 icon.")
        self.capture_inline_button.clicked.connect(self._capture_inline)
        self.capture_inline_button.setEnabled(False)
        preview_row.addWidget(self.capture_inline_button)
        self.preview_status = QLabel("")
        self.preview_status.setObjectName("new_item_intro")
        self.preview_status.setWordWrap(True)
        preview_row.addWidget(self.preview_status, 1)
        self.icon_thumbnail = QLabel("")
        self.icon_thumbnail.setFixedSize(72, 72)
        self.icon_thumbnail.setAlignment(Qt.AlignCenter)
        self.icon_thumbnail.setVisible(False)
        preview_row.addWidget(self.icon_thumbnail)
        preview_layout.addLayout(preview_row)
        self._preview_mesh_token: object = None
        self._preview_busy = False

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
        source_row.addWidget(self.icon_source, 1)
        self.icon_file_button = QPushButton("Image...")
        self.icon_file_button.setToolTip("Take a picture you already have.")
        self.icon_file_button.clicked.connect(self._pick_icon_file)
        source_row.addWidget(self.icon_file_button)
        self.icon_folder_button = QPushButton("Folder...")
        self.icon_folder_button.setToolTip("Pick the best-matching image out of a folder.")
        self.icon_folder_button.clicked.connect(self._pick_icon_folder)
        source_row.addWidget(self.icon_folder_button)
        icon_layout.addLayout(source_row)
        self.icon_group = icon

        model_icon_content_layout.addWidget(self.model_group)
        model_icon_content_layout.addStretch(1)
        model_icon_column_layout.addWidget(self.icon_group)
        placement_column_layout.addWidget(self.placement_group)
        placement_column_layout.addWidget(self.operation_banner)
        placement_column_layout.addStretch(1)
        self.workspace_splitter.addWidget(self.model_icon_column)
        self.workspace_splitter.addWidget(self.placement_column)
        self.workspace_splitter.addWidget(self.preview_group)
        for index, factor in enumerate((5, 4, 7)):
            self.workspace_splitter.setStretchFactor(index, factor)
        self.workspace_splitter.setSizes((620, 520, 880))

        controller.model_changed.connect(self._show_model)
        controller.model_changed.connect(lambda _result: self.refresh_preview())
        controller.model_import_changed.connect(lambda _source: self._show_model(controller.model_result))
        controller.model_import_changed.connect(lambda _source: self.refresh_preview())
        controller.model_placement_changed.connect(self._placement_changed)
        controller.busy_changed.connect(self._busy_changed)
        controller.operation_progress.connect(self._operation_progress)
        controller.template_changed.connect(lambda _key: self._show_model(controller.model_result))
        controller.template_changed.connect(lambda _key: self.refresh_preview())
        # the parts a glow is chosen by are the template's, so the list follows it
        controller.template_changed.connect(lambda _key: self.refresh_glow_parts())
        # and the parts are the imported model's, so they follow it too -- from the moment
        # the file is read, not from Apply the placement. The result only exists after
        # Apply, and listening for it alone left the list empty until then.
        controller.model_changed.connect(lambda _result: self.refresh_glow_parts())
        controller.model_import_changed.connect(lambda _source: self.refresh_glow_parts())
        controller.model_import_failed.connect(self._import_failed)
        self.preview.ready.connect(lambda: self.capture_inline_button.setEnabled(True))
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

    def mount_preview(self) -> None:
        """Move the shared resident viewport back into Model & Placement."""

        if self.preview.parentWidget() is not self.preview_group:
            self.preview_layout.insertWidget(0, self.preview, 1)

    def _model_source_changed(self, keep: bool) -> None:
        draft = self._controller.draft
        draft.model_source = ModelSource.TEMPLATE if keep else ModelSource.IMPORTED
        self.plain_pbr.setEnabled(not keep)
        self.own_sheath.setEnabled(not keep)
        self._refresh_import_widgets()
        self._controller.invalidate_plan()

    def _refresh_import_widgets(self) -> None:
        keep = self.keep_model.isChecked()
        for widget in self._import_widgets:
            widget.setVisible(not keep)
        has_sheathed_variant = self._controller.template_has_sheathed_variant()
        self.own_sheath.setVisible(not keep and has_sheathed_variant)
        self.own_sheath.setEnabled(not keep and has_sheathed_variant)
        self.clear_button.setVisible(self._controller.model_import is not None)
        has_source = self._controller.model_import is not None
        has_import = has_source or self._controller.model_result is not None
        self.keep_physics.setVisible(has_import and self._controller.template_has_model_physics())
        if keep:
            self.flip_texture_v.setVisible(False)

    def set_part_editor_state(self, active: bool, message: str = "") -> None:
        """Show the two ends of the cross-tab part-edit handoff."""

        self._part_editor_active = bool(active)
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

    def refresh_glow_parts(self) -> None:
        """Fill the part list from the chosen template, keeping what was already ticked."""

        chosen = set(self._controller.draft.glow_parts)
        parts = self._controller.material_parts()
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
        if not parts:
            self.glow_box.setChecked(False)
            self.glow_box.setToolTip("Import a model on this step to choose which of its parts glow.")

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
        self._controller.invalidate_plan()
        self._sync_glow_preview()

    def _sync_glow_preview(self) -> None:
        """Show the glow in the step's viewport as it stands in the draft.

        Only for the placement scene of a live import: that is the only mesh a glow
        applies to, and the only role the renderer's parameter channel can touch. The
        groups are a complete statement over the model's submeshes, so un-ticking a
        part restores the import's own emissive without remembering what was sent.
        A draft that never glowed sends nothing: there is nothing to restore.
        """

        preview = self.preview
        source = self._controller.model_import
        sender = getattr(preview.host, "apply_material_parameter_groups", None)
        if source is None or not callable(sender) or not preview.showing_placement:
            return
        glow = glow_choice(self._controller.draft)
        if glow is None and not self._glow_preview_touched:
            return
        try:
            mesh = source.baked_preview_mesh()
        except Exception:  # noqa: BLE001 - no preview glow is a smaller loss than a step that errors
            return
        from cdmw.services.new_item_materials import glow_preview_parameter_groups

        groups = glow_preview_parameter_groups(mesh, glow)
        if groups and sender(groups):
            self._glow_preview_touched = self._glow_preview_touched or glow is not None

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

    def _sheath_changed(self, own: bool) -> None:
        self._controller.draft.sheathed_model = SheathedModel.OWN_MODEL if own else SheathedModel.TEMPLATE
        self._controller.invalidate_plan()

    def _show_model(self, result: object) -> None:
        source = self._controller.model_import
        self.placement_group.setVisible(source is not None)
        self.flip_texture_v.setVisible(source is not None)
        self.clear_button.setVisible(source is not None)
        self.open_part_editor_button.setEnabled(source is not None and not self._controller.busy)
        self.use_part_editor_button.setEnabled(source is not None and not self._controller.busy)
        if source is not None and self.flip_texture_v.isChecked() != bool(source.flip_texture_v):
            self.flip_texture_v.blockSignals(True)
            self.flip_texture_v.setChecked(bool(source.flip_texture_v))
            self.flip_texture_v.blockSignals(False)
        if result is None and source is None:
            self.keep_model.setChecked(True)
            self.model_status.set_note("No imported model.", None)
            self.plain_pbr.setEnabled(False)
            self.own_sheath.setEnabled(False)
            self._refresh_import_widgets()
            self.apply_status.set_note("", None)
            return
        self.import_model.setChecked(True)
        self.plain_pbr.setEnabled(True)
        self.own_sheath.setEnabled(True)
        self._refresh_import_widgets()
        lines = []
        if source is not None:
            mesh = getattr(source.scene, "mesh", None)
            vertices = int(getattr(mesh, "total_vertices", 0) or 0)
            parts = len(tuple(getattr(mesh, "submeshes", ()) or ()))
            textures = f"{source.texture_count} texture(s) of its own" if source.texture_count else "no textures of its own found beside it"
            lines.append(note(f"{source.label}: {vertices:,} vertices, {parts} part(s), {textures}", OK))
            lines.extend(note(text, None) for text in source.notes[:2])
        if result is not None:
            entry = self._controller.model_entry
            head = f"Placed over {entry.basename}" if entry is not None else "Placed"
            size = len(getattr(result, "rebuilt_data", b"") or b"")
            extras = len(tuple(getattr(result, "supplemental_file_specs", ()) or ()))
            lines.append(note(f"{head}: the rebuilt mesh is {size:,} bytes, {extras} side file(s)", OK))
            self.apply_status.set_note("Applied: the plan will write this mesh.", OK)
        elif source is not None:
            self.apply_status.set_note("Not applied yet: the plan needs Apply the placement.", WARN)
        self.model_status.set_lines(lines)
        self._sync_placement_numbers(self._controller.model_placement)

    def _icon_source_changed(self, keep: bool) -> None:
        self._controller.draft.icon = IconSource.TEMPLATE if keep else IconSource.GENERATED
        for widget in (self.icon_source, self.icon_file_button, self.icon_folder_button):
            widget.setEnabled(not keep)
        self._controller.invalidate_plan()

    # ------------------------------------------------------------------ preview

    def showEvent(self, event) -> None:  # noqa: N802 - Qt virtual
        super().showEvent(event)
        self._show_preview_timer.start()

    def refresh_preview(self) -> None:
        """Show the item as it will be in the inline viewport, textured: the imported
        model's own preview, else the template's mesh decoded from the archives with its
        textures. The decode and the package run off the UI thread, and they start as
        soon as a template is chosen, shown or not, so the step opens with the item
        already there."""

        window = self.window()
        if not (self.isVisible() or (window is not None and window.isVisible())):
            # nothing on screen at all (tests, a tab never shown): no background work
            return
        source = self._controller.item_preview_source()
        if source is None:
            self.preview.show(None)
            self.capture_inline_button.setEnabled(False)
            self._preview_mesh_token = None
            return
        token, build = source
        imported = self._controller.model_import
        if imported is not None:
            # the placement scene: the same token only takes the new placement
            if token != self._preview_mesh_token:
                self.capture_inline_button.setEnabled(False)
            self._preview_mesh_token = token
            self.preview.show_placement(build, token=token, placement=self._controller.model_placement, model_bounds=imported.baked_bounds())
            self._refresh_placement_enabled()
            return
        if token == self._preview_mesh_token and self.preview.is_ready:
            return
        self._preview_mesh_token = token
        self.capture_inline_button.setEnabled(False)
        self.preview.show(build, token=token)

    # ------------------------------------------------------------------ the import and its placement

    def _pick_model_file(self) -> None:
        settings = QSettings("CrimsonDesertModWorkbench", "CrimsonDesertModWorkbench")
        start_dir = str(settings.value(IMPORT_DIR_SETTING, "") or "")
        if not start_dir or not Path(start_dir).is_dir():
            start_dir = str(Path.home())
        path, _selected = QFileDialog.getOpenFileName(self, "Import a model file", start_dir, IMPORT_FILE_FILTER)
        if not path:
            return
        settings.setValue(IMPORT_DIR_SETTING, str(Path(path).parent))
        self.import_model.setChecked(True)
        self._controller.start_model_import(Path(path))

    def _refresh_apply_status(self) -> None:
        if self._controller.model_import is None:
            return
        if self._controller.model_result is not None:
            self.apply_status.set_note("Applied: the plan will write this mesh.", OK)
        else:
            self.apply_status.set_note("Not applied yet: the plan needs Apply the placement.", WARN)

    def _fit_to_template(self) -> None:
        self._controller.fit_model_placement()

    def _placement_changed(self, placement: object) -> None:
        if isinstance(placement, ModelPlacement):
            self._sync_placement_numbers(placement)
            if self._controller.model_import is not None:
                self.preview.set_placement(placement)
                self.refresh_preview()

    def _sync_placement_numbers(self, placement: ModelPlacement) -> None:
        self._syncing_numbers = True
        try:
            for spins, values in ((self.offset_spins, placement.offset), (self.rotation_spins, placement.rotation), (self.scale_spins, placement.scale)):
                for spin, value in zip(spins, values):
                    if abs(spin.value() - float(value)) > 0.5 * 10 ** (-spin.decimals()):
                        spin.setValue(float(value))
        finally:
            self._syncing_numbers = False

    def _numbers_changed(self, _value: float) -> None:
        if self._syncing_numbers or self._controller.model_import is None:
            return
        self._controller.set_model_placement(ModelPlacement(
            offset=tuple(spin.value() for spin in self.offset_spins),
            rotation=tuple(spin.value() for spin in self.rotation_spins),
            scale=tuple(spin.value() for spin in self.scale_spins),
        ))

    def _gizmo_moved(self, placement: object, finished: bool) -> None:
        """The gizmo moved the model: the numbers follow every tick; the controller
        takes the placement when the drag ends (it drops a build made elsewhere)."""

        if not isinstance(placement, ModelPlacement):
            return
        self._sync_placement_numbers(placement)
        if finished:
            self._controller.set_model_placement(placement)

    def _import_failed(self, message: object) -> None:
        """Say on the step why nothing was imported. The note is otherwise left saying
        "Reading the model file...", which reads as a hang rather than a refusal."""

        self.model_status.set_note(str(message or "The model could not be read."), WARN)
        self.busy_bar.setVisible(False)

    def _busy_changed(self, busy: bool) -> None:
        lane = getattr(self._controller, "_lane", "")
        for widget in (
            self.import_button,
            self.apply_button,
            self.fit_button,
            self.open_part_editor_button,
            self.use_part_editor_button,
        ):
            widget.setEnabled(not busy)
        model_busy = bool(busy) and lane in {"model_import", "model_apply", "model_part_edit"}
        self.operation_banner.setVisible(model_busy or self._preview_busy)
        self.operation_spinner.set_running(model_busy or self._preview_busy)
        self.cancel_operation_button.setVisible(model_busy)
        self.cancel_operation_button.setEnabled(model_busy)
        if model_busy:
            self.busy_bar.setRange(0, 0)
            self.busy_bar.setVisible(True)
        elif not self._preview_busy:
            self.busy_bar.setVisible(False)
        if busy and lane == "model_import":
            self.model_status.set_note("Reading the model file...", EDIT)
            self.operation_label.setText("Reading the model file…")
        elif busy and lane == "model_apply":
            self.apply_status.set_note("Building the item's mesh at this placement...", EDIT)
            self.operation_label.setText("Building the item's mesh…")
        elif busy and lane == "model_part_edit":
            self.part_editor_status.setVisible(True)
            self.part_editor_status.set_note("Preparing the Mesh Editor changes...", EDIT)
            self.operation_label.setText("Preparing Mesh Editor changes…")
        self._refresh_placement_enabled()

    def _operation_progress(self, lane: str, current: int, total: int, detail: str) -> None:
        if str(lane) not in {"model_import", "model_apply", "model_part_edit"}:
            return
        self.operation_label.setText(str(detail or "Working…"))
        if int(total) > 0:
            self.busy_bar.setRange(0, int(total))
            self.busy_bar.setValue(max(0, min(int(total), int(current))))
        else:
            self.busy_bar.setRange(0, 0)

    def _cancel_operation(self) -> None:
        lane = str(getattr(self._controller, "_lane", "") or "")
        if self._controller.cancel_operation(lane):
            self.operation_label.setText("Cancelling…")
            self.cancel_operation_button.setEnabled(False)

    def _preview_status(self, text: str) -> None:
        message = str(text or "")
        self._preview_busy = message in {
            "Building the preview...",
            "Loading the viewport...",
            "Loading model textures…",
        }
        # Loading belongs to the pinned operation bar. Repeating the same sentence in
        # the preview footer makes one operation look like two. Errors, readiness notes
        # and capture results still use the footer.
        self.preview_status.setText("" if self._preview_busy else message)
        if not self._controller.busy:
            self.operation_banner.setVisible(self._preview_busy)
            self.operation_spinner.set_running(self._preview_busy)
            self.cancel_operation_button.setVisible(False)
            self.busy_bar.setRange(0, 0)
            self.busy_bar.setVisible(self._preview_busy)
            if self._preview_busy:
                self.operation_label.setText(message.replace("...", "…"))
        self._refresh_placement_enabled()

    def _refresh_placement_enabled(self) -> None:
        """The placement controls answer only while the viewport is showing the model:
        during a build the scene on screen is the one before, and nothing there is the
        item's to move."""

        ready = bool(getattr(self.preview, "showing_placement", False)) and not self._controller.busy
        for widget in (*self.offset_spins, *self.rotation_spins, *self.scale_spins, *self.gizmo_buttons.values(), self.view_mode, self.grid_visible, self.frame_view_button):
            widget.setEnabled(ready)
        building = self._controller.model_import is not None and not ready
        if building and not self._controller.busy:
            self.apply_status.set_note("Building the preview with your model...", EDIT)

    def _capture_inline(self) -> None:
        if not self.preview.capture():
            self.preview_status.setText("The viewport is not showing the item yet; wait for it, then capture.")

    @staticmethod
    def icon_region_dialog_factory(parent, image):
        from cdmw.ui.archive_browser.static_replacement_icon_selection import AlignmentIconSelectionDialog

        return AlignmentIconSelectionDialog(image, parent)

    def _inline_capture_done(self, path: object, image: object) -> None:
        """The viewport handed back the view as it is: let the user drag the rectangle that
        becomes the icon (the Builder's own picker), fit it into 512 x 512 and keep it."""

        from PySide6.QtGui import QImage
        from PySide6.QtWidgets import QDialog

        from cdmw.ui.archive_browser.static_replacement_custom_icon import custom_item_icon_selected_preview_image

        captured = image if isinstance(image, QImage) and not image.isNull() else QImage(str(path))
        if captured.isNull():
            self.preview_status.setText("The capture came back empty.")
            return
        dialog = self.icon_region_dialog_factory(self, captured)
        if dialog.exec() != QDialog.Accepted:
            self.preview_status.setText("Capture dropped; the icon is unchanged.")
            return
        try:
            icon = custom_item_icon_selected_preview_image(captured, dialog.selected_source_rect(), size=512)
            target = Path(str(path)).with_name(f"icon_{Path(str(path)).stem}_selected.png")
            if not icon.save(str(target)):
                raise ValueError(f"the icon could not be written to {target}")
        except Exception as exc:  # noqa: BLE001 - a bad selection is the user's to see, not a crash
            self.preview_status.setText(f"The icon could not be made from that selection: {exc}")
            return
        self.generate_icon.setChecked(True)
        self.icon_source.setText(str(target))
        self.preview_status.setText(f"Icon taken from the view: {icon.width()} x {icon.height()}.")
        try:
            from PySide6.QtGui import QPixmap

            self.icon_thumbnail.setPixmap(QPixmap.fromImage(icon).scaled(self.icon_thumbnail.size(), Qt.KeepAspectRatio, Qt.SmoothTransformation))
            self.icon_thumbnail.setVisible(True)
        except Exception:  # noqa: BLE001
            pass

    def shutdown_preview(self) -> None:
        self._show_preview_timer.stop()
        self.operation_spinner.set_running(False)
        try:
            self.preview.shutdown()
        except Exception:  # noqa: BLE001
            pass

    def request_shutdown_preview(self) -> None:
        self._show_preview_timer.stop()
        self.operation_spinner.set_running(False)
        try:
            self.preview.request_shutdown()
        except Exception:  # noqa: BLE001
            pass

    def iter_shutdown_workers(self):
        try:
            return self.preview.iter_shutdown_workers()
        except Exception:  # noqa: BLE001
            return ()

    def _store_icon_source(self, text: str) -> None:
        self._controller.draft.icon_source_path = str(text)
        self._controller.invalidate_plan()

    def _pick_icon_file(self) -> None:
        path, _selected = QFileDialog.getOpenFileName(
            self, "Choose an icon source image", self.icon_source.text() or "",
            "Images (*.png *.jpg *.jpeg *.bmp *.tga *.dds *.webp);;All files (*)",
        )
        if path:
            self.icon_source.setText(path)

    def _pick_icon_folder(self) -> None:
        path = QFileDialog.getExistingDirectory(self, "Choose a folder of icon source images", self.icon_source.text() or "")
        if path:
            self.icon_source.setText(path)


__all__ = ["ModelPanel"]
