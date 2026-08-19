"""New Item Studio, panel 5: where the item is sold and which item groups it joins."""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QFormLayout,
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
from cdmw.ui.new_item.ui_kit import OK, WARN, NoteLabel, intro_label, tone_color


class PlacementPanel(QGroupBox):
    def __init__(self, controller: NewItemStudioController, parent=None) -> None:
        super().__init__("6. Shop and item groups", parent)
        self._controller = controller
        layout = QVBoxLayout(self)
        layout.addWidget(intro_label("Where players get the item: a shop line (recommended, else nothing hands it out) and its item groups."))

        shop = QGroupBox("Shop")
        shop_layout = QVBoxLayout(shop)
        self.no_store = QRadioButton("Not sold in a shop")
        self.no_store.setChecked(True)
        self.swap = QRadioButton("Replace one shop entry with the new item")
        self.insert = QRadioButton("Add a new shop entry")
        for radio in (self.no_store, self.swap, self.insert):
            radio.toggled.connect(self._placement_changed)
            shop_layout.addWidget(radio)
        form = QFormLayout()
        form.setFieldGrowthPolicy(QFormLayout.AllNonFixedFieldsGrow)
        self.store = QComboBox()
        self.store.setEditable(False)
        self.store.setMaxVisibleItems(24)
        self.store.setToolTip("Every shop in the game's tables: your camp's shops first (Store_Camp_Equipment is the camp's equipment merchant), then the rest by name, each with its kind and how many lines it sells. Type to jump.")
        self.store.currentIndexChanged.connect(self._store_index_changed)
        self.store_label = QLabel("Shop:")
        form.addRow(self.store_label, self.store)
        self.old_item = QComboBox()
        self.old_item.setToolTip("The line of that shop the new item takes over; the old item leaves the shop.")
        self.old_item.currentIndexChanged.connect(self._old_item_changed)
        self.old_item_label = QLabel("Entry to replace:")
        form.addRow(self.old_item_label, self.old_item)
        shop_layout.addLayout(form)
        self.keep_requirement = QCheckBox("Keep the shop line's unlock requirement (a collection's knowledge; the shop shows Knowledge until the buyer has it)")
        self.keep_requirement.toggled.connect(self._keep_requirement_changed)
        shop_layout.addWidget(self.keep_requirement)
        self.unlimited_stock = QCheckBox("Unlimited stock (off: the line's own count, 1 on most equipment lines, so it sells once and then shows 0 in stock)")
        self.unlimited_stock.setChecked(bool(controller.draft.unlimited_stock))
        self.unlimited_stock.toggled.connect(self._unlimited_stock_changed)
        shop_layout.addWidget(self.unlimited_stock)
        self.requirement_note = NoteLabel("")
        shop_layout.addWidget(self.requirement_note)
        layout.addWidget(shop)

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
        self.group_list.setMinimumHeight(120)
        self.group_list.setMaximumHeight(260)
        self.group_list.itemChanged.connect(self._group_toggled)
        groups_layout.addWidget(self.group_list)
        layout.addWidget(groups)
        layout.addStretch(1)
        self._explicit_changed(False)
        self._placement_changed(True)
        controller.snapshot_ready.connect(self._refresh_stores)
        controller.template_changed.connect(self._template_changed)

    # ------------------------------------------------------------------ shop

    #: the shop the studio starts on: the player's camp equipment merchant (Tranan), where every check so far went
    DEFAULT_STORE = "Store_Camp_Equipment"

    def _refresh_stores(self) -> None:
        current = str(self.store.currentData() or self._controller.draft.store_name or "")
        self.store.blockSignals(True)
        try:
            self.store.clear()
            for name, label, _count, camp in self._controller.store_choices():
                self.store.addItem(label, name)
                if camp:
                    self.store.setItemData(self.store.count() - 1, QColor(tone_color(OK)), Qt.ForegroundRole)
            wanted = current or self.DEFAULT_STORE
            index = self.store.findData(wanted)
            if index < 0:
                index = self.store.findData(self.DEFAULT_STORE)
            self.store.setCurrentIndex(max(0, index))
        finally:
            self.store.blockSignals(False)
        self._store_index_changed(self.store.currentIndex())

    def choose_store(self, name: str) -> bool:
        """Select a shop by its table name; False when the tables have no such shop."""

        index = self.store.findData(str(name))
        if index < 0:
            return False
        self.store.setCurrentIndex(index)
        return True

    def _store_index_changed(self, _index: int) -> None:
        self._store_changed(str(self.store.currentData() or ""))

    def _placement_changed(self, _checked: bool) -> None:
        draft = self._controller.draft
        draft.placement_kind = PlacementKind.SWAP if self.swap.isChecked() else PlacementKind.INSERT if self.insert.isChecked() else PlacementKind.NONE
        enabled = draft.placement_kind is not PlacementKind.NONE
        swapping = draft.placement_kind is PlacementKind.SWAP
        self.store.setEnabled(enabled)
        self.store_label.setEnabled(enabled)
        self.old_item.setEnabled(swapping)
        self.old_item.setVisible(swapping)
        self.old_item_label.setVisible(swapping)
        self.keep_requirement.setEnabled(swapping)
        self.keep_requirement.setVisible(swapping)
        self.unlimited_stock.setEnabled(enabled)
        self._controller.plan = None
        self._refresh_requirement_note()

    def _store_changed(self, name: str) -> None:
        self._controller.draft.store_name = str(name or "").strip()
        self.old_item.blockSignals(True)
        try:
            self.old_item.clear()
            for key, item_name, requirement in self._controller.store_stock(self._controller.draft.store_name):
                label = f"{item_name} ({key})" + (f", unlocked by {requirement}" if requirement else "")
                self.old_item.addItem(label, item_name)
        finally:
            self.old_item.blockSignals(False)
        self._old_item_changed(self.old_item.currentIndex())
        self._controller.plan = None

    def _old_item_changed(self, _index: int) -> None:
        self._controller.draft.old_item_name = str(self.old_item.currentData() or "")
        self._controller.plan = None
        self._refresh_requirement_note()

    def _keep_requirement_changed(self, checked: bool) -> None:
        self._controller.draft.keep_requirement = bool(checked)
        self._controller.plan = None
        self._refresh_requirement_note()

    def _unlimited_stock_changed(self, checked: bool) -> None:
        self._controller.draft.unlimited_stock = bool(checked)
        self._controller.plan = None

    def _refresh_requirement_note(self) -> None:
        draft = self._controller.draft
        requirement = self._controller.line_requirement(draft.store_name, draft.old_item_name)
        if draft.placement_kind is PlacementKind.NONE:
            self.requirement_note.set_note("Not sold anywhere: the item will exist, but nothing in the game hands it out.", WARN)
        elif draft.placement_kind is PlacementKind.INSERT:
            self.requirement_note.set_note(f"A new line in {draft.store_name or 'the chosen shop'}: the item sells there freely, next to what the shop already has.", OK)
        elif not requirement:
            self.requirement_note.set_note("This shop line sells freely.", OK)
        elif self.keep_requirement.isChecked():
            self.requirement_note.set_note(f"Kept: the buyer needs the knowledge of {requirement} first.", WARN)
        else:
            self.requirement_note.set_note(f"This line normally needs the knowledge of {requirement}; the new item will sell freely instead.", OK)

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
