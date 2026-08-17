"""New Item Studio, panel 5: perks (the Abyss Gear socket items the item carries) and a weapon effect.

Perks are the item row's default socket items: the tooltip's "Insight I", "Malicebane I"
lines. The panel offers every item some shipped row embeds, by English name, and holds
up to eight of them (no shipped item carries more than four). An effect is one of the
shipped effect binaries, grafted into the item's own prefabs as an EffectComponent; the
game has not been seen drawing one yet, and the panel says so.
"""

from __future__ import annotations

from typing import List, Optional

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QVBoxLayout,
)

from cdmw.ui.new_item.controller import NewItemStudioController

MAX_PERKS = 8
SUGGESTED_EFFECT_TERMS = ("fire", "lightning", "ice", "aura", "sword", "weapon")


class PerksPanel(QGroupBox):
    def __init__(self, controller: NewItemStudioController, parent=None) -> None:
        super().__init__("5. Perks and effect", parent)
        self._controller = controller
        layout = QVBoxLayout(self)

        perks = QGroupBox("Perks (socket items embedded by default)")
        perks_layout = QVBoxLayout(perks)
        self.template_perks = QLabel("The clone carries the template's own perks.")
        self.template_perks.setWordWrap(True)
        perks_layout.addWidget(self.template_perks)
        self.own_perks = QCheckBox("Choose the perks myself (up to eight; no shipped item carries more than four)")
        self.own_perks.toggled.connect(self._own_perks_changed)
        perks_layout.addWidget(self.own_perks)
        chosen_row = QHBoxLayout()
        self.chosen = QListWidget()
        self.chosen.setMaximumHeight(110)
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
        self.perk_filter.setPlaceholderText("Filter perks by name (Insight, Destruction, Malicebane...)")
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

        effect = QGroupBox("Weapon effect")
        effect_layout = QVBoxLayout(effect)
        self.use_effect = QCheckBox("Give the weapon a persistent effect (grafted into its own prefabs; unproven in game)")
        self.use_effect.toggled.connect(self._use_effect_changed)
        effect_layout.addWidget(self.use_effect)
        effect_row = QHBoxLayout()
        self.effect_filter = QLineEdit()
        self.effect_filter.setPlaceholderText("Filter effects (fire, lightning, aura, sword...)")
        self.effect_filter.textChanged.connect(self._refresh_effects)
        effect_row.addWidget(self.effect_filter, 1)
        self.effect = QComboBox()
        self.effect.setMinimumWidth(260)
        self.effect.currentIndexChanged.connect(self._effect_changed)
        effect_row.addWidget(self.effect, 2)
        effect_layout.addLayout(effect_row)
        self.effect_note = QLabel("The effect is drawn at the weapon's own origin, as the shipped thrown lightning spear draws its aura. Effects made for other weapons may sit or scale oddly; try a few.")
        self.effect_note.setWordWrap(True)
        effect_layout.addWidget(self.effect_note)
        layout.addWidget(effect)

        self._own_perks_changed(False)
        self._use_effect_changed(False)
        controller.snapshot_ready.connect(self._refresh_all)
        controller.template_changed.connect(self._template_changed)
        self._refresh_all()

    # ------------------------------------------------------------------ perks

    def _refresh_all(self) -> None:
        self._refresh_catalogue()
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
        for widget in (self.chosen, self.remove_button, self.reset_button, self.perk_filter, self.catalogue, self.add_button):
            widget.setEnabled(bool(checked))
        self._controller.plan = None
        self._refresh_chosen()

    def _refresh_chosen(self) -> None:
        self.chosen.clear()
        for key in list(self._controller.draft.socket_items or ()):
            item = QListWidgetItem(self._controller.perk_label(key))
            item.setData(Qt.UserRole, int(key))
            self.chosen.addItem(item)

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
        for widget in (self.effect_filter, self.effect):
            widget.setEnabled(bool(checked))
        self._effect_changed(self.effect.currentIndex())

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

    def choose_effect(self, stem: str) -> None:
        """Select an effect by stem (used by tests and by callers with a known effect)."""

        self.use_effect.setChecked(True)
        self.effect_filter.setText(str(stem))
        index = self.effect.findData(str(stem))
        if index >= 0:
            self.effect.setCurrentIndex(index)
        self._effect_changed(index)


__all__ = ["MAX_PERKS", "PerksPanel"]
