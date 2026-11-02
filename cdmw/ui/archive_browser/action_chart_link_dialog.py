"""Pick the other charts that play a clip, to change that clip in them as well."""

from __future__ import annotations

from pathlib import PurePosixPath
from typing import Callable, Optional, Sequence

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QAbstractItemView,
    QDialog,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from cdmw.services.action_chart_edit_service import ClipUse

_PATH_ROLE = Qt.ItemDataRole.UserRole + 1


class ActionChartLinkDialog(QDialog):
    """`selected_charts` and `new_clip` hold the choice after Accept."""

    def __init__(
        self,
        clip: str,
        uses: Sequence[ClipUse],
        *,
        new_clip: str = "",
        users_of: Optional[Callable[[str], Sequence[str]]] = None,
        parent: Optional[QWidget] = None,
    ) -> None:
        super().__init__(parent)
        self.selected_charts: tuple[str, ...] = ()
        self.new_clip = ""
        self._clip = clip
        self.setWindowTitle("Other Charts Playing This Clip")
        self.resize(900, 520)
        layout = QVBoxLayout(self)
        intro = QLabel(
            f"{PurePosixPath(clip).name} is also played by these charts. The game picks a chart from the character "
            "and the weapon in hand, so the animation you see in game may come from one of them. Ticked charts get "
            "the same clip change everywhere they play it, in the same mod."
        )
        intro.setWordWrap(True)
        layout.addWidget(intro)
        row = QHBoxLayout()
        row.addWidget(QLabel("Replace with:"))
        self.new_clip_edit = QLineEdit(new_clip)
        row.addWidget(self.new_clip_edit, 1)
        layout.addLayout(row)
        self.table = QTableWidget(len(uses), 3)
        self.table.setHorizontalHeaderLabels(["Chart", "Animations", "Used by"])
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.verticalHeader().setVisible(False)
        header = self.table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)
        for position, use in enumerate(uses):
            chart = QTableWidgetItem(use.chart.removeprefix("actionchart/bin__/"))
            chart.setToolTip(use.chart)
            chart.setData(_PATH_ROLE, use.chart)
            chart.setFlags(chart.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            chart.setCheckState(Qt.CheckState.Checked)
            users = ", ".join(users_of(use.chart)) if users_of is not None else ""
            self.table.setItem(position, 0, chart)
            self.table.setItem(position, 1, QTableWidgetItem(str(use.animations)))
            self.table.setItem(position, 2, QTableWidgetItem(users))
        layout.addWidget(self.table, 1)
        self.error_label = QLabel()
        self.error_label.setStyleSheet("color: #d9534f;")
        layout.addWidget(self.error_label)
        buttons = QHBoxLayout()
        check_all = QPushButton("Check All")
        check_all.clicked.connect(lambda: self._check_all(True))
        uncheck_all = QPushButton("Uncheck All")
        uncheck_all.clicked.connect(lambda: self._check_all(False))
        self.add_button = QPushButton("Change in Ticked Charts")
        self.add_button.setDefault(True)
        self.add_button.clicked.connect(self._accept)
        cancel = QPushButton("Cancel")
        cancel.clicked.connect(self.reject)
        buttons.addWidget(check_all)
        buttons.addWidget(uncheck_all)
        buttons.addStretch(1)
        buttons.addWidget(self.add_button)
        buttons.addWidget(cancel)
        layout.addLayout(buttons)

    def _check_all(self, checked: bool) -> None:
        state = Qt.CheckState.Checked if checked else Qt.CheckState.Unchecked
        for position in range(self.table.rowCount()):
            self.table.item(position, 0).setCheckState(state)

    def _accept(self) -> None:
        new_clip = self.new_clip_edit.text().strip().replace("\\", "/")
        charts = tuple(
            str(self.table.item(position, 0).data(_PATH_ROLE))
            for position in range(self.table.rowCount())
            if self.table.item(position, 0).checkState() == Qt.CheckState.Checked
        )
        if not new_clip or new_clip == self._clip:
            self.error_label.setText("Enter the clip these charts should play instead.")
            return
        if not charts:
            self.error_label.setText("Tick at least one chart.")
            return
        self.new_clip, self.selected_charts = new_clip, charts
        self.accept()


__all__ = ["ActionChartLinkDialog"]
