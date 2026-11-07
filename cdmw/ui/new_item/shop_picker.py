"""New Item Studio: a searchable shop picker that can choose several shops at once.

Shops are listed with a readable name, place, kind and line count. Where a shop's
merchant is known from project evidence it is named; every other name is derived
from the StoreInfo key and marked as such, never invented. Checked shops are kept
by their StoreInfo key, so searching or sorting never changes what is chosen.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import dataclass

from PySide6.QtCore import QSortFilterProxyModel, Qt
from PySide6.QtGui import QFont, QStandardItem, QStandardItemModel
from PySide6.QtWidgets import (
    QAbstractItemView,
    QDialog,
    QDialogButtonBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QPushButton,
    QTableView,
    QVBoxLayout,
)

#: Shops whose merchant is confirmed by project evidence (in-game checks). Extend
#: this only with names that were seen in the game, not guessed from the key.
VERIFIED_SHOP_NAMES: dict[str, tuple[str, str]] = {
    "Store_Camp_Equipment": ("Camp equipment merchant (Tranan)", "Your camp"),
}

STORE_KEY_ROLE = Qt.ItemDataRole.UserRole + 1
SEARCH_TEXT_ROLE = Qt.ItemDataRole.UserRole + 2


@dataclass(frozen=True, slots=True)
class ShopChoice:
    """One StoreInfo row as the picker shows it."""

    key: str
    display_name: str
    location: str
    kind: str
    line_count: int
    is_camp: bool
    verified_name: bool
    stock_preview: tuple[str, ...] = ()

    @property
    def search_text(self) -> str:
        return " ".join(
            (self.display_name, self.location, self.kind, self.key, *self.stock_preview[:24])
        ).casefold()


def _words(value: str) -> str:
    """``BlackMarket`` -> ``Black Market``; ``Equipment`` stays."""

    out: list[str] = []
    for index, char in enumerate(value):
        if index and char.isupper() and not value[index - 1].isupper():
            out.append(" ")
        out.append(char)
    return "".join(out).strip()


def describe_shop(key: str, line_count: int, stock_preview: Sequence[str] = ()) -> ShopChoice:
    """Readable facts for one StoreInfo key; a derived name is flagged as unverified."""

    name = str(key or "").strip()
    parts = [part for part in name.split("_") if part]
    if parts and parts[0].casefold() == "store":
        parts = parts[1:]
    is_camp = bool(parts) and parts[0].casefold() == "camp"
    kind = _words(parts[-1]) if parts else name
    place = _words(" ".join(parts[:-1])) if len(parts) > 1 else ""
    verified = VERIFIED_SHOP_NAMES.get(name)
    if verified is not None:
        display_name, location = verified
    else:
        display_name = " ".join(_words(part) for part in parts) or name
        location = "Your camp" if is_camp else place
    return ShopChoice(
        key=name,
        display_name=display_name,
        location=location,
        kind=kind,
        line_count=int(line_count),
        is_camp=is_camp,
        verified_name=verified is not None,
        stock_preview=tuple(stock_preview),
    )


class _ShopFilterProxy(QSortFilterProxyModel):
    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._needle = ""

    def set_needle(self, text: str) -> None:
        begin = getattr(self, "beginFilterChange", None)
        if callable(begin):  # Qt 6.10 replaced invalidateFilter with this pair
            begin()
            self._needle = str(text or "").strip().casefold()
            self.endFilterChange()
            return
        self._needle = str(text or "").strip().casefold()
        self.invalidateRowsFilter()

    def filterAcceptsRow(self, source_row, source_parent) -> bool:
        if not self._needle:
            return True
        index = self.sourceModel().index(source_row, 0, source_parent)
        haystack = str(index.data(SEARCH_TEXT_ROLE) or "")
        return all(token in haystack for token in self._needle.split())


class ShopPickerDialog(QDialog):
    """Choose one shop, or several when ``multi`` is set."""

    COLUMNS = ("Shop / merchant", "Location", "Type", "Stock lines", "Internal ID")

    def __init__(
        self,
        shops: Iterable[ShopChoice],
        *,
        multi: bool,
        selected: Iterable[str] = (),
        already_routed: Iterable[str] = (),
        parent=None,
    ) -> None:
        super().__init__(parent)
        self.setObjectName("new_item_shop_picker")
        self.setWindowTitle("Choose shops" if multi else "Choose a shop")
        self.resize(860, 560)
        self._multi = bool(multi)
        self._shops = {shop.key: shop for shop in shops}
        self._already_routed = frozenset(already_routed)
        chosen = [key for key in selected if key in self._shops]
        self._chosen: list[str] = chosen if self._multi else chosen[:1]

        layout = QVBoxLayout(self)
        intro = QLabel(
            "Tick every shop that should sell the new item, then choose Add selected shops."
            if self._multi
            else "Choose the shop whose line the new item takes over."
        )
        intro.setWordWrap(True)
        layout.addWidget(intro)
        self.search = QLineEdit()
        self.search.setPlaceholderText("Search by merchant, place, type, internal Store_ ID or an item it sells")
        self.search.setClearButtonEnabled(True)
        self.search.setAccessibleName("Search shops")
        layout.addWidget(self.search)

        self.model = QStandardItemModel(0, len(self.COLUMNS), self)
        self.model.setHorizontalHeaderLabels(list(self.COLUMNS))
        bold = QFont()
        bold.setBold(True)
        for shop in sorted(self._shops.values(), key=lambda item: (not item.is_camp, item.display_name.casefold())):
            name_item = QStandardItem(shop.display_name if shop.verified_name else f"{shop.display_name} *")
            name_item.setData(shop.key, STORE_KEY_ROLE)
            name_item.setData(shop.search_text, SEARCH_TEXT_ROLE)
            name_item.setEditable(False)
            if shop.is_camp:
                name_item.setFont(bold)
            if self._multi:
                name_item.setCheckable(True)
                name_item.setCheckState(Qt.CheckState.Checked if shop.key in self._chosen else Qt.CheckState.Unchecked)
            tooltip = [
                "Merchant confirmed in game." if shop.verified_name else
                "* Name derived from the internal StoreInfo key; the in-game merchant is not confirmed.",
                f"Internal ID: {shop.key}",
            ]
            if shop.key in self._already_routed:
                tooltip.append("Already saved as a route; adding it again is skipped.")
            if shop.stock_preview:
                tooltip.append("Sells: " + ", ".join(shop.stock_preview[:12]) + (" ..." if len(shop.stock_preview) > 12 else ""))
            name_item.setToolTip("\n".join(tooltip))
            count_item = QStandardItem()
            count_item.setData(int(shop.line_count), Qt.ItemDataRole.DisplayRole)
            row = [
                name_item,
                QStandardItem(shop.location),
                QStandardItem(shop.kind),
                count_item,
                QStandardItem(shop.key),
            ]
            for item in row[1:]:
                item.setEditable(False)
                item.setToolTip(name_item.toolTip())
            self.model.appendRow(row)
        self.model.itemChanged.connect(self._item_changed)

        self.proxy = _ShopFilterProxy(self)
        self.proxy.setSourceModel(self.model)
        self.proxy.setSortCaseSensitivity(Qt.CaseSensitivity.CaseInsensitive)
        self.table = QTableView()
        self.table.setObjectName("new_item_shop_picker_table")
        self.table.setModel(self.proxy)
        self.table.setSortingEnabled(True)
        self.table.sortByColumn(-1, Qt.SortOrder.AscendingOrder)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.table.setAlternatingRowColors(True)
        self.table.verticalHeader().setVisible(False)
        self.table.horizontalHeader().setStretchLastSection(True)
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self.table.setAccessibleName("Shops")
        self.table.doubleClicked.connect(self._double_clicked)
        self.table.selectionModel().currentRowChanged.connect(self._current_changed)
        layout.addWidget(self.table, 1)

        self.detail = QLabel("")
        self.detail.setWordWrap(True)
        layout.addWidget(self.detail)
        footer = QHBoxLayout()
        self.selected_label = QLabel("")
        footer.addWidget(self.selected_label, 1)
        self.clear_button = QPushButton("Clear selection")
        self.clear_button.clicked.connect(self._clear)
        self.clear_button.setVisible(self._multi)
        footer.addWidget(self.clear_button)
        layout.addLayout(footer)
        self.buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Cancel)
        self.accept_button = self.buttons.addButton(
            "Add selected shops" if self._multi else "Use this shop",
            QDialogButtonBox.ButtonRole.AcceptRole,
        )
        self.buttons.accepted.connect(self.accept)
        self.buttons.rejected.connect(self.reject)
        layout.addWidget(self.buttons)
        self.search.textChanged.connect(self.proxy.set_needle)
        if not self._multi and self._chosen:
            self._select_key(self._chosen[0])
        self._refresh_state()
        self.search.setFocus()

    # ------------------------------------------------------------------ state

    def selected_keys(self) -> tuple[str, ...]:
        """Chosen StoreInfo keys, in the order they were chosen."""

        return tuple(self._chosen)

    def _source_item_for_key(self, key: str) -> QStandardItem | None:
        for row in range(self.model.rowCount()):
            item = self.model.item(row, 0)
            if item is not None and item.data(STORE_KEY_ROLE) == key:
                return item
        return None

    def set_checked(self, key: str, checked: bool) -> None:
        item = self._source_item_for_key(key)
        if item is None:
            return
        if self._multi:
            item.setCheckState(Qt.CheckState.Checked if checked else Qt.CheckState.Unchecked)
        elif checked:
            self._select_key(key)

    def _select_key(self, key: str) -> None:
        item = self._source_item_for_key(key)
        if item is None:
            return
        index = self.proxy.mapFromSource(item.index())
        if index.isValid():
            self.table.setCurrentIndex(index)
            self.table.scrollTo(index)

    def _item_changed(self, item: QStandardItem) -> None:
        if not self._multi or item.column() != 0:
            return
        key = str(item.data(STORE_KEY_ROLE) or "")
        if not key:
            return
        if item.checkState() == Qt.CheckState.Checked:
            if key not in self._chosen:
                self._chosen.append(key)
        elif key in self._chosen:
            self._chosen.remove(key)
        self._refresh_state()

    def _current_changed(self, current, _previous) -> None:
        source = self.proxy.mapToSource(current)
        item = self.model.item(source.row(), 0) if source.isValid() else None
        key = str(item.data(STORE_KEY_ROLE) or "") if item is not None else ""
        shop = self._shops.get(key)
        if shop is None:
            self.detail.setText("")
        else:
            sells = ", ".join(shop.stock_preview[:12]) if shop.stock_preview else "nothing buyable yet"
            more = f" and {len(shop.stock_preview) - 12} more" if len(shop.stock_preview) > 12 else ""
            self.detail.setText(f"{shop.display_name} ({shop.key}): {shop.line_count} line(s). Sells {sells}{more}.")
        if not self._multi:
            self._chosen = [key] if shop is not None else []
            self._refresh_state()

    def _double_clicked(self, index) -> None:
        if self._multi:
            source = self.proxy.mapToSource(index)
            item = self.model.item(source.row(), 0)
            if item is not None:
                item.setCheckState(
                    Qt.CheckState.Unchecked if item.checkState() == Qt.CheckState.Checked else Qt.CheckState.Checked
                )
            return
        if self._chosen:
            self.accept()

    def _clear(self) -> None:
        for key in tuple(self._chosen):
            self.set_checked(key, False)

    def _refresh_state(self) -> None:
        if self._multi:
            duplicates = [key for key in self._chosen if key in self._already_routed]
            text = f"Selected ({len(self._chosen)})"
            if self._chosen:
                names = [self._shops[key].display_name for key in self._chosen[:4]]
                text += ": " + ", ".join(names) + (" ..." if len(self._chosen) > 4 else "")
            if duplicates:
                text += f". {len(duplicates)} already saved as a route and will be skipped."
            self.selected_label.setText(text)
        else:
            shop = self._shops.get(self._chosen[0]) if self._chosen else None
            self.selected_label.setText(f"Selected: {shop.display_name}" if shop else "No shop selected.")
        self.accept_button.setEnabled(bool(self._chosen))


__all__ = [
    "VERIFIED_SHOP_NAMES",
    "ShopChoice",
    "ShopPickerDialog",
    "describe_shop",
]
