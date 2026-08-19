"""New Item Studio, panel 3: the model (template or imported) and the icon."""

from __future__ import annotations

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QCheckBox,
    QDialog,
    QFileDialog,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QRadioButton,
    QVBoxLayout,
)

from cdmw.domain.new_item.spec import IconSource, MaterialRoute, ModelSource, SheathedModel
from cdmw.ui.new_item.controller import NewItemStudioController
from cdmw.ui.new_item.ui_kit import OK, DetailsToggle, NoteLabel, intro_label, note


class ModelPanel(QGroupBox):
    """Keep the template's model or take a Builder result; keep the icon or generate one."""

    #: The tab starts the Builder over the template's mesh when this fires.
    import_requested = Signal()

    def __init__(self, controller: NewItemStudioController, parent=None) -> None:
        super().__init__("3. Model and icon", parent)
        self._controller = controller
        layout = QVBoxLayout(self)
        layout.addWidget(intro_label("What the item looks like: the template's model or one you import, and the icon the inventory shows."))

        model = QGroupBox("Model")
        model_layout = QVBoxLayout(model)
        self.keep_model = QRadioButton("Keep the template's model (no new model files)")
        self.keep_model.setChecked(True)
        self.keep_model.toggled.connect(self._model_source_changed)
        model_layout.addWidget(self.keep_model)
        self.import_model = QRadioButton("Use an imported model (glTF, GLB, OBJ through the Builder)")
        model_layout.addWidget(self.import_model)
        row = QHBoxLayout()
        self.import_button = QPushButton("Import through the Builder...")
        self.import_button.setToolTip(
            "Opens Import Mesh over the template's mesh. The Builder's result is kept here instead of being written over the template."
        )
        self.import_button.clicked.connect(self.import_requested.emit)
        row.addWidget(self.import_button)
        self.clear_button = QPushButton("Discard imported model")
        self.clear_button.clicked.connect(lambda: self._controller.set_imported_model(None, None))
        row.addWidget(self.clear_button)
        row.addStretch(1)
        model_layout.addLayout(row)
        self.model_status = NoteLabel("No imported model.", None)
        model_layout.addWidget(self.model_status)
        model_layout.addWidget(intro_label(
            "Hand placement: the Builder opens over the template's mesh and shows it as a wire under your model; align yours to it "
            "with the gizmo (grip at the origin, blade toward -z, the same size as the original) and the game holds the new item exactly "
            "as it holds the template."
        ))
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
            "Import tips. glTF, GLB and OBJ sources: tick Flip V in the Builder's texture setup, or the textures draw mirrored along "
            "the model (the game samples V from the top of the image). "
            "Head cover and placement come from the template: an imported model inherits the template's part prefabs (which "
            "character parts it occupies, and any mesh drawn beside it, such as a helm's helmet hair), so pick a helm template for "
            "the look it gives in game (the Northern Fighter's Plate Helm keeps the face drawn; the Unyielding Warrior's and Canta "
            "helms hide the head). Where the model sits is the Builder's placement review: on the shipped swords the guard's "
            "handle-side edge is 0.10 m in front of the hand (offset z, + toward the pommel), and a helm wants manual placement "
            "(a source in centimetres: scale 0.01, no rotation, origin at the head, about y 1.745, z -0.03).",
            title="Import tips",
        ))
        layout.addWidget(model)

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
        self.icon_capture_button = QPushButton("Capture from viewport...")
        self.icon_capture_button.setToolTip("Show the item's mesh (the imported model, else the template's) in the resident viewport, orbit it, and take the frame as the icon.")
        self.icon_capture_button.clicked.connect(self._capture_icon)
        source_row.addWidget(self.icon_capture_button)
        icon_layout.addLayout(source_row)
        layout.addWidget(icon)

        controller.model_changed.connect(self._show_model)
        layout.addStretch(1)
        controller.template_changed.connect(lambda _key: self._show_model(controller.model_result))
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
        if result is None:
            self.keep_model.setChecked(True)
            self.model_status.set_note("No imported model.", None)
            self.plain_pbr.setEnabled(False)
            self.own_sheath.setEnabled(False)
            return
        self.import_model.setChecked(True)
        self.plain_pbr.setEnabled(True)
        self.own_sheath.setEnabled(True)
        lines = list(getattr(result, "summary_lines", ()) or ())[:4]
        entry = self._controller.model_entry
        head = f"Imported model for {entry.basename}" if entry is not None else "Imported model"
        size = len(getattr(result, "rebuilt_data", b"") or b"")
        extras = len(tuple(getattr(result, "supplemental_file_specs", ()) or ()))
        self.model_status.set_lines([note(f"{head}: {size:,} bytes, {extras} side file(s)", OK)] + [note(line, None) for line in lines])

    def _icon_source_changed(self, keep: bool) -> None:
        self._controller.draft.icon = IconSource.TEMPLATE if keep else IconSource.GENERATED
        for widget in (self.icon_source, self.icon_file_button, self.icon_folder_button, self.icon_capture_button):
            widget.setEnabled(not keep)
        self._controller.plan = None

    def _capture_icon(self) -> None:
        mesh = self._controller.item_mesh_for_preview()
        if mesh is None:
            self._controller.status_message.emit("Choose a template (or import a model) first; there is no mesh to show.", True)
            return
        dialog = self.icon_capture_dialog_factory(self, item_mesh=mesh, item_label=self._controller.draft.internal_name or self._controller.template_name())
        if dialog.exec() != QDialog.Accepted or dialog.captured_path is None:
            return
        self.generate_icon.setChecked(True)
        self.icon_source.setText(str(dialog.captured_path))

    @staticmethod
    def icon_capture_dialog_factory(parent, **kwargs):
        from cdmw.ui.new_item.icon_capture_dialog import IconCaptureDialog

        return IconCaptureDialog(parent, **kwargs)

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
