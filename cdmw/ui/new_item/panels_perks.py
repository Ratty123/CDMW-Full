"""New Item Studio, panel 5: gameplay perks and staged visual effects.

Perks are the item row's default socket items: the tooltip's "Insight I", "Malicebane I"
lines. The panel offers every gem the archives know, by English name, and holds up to
eight of them (no shipped item carries more than four). The gems are of two kinds: the
`Item_Stat_*` ones (Destruction, Swift, the resistances) and the `Item_Skill_*` ones,
which grant Abyss skills, the elemental abilities among them (Volcanic Eruption, Frost
Hail, Orbs of Lightning, Storm Fang, Groundsurge, Tempest of Destruction, Wind Slash...);
shipped items embed both kinds by default (Crow Storm on the White Crow witch's war
hammer, Storm Fang on Endour's helm), so an elemental ability is a perk away. A visual
effect is one of the shipped effect binaries, structurally preflighted and grafted into
every compatible prefab the new item owns.
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
    QTabWidget,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from cdmw.ui.new_item.controller import NewItemStudioController
from cdmw.ui.new_item.effect_workspace import GuidedEffectsWorkspace
from cdmw.ui.new_item.ui_kit import DetailsToggle, NoteLabel, WARN, intro_label

MAX_PERKS = 8
SAFE_PERKS = 4


class PerksPanel(QGroupBox):
    def __init__(self, controller: NewItemStudioController, parent=None) -> None:
        super().__init__("5. Perks & Effects", parent)
        self._controller = controller
        self._syncing_effect = False
        self._syncing_catalogue = False
        layout = QVBoxLayout(self)
        self._legacy_intro = intro_label(
            "Gameplay perks change the item's built-in abilities or stats. Visual effects change appearance only; "
            "they do not add fire, ice, lightning or other attack damage."
        )
        layout.addWidget(self._legacy_intro)

        perks = self._build_perks_section()
        layout.addWidget(perks)

        effect = self._build_effect_section()
        layout.addWidget(effect)

        self.custom_perks.setVisible(False)
        self._own_perks_changed(False)
        self._use_effect_changed(False)

        self._install_workspace(layout, perks, effect)

        controller.snapshot_ready.connect(self._refresh_all)
        controller.effect_catalogue_ready.connect(self._catalogue_ready)
        controller.template_changed.connect(self._template_changed)
        self._refresh_all()

    def _build_perks_section(self) -> QGroupBox:
        perks = QGroupBox("Gameplay perks and abilities")
        perks_layout = QVBoxLayout(perks)
        self.template_perks = QLabel("The clone carries the template's own perks.")
        self.template_perks.setWordWrap(True)
        perks_layout.addWidget(self.template_perks)
        self.own_perks = QCheckBox("Customize perks and abilities")
        self.own_perks.setToolTip("Off keeps the template's exact perk list. On starts from that list and lets you add or remove entries.")
        self.own_perks.toggled.connect(self._own_perks_changed)
        perks_layout.addWidget(self.own_perks)

        self.custom_perks = QWidget()
        custom_layout = QVBoxLayout(self.custom_perks)
        custom_layout.setContentsMargins(0, 0, 0, 0)
        custom_layout.setSpacing(6)
        self.perk_count = QLabel("")
        self.perk_count.setWordWrap(True)
        columns = QHBoxLayout()
        columns.setSpacing(8)
        available_column = QVBoxLayout()
        available_column.setSpacing(4)
        available_column.addWidget(QLabel("Available perks"))
        self.perk_filter = QLineEdit()
        self.perk_filter.setPlaceholderText("Search perks or internal IDs")
        self.perk_filter.setClearButtonEnabled(True)
        self.perk_filter.textChanged.connect(self._refresh_catalogue)
        available_column.addWidget(self.perk_filter)
        self.perk_results = QListWidget()
        self.perk_results.setObjectName("new_item_perk_results")
        self.perk_results.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.perk_results.setTextElideMode(Qt.TextElideMode.ElideRight)
        self.perk_results.setFixedHeight(210)
        self.perk_results.currentItemChanged.connect(self._available_perk_changed)
        self.perk_results.itemDoubleClicked.connect(
            lambda _item, _column=0: self._add_selected()
        )
        available_column.addWidget(self.perk_results, 1)
        self.add_button = QPushButton("Add selected perk")
        self.add_button.clicked.connect(self._add_selected)
        available_column.addWidget(self.add_button)
        columns.addLayout(available_column, 1)

        selected_column = QVBoxLayout()
        selected_column.setSpacing(4)
        selected_column.addWidget(QLabel("Selected perks"))
        selected_column.addWidget(self.perk_count)
        self.chosen = QListWidget()
        self.chosen.currentItemChanged.connect(self._chosen_perk_changed)
        selected_column.addWidget(self.chosen, 1)
        buttons = QHBoxLayout()
        self.remove_button = QPushButton("Remove")
        self.remove_button.clicked.connect(self._remove_selected)
        buttons.addWidget(self.remove_button)
        self.reset_button = QPushButton("Keep template perks")
        self.reset_button.clicked.connect(self._reset_to_template)
        buttons.addWidget(self.reset_button)
        buttons.addStretch(1)
        selected_column.addLayout(buttons)
        columns.addLayout(selected_column, 1)
        custom_layout.addLayout(columns, 1)

        # Compatibility data adapter for older integrations. It mirrors the visible list
        # but never opens a popup; the inline list is the sole presented catalogue.
        self.catalogue = QComboBox(self.custom_perks)
        self.catalogue.setVisible(False)
        self.catalogue.currentIndexChanged.connect(self._catalogue_perk_changed)
        self.perk_details = NoteLabel("")
        custom_layout.addWidget(self.perk_details)
        self.experimental_perks = QCheckBox("Experimental: allow five to eight perks")
        self.experimental_perks.setToolTip("No shipped item carries more than four perks. The row format accepts eight, but five to eight remain unproven in game.")
        self.experimental_perks.toggled.connect(self._perk_limit_changed)
        custom_layout.addWidget(self.experimental_perks)
        perks_layout.addWidget(self.custom_perks)
        return perks

    def _build_effect_section(self) -> QGroupBox:
        effect = QGroupBox("Visual effect (optional)")
        effect_layout = QVBoxLayout(effect)
        self.visual_only = intro_label("Visual only — this does not change attack damage or apply an elemental status.")
        effect_layout.addWidget(self.visual_only)
        self.effect_support = NoteLabel("")
        effect_layout.addWidget(self.effect_support)
        self.use_effect = QCheckBox("Add a visual effect to the item")
        self.use_effect.setToolTip("The effect is grafted only into compatible prefabs the new item owns. Shipped shared prefabs stay untouched.")
        self.use_effect.toggled.connect(self._use_effect_changed)
        effect_layout.addWidget(self.use_effect)
        self.effect_primary = self._build_effect_primary()
        effect_layout.addWidget(self.effect_primary)
        self.effect_advanced = self._build_effect_advanced()
        self.effect_advanced.setVisible(False)
        effect_layout.addWidget(self.effect_advanced)
        #: Everything below the opt-in is hidden while it is off. Advanced controls remain
        #: folded until separately requested.
        self._effect_rows = (self.effect_primary,)
        for row in self._effect_rows:
            row.setVisible(False)
        return effect

    def _build_effect_primary(self) -> QWidget:
        self.effect_primary = QWidget()
        primary_layout = QVBoxLayout(self.effect_primary)
        primary_layout.setContentsMargins(0, 0, 0, 0)
        choose = QFormLayout()
        choose.setFieldGrowthPolicy(QFormLayout.AllNonFixedFieldsGrow)
        self.effect_preset = QComboBox()
        self.effect_preset.setToolTip("Compatibility control retained for older integrations; use the Effect Library in the visible workspace.")
        self.effect_preset.currentIndexChanged.connect(self._preset_chosen)
        choose.addRow("Visual:", self.effect_preset)
        primary_layout.addLayout(choose)
        self.effect_selection = NoteLabel("")
        primary_layout.addWidget(self.effect_selection)
        self.place_button = QPushButton("Place on item in viewport...")
        self.place_button.setToolTip("Open the resident viewport to move and scale the selected visual on the item.")
        self.place_button.clicked.connect(self._place_in_viewport)
        primary_layout.addWidget(self.place_button)
        self.effect_advanced_toggle = QToolButton()
        self.effect_advanced_toggle.setText("Advanced")
        self.effect_advanced_toggle.setCheckable(True)
        self.effect_advanced_toggle.setToolButtonStyle(Qt.ToolButtonTextBesideIcon)
        self.effect_advanced_toggle.setArrowType(Qt.RightArrow)
        self.effect_advanced_toggle.setAutoRaise(True)
        self.effect_advanced_toggle.toggled.connect(self._toggle_effect_advanced)
        primary_layout.addWidget(self.effect_advanced_toggle)
        return self.effect_primary

    def _build_effect_advanced(self) -> QGroupBox:
        self.effect_advanced = QGroupBox("Advanced effect browser and tuning")
        advanced_layout = QVBoxLayout(self.effect_advanced)
        advanced_warning = NoteLabel("")
        advanced_warning.set_note(
            "Recolouring and particle tuning require a fully decoded effect. Verify the final visual fit in game.",
            WARN,
        )
        advanced_layout.addWidget(advanced_warning)

        browser_form = QFormLayout()
        self.effect_filter = QLineEdit()
        self.effect_filter.setPlaceholderText("Search effect files")
        self.effect_filter.textChanged.connect(self._refresh_effects)
        browser_form.addRow("Search:", self.effect_filter)
        self.effect = QComboBox()
        self.effect.currentIndexChanged.connect(self._effect_changed)
        browser_form.addRow("Effect file:", self.effect)
        self.index_button = QPushButton("Build optional effect index...")
        self.index_button.setToolTip(
            "Read every shipped effect once and keep the index on disk: the filter then also matches the emitters, "
            "textures and meshes an effect is made of, and the line below says what the chosen effect draws and how big it is."
        )
        self.index_button.clicked.connect(self._index_effects)
        browser_form.addRow("Optional catalogue:", self.index_button)
        advanced_layout.addLayout(browser_form)
        self.effect_facts = QLabel("")
        self.effect_facts.setObjectName("new_item_intro")
        self.effect_facts.setWordWrap(True)
        self.effect_facts.setTextInteractionFlags(Qt.TextSelectableByMouse)
        advanced_layout.addWidget(self.effect_facts)

        self.placement_holder = QWidget()
        placement_form = QFormLayout(self.placement_holder)
        self.effect_scale = QDoubleSpinBox()
        self.effect_scale.setRange(0.01, 10.0)
        self.effect_scale.setSingleStep(0.1)
        self.effect_scale.setDecimals(2)
        self.effect_scale.setValue(1.0)
        self.effect_scale.setToolTip("A uniform scale on the grafted effect. Use Fit to item as a neutral starting point for effects authored at a different size.")
        self.effect_scale.valueChanged.connect(self._effect_transform_changed)
        placement_form.addRow("Visual scale:", self.effect_scale)
        self.effect_offset = []
        for axis in ("X", "Y", "Z"):
            box = QDoubleSpinBox()
            box.setRange(-5.0, 5.0)
            box.setSingleStep(0.05)
            box.setDecimals(2)
            box.setValue(0.0)
            box.setToolTip("Moves the effect along the item's own axes, in metres, from the item's origin.")
            box.valueChanged.connect(self._effect_transform_changed)
            placement_form.addRow(f"Offset {axis} (m):", box)
            self.effect_offset.append(box)
        self.effect_rotation = []
        for axis in ("X", "Y", "Z"):
            box = QDoubleSpinBox()
            box.setRange(-180.0, 180.0)
            box.setSingleStep(5.0)
            box.setDecimals(1)
            box.setWrapping(True)
            box.setValue(0.0)
            box.setToolTip("Turns the effect about the item's own axes, in degrees; x, then y, then z. The viewport's Rotate tool sets the same numbers.")
            box.valueChanged.connect(self._effect_transform_changed)
            placement_form.addRow(f"Rotation {axis} (°):", box)
            self.effect_rotation.append(box)
        advanced_layout.addWidget(self.placement_holder)

        self.look_holder = QWidget()
        look_form = QFormLayout(self.look_holder)
        color_row = QHBoxLayout()
        self.color_button = QPushButton("Colour: as shipped")
        self.color_button.setToolTip("Recolour a clone of the effect and its emitters. In-game colour behavior remains unproven.")
        self.color_button.clicked.connect(self._pick_color)
        color_row.addWidget(self.color_button)
        self.color_reset = QPushButton("Drop the colour")
        self.color_reset.setToolTip("Back to the shipped colour.")
        self.color_reset.clicked.connect(self._reset_color)
        color_row.addWidget(self.color_reset)
        color_row.addStretch(1)
        look_form.addRow("Colour:", color_row)
        self.look_factors: dict[str, QDoubleSpinBox] = {}
        for key, label, tip in (
            ("intensity", "Brightness multiplier:", "Multiplies the emitters' emissive brightness (and the temperature ramp's brightness)."),
            ("size", "Particle-size multiplier:", "Multiplies the particle scale (and the effect's bounding boxes)."),
            ("rate", "Spawn-rate multiplier:", "Multiplies the spawn counts and the particle cap."),
            ("lifetime", "Lifetime multiplier:", "Multiplies the particle lifetimes."),
        ):
            box = QDoubleSpinBox()
            box.setRange(0.05, 20.0)
            box.setDecimals(2)
            box.setSingleStep(0.1)
            box.setValue(1.0)
            box.setToolTip(tip)
            box.valueChanged.connect(self._look_changed)
            look_form.addRow(label, box)
            self.look_factors[key] = box
        advanced_layout.addWidget(self.look_holder)
        self.effect_reset_button = QPushButton("Restore effect defaults")
        self.effect_reset_button.clicked.connect(self._reset_effect_tuning)
        advanced_layout.addWidget(self.effect_reset_button)
        self.effect_note = DetailsToggle(
            "The effect starts at the item's origin. Origin, Center, End and an exposed Trail Socket provide asset-neutral anchors; "
            "scale, position and rotation refine the placement, and the viewport shows the effect's bounds and approximate particles. A colour edit recolours the "
            "effect's data on a clone; whether each colour or particle field changes the in-game result is experimental.",
            title="How the effect and its look work",
        )
        advanced_layout.addWidget(self.effect_note)
        return self.effect_advanced

    def _install_workspace(self, layout: QVBoxLayout, perks: QGroupBox, effect: QGroupBox) -> None:
        # Step 5 is one full-height page with two real workspaces. The legacy effect
        # widgets stay alive as compatibility objects for existing callers, but are no
        # longer presented; the resident staged workspace owns the visible Effects tab.
        self.tabs = QTabWidget()
        self.tabs.setObjectName("new_item_perks_effects_tabs")
        self.perks_page = QWidget()
        perks_page_layout = QVBoxLayout(self.perks_page)
        perks_page_layout.setContentsMargins(8, 6, 8, 6)
        perks_page_layout.setSpacing(6)
        perks_page_layout.addWidget(perks)
        perks_page_layout.addStretch(1)
        self.effects_workspace = GuidedEffectsWorkspace(self._controller)
        self.effects_page = self.effects_workspace
        self.tabs.addTab(self.perks_page, "Perks")
        self.tabs.addTab(self.effects_page, "Effects")
        self.tabs.setCurrentWidget(self.effects_page)
        self.own_perks.toggled.connect(self._show_perks_when_customizing)
        while layout.count():
            layout.takeAt(0)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self.tabs, 1)
        self._legacy_intro.setVisible(False)
        effect.setVisible(False)

    # ------------------------------------------------------------------ perks

    def _show_perks_when_customizing(self, checked: bool) -> None:
        if checked:
            self.tabs.setCurrentWidget(self.perks_page)

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
        self._refresh_effect_support()

    def _own_perks_changed(self, checked: bool) -> None:
        draft = self._controller.draft
        if checked and draft.socket_items is None:
            draft.socket_items = list(self._controller.template_socket_items())
        elif not checked:
            draft.socket_items = None
        self.custom_perks.setVisible(bool(checked))
        self._controller.invalidate_plan()
        self._refresh_chosen()

    def _refresh_chosen(self) -> None:
        current_key = self.chosen.currentItem().data(Qt.UserRole) if self.chosen.currentItem() is not None else None
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
        if current_key is not None:
            for index in range(self.chosen.count()):
                if self.chosen.item(index).data(Qt.UserRole) == current_key:
                    self.chosen.setCurrentRow(index)
                    break
        if self.chosen.currentRow() < 0 and self.chosen.count():
            self.chosen.setCurrentRow(0)
        count = self.chosen.count()
        safe_note = "Shipped items use at most four." if count <= SAFE_PERKS else "Five to eight perks are experimental."
        self.perk_count.setText(f"Selected: {count}/{MAX_PERKS}. {safe_note} Duplicate stacking is unverified.")
        selected_item = self.chosen.currentItem()
        selected_key = selected_item.data(Qt.UserRole) if selected_item is not None else None
        self._refresh_perk_details(int(selected_key) if isinstance(selected_key, int) else None)
        self._update_add_enabled()

    def _refresh_catalogue(self, *_args) -> None:
        current_item = self.perk_results.currentItem()
        current = current_item.data(Qt.ItemDataRole.UserRole) if current_item is not None else self.catalogue.currentData()
        entries = tuple(self._controller.perk_catalogue(self.perk_filter.text()))
        self._syncing_catalogue = True
        self.perk_results.blockSignals(True)
        self.catalogue.blockSignals(True)
        try:
            self.perk_results.clear()
            self.catalogue.clear()
            selected_row = -1
            for row, (key, label) in enumerate(entries):
                item = QListWidgetItem(label)
                item.setData(Qt.ItemDataRole.UserRole, key)
                item.setToolTip(self._controller.perk_details(int(key)))
                self.perk_results.addItem(item)
                self.catalogue.addItem(label, key)
                if key == current:
                    selected_row = row
            if selected_row < 0 and entries:
                selected_row = 0
            self.perk_results.setCurrentRow(selected_row)
            if selected_row >= 0:
                self.catalogue.setCurrentIndex(selected_row)
        finally:
            self.catalogue.blockSignals(False)
            self.perk_results.blockSignals(False)
            self._syncing_catalogue = False
        self._available_perk_changed(self.perk_results.currentItem(), None)

    def _catalogue_perk_changed(self, _index: int) -> None:
        if self._syncing_catalogue:
            return
        key = self.catalogue.currentData()
        for row in range(self.perk_results.count()):
            if self.perk_results.item(row).data(Qt.ItemDataRole.UserRole) == key:
                self.perk_results.setCurrentRow(row)
                break
        self._refresh_perk_details(int(key) if isinstance(key, int) else None)
        self._update_add_enabled()

    def _available_perk_changed(self, current, _previous) -> None:
        key = current.data(Qt.ItemDataRole.UserRole) if current is not None else None
        if isinstance(key, int):
            index = self.catalogue.findData(key)
            if index >= 0 and self.catalogue.currentIndex() != index:
                self.catalogue.blockSignals(True)
                self.catalogue.setCurrentIndex(index)
                self.catalogue.blockSignals(False)
        self._refresh_perk_details(int(key) if isinstance(key, int) else None)
        self._update_add_enabled()

    def _chosen_perk_changed(self, current, _previous) -> None:
        key = current.data(Qt.UserRole) if current is not None else None
        self._refresh_perk_details(int(key) if isinstance(key, int) else None)

    def _refresh_perk_details(self, key: Optional[int] = None) -> None:
        if key is None:
            item = self.perk_results.currentItem()
            current = item.data(Qt.ItemDataRole.UserRole) if item is not None else self.catalogue.currentData()
            key = int(current) if isinstance(current, int) else None
        if key is None:
            self.perk_details.set_note("Choose a perk to see what the game calls it and whether shipped equipment uses it.", None)
            return
        text = self._controller.perk_details(int(key))
        selected_count = list(self._controller.draft.socket_items or ()).count(int(key))
        if selected_count > 1:
            text += f" Selected {selected_count} times; whether duplicates stack is unverified."
        self.perk_details.set_note(text, WARN if "experimental" in text.casefold() or selected_count > 1 else None)

    def _perk_limit_changed(self, _checked: bool) -> None:
        self._update_add_enabled()

    def _update_add_enabled(self) -> None:
        selected = len(self._controller.draft.socket_items or ())
        limit = MAX_PERKS if self.experimental_perks.isChecked() else SAFE_PERKS
        current = self.perk_results.currentItem()
        key = current.data(Qt.ItemDataRole.UserRole) if current is not None else self.catalogue.currentData()
        self.add_button.setEnabled(self.own_perks.isChecked() and isinstance(key, int) and selected < limit)

    def _add_selected(self) -> None:
        current = self.perk_results.currentItem()
        key = current.data(Qt.ItemDataRole.UserRole) if current is not None else self.catalogue.currentData()
        draft = self._controller.draft
        if not isinstance(key, int) or draft.socket_items is None:
            return
        limit = MAX_PERKS if self.experimental_perks.isChecked() else SAFE_PERKS
        if len(draft.socket_items) >= limit:
            message = f"Enable the experimental five-to-eight option to exceed {SAFE_PERKS} perks." if limit == SAFE_PERKS else f"An item carries at most {MAX_PERKS} perks."
            self._controller.status_message.emit(message, True)
            return
        draft.socket_items.append(int(key))
        self._controller.invalidate_plan()
        self._refresh_chosen()

    def _remove_selected(self) -> None:
        draft = self._controller.draft
        row = self.chosen.currentRow()
        if draft.socket_items is None or row < 0 or row >= len(draft.socket_items):
            return
        del draft.socket_items[row]
        self._controller.invalidate_plan()
        self._refresh_chosen()

    def _reset_to_template(self) -> None:
        self.own_perks.setChecked(False)

    # ------------------------------------------------------------------ effect

    def _use_effect_changed(self, checked: bool) -> None:
        if checked and not self.use_effect.isEnabled():
            self.use_effect.setChecked(False)
            return
        for row in self._effect_rows:
            row.setVisible(bool(checked))
        if not checked:
            self.effect_advanced_toggle.setChecked(False)
            self._syncing_effect = True
            try:
                self.effect_preset.setCurrentIndex(0)
                self.effect.setCurrentIndex(0)
            finally:
                self._syncing_effect = False
            self._controller.draft.effect_stem = ""
            self._reset_effect_tuning(invalidate=False)
            self._controller.invalidate_plan()
        else:
            # Opting in does not silently choose the first of thousands of files. The
            # The compatibility selector and advanced browser both start on an explicit placeholder.
            self._effect_changed(self.effect.currentIndex())
        self._refresh_effect_selection()

    def _toggle_effect_advanced(self, checked: bool) -> None:
        self.effect_advanced.setVisible(bool(checked) and self.use_effect.isChecked())
        self.effect_advanced_toggle.setArrowType(Qt.DownArrow if checked else Qt.RightArrow)

    def _effect_transform_changed(self, *_args) -> None:
        if self._syncing_effect:
            return
        draft = self._controller.draft
        draft.effect_scale = float(self.effect_scale.value())
        draft.effect_offset = tuple(float(box.value()) for box in self.effect_offset)
        draft.effect_rotation = tuple(float(box.value()) for box in self.effect_rotation)
        self._controller.invalidate_plan()
        self._refresh_facts()
        self._refresh_effect_selection()

    def _index_effects(self) -> None:
        self._controller.start_effect_index()

    def _look_changed(self, *_args) -> None:
        if self._syncing_effect:
            return
        draft = self._controller.draft
        draft.effect_intensity = float(self.look_factors["intensity"].value())
        draft.effect_size = float(self.look_factors["size"].value())
        draft.effect_rate = float(self.look_factors["rate"].value())
        draft.effect_lifetime = float(self.look_factors["lifetime"].value())
        self._controller.invalidate_plan()
        self._refresh_effect_selection()

    def _reset_effect_tuning(self, _checked: bool = False, *, scale: float = 1.0, invalidate: bool = True) -> None:
        self._syncing_effect = True
        try:
            self.effect_scale.setValue(float(scale))
            for box in self.effect_offset:
                box.setValue(0.0)
            for box in self.effect_rotation:
                box.setValue(0.0)
            for box in self.look_factors.values():
                box.setValue(1.0)
            draft = self._controller.draft
            draft.effect_scale = float(scale)
            draft.effect_offset = (0.0, 0.0, 0.0)
            draft.effect_rotation = (0.0, 0.0, 0.0)
            draft.effect_color = None
            draft.effect_intensity = 1.0
            draft.effect_size = 1.0
            draft.effect_rate = 1.0
            draft.effect_lifetime = 1.0
            self.color_button.setText("Colour: as shipped")
            self.color_button.setStyleSheet("")
        finally:
            self._syncing_effect = False
        if invalidate:
            self._controller.invalidate_plan()
        self._refresh_facts()
        self._refresh_effect_selection()

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
        self._controller.invalidate_plan()
        self._refresh_effect_selection()

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
            offset=tuple(float(box.value()) for box in self.effect_offset),
            rotation=tuple(float(box.value()) for box in self.effect_rotation),
            scale=float(self.effect_scale.value()), effect_label=stem,
            effect_preview=effect_preview, texture_reader=texture_reader,
            character_builder=self._controller.character_holding_the_item,
        )
        if dialog.exec() != QDialog.Accepted:
            return
        self.effect_scale.setValue(float(dialog.scale))
        for box, value in zip(self.effect_offset, dialog.offset):
            box.setValue(float(value))
        for box, value in zip(self.effect_rotation, dialog.rotation):
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
            self.effect_facts.setText("The optional index adds technical contents and approximate dimensions for this file.")
            return
        emitters = ", ".join(name.rsplit("/", 1)[-1] for name in facts.emitters) or "none named"
        textures = ", ".join(path.rsplit("/", 1)[-1] for path in facts.textures) or "none"
        meshes = ", ".join(path.rsplit("/", 1)[-1] for path in facts.meshes)
        width, height, depth = facts.size
        scale = float(self.effect_scale.value())
        loop = "loops" if facts.loops else f"plays once ({facts.max_spawnable_time:.1f} s)"
        text = (
            f"{facts.name or facts.stem}\n"
            f"Behavior: {loop}. Approximate box at scale {scale:.2f}: "
            f"{width * scale:.2f} × {height * scale:.2f} × {depth * scale:.2f} m.\n"
            f"Technical contents: emitters {emitters}; textures {textures}"
        )
        if meshes:
            text += f"; meshes {meshes}"
        if facts.has_lights:
            text += "; carries lights"
        if facts.walk_note:
            text += f"; the file did not decode fully ({facts.walk_note})"
        self.effect_facts.setText(text)

    def _refresh_presets(self) -> None:
        self.effect_preset.blockSignals(True)
        try:
            self.effect_preset.clear()
            self.effect_preset.addItem("", "")
        finally:
            self.effect_preset.blockSignals(False)

    def _preset_chosen(self, index: int) -> None:
        return

    def _refresh_effects(self, *_args) -> None:
        current = str(self._controller.draft.effect_stem or "")
        matches = list(self._controller.effect_stems(self.effect_filter.text()))
        if current and current not in matches:
            matches.insert(0, current)
        self.effect.blockSignals(True)
        try:
            self.effect.clear()
            self.effect.addItem("Choose an effect file...", "")
            for stem in matches:
                self.effect.addItem(stem, stem)
            if current:
                index = self.effect.findData(current)
                if index >= 0:
                    self.effect.setCurrentIndex(index)
        finally:
            self.effect.blockSignals(False)
        self._refresh_facts()

    def _effect_changed(self, _index: int) -> None:
        if self._syncing_effect:
            return
        stem = str(self.effect.currentData() or "") if self.use_effect.isChecked() else ""
        draft = self._controller.draft
        if stem == draft.effect_stem:
            self._refresh_facts()
            self._refresh_effect_selection()
            return
        draft.effect_stem = stem
        self._reset_effect_tuning(invalidate=False)
        self._sync_preset_to_effect()
        self._controller.invalidate_plan()
        self._refresh_facts()
        self._refresh_effect_selection()

    def choose_effect(self, stem: str, *, scale: float = 1.0) -> None:
        """Select an effect by stem (used by tests and by callers with a known effect)."""

        workspace = getattr(self, "effects_workspace", None)
        if workspace is not None:
            workspace.choose_effect(stem, scale=scale)
            self.tabs.setCurrentWidget(self.effects_page)
            return

        clean = str(stem or "").strip()
        if not clean:
            return
        self.use_effect.setChecked(True)
        self._syncing_effect = True
        try:
            self.effect_filter.setText(clean)
            index = self.effect.findData(clean)
            if index >= 0:
                self.effect.setCurrentIndex(index)
            self._controller.draft.effect_stem = clean
        finally:
            self._syncing_effect = False
        self._reset_effect_tuning(scale=float(scale), invalidate=False)
        self._sync_preset_to_effect()
        self._controller.invalidate_plan()
        self._refresh_facts()
        self._refresh_effect_selection()

    def _sync_preset_to_effect(self) -> None:
        self._syncing_effect = True
        try:
            self.effect_preset.setCurrentIndex(0)
        finally:
            self._syncing_effect = False

    def _refresh_effect_selection(self) -> None:
        stem = str(self._controller.draft.effect_stem or "")
        if not self.use_effect.isChecked():
            self.effect_selection.set_note("No visual effect. Gameplay damage is unchanged.", None)
            return
        if not stem:
            self.effect_selection.set_note("Choose an effect. Nothing is added until one is selected and applied.", WARN)
            return
        draft = self._controller.draft
        customized = bool(
            draft.effect_color is not None
            or draft.effect_scale != 1.0
            or draft.effect_offset != (0.0, 0.0, 0.0)
            or any(value != 1.0 for value in (draft.effect_intensity, draft.effect_size, draft.effect_rate, draft.effect_lifetime))
        )
        suffix = " Advanced tuning differs from its starting values." if customized else " Using its starting values."
        self.effect_selection.set_note(f"Selected visual: {stem}. Visual only; attack damage is unchanged.{suffix}", WARN if customized else None)

    def _refresh_effect_support(self) -> None:
        snapshot = self._controller.snapshot
        key = self._controller.draft.template_key
        if snapshot is None or key is None:
            supported = False
            text = "Choose a template before adding a visual effect."
        else:
            row = snapshot.row(int(key))
            equip = snapshot.equip_type_name(row) or "Unknown equipment type"
            candidate = self._controller.draft.effect_stem
            if not candidate:
                candidate = next(iter(self._controller.effect_stems("", limit=1)), "")
            compatibility = self._controller.effect_target_compatibility(candidate) if candidate else None
            supported = bool(compatibility is not None and compatibility.supported)
            text = compatibility.message if compatibility is not None else f"{equip}: no effect target could be checked."
        self.use_effect.setEnabled(supported)
        self.effect_support.set_note(text, None if supported else WARN)
        self._refresh_effect_selection()

    def perks_summary(self) -> tuple[str, bool]:
        selected = self._controller.draft.socket_items
        template = tuple(self._controller.template_socket_items())
        if selected is None or tuple(selected) == template:
            return f"Perks: template list ({len(template)})", False
        return f"Perks: {len(selected)} custom", True

    def effect_summary(self) -> tuple[str, bool]:
        stem = str(self._controller.draft.effect_stem or "")
        if not stem:
            return "Visual effect: none", False
        return f"Visual effect: {stem} (visual only)", True

    def has_staged_effect_changes(self) -> bool:
        return self.effects_workspace.has_staged_changes()

    def apply_staged_effect(self) -> bool:
        return self.effects_workspace.apply_staged()

    def discard_staged_effect(self) -> None:
        self.effects_workspace.discard_staged()

    def _placement_dialogs(self):
        from cdmw.ui.new_item.effect_placement_dialog import EffectPlacementDialog

        return tuple(self.findChildren(EffectPlacementDialog))

    def iter_shutdown_workers(self):
        workers = list(self.effects_workspace.iter_shutdown_workers())
        for dialog in self._placement_dialogs():
            workers.extend(dialog.iter_shutdown_workers())
        return tuple(workers)

    def request_shutdown(self) -> None:
        self.effects_workspace.request_shutdown()
        for dialog in self._placement_dialogs():
            dialog.request_shutdown()


__all__ = ["MAX_PERKS", "PerksPanel"]
