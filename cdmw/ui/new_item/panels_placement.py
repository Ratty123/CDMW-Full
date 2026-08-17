"""New Item Studio, panel 5: where the item is sold and which item groups it joins."""

from __future__ import annotations

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
    QRadioButton,
    QVBoxLayout,
)

from cdmw.domain.new_item.spec import ItemGroupsChoice, PlacementKind
from cdmw.ui.new_item.controller import NewItemStudioController


class PlacementPanel(QGroupBox):
    def __init__(self, controller: NewItemStudioController, parent=None) -> None:
        super().__init__("6. Shop and item groups", parent)
        self._controller = controller
        layout = QVBoxLayout(self)

        self.no_store = QRadioButton("Not sold in a shop")
        self.no_store.setChecked(True)
        self.swap = QRadioButton("Replace one shop entry with the new item (the form the game accepted)")
        self.insert = QRadioButton("Add a new shop entry (unproven in game)")
        for radio in (self.no_store, self.swap, self.insert):
            radio.toggled.connect(self._placement_changed)
            layout.addWidget(radio)
        row = QHBoxLayout()
        row.addWidget(QLabel("Shop:"))
        self.store = QComboBox()
        self.store.setEditable(True)
        self.store.currentTextChanged.connect(self._store_changed)
        row.addWidget(self.store, 1)
        row.addWidget(QLabel("Entry to replace:"))
        self.old_item = QComboBox()
        self.old_item.currentIndexChanged.connect(self._old_item_changed)
        row.addWidget(self.old_item, 1)
        layout.addLayout(row)

        groups = QGroupBox("Item groups")
        groups_layout = QVBoxLayout(groups)
        self.template_groups = QLabel("The clone joins every group the template is in.")
        self.template_groups.setWordWrap(True)
        groups_layout.addWidget(self.template_groups)
        self.explicit = QCheckBox("Choose the groups myself instead")
        self.explicit.toggled.connect(self._explicit_changed)
        groups_layout.addWidget(self.explicit)
        self.group_filter = QLineEdit()
        self.group_filter.setPlaceholderText("Filter groups by name")
        self.group_filter.textChanged.connect(self._refresh_groups)
        groups_layout.addWidget(self.group_filter)
        self.group_list = QListWidget()
        self.group_list.setMaximumHeight(120)
        self.group_list.itemChanged.connect(self._group_toggled)
        groups_layout.addWidget(self.group_list)
        layout.addWidget(groups)
        self._explicit_changed(False)
        controller.snapshot_ready.connect(self._refresh_stores)
        controller.template_changed.connect(self._template_changed)

    # ------------------------------------------------------------------ shop

    def _refresh_stores(self) -> None:
        current = self.store.currentText()
        self.store.blockSignals(True)
        try:
            self.store.clear()
            self.store.addItems(list(self._controller.store_names()))
            if current:
                self.store.setEditText(current)
        finally:
            self.store.blockSignals(False)
        self._store_changed(self.store.currentText())

    def _placement_changed(self, _checked: bool) -> None:
        draft = self._controller.draft
        draft.placement_kind = PlacementKind.SWAP if self.swap.isChecked() else PlacementKind.INSERT if self.insert.isChecked() else PlacementKind.NONE
        enabled = draft.placement_kind is not PlacementKind.NONE
        self.store.setEnabled(enabled)
        self.old_item.setEnabled(draft.placement_kind is PlacementKind.SWAP)
        self._controller.plan = None

    def _store_changed(self, name: str) -> None:
        self._controller.draft.store_name = str(name or "").strip()
        self.old_item.blockSignals(True)
        try:
            self.old_item.clear()
            for key, item_name in self._controller.store_stock(self._controller.draft.store_name):
                self.old_item.addItem(f"{item_name} ({key})", item_name)
        finally:
            self.old_item.blockSignals(False)
        self._old_item_changed(self.old_item.currentIndex())
        self._controller.plan = None

    def _old_item_changed(self, _index: int) -> None:
        self._controller.draft.old_item_name = str(self.old_item.currentData() or "")
        self._controller.plan = None

    # ------------------------------------------------------------------ groups

    def _template_changed(self, _key: object) -> None:
        names = self._controller.template_group_names()
        if names:
            shown = ", ".join(names[:6]) + (f" and {len(names) - 6} more" if len(names) > 6 else "")
            self.template_groups.setText(f"The clone joins the template's {len(names)} group(s): {shown}.")
        else:
            self.template_groups.setText("The clone joins every group the template is in.")
        self._refresh_groups()

    def _explicit_changed(self, checked: bool) -> None:
        self._controller.draft.item_groups = ItemGroupsChoice.EXPLICIT if checked else ItemGroupsChoice.TEMPLATE
        self.group_filter.setEnabled(bool(checked))
        self.group_list.setEnabled(bool(checked))
        self._controller.plan = None

    def _refresh_groups(self, *_args) -> None:
        chosen = set(self._controller.draft.explicit_item_groups)
        self.group_list.blockSignals(True)
        try:
            self.group_list.clear()
            for key, name in self._controller.item_groups(self.group_filter.text()):
                item = QListWidgetItem(name)
                item.setData(Qt.UserRole, key)
                item.setFlags(item.flags() | Qt.ItemIsUserCheckable)
                item.setCheckState(Qt.Checked if key in chosen else Qt.Unchecked)
                self.group_list.addItem(item)
        finally:
            self.group_list.blockSignals(False)

    def _group_toggled(self, item: QListWidgetItem) -> None:
        key = item.data(Qt.UserRole)
        if not isinstance(key, int):
            return
        chosen = set(self._controller.draft.explicit_item_groups)
        if item.checkState() == Qt.Checked:
            chosen.add(key)
        else:
            chosen.discard(key)
        self._controller.draft.explicit_item_groups = tuple(sorted(chosen))
        self._controller.plan = None


__all__ = ["PlacementPanel"]
