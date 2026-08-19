"""New Item Studio, panel 3: the model (template or imported) and the icon."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QSettings, Qt, QTimer
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
    QProgressBar,
    QPushButton,
    QRadioButton,
    QVBoxLayout,
    QWidget,
)

from cdmw.domain.new_item.spec import IconSource, MaterialRoute, ModelSource, SheathedModel
from cdmw.ui.new_item.controller import NewItemStudioController
from cdmw.ui.new_item.item_preview import GIZMO_TOOLS, ItemPreviewFrame
from cdmw.ui.new_item.model_import import ModelPlacement
from cdmw.ui.new_item.ui_kit import EDIT, OK, WARN, DetailsToggle, NoteLabel, intro_label, note

IMPORT_FILE_FILTER = "Model files (*.gltf *.glb *.obj *.dae *.zip);;glTF / GLB (*.gltf *.glb);;Wavefront OBJ (*.obj);;Collada DAE (*.dae);;Zip with a model inside (*.zip);;All files (*)"
IMPORT_DIR_SETTING = "ui/new_item_import_dir"


def _spin(minimum: float, maximum: float, step: float, decimals: int, suffix: str = "") -> QDoubleSpinBox:
    spin = QDoubleSpinBox()
    spin.setRange(minimum, maximum)
    spin.setSingleStep(step)
    spin.setDecimals(decimals)
    if suffix:
        spin.setSuffix(suffix)
    spin.setKeyboardTracking(False)
    spin.setMinimumWidth(88)
    return spin


class ModelPanel(QGroupBox):
    """Keep the template's model or import one and place it over the template here, in
    the step's own viewport (the gizmo, the numbers); keep the icon or generate one."""

    def __init__(self, controller: NewItemStudioController, parent=None) -> None:
        super().__init__("3. Model and icon", parent)
        self._controller = controller
        outer = QVBoxLayout(self)
        outer.addWidget(intro_label("The model (the template's, or one of your own placed over it) and the inventory icon."))
        # two columns: the choices and numbers on the left, the viewport on the right with
        # the height to itself, so the step uses the width instead of stacking everything
        columns = QHBoxLayout()
        columns.setSpacing(12)
        outer.addLayout(columns, 1)
        left = QWidget()
        left.setMaximumWidth(640)
        layout = QVBoxLayout(left)
        layout.setContentsMargins(0, 0, 0, 0)
        columns.addWidget(left, 0)
        self.preview = ItemPreviewFrame(self)
        self._syncing_numbers = False

        model = QGroupBox("Model")
        model_layout = QVBoxLayout(model)
        self.keep_model = QRadioButton("Keep the template's model (no new model files)")
        self.keep_model.setChecked(True)
        self.keep_model.toggled.connect(self._model_source_changed)
        model_layout.addWidget(self.keep_model)
        self.import_model = QRadioButton("Use a model file of your own (glTF, GLB, OBJ, DAE, or a zip holding one)")
        model_layout.addWidget(self.import_model)
        row = QHBoxLayout()
        self.import_button = QPushButton("Import a model file...")
        self.import_button.setToolTip(
            "Pick a glTF, GLB, OBJ or DAE file, or a zip with one inside, from anywhere on disk. It is read the way the Model "
            "Library reads it (its own textures too) and shown over the template below, where you place it."
        )
        self.import_button.clicked.connect(self._pick_model_file)
        row.addWidget(self.import_button)
        self.clear_button = QPushButton("Discard imported model")
        self.clear_button.clicked.connect(self._controller.discard_model)
        row.addWidget(self.clear_button)
        row.addStretch(1)
        model_layout.addLayout(row)
        self.model_status = NoteLabel("No imported model.", None)
        model_layout.addWidget(self.model_status)
        self.busy_bar = QProgressBar()
        self.busy_bar.setRange(0, 0)
        self.busy_bar.setTextVisible(False)
        self.busy_bar.setFixedHeight(6)
        self.busy_bar.setVisible(False)
        model_layout.addWidget(self.busy_bar)
        self.plain_pbr = QCheckBox("Use the game's plain PBR shaders for the imported textures (recommended)")
        self.plain_pbr.setChecked(True)
        self.plain_pbr.setToolTip(
            "SkinnedMeshStandard: base colour, normal, roughness/metal, the shaders the shipped texture-driven weapons use, "
            "with a real _sp map from the source. Off: the Builder's layered material goes in as it came, and the game draws "
            "its own detail layers over the imported textures."
        )
        self.plain_pbr.toggled.connect(self._material_route_changed)
        model_layout.addWidget(self.plain_pbr)
        self.own_sheath = QCheckBox("When sheathed on the back, draw the imported model (not the template's borrowed scabbard)")
        self.own_sheath.setChecked(True)
        self.own_sheath.setToolTip(
            "A weapon's sheathed look is a part of its own (the _IN stems), usually borrowed from another item, so an imported "
            "sword would show that scabbard beside it. On: the borrowed record is cloned under the item's stem and pointed at the "
            "imported mesh. Off: the template's stays borrowed."
        )
        self.own_sheath.toggled.connect(self._sheath_changed)
        model_layout.addWidget(self.own_sheath)
        model_layout.addWidget(DetailsToggle(
            "Import tips. Head cover and placement come from the template: an imported model inherits the template's part prefabs "
            "(which character parts it occupies, and any mesh drawn beside it, such as a helm's helmet hair), so pick a helm template "
            "for the look it gives in game (the Northern Fighter's Plate Helm keeps the face drawn; the Unyielding Warrior's and Canta "
            "helms hide the head). Where the model sits: on the shipped swords the guard's handle-side edge is 0.10 m in front of the "
            "hand (offset z, + toward the pommel), and a helm wants manual placement (a source in centimetres: scale 0.01, no "
            "rotation, origin at the head, about y 1.745, z -0.03). Fit to the template gives a first guess; the gizmo does the rest.",
            title="Import tips",
        ))
        layout.addWidget(model)

        # ---- placement: the model over the template, in the viewport below
        self.placement_group = QGroupBox("Place the model over the template")
        placement_layout = QVBoxLayout(self.placement_group)
        placement_layout.addWidget(intro_label(
            "The model starts at its fit to the template; the gizmo and the numbers move it from there (origin = the hand, "
            "blade toward -z). Apply the placement builds the item's mesh from it."
        ))
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
        view_row.addSpacing(12)
        view_row.addWidget(QLabel("Gizmo:"))
        self.gizmo_buttons = {"move": QRadioButton("Move"), "rotate": QRadioButton("Rotate"), "scale": QRadioButton("Scale")}
        for tool in GIZMO_TOOLS:
            button = self.gizmo_buttons[tool]
            button.toggled.connect(lambda checked, t=tool: self.preview.set_gizmo_tool(t) if checked else None)
            view_row.addWidget(button)
        self.gizmo_buttons["move"].setChecked(True)
        view_row.addSpacing(12)
        self.frame_view_button = QPushButton("Frame the model")
        self.frame_view_button.setToolTip("Bring the camera back onto the model where it sits now.")
        self.frame_view_button.clicked.connect(self.preview.fit_view)
        view_row.addWidget(self.frame_view_button)
        view_row.addStretch(1)
        placement_layout.addLayout(view_row)
        numbers = QGridLayout()
        numbers.setHorizontalSpacing(8)
        self.offset_spins = tuple(_spin(-50.0, 50.0, 0.01, 3, " m") for _ in range(3))
        self.rotation_spins = tuple(_spin(-360.0, 360.0, 1.0, 1, "\u00b0") for _ in range(3))
        self.scale_spins = tuple(_spin(0.0001, 1000.0, 0.01, 4) for _ in range(3))
        for row, (title, spins) in enumerate((("Offset x / y / z (m):", self.offset_spins), ("Rotation x / y / z (\u00b0):", self.rotation_spins), ("Scale x / y / z:", self.scale_spins))):
            numbers.addWidget(QLabel(title), row, 0)
            for axis, spin in enumerate(spins):
                spin.valueChanged.connect(self._numbers_changed)
                numbers.addWidget(spin, row, 1 + axis)
        numbers.setColumnStretch(4, 1)
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
        self.apply_status = NoteLabel("", None)
        action_row.addWidget(self.apply_status, 1)
        placement_layout.addLayout(action_row)
        self.placement_group.setVisible(False)
        layout.addWidget(self.placement_group)

        preview = QGroupBox("Preview: the item as it will be")
        preview_layout = QVBoxLayout(preview)
        preview_layout.addWidget(intro_label("Your model (textured) over the template, or the template alone. Orbit and zoom; the icon is taken from this view."))
        self.preview.setMinimumHeight(420)
        self.preview.status_changed.connect(self._preview_status)
        self.preview.captured.connect(self._inline_capture_done)
        self.preview.placement_changed.connect(self._gizmo_moved)
        preview_layout.addWidget(self.preview, 1)
        preview_row = QHBoxLayout()
        self.capture_inline_button = QPushButton("Capture the icon from this view")
        self.capture_inline_button.setToolTip("The view as it is, at 512 x 512, grid and gizmo hidden, as the item's icon.")
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
        columns.addWidget(preview, 1)
        self._preview_mesh_token: object = None

        icon = QGroupBox("Icon")
        icon_layout = QVBoxLayout(icon)
        self.keep_icon = QRadioButton("Keep the template's icon")
        self.keep_icon.setChecked(True)
        self.keep_icon.toggled.connect(self._icon_source_changed)
        icon_layout.addWidget(self.keep_icon)
        self.generate_icon = QRadioButton("Give the item its own icon (from a picture, or captured in the viewport)")
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
        layout.addWidget(icon)

        controller.model_changed.connect(self._show_model)
        controller.model_changed.connect(lambda _result: self.refresh_preview())
        controller.model_import_changed.connect(lambda _source: self._show_model(controller.model_result))
        controller.model_import_changed.connect(lambda _source: self.refresh_preview())
        controller.model_placement_changed.connect(self._placement_changed)
        controller.busy_changed.connect(self._busy_changed)
        layout.addStretch(1)
        controller.template_changed.connect(lambda _key: self._show_model(controller.model_result))
        controller.template_changed.connect(lambda _key: self.refresh_preview())
        self.preview.ready.connect(lambda: self.capture_inline_button.setEnabled(True))
        self.preview.ready.connect(self._refresh_placement_enabled)
        self.preview.ready.connect(self._refresh_apply_status)
        self._icon_source_changed(True)
        self.plain_pbr.setEnabled(False)
        self.own_sheath.setEnabled(False)

    def _model_source_changed(self, keep: bool) -> None:
        draft = self._controller.draft
        draft.model_source = ModelSource.TEMPLATE if keep else ModelSource.IMPORTED
        self.plain_pbr.setEnabled(not keep)
        self.own_sheath.setEnabled(not keep)
        self._controller.plan = None

    def _material_route_changed(self, plain: bool) -> None:
        self._controller.draft.material_route = MaterialRoute.PLAIN_PBR if plain else MaterialRoute.BUILDER
        self._controller.plan = None

    def _sheath_changed(self, own: bool) -> None:
        self._controller.draft.sheathed_model = SheathedModel.OWN_MODEL if own else SheathedModel.TEMPLATE
        self._controller.plan = None

    def _show_model(self, result: object) -> None:
        source = self._controller.model_import
        self.placement_group.setVisible(source is not None)
        if result is None and source is None:
            self.keep_model.setChecked(True)
            self.model_status.set_note("No imported model.", None)
            self.plain_pbr.setEnabled(False)
            self.own_sheath.setEnabled(False)
            self.apply_status.set_note("", None)
            return
        self.import_model.setChecked(True)
        self.plain_pbr.setEnabled(True)
        self.own_sheath.setEnabled(True)
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
        self._controller.plan = None

    # ------------------------------------------------------------------ preview

    def showEvent(self, event) -> None:  # noqa: N802 - Qt virtual
        super().showEvent(event)
        QTimer.singleShot(0, self.refresh_preview)

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

    def _busy_changed(self, busy: bool) -> None:
        lane = getattr(self._controller, "_lane", "")
        for widget in (self.import_button, self.apply_button, self.fit_button):
            widget.setEnabled(not busy)
        self.busy_bar.setVisible(bool(busy) and lane in {"model_import", "model_apply"})
        if busy and lane == "model_import":
            self.model_status.set_note("Reading the model file...", EDIT)
        elif busy and lane == "model_apply":
            self.apply_status.set_note("Building the item's mesh at this placement...", EDIT)

    def _preview_status(self, text: str) -> None:
        self.preview_status.setText(str(text or ""))
        self._refresh_placement_enabled()

    def _refresh_placement_enabled(self) -> None:
        """The placement controls answer only while the viewport is showing the model:
        during a build the scene on screen is the one before, and nothing there is the
        item's to move."""

        ready = bool(getattr(self.preview, "showing_placement", False))
        for widget in (*self.offset_spins, *self.rotation_spins, *self.scale_spins, *self.gizmo_buttons.values(), self.view_mode, self.grid_visible, self.frame_view_button):
            widget.setEnabled(ready)
        building = self._controller.model_import is not None and not ready
        self.busy_bar.setVisible(building or self.busy_bar.isVisible() and self._controller.busy)
        if building and not self._controller.busy:
            self.apply_status.set_note("Building the preview with your model...", EDIT)

    def _capture_inline(self) -> None:
        if not self.preview.capture():
            self.preview_status.setText("The viewport is not showing the item yet; wait for it, then capture.")

    def _inline_capture_done(self, path: object, image: object) -> None:
        self.generate_icon.setChecked(True)
        self.icon_source.setText(str(path))
        try:
            from PySide6.QtGui import QPixmap

            self.icon_thumbnail.setPixmap(QPixmap.fromImage(image).scaled(self.icon_thumbnail.size(), Qt.KeepAspectRatio, Qt.SmoothTransformation))
            self.icon_thumbnail.setVisible(True)
        except Exception:  # noqa: BLE001
            pass

    def shutdown_preview(self) -> None:
        try:
            self.preview.shutdown()
        except Exception:  # noqa: BLE001
            pass

    def _store_icon_source(self, text: str) -> None:
        self._controller.draft.icon_source_path = str(text)

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
