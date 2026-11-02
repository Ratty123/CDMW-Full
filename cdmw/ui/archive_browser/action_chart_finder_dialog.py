"""Find the action chart a character uses, by character and weapon slot."""

from __future__ import annotations

from typing import Optional, Sequence

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

from cdmw.services.action_chart_edit_service import CharacterChartRow

_PATH_ROLE = Qt.ItemDataRole.UserRole + 1


class ActionChartFinderDialog(QDialog):
    """Lists every character package's charts; `selected_path` is the chart to edit."""

    def __init__(
        self,
        rows: Sequence[CharacterChartRow],
        *,
        available: Optional[set[str]] = None,
        parent: Optional[QWidget] = None,
    ) -> None:
        super().__init__(parent)
        self.selected_path = ""
        self._available = available
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

    def _filter(self, text: str) -> None:
        needle = str(text or "").strip().lower()
        for index in range(self.tree.topLevelItemCount()):
            parent = self.tree.topLevelItem(index)
            package_hit = needle in parent.text(0).lower()
            visible = False
            for child_index in range(parent.childCount()):
                child = parent.child(child_index)
                hit = not needle or package_hit or needle in child.text(0).lower() or needle in child.text(1).lower()
                child.setHidden(not hit)
                visible = visible or hit
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
