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
    QScrollArea,
    QSpinBox,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from dataclasses import replace

from cdmw.domain.new_item.spec import ItemGroupsChoice, PlacementKind
from cdmw.services.new_item_snapshot import NewItemSnapshotError
from cdmw.ui.new_item.controller import NewItemStudioController
from cdmw.ui.new_item.ui_kit import OK, WARN, NoteLabel

class PlacementPanel(QGroupBox):
    set_copper_price_requested = Signal()
    recipes_requested = Signal()

    def __init__(self, controller: NewItemStudioController, parent=None) -> None:
        super().__init__("6. Shop and item groups", parent)
        self._controller = controller
        self._group_lookup = controller.create_lookup_lane()
        self._group_lookup.completed.connect(self._publish_groups)
        self._group_lookup.failed.connect(self._group_lookup_failed)
        layout = QVBoxLayout(self)
        self.setToolTip("Choose shops, crafting recipes or existing reward sources, and review group memberships.")

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
        # The combo holds the chosen shop by its StoreInfo key, but is never shown:
        # its popup, scrolled and clicked while the wizard changed pages, was where
        # the reported crashes happened. Shops are chosen in a modal picker instead.
        self.store = QComboBox(self)
        self.store.setEditable(False)
        self.store.setVisible(False)
        self.store.currentIndexChanged.connect(self._store_index_changed)
        self.store_label = QLabel("Shop:")
        store_row = QHBoxLayout()
        self.store_summary = QLabel("")
        self.store_summary.setWordWrap(True)
        self.store_summary.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        store_row.addWidget(self.store_summary, 1)
        self.choose_store_button = QPushButton("Choose shop...")
        self.choose_store_button.setToolTip(
            "Search every shop by merchant, place, type, internal Store_ ID or an item it sells. "
            "When adding a new shop entry you can tick several shops at once."
        )
        self.choose_store_button.clicked.connect(self._open_shop_picker)
        store_row.addWidget(self.choose_store_button)
        form.addRow(self.store_label, store_row)
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
        stock_row = QHBoxLayout()
        stock_row.addWidget(self.unlimited_stock)
        self.stock_count = QSpinBox()
        self.stock_count.setRange(0,2147483647)
        self.stock_count.setSpecialValueText("Inherit quantity")
        self.stock_count.setToolTip("Stock quantity when unlimited stock is off; zero keeps the source entry's quantity.")
        self.stock_count.setValue(controller.draft.stock_count or 0)
        self.stock_count.setEnabled(not controller.draft.unlimited_stock)
        self.stock_count.valueChanged.connect(self._stock_count_changed)
        stock_row.addWidget(self.stock_count,1)
        shop_layout.addLayout(stock_row)
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
        from cdmw.ui.new_item.shop_routes_editor import ShopRoutesEditor
        self.shop_routes = ShopRoutesEditor(controller)
        layout.addWidget(self.shop_routes)

        groups = QGroupBox("Item groups")
        groups_layout = QVBoxLayout(groups)
        self.template_groups = QLabel("The clone joins every group the template is in.")
        self.template_groups.setWordWrap(True)
        groups_layout.addWidget(self.template_groups)
        self.explicit = QCheckBox("Choose the groups myself instead")
        self.explicit.toggled.connect(self._explicit_changed)
        groups_layout.addWidget(self.explicit)
        self.inherit_all = QCheckBox("Advanced: inherit all template groups")
        self.inherit_all.setToolTip("Includes quest, special, collection and other non-category memberships carried by the template.")
        self.inherit_all.setChecked(controller.draft.item_groups is ItemGroupsChoice.TEMPLATE)
        self.inherit_all.toggled.connect(lambda _checked: self._explicit_changed(self.explicit.isChecked()))
        groups_layout.addWidget(self.inherit_all)
        self.group_filter = QLineEdit()
        self.group_filter.setPlaceholderText("Filter groups by name")
        self.group_filter.textChanged.connect(self._refresh_groups)
        groups_layout.addWidget(self.group_filter)
        self.group_list = QListWidget()
        self.group_list.setMinimumHeight(96)
        self._group_item_pool = []
        self.group_list.itemChanged.connect(self._group_toggled)
        groups_layout.addWidget(self.group_list, 1)
        layout.addWidget(groups)
        # Acquisition settings share one page family; group membership no longer
        # occupies a permanent half-width panel beside the shop controls.
        for widget in (shop, self.shop_routes, groups):
            layout.removeWidget(widget)
        columns = QHBoxLayout()
        columns.addWidget(self.shop_routes, 2, Qt.AlignmentFlag.AlignTop)
        columns.addWidget(shop, 3, Qt.AlignmentFlag.AlignTop)
        shop_page = QWidget()
        page_layout = QVBoxLayout(shop_page)
        page_layout.addLayout(columns, 1)
        shop_scroll = QScrollArea()
        shop_scroll.setWidgetResizable(True)
        shop_scroll.setFrameShape(QScrollArea.Shape.NoFrame)
        shop_scroll.setWidget(shop_page)
        self.routes_view = QTabWidget()
        self.routes_view.addTab(shop_scroll, "Shops")
        from cdmw.ui.new_item.reward_editor import RewardEditor
        self.rewards = RewardEditor(controller)
        self.routes_view.addTab(self.rewards, "Loot and rewards (experimental)")
        self.groups_page = groups
        self.routes_view.addTab(groups, "Item groups")
        layout.addWidget(self.routes_view, 1)
        self.crafting = QPushButton("Edit crafting and enhancement recipes")
        self.crafting.clicked.connect(self.recipes_requested.emit)
        self.crafting.setParent(self)
        self.crafting.hide()
        self.explicit.setChecked(controller.draft.item_groups is ItemGroupsChoice.EXPLICIT)
        self._explicit_changed(self.explicit.isChecked())
        self._placement_changed(True)
        controller.snapshot_ready.connect(self._refresh_stores)
        controller.template_changed.connect(self._template_changed)

    def mount_recipes(self, recipes: QWidget) -> None:
        """Move the existing recipe editor here; keep its controller and signals."""
        self.recipes = recipes
        self.routes_view.insertTab(1, recipes, "Recipes (experimental)")

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

    def close_popups(self) -> None:
        """Close the stock-line list before the wizard leaves this page."""

        for combo in (self.store, self.old_item):
            try:
                combo.hidePopup()
            except RuntimeError:
                pass

    def _open_shop_picker(self) -> None:
        from cdmw.ui.new_item.shop_picker import ShopPickerDialog

        draft = self._controller.draft
        multi = draft.placement_kind is PlacementKind.INSERT
        routed = tuple(
            route.store_name
            for route in (draft.shop_placements or ())
            if route.kind is PlacementKind.INSERT
        )
        dialog = ShopPickerDialog(
            self._controller.shop_choices(),
            multi=multi,
            selected=(draft.store_name,) if draft.store_name else (),
            already_routed=routed,
            parent=self,
        )
        try:
            if dialog.exec() != dialog.DialogCode.Accepted:
                return
            chosen = dialog.selected_keys()
        finally:
            dialog.deleteLater()
        self.apply_shop_selection(chosen)

    def apply_shop_selection(self, store_names) -> str:
        """Use the picked shops: one sets the shop; several become saved INSERT routes.

        Returns a short message describing what changed (also shown in the note).
        """

        names = [name for name in dict.fromkeys(str(name) for name in store_names) if self._controller.has_store(name)]
        if not names:
            return ""
        if not self.choose_store(names[0]):
            return ""
        draft = self._controller.draft
        if len(names) == 1 or draft.placement_kind is not PlacementKind.INSERT:
            self.shop_routes.refresh()
            return f"Shop: {names[0]}."
        template = self._controller.current_spec().placement
        existing = tuple(draft.shop_placements or ())
        taken = {(route.kind, route.store_name) for route in existing}
        added, skipped = [], []
        for name in names:
            if (PlacementKind.INSERT, name) in taken:
                skipped.append(name)
                continue
            added.append(replace(template, kind=PlacementKind.INSERT, store_name=name, old_item_name="", stock_index=None))
            taken.add((PlacementKind.INSERT, name))
        if added:
            draft.shop_placements = (*existing, *added)
            self._controller.invalidate_plan()
        self.shop_routes.refresh()
        message = f"Added {len(added)} shop route(s)."
        if skipped:
            message += f" Skipped {len(skipped)} already saved: {', '.join(skipped[:4])}."
        self.shop_routes.state.setText(message + " " + self.shop_routes.state.text())
        return message

    def _refresh_store_summary(self) -> None:
        name = str(self.store.currentData() or "")
        if not name:
            self.store_summary.setText("No shop chosen.")
            self.store_summary.setToolTip("")
            return
        from cdmw.ui.new_item.shop_picker import describe_shop

        count = 0
        snapshot = self._controller.snapshot
        if snapshot is not None:
            try:
                count = len(snapshot.store(name).buyable_entries)
            except NewItemSnapshotError:
                count = 0
        shop = describe_shop(name, count)
        marker = "" if shop.verified_name else " *"
        place = f", {shop.location}" if shop.location else ""
        self.store_summary.setText(f"{shop.display_name}{marker} ({shop.kind}{place}, {count} line(s)) · {name}")
        self.store_summary.setToolTip(
            "Merchant confirmed in game." if shop.verified_name
            else "* Name derived from the internal StoreInfo key; the in-game merchant is not confirmed."
        )

    def show_draft(self) -> None:
        """Show the draft's shop and group choices after it was replaced."""

        draft = self._controller.draft
        kind, store, stock_index = draft.placement_kind, draft.store_name, draft.stock_index
        keep, unlimited, count = draft.keep_requirement, draft.unlimited_stock, draft.stock_count
        groups, explicit_groups = draft.item_groups, tuple(draft.explicit_item_groups)
        radio = self.swap if kind is PlacementKind.SWAP else self.insert if kind is PlacementKind.INSERT else self.no_store
        radio.setChecked(True)
        self._placement_changed(True)
        if store:
            index = self.store.findData(store)
            if index >= 0:
                self.store.blockSignals(True)
                try:
                    self.store.setCurrentIndex(index)
                finally:
                    self.store.blockSignals(False)
                self._store_index_changed(index)
        if kind is PlacementKind.SWAP and stock_index is not None:
            for index in range(self.old_item.count()):
                if self.old_item.itemData(index, Qt.UserRole + 1) == stock_index:
                    self.old_item.setCurrentIndex(index)
                    self._old_item_changed(index)
                    break
        self.keep_requirement.setChecked(bool(keep))
        self.unlimited_stock.setChecked(bool(unlimited))
        self.stock_count.setValue(int(count or 0))
        draft.stock_count = count
        for box, checked in ((self.inherit_all, groups is ItemGroupsChoice.TEMPLATE),
                             (self.explicit, groups is ItemGroupsChoice.EXPLICIT)):
            box.blockSignals(True)
            try:
                box.setChecked(checked)
            finally:
                box.blockSignals(False)
        draft.explicit_item_groups = explicit_groups
        self._explicit_changed(groups is ItemGroupsChoice.EXPLICIT)
        draft.item_groups, draft.explicit_item_groups = groups, explicit_groups
        self.shop_routes.refresh()

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
        self.store_summary.setVisible(enabled)
        self.choose_store_button.setEnabled(enabled)
        self.choose_store_button.setVisible(enabled)
        self.choose_store_button.setText("Choose shops..." if draft.placement_kind is PlacementKind.INSERT else "Choose shop...")
        self.store_label.setEnabled(enabled)
        self.store_label.setVisible(enabled)
        self.old_item.setEnabled(swapping)
        self.old_item.setVisible(swapping)
        self.old_item_label.setVisible(swapping)
        self.keep_requirement.setEnabled(swapping)
        self.keep_requirement.setVisible(swapping)
        self.unlimited_stock.setEnabled(enabled)
        self.unlimited_stock.setVisible(enabled)
        self.stock_count.setVisible(enabled)
        self.stock_count.setEnabled(enabled and not self.unlimited_stock.isChecked())
        self._controller.invalidate_plan()
        self._refresh_requirement_note()
        self.refresh_price_state()

    def _store_changed(self, name: str) -> None:
        name = str(name or "").strip()
        self._controller.draft.store_name = name
        self.old_item.hidePopup()
        self.old_item.blockSignals(True)
        try:
            self.old_item.clear()
            snapshot = self._controller.snapshot
            try:
                entries = snapshot.store(name).buyable_entries if snapshot and name else ()
            except NewItemSnapshotError:
                # A stale shop (a restored draft against another snapshot): no lines,
                # and nothing of the previous shop's stock is left selectable.
                entries = ()
            for entry,(key,item_name,requirement) in zip(entries,self._controller.store_stock(name)):
                label = f"{item_name} ({key}) · entry {entry.stock_index}" + (f", unlocked by {requirement}" if requirement else "")
                self.old_item.addItem(label, item_name)
                at = self.old_item.count()-1
                self.old_item.setItemData(at,entry.stock_index,Qt.UserRole+1)
                self.old_item.setItemData(at,f"Quantity: {entry.count}; order: {entry.order_index}; preserved conditions: {entry.condition_data.hex() or 'none'}",Qt.ToolTipRole)
        finally:
            self.old_item.blockSignals(False)
        # One shop change is one draft change: the stock line follows it in the same
        # step, and the plan is invalidated once, not once per dependent control.
        self._old_item_changed(self.old_item.currentIndex(), invalidate=False)
        self._refresh_store_summary()
        self._controller.invalidate_plan()

    def _old_item_changed(self, _index: int, *, invalidate: bool = True) -> None:
        self._controller.draft.old_item_name = str(self.old_item.currentData() or "")
        self._controller.draft.stock_index = self.old_item.currentData(Qt.UserRole+1)
        if invalidate:
            self._controller.invalidate_plan()
        self._refresh_requirement_note()

    def _keep_requirement_changed(self, checked: bool) -> None:
        self._controller.draft.keep_requirement = bool(checked)
        self._controller.invalidate_plan()
        self._refresh_requirement_note()

    def _unlimited_stock_changed(self, checked: bool) -> None:
        self._controller.draft.unlimited_stock = bool(checked)
        self.stock_count.setEnabled(not checked and self._controller.draft.placement_kind is not PlacementKind.NONE)
        self._controller.invalidate_plan()

    def _stock_count_changed(self, value: int) -> None:
        self._controller.draft.stock_count = value or None
        self._controller.invalidate_plan()

    def _refresh_requirement_note(self) -> None:
        draft = self._controller.draft
        self.requirement_note.setToolTip("")
        requirement = self._controller.line_requirement(draft.store_name, draft.old_item_name)
        if self._controller.snapshot and draft.store_name and draft.stock_index is not None:
            try:
                store_entries = self._controller.snapshot.store(draft.store_name).entries
            except NewItemSnapshotError:
                store_entries = ()
            entry = next((e for e in store_entries if e.stock_index == draft.stock_index),None)
            key = entry.requirement_item_key if entry else None
            row = self._controller.snapshot.rows.get(key)
            requirement = row.string_key if row else str(key or "")
        if draft.placement_kind is PlacementKind.NONE:
            self.requirement_note.set_note("No current shop placement.", WARN)
            self.requirement_note.setToolTip("Saved shop routes, crafting and rewards are reviewed in Output.")
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
        from cdmw.domain.new_item.groups import ordinary_group
        c = self._controller
        groups = [group for group in c.snapshot.item_groups if c.draft.template_key in group.members] if c.snapshot else []
        if c.draft.item_groups is ItemGroupsChoice.ORDINARY:
            groups = [group for group in groups if ordinary_group(group)]
        elif c.draft.item_groups is ItemGroupsChoice.EXPLICIT:
            groups = [group for group in c.snapshot.item_groups if group.key in c.draft.explicit_item_groups] if c.snapshot else []
        names = [group.name for group in groups]
        if names:
            shown = ", ".join(names[:6]) + (f" and {len(names) - 6} more" if len(names) > 6 else "")
            self.template_groups.setText(f"{len(names)} group(s) selected: {shown}.")
        else:
            self.template_groups.setText("No memberships selected. Ordinary equipment/category groups are offered by default.")
        self._refresh_groups()
        self.refresh_price_state()

    def _explicit_changed(self, checked: bool) -> None:
        self._controller.draft.item_groups = ItemGroupsChoice.EXPLICIT if checked else (ItemGroupsChoice.TEMPLATE if self.inherit_all.isChecked() else ItemGroupsChoice.ORDINARY)
        self.inherit_all.setEnabled(not checked)
        # hidden rather than greyed: the group list is tall, and the template's groups are
        # the usual answer, so an unticked step 6 is three lines instead of half a page
        for widget in (self.group_filter, self.group_list):
            widget.setEnabled(bool(checked))
            widget.setVisible(bool(checked))
        self._controller.invalidate_plan()
        self._template_changed(None)

    def _refresh_groups(self, *_args) -> None:
        from cdmw.services.new_item_panel_search import group_choices
        snapshot, query = self._controller.snapshot, self.group_filter.text()
        self._group_lookup.request((id(snapshot), query), lambda stop: group_choices(snapshot, query, stop), delay_ms=150)

    def _group_lookup_failed(self, _key, message):
        self._controller.status_message.emit(f"Item groups could not be loaded: {message}", True)

    def _publish_groups(self, request, groups) -> None:
        if request != (id(self._controller.snapshot), self.group_filter.text()):
            return
        chosen = set(self._controller.draft.explicit_item_groups)
        self.group_list.blockSignals(True)
        try:
            while self.group_list.count() > len(groups):
                self._group_item_pool.append(self.group_list.takeItem(self.group_list.count() - 1))
            while self.group_list.count() < len(groups):
                item = self._group_item_pool.pop() if self._group_item_pool else QListWidgetItem()
                self.group_list.addItem(item)
            for row, (key, name) in enumerate(groups):
                item = self.group_list.item(row)
                item.setText(name)
                from cdmw.domain.new_item.groups import group_purpose
                purpose, consequence, _ordinary = group_purpose(name)
                item.setToolTip(f"{purpose}: {consequence}")
                item.setData(Qt.UserRole, key)
                item.setFlags(item.flags() | Qt.ItemIsUserCheckable)
                item.setCheckState(Qt.Checked if key in chosen else Qt.Unchecked)
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
