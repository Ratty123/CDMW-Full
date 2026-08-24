"""New Item Studio, panel 1: choose the template item."""

from __future__ import annotations

from typing import Optional

from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import QGroupBox, QHBoxLayout, QLabel, QLineEdit, QListWidget, QListWidgetItem, QVBoxLayout

from cdmw.ui.new_item.controller import NewItemStudioController
from cdmw.ui.new_item.ui_kit import intro_label

#: How long the list waits before it takes a row as chosen. Long enough that arrow-keying
#: through the list passes rows without rebuilding five steps at each one, short enough
#: that a click reads as instant.
_SETTLE_MS = 180


class TemplatePanel(QGroupBox):
    """A search box over equipment items; picking one fixes the class the clone inherits."""

    def __init__(self, controller: NewItemStudioController, parent=None) -> None:
        super().__init__("1. Template", parent)
        self._controller = controller
        self._syncing = False
        layout = QVBoxLayout(self)
        layout.addWidget(intro_label("Every new item is a copy of a shipped one: the template sets its slot, type, sockets, animations and any optional sheathed variant; everything after changes the copy. Equipment only."))
        row = QHBoxLayout()
        row.addWidget(QLabel("Find:"))
        self.filter_edit = QLineEdit()
        self.filter_edit.setPlaceholderText("Internal name or item key")
        self.filter_edit.textChanged.connect(self._refresh_matches)
        row.addWidget(self.filter_edit, 1)
        layout.addLayout(row)
        self.matches = QListWidget()
        self.matches.setMinimumHeight(160)
        self.matches.currentItemChanged.connect(self._pick)
        # Choosing a template rebuilds five steps, which is ~100 ms of work that has to
        # happen; arrow-keying down the list asked for it once per row it passed through.
        # The list still moves at once (Qt owns that); the work waits for the reader to
        # settle on one, and a click is indistinguishable from settling immediately.
        self._pick_timer = QTimer(self)
        self._pick_timer.setSingleShot(True)
        self._pick_timer.setInterval(_SETTLE_MS)
        self._pick_timer.timeout.connect(self._apply_pick)
        self._pending_key: Optional[int] = None
        layout.addWidget(self.matches, 1)
        chosen = QGroupBox("The chosen template")
        chosen_layout = QVBoxLayout(chosen)
        self.summary = QLabel("Choose a template item.")
        self.summary.setWordWrap(True)
        self.summary.setTextInteractionFlags(Qt.TextSelectableByMouse)
        chosen_layout.addWidget(self.summary)
        layout.addWidget(chosen)
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
            self._pending_key = key
            self._pick_timer.start()

    def _apply_pick(self) -> None:
        """The row the reader stopped on, once they have stopped on it."""

        key, self._pending_key = self._pending_key, None
        if key is not None and key != self._controller.draft.template_key:
            self._controller.set_template(key)

    def apply_pending_pick(self) -> None:
        """Take the pending row now: leaving the step must not leave it unchosen."""

        if self._pick_timer.isActive():
            self._pick_timer.stop()
            self._apply_pick()

    def prefill(self, template_key: int) -> None:
        self._pick_timer.stop()
        self._pending_key = None
        self.filter_edit.setText(str(template_key))
        self._controller.set_template(template_key)
        self._refresh_matches()

    def _show_template(self, key: object) -> None:
        if key is None:
            self.summary.setText("Choose a template item.")
            return
        self.summary.setText("\n".join(self._controller.template_summary()))


__all__ = ["TemplatePanel"]
