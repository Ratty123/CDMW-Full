"""Format Explorer: what can I mod, and where do I do it?

Everything this shows already existed as data. `schemas/archive_content_capabilities.v1.json`
records, for all 141 formats, how far each is read, how far it is written, what the claim
rests on, and what is left. None of that was reachable from inside the app, so the
question a new modder actually asks -- *can I change this, and with what?* -- had no
answer short of reading a JSON file in a schemas directory.

The panel defaults to what is useful rather than what is complete: formats the build
actually ships, most files first. The entries the game does not contain are one
checkbox away, not in the way.
"""

from __future__ import annotations

from typing import Optional

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QComboBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QTableWidget,
    QTableWidgetItem,
    QTextBrowser,
    QVBoxLayout,
    QWidget,
)

from cdmw.services.active_ui_translation import (
    active_ui_localizer,
    translate_active_ui_text,
)

from .catalogue import FormatRow, filter_rows, groups, headline, load_rows

_ALL = "All areas"
_EDITABLE = QColor(58, 74, 42)
_READ_ONLY = QColor(70, 62, 40)


def localized_tool_location(location: str) -> str:
    """A location, translated the way the interface translates its own labels.

    Each ` > ` segment — and each ` / ` alternative inside one — is a tab label
    or a context-action name with its own catalog entry, so translating them one
    by one keeps this column reading exactly like the tabs and menus it points
    at. The joined path itself is deliberately not a catalog key.
    """

    return " > ".join(
        " / ".join(
            translate_active_ui_text(alternative.strip())
            for alternative in segment.split(" / ")
        )
        for segment in location.split(" > ")
    )


