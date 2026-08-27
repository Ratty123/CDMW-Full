"""New Item Studio, panel 5: where the item is sold and which item groups it joins."""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
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
    QPushButton,
    QRadioButton,
    QVBoxLayout,
)

from cdmw.domain.new_item.spec import ItemGroupsChoice, PlacementKind
from cdmw.ui.new_item.controller import NewItemStudioController
from cdmw.ui.new_item.ui_kit import OK, WARN, NoteLabel, intro_label

# A normal shell tab leaves about 600 px for a guided page at 1280x720. Keep the
# optional group picker inside that page; its own list remains scrollable when there
# are more groups than the compact viewport can show.
_COMPACT_PAGE_HEIGHT = 650
_COMPACT_GROUP_LIST_HEIGHT = 120


class PlacementPanel(QGroupBox):
    set_copper_price_requested = Signal()

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
        self.price_label = QLabel("Price")
        self.price_value = QLabel("")
        form.addRow(self.price_label, self.price_value)
        shop_layout.addLayout(form)
        # a checkbox's text does not wrap; the rest of each sentence is in the tooltip
        self.keep_requirement = QCheckBox("Keep the shop line's unlock requirement")
        self.keep_requirement.setToolTip("The replaced line's own unlock, a collection's knowledge: until the buyer has it the shop shows Knowledge instead of the item. Off: the new line sells from the start.")
        self.keep_requirement.toggled.connect(self._keep_requirement_changed)
        shop_layout.addWidget(self.keep_requirement)
        self.unlimited_stock = QCheckBox("Unlimited stock")
        self.unlimited_stock.setToolTip("Off: the line keeps its own count, 1 on most equipment lines, so the item sells once and the shop then shows 0 in stock.")
        self.unlimited_stock.setChecked(bool(controller.draft.unlimited_stock))
        self.unlimited_stock.toggled.connect(self._unlimited_stock_changed)
        shop_layout.addWidget(self.unlimited_stock)
        self.requirement_note = NoteLabel("")
        shop_layout.addWidget(self.requirement_note)
        self.price_note = NoteLabel("")
        self.price_note.setVisible(False)
        shop_layout.addWidget(self.price_note)
        self.set_copper_price_button = QPushButton("Set price to 1 Copper")
        self.set_copper_price_button.clicked.connect(lambda: self.set_copper_price_requested.emit())
        self.set_copper_price_button.setVisible(False)
        shop_layout.addWidget(self.set_copper_price_button)
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
        self.group_list.setMinimumHeight(96)
        self.group_list.setMaximumHeight(260)
        self._group_list_default_maximum = self.group_list.maximumHeight()
        self._group_list_compact = None
        self.group_list.itemChanged.connect(self._group_toggled)
        groups_layout.addWidget(self.group_list)
        layout.addWidget(groups)
        layout.addStretch(1)
        self._explicit_changed(False)
        self._placement_changed(True)
        controller.snapshot_ready.connect(self._refresh_stores)
        controller.template_changed.connect(self._template_changed)

    def resizeEvent(self, event) -> None:  # noqa: N802 - Qt override
        super().resizeEvent(event)
        compact = self.height() <= _COMPACT_PAGE_HEIGHT
        if compact == self._group_list_compact:
            return
        self._group_list_compact = compact
        self.group_list.setMaximumHeight(
            _COMPACT_GROUP_LIST_HEIGHT if compact else self._group_list_default_maximum
        )

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
                    preferred_font = self.store.font()
                    preferred_font.setBold(True)
                    self.store.setItemData(self.store.count() - 1, preferred_font, Qt.FontRole)
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
        self.store.setVisible(enabled)
        self.store_label.setEnabled(enabled)
        self.store_label.setVisible(enabled)
        self.old_item.setEnabled(swapping)
        self.old_item.setVisible(swapping)
        self.old_item_label.setVisible(swapping)
        self.keep_requirement.setEnabled(swapping)
        self.keep_requirement.setVisible(swapping)
        self.unlimited_stock.setEnabled(enabled)
        self.unlimited_stock.setVisible(enabled)
        self._controller.invalidate_plan()
        self._refresh_requirement_note()
        self.refresh_price_state()

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
        self._controller.invalidate_plan()

    def _old_item_changed(self, _index: int) -> None:
        self._controller.draft.old_item_name = str(self.old_item.currentData() or "")
        self._controller.invalidate_plan()
        self._refresh_requirement_note()

    def _keep_requirement_changed(self, checked: bool) -> None:
        self._controller.draft.keep_requirement = bool(checked)
        self._controller.invalidate_plan()
        self._refresh_requirement_note()

    def _unlimited_stock_changed(self, checked: bool) -> None:
        self._controller.draft.unlimited_stock = bool(checked)
        self._controller.invalidate_plan()

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

    def refresh_price_state(self) -> None:
        """Show the ItemInfo price that the selected shop line will consume."""

        selling = self._controller.draft.placement_kind is not PlacementKind.NONE
        self.price_label.setVisible(selling)
        self.price_value.setVisible(selling)
        if not selling:
            self.price_value.setText("")
            self.price_note.setVisible(False)
            self.set_copper_price_button.setVisible(False)
            return

        draft = self._controller.draft
        grid = self._controller.stat_grid()
        prices = []
        if grid is not None:
            for key, label, template in grid.price_items:
                value = draft.price_values.get(key, template)
                if value is not None:
                    prices.append(f"{label}: {int(value):,}")
        self.price_value.setText(", ".join(prices))
        if prices:
            self.price_note.setVisible(False)
            self.set_copper_price_button.setVisible(False)
            return

        snapshot = self._controller.snapshot
        row = snapshot.row(draft.template_key) if snapshot is not None and draft.template_key is not None else None
        editable = row is not None and row.stat_block_offset is not None
        self.price_note.set_note(
            "No shop price is set. Add one before placing the item in a shop."
            if editable
            else "This template's stat block did not decode; stats and prices cannot be edited.",
            WARN,
        )
        self.price_note.setVisible(True)
        self.set_copper_price_button.setVisible(editable)
        self.set_copper_price_button.setEnabled(editable)

    # ------------------------------------------------------------------ groups

    def _template_changed(self, _key: object) -> None:
        names = self._controller.template_group_names()
        if names:
            shown = ", ".join(names[:6]) + (f" and {len(names) - 6} more" if len(names) > 6 else "")
            self.template_groups.setText(f"The clone joins the template's {len(names)} group(s): {shown}.")
        else:
            self.template_groups.setText("The clone joins every group the template is in.")
        self._refresh_groups()
        self.refresh_price_state()

    def _explicit_changed(self, checked: bool) -> None:
        self._controller.draft.item_groups = ItemGroupsChoice.EXPLICIT if checked else ItemGroupsChoice.TEMPLATE
        # hidden rather than greyed: the group list is tall, and the template's groups are
        # the usual answer, so an unticked step 6 is three lines instead of half a page
        for widget in (self.group_filter, self.group_list):
            widget.setEnabled(bool(checked))
            widget.setVisible(bool(checked))
        self._controller.invalidate_plan()

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
        self._controller.invalidate_plan()


__all__ = ["PlacementPanel"]
