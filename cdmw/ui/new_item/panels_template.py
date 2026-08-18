"""New Item Studio, panel 1: choose the template item."""

from __future__ import annotations

from typing import Optional

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QGroupBox, QHBoxLayout, QLabel, QLineEdit, QListWidget, QListWidgetItem, QVBoxLayout

from cdmw.ui.new_item.controller import NewItemStudioController


class TemplatePanel(QGroupBox):
    """A search box over equipment items; picking one fixes the class the clone inherits."""

    def __init__(self, controller: NewItemStudioController, parent=None) -> None:
        super().__init__("1. Template", parent)
        self._controller = controller
        self._syncing = False
        layout = QVBoxLayout(self)
        intro = QLabel(
            "The template fixes what the new item is: its equip type, item type, sockets, animations, "
            "sheath and stat shape. Only equipment can be cloned."
        )
        intro.setWordWrap(True)
        layout.addWidget(intro)
        row = QHBoxLayout()
        row.addWidget(QLabel("Find:"))
        self.filter_edit = QLineEdit()
        self.filter_edit.setPlaceholderText("Internal name or item key, e.g. Ziane_OneHandSword or 1001295")
        self.filter_edit.textChanged.connect(self._refresh_matches)
        row.addWidget(self.filter_edit, 1)
        layout.addLayout(row)
        self.matches = QListWidget()
        self.matches.setMinimumHeight(160)
        self.matches.currentItemChanged.connect(self._pick)
        layout.addWidget(self.matches)
        self.summary = QLabel("Choose a template item.")
        self.summary.setWordWrap(True)
        self.summary.setTextInteractionFlags(Qt.TextSelectableByMouse)
        layout.addWidget(self.summary)
        controller.snapshot_ready.connect(self._refresh_matches)
        controller.template_changed.connect(self._show_template)

    def _refresh_matches(self, *_args) -> None:
        self._syncing = True
        try:
            self.matches.clear()
            for key, name, equip in self._controller.template_options(self.filter_edit.text()):
                item = QListWidgetItem(f"{name}  ({key}, {equip})")
                item.setData(Qt.UserRole, key)
                self.matches.addItem(item)
                if key == self._controller.draft.template_key:
                    self.matches.setCurrentItem(item)
        finally:
            self._syncing = False

    def _pick(self, current: Optional[QListWidgetItem], _previous=None) -> None:
        if self._syncing or current is None:
            return
        key = current.data(Qt.UserRole)
        if isinstance(key, int) and key != self._controller.draft.template_key:
            self._controller.set_template(key)

    def prefill(self, template_key: int) -> None:
        self.filter_edit.setText(str(template_key))
        self._controller.set_template(template_key)
        self._refresh_matches()

    def _show_template(self, key: object) -> None:
        if key is None:
            self.summary.setText("Choose a template item.")
            return
        self.summary.setText("\n".join(self._controller.template_summary()))


__all__ = ["TemplatePanel"]
