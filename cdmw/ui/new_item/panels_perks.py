"""New Item Studio, panel 5: perks (the Abyss Gear socket items the item carries) and a weapon effect.

Perks are the item row's default socket items: the tooltip's "Insight I", "Malicebane I"
lines. The panel offers every gem the archives know, by English name, and holds up to
eight of them (no shipped item carries more than four). The gems are of two kinds: the
`Item_Stat_*` ones (Destruction, Swift, the resistances) and the `Item_Skill_*` ones,
which grant Abyss skills, the elemental abilities among them (Volcanic Eruption, Frost
Hail, Orbs of Lightning, Storm Fang, Groundsurge, Tempest of Destruction, Wind Slash...);
shipped items embed both kinds by default (Crow Storm on the White Crow witch's war
hammer, Storm Fang on Endour's helm), so an elemental ability is a perk away. An effect is one of the
shipped effect binaries, grafted into the item's own prefabs as an EffectComponent; a
grafted fire drew on the sword in game (2026-08-18), and the presets start from the
effects named for weapons and elements.
"""

from __future__ import annotations

from typing import List, Optional

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDoubleSpinBox,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from cdmw.domain.new_item.effects import presets_for
from cdmw.ui.new_item.controller import NewItemStudioController
from cdmw.ui.new_item.ui_kit import DetailsToggle, intro_label

MAX_PERKS = 8
SUGGESTED_EFFECT_TERMS = ("fire", "lightning", "ice", "aura", "sword", "weapon")