class FormatExplorerTab(QWidget):
    """A browsable view of what each game file format can and cannot do."""

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self._rows: tuple[FormatRow, ...] = ()
        self._shown: tuple[FormatRow, ...] = ()
        self._build_ui()
        # The "Where to edit it" cells are composed of translated label segments
        # at fill time, so a language switch must refill them; nothing else in
        # the table re-renders composed text.
        localizer = active_ui_localizer()
        signal = getattr(localizer, "language_changed", None)
        if signal is not None and hasattr(signal, "connect"):
            signal.connect(self._on_language_changed)
        self.reload()

    def _on_language_changed(self, *_args) -> None:
        self._refresh()

    # ------------------------------------------------------------------ widgets

    def _build_ui(self) -> None:
        outer = QVBoxLayout(self)
        outer.setContentsMargins(8, 8, 8, 8)
        outer.setSpacing(6)

        self.headline_label = QLabel("")
        self.headline_label.setWordWrap(True)
        outer.addWidget(self.headline_label)

        controls = QHBoxLayout()
        controls.addWidget(QLabel("Find"))
        self.search_box = QLineEdit()
        self.search_box.setPlaceholderText("Extension, area, or tool — e.g. texture, mesh, .paa")
        self.search_box.setClearButtonEnabled(True)
        self.search_box.textChanged.connect(self._refresh)
        controls.addWidget(self.search_box, 2)
        controls.addWidget(QLabel("Area"))
        self.group_box = QComboBox()
        self.group_box.currentIndexChanged.connect(self._refresh)
        controls.addWidget(self.group_box, 1)
        self.editable_only = QCheckBox("Only what I can edit")
        self.editable_only.toggled.connect(self._refresh)
        controls.addWidget(self.editable_only)
        self.include_absent = QCheckBox("Include formats the game does not ship")
        self.include_absent.toggled.connect(self._refresh)
        controls.addWidget(self.include_absent)
        controls.addStretch(1)
        self.count_label = QLabel("")
        controls.addWidget(self.count_label)
        outer.addLayout(controls)

        self.table = QTableWidget(0, 6)
        self.table.setHorizontalHeaderLabels(
            ["Format", "Files", "What it is", "Read", "Write", "Where to edit it"]
        )
        self.table.verticalHeader().setVisible(False)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SingleSelection)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.setWordWrap(False)
        self.table.setAlternatingRowColors(True)
        self.table.setTextElideMode(Qt.ElideRight)
        # Interactive with one sizing pass after each fill, not ResizeToContents:
        # auto mode re-measured four columns on every one of the ~500 setItem
        # calls a refresh makes, which is what the filter checkboxes' lag was.
        header = self.table.horizontalHeader()
        for column in (0, 1, 3, 4, 5):
            header.setSectionResizeMode(column, QHeaderView.Interactive)
        header.setSectionResizeMode(2, QHeaderView.Stretch)
        self.table.itemSelectionChanged.connect(self._on_selected)
        outer.addWidget(self.table, 3)

        self.detail = QTextBrowser()
        self.detail.setOpenExternalLinks(False)
        self.detail.setMinimumHeight(150)
        outer.addWidget(self.detail, 1)

    # ------------------------------------------------------------------ loading

    def reload(self) -> None:
        try:
            self._rows = load_rows()
        except Exception as error:  # noqa: BLE001 - never take the window down
            self.headline_label.setText(f"Could not read the capability manifest: {error}")
            return
        self.headline_label.setText(headline(self._rows))
        self.group_box.blockSignals(True)
        self.group_box.clear()
        self.group_box.addItem(_ALL, None)
        for group in groups(self._rows):
            self.group_box.addItem(group.replace("_", " "), group)
        self.group_box.blockSignals(False)
        self._refresh()

    def _refresh(self) -> None:
        if not self._rows:
            return
        rows = filter_rows(
            self._rows,
            self.search_box.text(),
            editable_only=self.editable_only.isChecked(),
            shipped_only=not self.include_absent.isChecked(),
            group=self.group_box.currentData(),
        )
        self._shown = rows
        self.count_label.setText(f"{len(rows)} format(s)")
        # One repaint and one selection change per refresh. Filling item by item
        # with updates live repainted per cell, and every row the shrinking
        # selection crossed re-rendered the detail pane on the way.
        self.table.setUpdatesEnabled(False)
        self.table.blockSignals(True)
        try:
            self.table.setRowCount(len(rows))
            for index, row in enumerate(rows):
                extension = QTableWidgetItem(row.extension)
                if row.moddable:
                    extension.setBackground(_EDITABLE)
                elif row.shipped and row.decode != "none":
                    extension.setBackground(_READ_ONLY)
                self.table.setItem(index, 0, extension)
                files = QTableWidgetItem(f"{row.files:,}" if row.files else "—")
                files.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
                self.table.setItem(index, 1, files)
                self.table.setItem(index, 2, QTableWidgetItem(
                    f"{row.role} · {row.group.replace('_', ' ')}"))
                self.table.setItem(index, 3, QTableWidgetItem(row.read_label))
                self.table.setItem(index, 4, QTableWidgetItem(row.write_label))
                location = localized_tool_location(row.tool)
                where = QTableWidgetItem(location)
                where.setToolTip(location)
                self.table.setItem(index, 5, where)
            if rows:
                self.table.selectRow(0)
            for column in (0, 1, 3, 4, 5):
                self.table.resizeColumnToContents(column)
        finally:
            self.table.blockSignals(False)
            self.table.setUpdatesEnabled(True)
        if rows:
            # Refresh the detail directly rather than relying on the selection signal:
            # when row 0 was already selected before the filter changed, Qt emits
            # nothing and the pane would keep describing the previous format.
            self._on_selected()
        else:
            self.detail.setHtml("<p>Nothing matches that filter.</p>")

    # ---------------------------------------------------------------- selection

    def selected_row(self) -> Optional[FormatRow]:
        rows = self.table.selectionModel().selectedRows() if self.table.selectionModel() else []
        if not rows:
            return None
        index = rows[0].row()
        return self._shown[index] if 0 <= index < len(self._shown) else None

    def _on_selected(self) -> None:
        row = self.selected_row()
        if row is None:
            return
        remaining = row.remaining.strip() or "Nothing outstanding."
        self.detail.setHtml(
            f"<h3>{row.extension} &mdash; {row.read_label.lower()}, {row.write_label.lower()}</h3>"
            f"<p><b>{row.files:,}</b> file(s) in the shipped build &middot; "
            f"{row.origin} format &middot; edited in: <b>{localized_tool_location(row.tool)}</b></p>"
            f"<p><b>What this rests on:</b> {row.evidence}</p>"
            f"<p><b>What is left:</b> {remaining}</p>"
        )
