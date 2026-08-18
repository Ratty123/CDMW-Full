"""New Item Studio, panel 3: the model (template or imported) and the icon."""

from __future__ import annotations

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QCheckBox,
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


class ModelPanel(QGroupBox):
    """Keep the template's model or take a Builder result; keep the icon or generate one."""

    #: The tab starts the Builder over the template's mesh when this fires.
    import_requested = Signal()

    def __init__(self, controller: NewItemStudioController, parent=None) -> None:
        super().__init__("3. Model and icon", parent)
        self._controller = controller
        layout = QVBoxLayout(self)

        self.keep_model = QRadioButton("Keep the template's model (no new model files)")
        self.keep_model.setChecked(True)
        self.keep_model.toggled.connect(self._model_source_changed)
        layout.addWidget(self.keep_model)
        self.import_model = QRadioButton("Use an imported model, re-pathed to the new item's own family")
        layout.addWidget(self.import_model)
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
        layout.addLayout(row)
        self.model_status = QLabel("No imported model.")
        self.model_status.setWordWrap(True)
        layout.addWidget(self.model_status)
        flip_note = QLabel(
            "glTF, GLB and OBJ sources: tick Flip V in the Builder's texture setup. The importer stores their texture V as 1-v, "
            "and the game samples a mesh's V from the top of the image, the way the file has it, so without the flip the textures "
            "draw mirrored along the model (seen in game 2026-08-18)."
        )
        flip_note.setWordWrap(True)
        layout.addWidget(flip_note)
        baseline_note = QLabel(
            "Head cover and placement come from the template. An imported model inherits the template's part prefabs (which "
            "character parts it occupies, and any mesh drawn beside it, such as a helm's helmet hair; the Template panel lists "
            "them), so pick a helm template for the look it gives in game: the Northern Fighter's Plate Helm keeps the face drawn, "
            "the Unyielding Warrior's and Canta helms hide the head. Where the model sits is the Builder's placement review: on the "
            "shipped swords the guard's handle-side edge is 0.10 m in front of the hand (offset z, + toward the pommel), and a helm "
            "wants manual placement (a source in centimetres: scale 0.01, no rotation, origin at the head, about y 1.745, z -0.03)."
        )
        baseline_note.setWordWrap(True)
        layout.addWidget(baseline_note)
        self.plain_pbr = QCheckBox("Write the imported materials for the game's plain PBR shaders (SkinnedMeshStandard: base colour, normal, roughness/metal)")
        self.plain_pbr.setChecked(True)
        self.plain_pbr.setToolTip(
            "The Builder keeps the template's layered material and fits the imported textures into it, and the game draws "
            "its own detail layers over them. Checked, the wrappers the import owns are rewritten to the shaders the shipped "
            "texture-driven weapons use, with a real _sp roughness/metal map from the source. Unchecked, the Builder's sidecar "
            "goes in as it came (Material Authority)."
        )
        self.plain_pbr.toggled.connect(self._material_route_changed)
        layout.addWidget(self.plain_pbr)
        self.own_sheath = QCheckBox("Sheathed on the back, draw the imported model itself (instead of the template's borrowed scabbard part)")
        self.own_sheath.setChecked(True)
        self.own_sheath.setToolTip(
            "A weapon's sheathed look is a part of its own (the _IN stems), usually borrowed from another item: Reckleeman's greatsword "
            "borrows the shipped sword-in-scabbard model, so an imported sword shows that scabbard beside it. Checked, the borrowed "
            "record is cloned under the item's stem and its prefab re-pathed to the imported mesh. Unchecked, the template's stays borrowed."
        )
        self.own_sheath.toggled.connect(self._sheath_changed)
        layout.addWidget(self.own_sheath)

        icon = QGroupBox("Icon")
        icon_layout = QVBoxLayout(icon)
        self.keep_icon = QRadioButton("Keep the template's icon")
        self.keep_icon.setChecked(True)
        self.keep_icon.toggled.connect(self._icon_source_changed)
        icon_layout.addWidget(self.keep_icon)
        self.generate_icon = QRadioButton("Generate an icon at the new item's own path (unproven in game until the first check)")
        icon_layout.addWidget(self.generate_icon)
        source_row = QHBoxLayout()
        self.icon_source = QLineEdit()
        self.icon_source.setPlaceholderText("Image file, or a folder the best-matching image is picked from")
        self.icon_source.textChanged.connect(self._store_icon_source)
        source_row.addWidget(self.icon_source, 1)
        self.icon_file_button = QPushButton("Image...")
        self.icon_file_button.clicked.connect(self._pick_icon_file)
        source_row.addWidget(self.icon_file_button)
        self.icon_folder_button = QPushButton("Folder...")
        self.icon_folder_button.clicked.connect(self._pick_icon_folder)
        source_row.addWidget(self.icon_folder_button)
        icon_layout.addLayout(source_row)
        note = QLabel(
            "The icon is fitted and encoded against the template icon's DDS format, the way the Builder's "
            "Generate Icon does. A capture from the resident preview can be saved as an image and picked here."
        )
        note.setWordWrap(True)
        icon_layout.addWidget(note)
        layout.addWidget(icon)

        controller.model_changed.connect(self._show_model)
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
            self.model_status.setText("No imported model.")
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
        self.model_status.setText("\n".join([f"{head}: {size:,} bytes, {extras} side file(s)"] + lines))

    def _icon_source_changed(self, keep: bool) -> None:
        self._controller.draft.icon = IconSource.TEMPLATE if keep else IconSource.GENERATED
        for widget in (self.icon_source, self.icon_file_button, self.icon_folder_button):
            widget.setEnabled(not keep)
        self._controller.plan = None

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
