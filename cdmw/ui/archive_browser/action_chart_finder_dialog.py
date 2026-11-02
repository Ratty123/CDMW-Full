"""Find the action chart a character uses, by character and weapon slot."""

from __future__ import annotations

from typing import Mapping, Optional, Sequence

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from cdmw.services.action_chart_edit_service import CHART_ROOT, CharacterChartRow, included_charts

_PATH_ROLE = Qt.ItemDataRole.UserRole + 1


class ActionChartFinderDialog(QDialog):
    """Lists every character package's charts; `selected_path` is the chart to edit."""

    def __init__(
        self,
        rows: Sequence[CharacterChartRow],
        *,
        available: Optional[set[str]] = None,
        includes: Optional[Mapping[str, Sequence[str]]] = None,
        parent: Optional[QWidget] = None,
    ) -> None:
        super().__init__(parent)
        self.selected_path = ""
        self._available = available
        self._includes = includes or {}
        self.setWindowTitle("Find Action Chart by Character")
        self.resize(900, 640)
        layout = QVBoxLayout(self)
        intro = QLabel(
            "Each character package names the chart for its main actions and one per weapon slot. "
            "Player_Kliff's Sword slot, for example, is upperaction/1_pc/1_phm/sword_upper. "
            "Select a chart and click Edit Chart."
        )
        intro.setWordWrap(True)
        layout.addWidget(intro)
        hint = QLabel(
            "Which chart plays depends on the weapons equipped: check the slot for that loadout and the charts it "
            "includes. Kliff's dual-wield idle, for example, comes from dualweapon_upper, which his SubWeapon chart "
            "includes."
        )
        hint.setWordWrap(True)
        layout.addWidget(hint)
        self.filter_edit = QLineEdit()
        self.filter_edit.setPlaceholderText("Filter by character, slot or chart...")
        self.filter_edit.textChanged.connect(self._filter)
        layout.addWidget(self.filter_edit)
        self.tree = QTreeWidget()
        self.tree.setHeaderLabels(["Character / slot", "Chart"])
        self.tree.setColumnWidth(0, 340)
        self.tree.itemDoubleClicked.connect(lambda _item, _column: self._edit())
        self.tree.itemSelectionChanged.connect(self._sync)
        layout.addWidget(self.tree, 1)
        buttons = QHBoxLayout()
        self.edit_button = QPushButton("Edit Chart")
        self.edit_button.setDefault(True)
        self.edit_button.clicked.connect(self._edit)
        cancel = QPushButton("Cancel")
        cancel.clicked.connect(self.reject)
        buttons.addStretch(1)
        buttons.addWidget(self.edit_button)
        buttons.addWidget(cancel)
        layout.addLayout(buttons)
        self._fill(rows)
        self._sync()

    def _fill(self, rows: Sequence[CharacterChartRow]) -> None:
        packages: dict[str, QTreeWidgetItem] = {}
        for row in rows:
            parent = packages.get(row.package)
            if parent is None:
                parent = QTreeWidgetItem([row.package, ""])
                packages[row.package] = parent
                self.tree.addTopLevelItem(parent)
            child = QTreeWidgetItem([row.slot, row.chart])
            child.setData(0, _PATH_ROLE, row.archive_path)
            if self._available is not None and row.archive_path.lower() not in self._available:
                child.setDisabled(True)
                child.setToolTip(1, "This chart is not in the loaded archives.")
            if row.main:
                font = child.font(0)
                font.setBold(True)
                child.setFont(0, font)
            parent.addChild(child)
            self._add_included(child, row.archive_path, {row.archive_path.lower()})

    def _add_included(self, item: QTreeWidgetItem, chart: str, seen: set[str]) -> None:
        """List the charts `chart` includes under it, each chart once per slot."""

        for path in self._includes.get(chart.lower(), ()):
            if path.lower() in seen:
                continue
            seen.add(path.lower())
            name = path[len(CHART_ROOT):] if path.lower().startswith(CHART_ROOT) else path
            if name.lower().endswith(".paac"):
                name = name[: -len(".paac")]
            child = QTreeWidgetItem(["includes", name])
            child.setData(0, _PATH_ROLE, path)
            child.setToolTip(1, path)
            item.addChild(child)
            self._add_included(child, path, seen)

    def _filter(self, text: str) -> None:
        needle = str(text or "").strip().lower()

        def show(item: QTreeWidgetItem, forced: bool) -> bool:
            own = not needle or forced or needle in item.text(0).lower() or needle in item.text(1).lower()
            below = False
            for index in range(item.childCount()):
                below = show(item.child(index), own and bool(needle) and forced) or below
            visible = own or below
            item.setHidden(not visible)
            item.setExpanded(bool(needle) and below)
            return visible

        for index in range(self.tree.topLevelItemCount()):
            parent = self.tree.topLevelItem(index)
            package_hit = bool(needle) and needle in parent.text(0).lower()
            visible = False
            for child_index in range(parent.childCount()):
                visible = show(parent.child(child_index), package_hit) or visible
            parent.setHidden(not visible)
            parent.setExpanded(bool(needle) and visible)

    def _current_path(self) -> str:
        item = self.tree.currentItem()
        if item is None or item.isDisabled():
            return ""
        return str(item.data(0, _PATH_ROLE) or "")

    def _sync(self) -> None:
        self.edit_button.setEnabled(bool(self._current_path()))

    def _edit(self) -> None:
        path = self._current_path()
        if path:
            self.selected_path = path
            self.accept()


__all__ = ["ActionChartFinderDialog"]
