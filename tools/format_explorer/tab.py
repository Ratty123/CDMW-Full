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

from html import escape
from typing import Callable, Optional

from PySide6.QtCore import QEvent, QObject, QSize, QTimer, Qt
from PySide6.QtGui import QColor, QPalette
from PySide6.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QComboBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QSplitter,
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
_TOOL_LINK_PREFIX = "cdmw-tool:"
_TOOL_KEYS = {
    "Archive Browser": "archive_browser",
    "Mesh Editor": "mesh_editor",
    "Placement & Animations": "placement_studio",
    "Texture Upscaling & Editing": "texture_workflow",
    "Texture Replacer": "replace_assistant",
    "Texture Editor": "texture_editor",
    "Translations": "translation_studio",
}


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


def linked_tool_location(location: str, *, link_color: str = "") -> str:
    """Render in-app tool names as links while leaving guidance as plain text."""

    def linked(alternative: str) -> str:
        source = alternative.strip()
        label = escape(translate_active_ui_text(source))
        tool_key = _TOOL_KEYS.get(source)
        if tool_key is None:
            return label
        style = f' style="color: {escape(link_color)}"' if link_color else ""
        return f'<a href="{_TOOL_LINK_PREFIX}{tool_key}"{style}>{label}</a>'

    return " &gt; ".join(
        " / ".join(linked(alternative) for alternative in segment.split(" / "))
        for segment in location.split(" > ")
    )


class FormatExplorerTab(QWidget):
    """A browsable view of what each game file format can and cannot do."""

    def __init__(
        self,
        parent: Optional[QWidget] = None,
        *,
        activate_tool: Optional[Callable[[str], None]] = None,
    ) -> None:
        super().__init__(parent)
        self._activate_tool = activate_tool
        self._rows: tuple[FormatRow, ...] = ()
        self._shown: tuple[FormatRow, ...] = ()
        self._natural_column_widths: tuple[int, ...] = ()
        self._applying_column_widths = False
        self._column_resize_timer = QTimer(self)
        self._column_resize_timer.setSingleShot(True)
        self._column_resize_timer.timeout.connect(self._apply_column_widths)
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

    def eventFilter(self, watched: QObject, event: QEvent) -> bool:  # noqa: N802 - Qt contract
        if (
            hasattr(self, "table")
            and watched is self.table.viewport()
            and event.type() == QEvent.Resize
        ):
            self._column_resize_timer.start(0)
        return super().eventFilter(watched, event)

    def changeEvent(self, event: QEvent) -> None:
        super().changeEvent(event)
        if event.type() == QEvent.PaletteChange and hasattr(self, "table"):
            self._refresh_tool_link_colors()

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

        self.main_splitter = QSplitter(Qt.Horizontal)
        self.main_splitter.setChildrenCollapsible(False)
        outer.addWidget(self.main_splitter, 1)

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
        # auto mode re-measured every column on each of the ~500 setItem calls a
        # refresh makes, which is what the filter checkboxes' lag was.
        header = self.table.horizontalHeader()
        header.setStretchLastSection(False)
        for column in range(self.table.columnCount()):
            header.setSectionResizeMode(column, QHeaderView.Interactive)
        self.table.itemSelectionChanged.connect(self._on_selected)
        self.table.viewport().installEventFilter(self)
        self.main_splitter.addWidget(self.table)

        self.detail = QTextBrowser()
        self.detail.setOpenExternalLinks(False)
        self.detail.setMinimumWidth(300)
        self.main_splitter.addWidget(self.detail)
        self.main_splitter.setStretchFactor(0, 7)
        self.main_splitter.setStretchFactor(1, 3)
        self.main_splitter.setSizes([980, 420])

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
                where = QTableWidgetItem("")
                where.setToolTip(location)
                link = QLabel(linked_tool_location(row.tool))
                link.setObjectName("FormatExplorerToolLink")
                link.setTextFormat(Qt.RichText)
                link.setTextInteractionFlags(Qt.LinksAccessibleByMouse | Qt.LinksAccessibleByKeyboard)
                link.setOpenExternalLinks(False)
                link.setFocusPolicy(Qt.StrongFocus)
                link.setToolTip(location)
                link.setProperty("sourceLocation", row.tool)
                link.linkActivated.connect(
                    lambda target, row_index=index: self._follow_tool_link(row_index, target)
                )
                where.setSizeHint(QSize(link.sizeHint().width() + 8, link.sizeHint().height()))
                self.table.setItem(index, 5, where)
                self.table.setCellWidget(index, 5, link)
            if rows:
                self.table.selectRow(0)
            self._measure_column_widths()
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

    def _measure_column_widths(self) -> None:
        for column in range(self.table.columnCount()):
            self.table.resizeColumnToContents(column)
        self._natural_column_widths = tuple(
            self.table.horizontalHeader().sectionSize(column)
            for column in range(self.table.columnCount())
        )
        self._apply_column_widths()

    def _apply_column_widths(self) -> None:
        if self._applying_column_widths or len(self._natural_column_widths) != self.table.columnCount():
            return
        widths = list(self._natural_column_widths)
        available = max(0, self.table.viewport().width())
        slack = available - sum(widths)
        if slack > 0:
            flexible = (2, 5)
            weight = max(1, sum(widths[column] for column in flexible))
            what_extra = round(slack * widths[2] / weight)
            widths[2] += what_extra
            widths[5] += slack - what_extra
        self._applying_column_widths = True
        try:
            header = self.table.horizontalHeader()
            for column, width in enumerate(widths):
                header.resizeSection(column, width)
        finally:
            self._applying_column_widths = False

    def _follow_tool_link(self, row_index: int, target: str) -> None:
        if not target.startswith(_TOOL_LINK_PREFIX):
            return
        tool_key = target[len(_TOOL_LINK_PREFIX):]
        if tool_key not in _TOOL_KEYS.values():
            return
        if 0 <= row_index < self.table.rowCount():
            self.table.selectRow(row_index)
        if self._activate_tool is not None:
            self._activate_tool(tool_key)

    def _refresh_tool_link_colors(self) -> None:
        selected = self.table.currentRow()
        selected_color = self.table.palette().color(QPalette.HighlightedText).name()
        for row_index in range(self.table.rowCount()):
            label = self.table.cellWidget(row_index, 5)
            if not isinstance(label, QLabel):
                continue
            location = str(label.property("sourceLocation") or "")
            label.setText(
                linked_tool_location(
                    location,
                    link_color=selected_color if row_index == selected else "",
                )
            )

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
        self._refresh_tool_link_colors()
        remaining = row.remaining.strip() or "Nothing outstanding."
        self.detail.setHtml(
            f"<h3>{row.extension} &mdash; {row.read_label.lower()}, {row.write_label.lower()}</h3>"
            f"<p><b>{row.files:,}</b> file(s) in the shipped build &middot; "
            f"{row.origin} format &middot; edited in: <b>{localized_tool_location(row.tool)}</b></p>"
            f"<p><b>What this rests on:</b> {row.evidence}</p>"
            f"<p><b>What is left:</b> {remaining}</p>"
        )