class PerksPanel(QGroupBox):
    def __init__(self, controller: NewItemStudioController, parent=None) -> None:
        super().__init__("5. Perks and effect", parent)
        self._controller = controller
        layout = QVBoxLayout(self)
        layout.addWidget(intro_label("The perks the item comes with, and an optional effect on the drawn weapon."))

        perks = QGroupBox("Perks (the socket items embedded in the item)")
        perks_layout = QVBoxLayout(perks)
        self.template_perks = QLabel("The clone carries the template's own perks.")
        self.template_perks.setWordWrap(True)
        perks_layout.addWidget(self.template_perks)
        self.own_perks = QCheckBox("Choose the perks myself (up to eight; no shipped item carries more than four)")
        self.own_perks.toggled.connect(self._own_perks_changed)
        perks_layout.addWidget(self.own_perks)
        chosen_row = QHBoxLayout()
        self.chosen = QListWidget()
        chosen_row.addWidget(self.chosen, 1)
        buttons = QVBoxLayout()
        self.remove_button = QPushButton("Remove")
        self.remove_button.clicked.connect(self._remove_selected)
        buttons.addWidget(self.remove_button)
        self.reset_button = QPushButton("Back to the template's")
        self.reset_button.clicked.connect(self._reset_to_template)
        buttons.addWidget(self.reset_button)
        buttons.addStretch(1)
        chosen_row.addLayout(buttons)
        perks_layout.addLayout(chosen_row)
        add_row = QHBoxLayout()
        self.perk_filter = QLineEdit()
        self.perk_filter.setPlaceholderText("Filter perks by name (Insight, Destruction, Malicebane; Item_Skill for the Abyss skills: Volcanic Eruption, Storm Fang, Groundsurge...)")
        self.perk_filter.textChanged.connect(self._refresh_catalogue)
        add_row.addWidget(self.perk_filter, 1)
        self.catalogue = QComboBox()
        self.catalogue.setMinimumWidth(240)
        add_row.addWidget(self.catalogue, 2)
        self.add_button = QPushButton("Add")
        self.add_button.clicked.connect(self._add_selected)
        add_row.addWidget(self.add_button)
        perks_layout.addLayout(add_row)
        layout.addWidget(perks)

        effect = QGroupBox("Weapon effect (optional)")
        effect_layout = QVBoxLayout(effect)
        self.use_effect = QCheckBox("Give the weapon a visual effect while it is drawn (fire proven in game)")
        self.use_effect.setToolTip("The effect is grafted into the item's own prefabs, so the shipped items keep theirs.")
        self.use_effect.toggled.connect(self._use_effect_changed)
        effect_layout.addWidget(self.use_effect)
        choose = QFormLayout()
        choose.setFieldGrowthPolicy(QFormLayout.AllNonFixedFieldsGrow)
        self.effect_preset = QComboBox()
        self.effect_preset.setToolTip("Shipped effects named for weapons and elements (fire, lightning, frost...) with a starting scale, as a place to begin; the list below has every shipped effect.")
        self.effect_preset.currentIndexChanged.connect(self._preset_chosen)
        choose.addRow("Start from a preset:", self.effect_preset)
        effect_row = QHBoxLayout()
        self.effect_filter = QLineEdit()
        self.effect_filter.setPlaceholderText("Filter (fire, lightning, aura, sword...)")
        self.effect_filter.textChanged.connect(self._refresh_effects)
        effect_row.addWidget(self.effect_filter, 1)
        self.effect = QComboBox()
        self.effect.setMinimumWidth(260)
        self.effect.currentIndexChanged.connect(self._effect_changed)
        effect_row.addWidget(self.effect, 2)
        self.index_button = QPushButton("Index effects (once, about a minute)")
        self.index_button.setToolTip(
            "Read every shipped effect once and keep the index on disk: the filter then also matches the emitters, "
            "textures and meshes an effect is made of, and the line below says what the chosen effect draws and how big it is."
        )
        self.index_button.clicked.connect(self._index_effects)
        effect_row.addWidget(self.index_button)
        choose.addRow("Or any shipped effect:", effect_row)
        choose_holder = QWidget()
        choose_holder.setLayout(choose)
        effect_layout.addWidget(choose_holder)
        self.effect_facts = QLabel("")
        self.effect_facts.setObjectName("new_item_intro")
        self.effect_facts.setWordWrap(True)
        self.effect_facts.setTextInteractionFlags(Qt.TextSelectableByMouse)
        effect_layout.addWidget(self.effect_facts)
        placement_row = QHBoxLayout()
        placement_row.addWidget(QLabel("Where it sits:  scale"))
        self.effect_scale = QDoubleSpinBox()
        self.effect_scale.setRange(0.01, 10.0)
        self.effect_scale.setSingleStep(0.1)
        self.effect_scale.setDecimals(2)
        self.effect_scale.setValue(1.0)
        self.effect_scale.setToolTip("A uniform scale on the grafted effect. Effects made for bigger weapons (the titan's lightning, the fire sweep) reach past a sword at 1.0; the shipped spear carries 0.7.")
        self.effect_scale.valueChanged.connect(self._effect_transform_changed)
        placement_row.addWidget(self.effect_scale)
        placement_row.addWidget(QLabel("offset x, y, z (m):"))
        self.effect_offset = []
        for _axis in range(3):
            box = QDoubleSpinBox()
            box.setRange(-5.0, 5.0)
            box.setSingleStep(0.05)
            box.setDecimals(2)
            box.setValue(0.0)
            box.setToolTip("Moves the effect along the weapon's own axes, in metres, from the weapon's origin.")
            box.valueChanged.connect(self._effect_transform_changed)
            placement_row.addWidget(box)
            self.effect_offset.append(box)
        placement_row.addStretch(1)
        placement_holder = QWidget()
        placement_holder.setLayout(placement_row)
        effect_layout.addWidget(placement_holder)
        self.place_button = QPushButton("Place in viewport...")
        self.place_button.setToolTip(
            "Open the resident viewport with the item's mesh and the effect's box at the current scale and offset; "
            "drag the gizmo to move or scale it, and the numbers come back here."
        )
        self.place_button.clicked.connect(self._place_in_viewport)
        placement_row.addWidget(self.place_button)
        look_row = QHBoxLayout()
        look_row.addWidget(QLabel("How it looks:  colour"))
        self.color_button = QPushButton("Colour: as shipped")
        self.color_button.setToolTip("Recolour the effect (a fire's colour curve and temperature ramp; proven blue in game). The effect and its emitters are cloned under the item's own stems; the shipped ones stay as they are.")
        self.color_button.clicked.connect(self._pick_color)
        look_row.addWidget(self.color_button)
        self.color_reset = QPushButton("Drop the colour")
        self.color_reset.setToolTip("Back to the shipped colour.")
        self.color_reset.clicked.connect(self._reset_color)
        look_row.addWidget(self.color_reset)
        look_row.addStretch(1)
        # the four factors go on their own row: eight widgets beside the colour buttons set a
        # minimum width the step could not be read at
        factor_row = QHBoxLayout()
        factor_row.addSpacing(24)
        self.look_factors: dict[str, QDoubleSpinBox] = {}
        for key, label, tip in (
            ("intensity", "brightness x", "Multiplies the emitters' emissive brightness (and the temperature ramp's brightness)."),
            ("size", "particle size x", "Multiplies the particle scale (and the effect's bounding boxes)."),
            ("rate", "spawn rate x", "Multiplies the spawn counts and the particle cap."),
            ("lifetime", "lifetime x", "Multiplies the particle lifetimes."),
        ):
            factor_row.addWidget(QLabel(label))
            box = QDoubleSpinBox()
            box.setRange(0.05, 20.0)
            box.setDecimals(2)
            box.setSingleStep(0.1)
            box.setValue(1.0)
            box.setToolTip(tip)
            box.valueChanged.connect(self._look_changed)
            factor_row.addWidget(box)
            self.look_factors[key] = box
        factor_row.addStretch(1)
        look_holder = QWidget()
        look_column = QVBoxLayout(look_holder)
        look_column.setContentsMargins(0, 0, 0, 0)
        look_column.addLayout(look_row)
        look_column.addLayout(factor_row)
        effect_layout.addWidget(look_holder)
        self.effect_note = DetailsToggle(
            "The effect is drawn at the weapon's own origin, as the shipped thrown lightning spear draws its aura. Effects made for "
            "other weapons may sit or scale oddly; the scale and offset above move them, the presets carry a starting scale, and "
            "Place in viewport shows the effect's box (and its particles, approximately) on the item. A colour edit recolours the "
            "effect's colour curve and temperature ramp on a clone of the effect; the factors multiply the emitters' brightness, "
            "particle size, spawn rate and lifetime.",
            title="How the effect and its look work",
        )
        effect_layout.addWidget(self.effect_note)
        #: everything below the "give it an effect" tick: hidden while it is off, so the
        #: step is one line when the answer is no
        self._effect_rows = (choose_holder, self.effect_facts, placement_holder, look_holder, self.effect_note)
        for row in self._effect_rows:
            row.setVisible(False)
        layout.addWidget(effect)

        self._own_perks_changed(False)
        self._use_effect_changed(False)
        layout.addStretch(1)
        controller.snapshot_ready.connect(self._refresh_all)
        controller.effect_catalogue_ready.connect(self._catalogue_ready)
        controller.template_changed.connect(self._template_changed)
        self._refresh_all()

    # ------------------------------------------------------------------ perks

    def _refresh_all(self) -> None:
        self._refresh_catalogue()
        self._refresh_presets()
        self._refresh_effects()
        self._template_changed(None)

    def _template_changed(self, _key: object) -> None:
        keys = self._controller.template_socket_items()
        if keys:
            names = [self._controller.perk_label(key) for key in keys]
            self.template_perks.setText(f"The template carries {len(keys)} perk(s): {', '.join(names)}.")
        else:
            self.template_perks.setText("The template carries no perks; the clone gets none unless you choose some.")
        if self._controller.draft.socket_items is None:
            self.own_perks.setChecked(False)
        self._refresh_chosen()

    def _own_perks_changed(self, checked: bool) -> None:
        draft = self._controller.draft
        if checked and draft.socket_items is None:
            draft.socket_items = list(self._controller.template_socket_items())
        elif not checked:
            draft.socket_items = None
        # hidden rather than greyed: an empty list box the height of the panel is dead
        # space on a step whose usual answer is "the template's"
        for widget in (self.chosen, self.remove_button, self.reset_button, self.perk_filter, self.catalogue, self.add_button):
            widget.setEnabled(bool(checked))
            widget.setVisible(bool(checked))
        self._controller.plan = None
        self._refresh_chosen()

    def _refresh_chosen(self) -> None:
        self.chosen.clear()
        for key in list(self._controller.draft.socket_items or ()):
            item = QListWidgetItem(self._controller.perk_label(key))
            item.setData(Qt.UserRole, int(key))
            self.chosen.addItem(item)
        # the box is as tall as what it holds (two rows at the least, the eight-perk cap at
        # the most), so two chosen perks do not sit in half a panel of empty list
        rows = max(2, min(8, self.chosen.count()))
        height = rows * max(18, self.chosen.sizeHintForRow(0) if self.chosen.count() else 18) + 2 * self.chosen.frameWidth() + 4
        self.chosen.setFixedHeight(height)

    def _refresh_catalogue(self, *_args) -> None:
        current = self.catalogue.currentData()
        self.catalogue.blockSignals(True)
        try:
            self.catalogue.clear()
            for key, label in self._controller.perk_catalogue(self.perk_filter.text()):
                self.catalogue.addItem(label, key)
            if current is not None:
                index = self.catalogue.findData(current)
                if index >= 0:
                    self.catalogue.setCurrentIndex(index)
        finally:
            self.catalogue.blockSignals(False)

    def _add_selected(self) -> None:
        key = self.catalogue.currentData()
        draft = self._controller.draft
        if not isinstance(key, int) or draft.socket_items is None:
            return
        if len(draft.socket_items) >= MAX_PERKS:
            self._controller.status_message.emit(f"An item carries at most {MAX_PERKS} perks.", True)
            return
        draft.socket_items.append(int(key))
        self._controller.plan = None
        self._refresh_chosen()

    def _remove_selected(self) -> None:
        draft = self._controller.draft
        row = self.chosen.currentRow()
        if draft.socket_items is None or row < 0 or row >= len(draft.socket_items):
            return
        del draft.socket_items[row]
        self._controller.plan = None
        self._refresh_chosen()

    def _reset_to_template(self) -> None:
        self._controller.draft.socket_items = list(self._controller.template_socket_items())
        self._controller.plan = None
        self._refresh_chosen()

    # ------------------------------------------------------------------ effect

    def _use_effect_changed(self, checked: bool) -> None:
        for widget in (self.effect_filter, self.effect, self.effect_preset, self.effect_scale, self.index_button, self.place_button, self.color_button, self.color_reset, *self.effect_offset, *self.look_factors.values()):
            widget.setEnabled(bool(checked))
        for row in self._effect_rows:
            row.setVisible(bool(checked))
        self._effect_changed(self.effect.currentIndex())

    def _effect_transform_changed(self, *_args) -> None:
        draft = self._controller.draft
        draft.effect_scale = float(self.effect_scale.value())
        draft.effect_offset = tuple(float(box.value()) for box in self.effect_offset)
        self._controller.plan = None
        self._refresh_facts()

    def _index_effects(self) -> None:
        self._controller.start_effect_index()

    def _look_changed(self, *_args) -> None:
        draft = self._controller.draft
        draft.effect_intensity = float(self.look_factors["intensity"].value())
        draft.effect_size = float(self.look_factors["size"].value())
        draft.effect_rate = float(self.look_factors["rate"].value())
        draft.effect_lifetime = float(self.look_factors["lifetime"].value())
        self._controller.plan = None

    def _pick_color(self) -> None:
        from PySide6.QtGui import QColor
        from PySide6.QtWidgets import QColorDialog

        current = self._controller.draft.effect_color
        start = QColor.fromRgbF(*current) if current else QColor(255, 120, 30)
        chosen = self.color_dialog(start, self)
        if chosen is None:
            return
        self.set_effect_color((chosen.redF(), chosen.greenF(), chosen.blueF()))

    @staticmethod
    def color_dialog(start, parent):
        from PySide6.QtWidgets import QColorDialog

        chosen = QColorDialog.getColor(start, parent, "Effect colour")
        return chosen if chosen.isValid() else None

    def set_effect_color(self, rgb) -> None:
        draft = self._controller.draft
        draft.effect_color = tuple(max(0.0, min(1.0, float(v))) for v in rgb) if rgb is not None else None
        if draft.effect_color is None:
            self.color_button.setText("Colour: as shipped")
            self.color_button.setStyleSheet("")
        else:
            r, g, b = (int(round(v * 255)) for v in draft.effect_color)
            self.color_button.setText(f"Colour: #{r:02x}{g:02x}{b:02x}")
            self.color_button.setStyleSheet(f"background-color: rgb({r},{g},{b}); color: {'black' if (r + g + b) > 380 else 'white'};")
        self._controller.plan = None

    def _reset_color(self) -> None:
        self.set_effect_color(None)

    def _place_in_viewport(self, *_args) -> None:
        stem = str(self._controller.draft.effect_stem or "")
        if not stem:
            self._controller.status_message.emit("Choose an effect first.", True)
            return
        mesh, item_label = self._controller.item_mesh_as_planned()
        if mesh is None:
            self._controller.status_message.emit("Choose a template (or import a model) first; there is no mesh to place the effect on.", True)
            return
        box_min, box_max = self._controller.effect_box(stem)
        effect_preview, texture_reader = self._controller.effect_preview_for_placement(stem)
        if effect_preview is not None and self._controller.effect_facts(stem) is None:
            # not indexed yet: the effect's own bounding box, read from its binary, not the metre cube
            box_min, box_max = effect_preview.box_min, effect_preview.box_max
        dialog = self.placement_dialog_factory(
            self, item_mesh=mesh, box_min=box_min, box_max=box_max, item_label=item_label,
            offset=tuple(float(box.value()) for box in self.effect_offset), scale=float(self.effect_scale.value()), effect_label=stem,
            effect_preview=effect_preview, texture_reader=texture_reader,
        )
        if dialog.exec() != QDialog.Accepted:
            return
        self.effect_scale.setValue(float(dialog.scale))
        for box, value in zip(self.effect_offset, dialog.offset):
            box.setValue(float(value))
        self._effect_transform_changed()

    @staticmethod
    def placement_dialog_factory(parent, **kwargs):
        from cdmw.ui.new_item.effect_placement_dialog import EffectPlacementDialog

        return EffectPlacementDialog(parent, **kwargs)

    def _catalogue_ready(self) -> None:
        catalogue = self._controller.effect_catalogue
        count = len(catalogue) if catalogue is not None else 0
        self.index_button.setText(f"{count} effects indexed")
        self.index_button.setEnabled(False)
        self._refresh_effects()

    def _refresh_facts(self) -> None:
        stem = str(self._controller.draft.effect_stem or "")
        facts = self._controller.effect_facts(stem) if stem else None
        if not stem or not self.use_effect.isChecked():
            self.effect_facts.setText("")
            return
        if facts is None:
            self.effect_facts.setText("Index the effects to see what this one draws and how big it is.")
            return
        emitters = ", ".join(name.rsplit("/", 1)[-1] for name in facts.emitters) or "none named"
        textures = ", ".join(path.rsplit("/", 1)[-1] for path in facts.textures) or "none"
        meshes = ", ".join(path.rsplit("/", 1)[-1] for path in facts.meshes)
        width, height, depth = facts.size
        scale = float(self.effect_scale.value())
        loop = "loops" if facts.loops else f"plays once ({facts.max_spawnable_time:.1f} s)"
        text = (
            f"{facts.name or facts.stem}: emitters {emitters}; textures {textures}; "
            f"box {width:.2f} x {height:.2f} x {depth:.2f} m, at scale {scale:.2f}: {width * scale:.2f} x {height * scale:.2f} x {depth * scale:.2f} m; {loop}"
        )
        if meshes:
            text += f"; meshes {meshes}"
        if facts.has_lights:
            text += "; carries lights"
        if facts.walk_note:
            text += f"; the file did not decode fully ({facts.walk_note})"
        self.effect_facts.setText(text)

    def _refresh_presets(self) -> None:
        available = set(self._controller.effect_stems("", limit=100000))
        self.effect_preset.blockSignals(True)
        try:
            self.effect_preset.clear()
            self.effect_preset.addItem("Choose a preset...", "")
            for preset in presets_for(available):
                label = preset.label + (" (proven)" if preset.proven else "")
                self.effect_preset.addItem(label, preset.stem)
                if preset.note:
                    self.effect_preset.setItemData(self.effect_preset.count() - 1, f"{preset.stem}: {preset.note}", Qt.ItemDataRole.ToolTipRole)
        finally:
            self.effect_preset.blockSignals(False)

    def _preset_chosen(self, index: int) -> None:
        stem = self.effect_preset.itemData(index) if index >= 0 else ""
        if stem:
            self.choose_effect(str(stem))
            for preset in presets_for(None):
                if preset.stem == str(stem):
                    self.effect_scale.setValue(float(preset.scale))
                    break

    def _refresh_effects(self, *_args) -> None:
        current = self.effect.currentData()
        self.effect.blockSignals(True)
        try:
            self.effect.clear()
            for stem in self._controller.effect_stems(self.effect_filter.text()):
                self.effect.addItem(stem, stem)
            if current is not None:
                index = self.effect.findData(current)
                if index >= 0:
                    self.effect.setCurrentIndex(index)
        finally:
            self.effect.blockSignals(False)
        self._effect_changed(self.effect.currentIndex())

    def _effect_changed(self, _index: int) -> None:
        stem = self.effect.currentData() if self.use_effect.isChecked() else None
        self._controller.draft.effect_stem = str(stem or "")
        self._controller.plan = None
        self._refresh_facts()

    def choose_effect(self, stem: str) -> None:
        """Select an effect by stem (used by tests and by callers with a known effect)."""

        self.use_effect.setChecked(True)
        self.effect_filter.setText(str(stem))
        index = self.effect.findData(str(stem))
        if index >= 0:
            self.effect.setCurrentIndex(index)
        self._effect_changed(index)


__all__ = ["MAX_PERKS", "PerksPanel"]
