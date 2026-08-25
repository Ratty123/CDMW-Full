"""New Item Studio, panel 1: choose the template item."""

from __future__ import annotations

from typing import Optional

from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import (
    QAbstractItemView,
    QGroupBox,
    QHeaderView,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from cdmw.ui.new_item.controller import NewItemStudioController
from cdmw.ui.new_item.ui_kit import intro_label

#: How long keyboard row navigation waits before it takes a row as chosen. Long enough
#: that arrow-keying through the list passes rows without rebuilding five steps at each
#: one. An explicit mouse click commits immediately through ``_apply_clicked_pick``.
_SETTLE_MS = 180


class TemplatePanel(QGroupBox):
    """A search box over equipment items; picking one fixes the class the clone inherits."""

    def __init__(self, controller: NewItemStudioController, parent=None) -> None:
        super().__init__("1. Template", parent)
        self._controller = controller
        self._syncing = False
        layout = QVBoxLayout(self)
        layout.addWidget(intro_label("Every new item is a copy of a shipped one: the template sets its slot, type, sockets, animations and any optional sheathed variant; everything after changes the copy. Equipment only."))
        self.workspace_layout = QHBoxLayout()
        self.workspace_layout.setContentsMargins(0, 0, 0, 0)
        self.selection_column = QWidget(self)
        selection_layout = QVBoxLayout(self.selection_column)
        selection_layout.setContentsMargins(0, 0, 0, 0)
        row = QHBoxLayout()
        row.addWidget(QLabel("Find:"))
        self.filter_edit = QLineEdit()
        self.filter_edit.setPlaceholderText("Internal name or item key")
        self.filter_edit.textChanged.connect(self._refresh_matches)
        row.addWidget(self.filter_edit, 1)
        selection_layout.addLayout(row)
        self.matches = QTreeWidget()
        self.matches.setColumnCount(4)
        self.matches.setHeaderLabels(["Internal name:", "Item Name", "Key", "Type"])
        self.matches.setRootIsDecorated(False)
        self.matches.setUniformRowHeights(True)
        self.matches.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.matches.setAllColumnsShowFocus(True)
        header = self.matches.header()
        header.setStretchLastSection(False)
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(3, QHeaderView.ResizeMode.ResizeToContents)
        self.matches.setMinimumHeight(160)
        self.matches.currentItemChanged.connect(self._pick)
        self.matches.itemClicked.connect(self._apply_clicked_pick)
        # Choosing a template rebuilds five steps, which is ~100 ms of work that has to
        # happen; arrow-keying down the list asked for it once per row it passed through.
        # The list still moves at once (Qt owns that); navigation waits for the reader to
        # settle on one, while an explicit mouse click takes that row immediately.
        self._pick_timer = QTimer(self)
        self._pick_timer.setSingleShot(True)
        self._pick_timer.setInterval(_SETTLE_MS)
        self._pick_timer.timeout.connect(self._apply_pick)
        self._pending_key: Optional[int] = None
        selection_layout.addWidget(self.matches, 1)
        chosen = QGroupBox("The chosen template")
        chosen_layout = QVBoxLayout(chosen)
        self.summary = QLabel("Choose a template item.")
        self.summary.setWordWrap(True)
        self.summary.setTextInteractionFlags(Qt.TextSelectableByMouse)
        chosen_layout.addWidget(self.summary)
        selection_layout.addWidget(chosen)
        self.workspace_layout.addWidget(self.selection_column, 2)
        self.preview_group = QGroupBox("Preview")
        self.preview_group.setMinimumHeight(340)
        preview_layout = QVBoxLayout(self.preview_group)
        preview_note = QLabel(
            "Preview controls: left-drag orbits around the model; middle-drag, right-drag, or Shift+left-drag pans; "
            "mouse wheel zooms; Fit resets the view framing. These controls only move the preview camera/view."
        )
        preview_note.setObjectName("new_item_intro")
        preview_note.setWordWrap(True)
        preview_layout.addWidget(preview_note)
        self.preview_holder = QWidget(self.preview_group)
        self.preview_holder_layout = QVBoxLayout(self.preview_holder)
        self.preview_holder_layout.setContentsMargins(0, 0, 0, 0)
        preview_layout.addWidget(self.preview_holder, 1)
        self.preview_status = QLabel("")
        self.preview_status.setObjectName("new_item_intro")
        self.preview_status.setWordWrap(True)
        preview_layout.addWidget(self.preview_status)
        self.workspace_layout.addWidget(self.preview_group, 3)
        layout.addLayout(self.workspace_layout, 1)
        self._preview = None
        controller.snapshot_ready.connect(self._refresh_matches)
        controller.template_changed.connect(self._show_template)

    def mount_preview(self, preview: QWidget) -> None:
        """Keep the one resident item viewport under the selected template."""

        if self._preview is not preview:
            self._preview = preview
            preview.status_changed.connect(self.preview_status.setText)
        if preview.parentWidget() is not self.preview_holder:
            self.preview_holder_layout.addWidget(preview, 1)

    def _refresh_matches(self, *_args) -> None:
        self._syncing = True
        try:
            self.matches.clear()
            for key, internal_name, item_name, equip in self._controller.template_options(self.filter_edit.text()):
                item = QTreeWidgetItem([internal_name, item_name, str(key), equip])
                item.setData(0, Qt.UserRole, key)
                self.matches.addTopLevelItem(item)
                if key == self._controller.draft.template_key:
                    self.matches.setCurrentItem(item)
        finally:
            self._syncing = False

    def _pick(self, current: Optional[QTreeWidgetItem], _previous=None) -> None:
        if self._syncing or current is None:
            return
        key = current.data(0, Qt.UserRole)
        if isinstance(key, int) and key != self._controller.draft.template_key:
            self._pending_key = key
            self._pick_timer.start()

    def _apply_pick(self) -> None:
        """The row the reader stopped on, once they have stopped on it."""

        key, self._pending_key = self._pending_key, None
        if key is not None and key != self._controller.draft.template_key:
            self._controller.set_template(key)

    def _apply_clicked_pick(self, current: QTreeWidgetItem, _column: int = 0) -> None:
        """Take an explicitly clicked row now; only row navigation needs settling."""

        if self._syncing:
            return
        key = current.data(0, Qt.UserRole)
        self._pick_timer.stop()
        self._pending_key = key if isinstance(key, int) and key != self._controller.draft.template_key else None
        self._apply_pick()

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
            self.preview_status.setText("")
            return
        self.summary.setText("\n".join(self._controller.template_summary()))


__all__ = ["TemplatePanel"]
