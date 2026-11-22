"""Browse stored archive facts alongside current CDMW application workflows."""

from __future__ import annotations

from html import escape
from typing import Callable, Optional

from PySide6.QtCore import QEvent, QObject, QSize, QTimer, Qt
from PySide6.QtGui import QColor, QFont, QFontMetrics, QPalette
from PySide6.QtWidgets import (
    QAbstractItemView,
    QApplication,
    QCheckBox,
    QComboBox,
    QFrame,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QSizePolicy,
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

from .catalogue import NO_REMAINING_NOTE, FormatRow, detail_text_segments, filter_rows, groups, headline, load_rows
from .workflows import OPERATION_LABELS

_ALL = "All areas"
_EDITABLE = QColor(63, 143, 69, 72)
_READ_ONLY = QColor(161, 122, 44, 72)
_TOOL_LINK_PREFIX = "cdmw-tool:"
_TOOL_KEYS = {
    "Browse Archives": "archive_browser",
    "Mesh Editor": "mesh_editor",
    "Placement & Animations": "placement_studio",
    "Texture Upscaling & Editing": "texture_workflow",
    "Texture Replacer": "replace_assistant",
    "Textures": "textures",
    "Edit Translations": "translation_studio",
    "Create New Item": "new_item_studio",
    "Mod Management": "mod_management",
}


def _active_palette(widget: QWidget) -> QPalette:
    """Return the live application palette so theme switches are never masked by cached widget palettes."""

    app = QApplication.instance()
    if app is not None:
        return app.palette()
    return widget.palette()


def _semantic_colors(palette: QPalette) -> dict[str, QColor]:
    """Return theme-adaptive semantic colors for Read/import and Edit/output states."""

    base = palette.color(QPalette.Base)
    is_dark = base.lightnessF() < 0.5
    muted = palette.color(QPalette.PlaceholderText)
    if not muted.isValid() or muted == base:
        muted = QColor("#9aa4b2" if is_dark else "#525a66")
    if is_dark:
        return {
            "good": QColor("#4ade80"),
            "warn": QColor("#fbbf24"),
            "muted": muted,
            "good_bg": QColor(63, 143, 69, 64),
            "warn_bg": QColor(180, 128, 36, 56),
        }
    return {
        "good": QColor("#146c32"),
        "warn": QColor("#9a4406"),
        "muted": muted,
        "good_bg": QColor(22, 130, 56, 32),
        "warn_bg": QColor(180, 108, 12, 32),
    }


def _read_tone(row: FormatRow) -> str:
    if row.decode == "full" or row.read_label == "Fully read":
        return "good"
    if row.decode == "partial" or row.read_label in ("Partly read", "Via Blender"):
        return "warn"
    return "muted"


def _write_tone(row: FormatRow) -> str:
    if row.write == "full" and row.moddable:
        return "good"
    if row.moddable or row.write == "constrained":
        return "warn"
    return "muted"


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


def localized_detail_text(text: str) -> str:
    return "".join(translate_active_ui_text(part) for part in detail_text_segments(text))


def linked_tool_location(
    location: str,
    *,
    link_color: str = "",
    text_color: str = "",
    bold_links: bool = False,
) -> str:
    """Render in-app tool names as links while leaving guidance as plain text."""

    def linked(alternative: str) -> str:
        source = alternative.strip()
        label = escape(translate_active_ui_text(source))
        tool_key = _TOOL_KEYS.get(source)
        if tool_key is None:
            return label
        parts: list[str] = []
        if link_color:
            parts.append(f"color: {escape(link_color)}")
        if bold_links:
            parts.append("font-weight: 600")
        parts.append("text-decoration: underline")
        style = f' style="{"; ".join(parts)}"'
        return f'<a href="{_TOOL_LINK_PREFIX}{tool_key}"{style}>{label}</a>'

    rendered = " &gt; ".join(
        " / ".join(linked(alternative) for alternative in segment.split(" / "))
        for segment in location.split(" > ")
    )
    if text_color:
        return f'<span style="color: {escape(text_color)}">{rendered}</span>'
    return rendered


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
        if hasattr(self, "table"):
            if watched is self.table.viewport() and event.type() == QEvent.Resize:
                self._column_resize_timer.start(0)
            elif watched is self.table and event.type() in (QEvent.FocusIn, QEvent.FocusOut):
                self._refresh_tool_link_colors()
        return super().eventFilter(watched, event)

    def showEvent(self, event: QEvent) -> None:
        super().showEvent(event)
        if hasattr(self, "table"):
            self._apply_semantic_colors()
            self._refresh_tool_link_colors()
            QTimer.singleShot(0, self._measure_column_widths)

    def changeEvent(self, event: QEvent) -> None:
        super().changeEvent(event)
        if hasattr(self, "table"):
            if event.type() in (
                QEvent.PaletteChange,
                QEvent.ApplicationPaletteChange,
                QEvent.StyleChange,
            ):
                self._apply_semantic_colors()
                self._refresh_tool_link_colors()
                if self.selected_row() is not None:
                    self._on_selected()
            if event.type() in (QEvent.FontChange, QEvent.StyleChange):
                QTimer.singleShot(0, self._measure_column_widths)

    # ------------------------------------------------------------------ widgets

    def _build_ui(self) -> None:
        outer = QVBoxLayout(self)
        outer.setContentsMargins(10, 10, 10, 10)
        outer.setSpacing(8)

        toolbar_card = QFrame()
        toolbar_card.setProperty("surfaceCard", True)
        toolbar_layout = QVBoxLayout(toolbar_card)
        toolbar_layout.setContentsMargins(10, 8, 10, 8)
        toolbar_layout.setSpacing(6)

        controls = QHBoxLayout()
        controls.setSpacing(8)
        controls.addWidget(QLabel("Find"))
        self.search_box = QLineEdit()
        self.search_box.setPlaceholderText("Extension, area, tool or operation (e.g. texture, mesh, .paa)")
        self.search_box.setClearButtonEnabled(True)
        self.search_box.textChanged.connect(self._refresh)
        controls.addWidget(self.search_box, 3)
        controls.addWidget(QLabel("Area"))
        self.group_box = QComboBox()
        self.group_box.setProperty("_i18n_translate_combo_items", True)
        self.group_box.currentIndexChanged.connect(self._refresh)
        controls.addWidget(self.group_box, 1)
        self.count_label = QLabel("")
        self.count_label.setObjectName("HintLabel")
        controls.addWidget(self.count_label)
        toolbar_layout.addLayout(controls)

        filter_row = QHBoxLayout()
        filter_row.setSpacing(12)
        self.editable_only = QCheckBox("Only what I can edit")
        self.editable_only.setToolTip(
            "Includes supported bounded edits and working-mesh edits. Import, export or package creation alone does not qualify."
        )
        self.editable_only.toggled.connect(self._refresh)
        filter_row.addWidget(self.editable_only)
        self.include_absent = QCheckBox("Include application and non-shipped formats")
        self.include_absent.toggled.connect(self._refresh)
        filter_row.addWidget(self.include_absent)
        filter_row.addStretch(1)
        toolbar_layout.addLayout(filter_row)

        self.headline_label = QLabel("")
        self.headline_label.setObjectName("HintLabel")
        self.headline_label.setWordWrap(True)
        toolbar_layout.addWidget(self.headline_label)
        outer.addWidget(toolbar_card)

        self.main_splitter = QSplitter(Qt.Horizontal)
        self.main_splitter.setChildrenCollapsible(False)
        outer.addWidget(self.main_splitter, 1)

        table_card = QFrame()
        table_card.setProperty("surfaceCard", True)
        table_card_layout = QVBoxLayout(table_card)
        table_card_layout.setContentsMargins(0, 0, 0, 0)
        table_card_layout.setSpacing(0)

        self.table = QTableWidget(0, 6)
        self.table.setHorizontalHeaderLabels(
            ["Format", "Files", "What it is", "Read / import", "Edit / output", "Where to use it"]
        )
        self.table.verticalHeader().setVisible(False)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SingleSelection)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.setWordWrap(False)
        self.table.setShowGrid(False)
        self.table.setAlternatingRowColors(False)
        self.table.setTextElideMode(Qt.ElideRight)
        self.table.setVerticalScrollMode(QAbstractItemView.ScrollPerPixel)
        self.table.setHorizontalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        self.table.setProperty("_cdmwKeepFixedColumns", True)
        self.table.setProperty("_cdmwKeepElide", True)
        # Interactive with one sizing pass after each fill, not ResizeToContents:
        # auto mode re-measured every column on each of the ~500 setItem calls a
        # refresh makes, which is what the filter checkboxes' lag was.
        header = self.table.horizontalHeader()
        header.setStretchLastSection(False)
        for column in range(self.table.columnCount()):
            header.setSectionResizeMode(column, QHeaderView.Interactive)
        self.table.itemSelectionChanged.connect(self._on_selected)
        self.table.installEventFilter(self)
        self.table.viewport().installEventFilter(self)
        table_card_layout.addWidget(self.table)
        self.main_splitter.addWidget(table_card)

        self.detail = QTextBrowser()
        self.detail.setOpenExternalLinks(False)
        self.detail.setOpenLinks(False)
        self.detail.anchorClicked.connect(
            lambda url: self._follow_tool_link(self.table.currentRow(), url.toString())
        )
        self.detail.setMinimumWidth(250)
        self.main_splitter.addWidget(self.detail)
        self.main_splitter.setStretchFactor(0, 77)
        self.main_splitter.setStretchFactor(1, 23)
        self.main_splitter.setSizes([940, 270])

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
        selected = self.selected_row()
        selected_extension = selected.extension if selected is not None else None
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
                self.table.setItem(index, 0, extension)
                files = QTableWidgetItem(
                    f"{row.files:,}" if row.files is not None else translate_active_ui_text("N/A")
                )
                files.setToolTip(translate_active_ui_text(
                    "Application format; archive count does not apply."
                    if row.files is None else "File count from the stored archive inventory."
                ))
                files.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
                self.table.setItem(index, 1, files)
                self.table.setItem(index, 2, QTableWidgetItem(
                    f"{translate_active_ui_text(row.role)} · "
                    f"{translate_active_ui_text(row.group.replace('_', ' '))}"))
                self.table.setItem(index, 3, QTableWidgetItem(translate_active_ui_text(row.read_label)))
                self.table.setItem(index, 4, QTableWidgetItem(translate_active_ui_text(row.write_label)))
                location = localized_tool_location(row.tool)
                guidance = localized_detail_text(row.workflow.prerequisites)
                tooltip = location + ("\n\n" + guidance if guidance else "")
                where = QTableWidgetItem("")
                where.setToolTip(tooltip)
                link = QLabel(linked_tool_location(row.tool))
                link.setObjectName("FormatExplorerToolLink")
                link.setStyleSheet("QLabel#FormatExplorerToolLink { background: transparent; padding: 0px 8px; }")
                link.setTextFormat(Qt.RichText)
                link.setTextInteractionFlags(Qt.LinksAccessibleByMouse | Qt.LinksAccessibleByKeyboard)
                link.setOpenExternalLinks(False)
                link.setFocusPolicy(Qt.StrongFocus)
                link.setMinimumWidth(0)
                link.setToolTip(tooltip)
                link.setProperty("sourceLocation", row.tool)
                link.linkActivated.connect(
                    lambda target, row_index=index: self._follow_tool_link(row_index, target)
                )
                where_width = max(link.sizeHint().width() + 16, self.table.fontMetrics().horizontalAdvance(location) + 28)
                where.setSizeHint(QSize(where_width, max(24, link.sizeHint().height())))
                self.table.setItem(index, 5, where)
                self.table.setCellWidget(index, 5, link)
            self._apply_semantic_colors()
            if rows:
                self.table.selectRow(next(
                    (index for index, row in enumerate(rows) if row.extension == selected_extension), 0,
                ))
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

    def _apply_semantic_colors(self) -> None:
        colors = _semantic_colors(_active_palette(self.table))
        strong_font = QFont(self.table.font())
        strong_font.setWeight(QFont.Weight.DemiBold)
        normal_font = QFont(self.table.font())
        for index, row in enumerate(self._shown):
            ext_item = self.table.item(index, 0)
            if ext_item is not None:
                if row.moddable:
                    ext_item.setBackground(colors["good_bg"])
                    ext_item.setForeground(colors["good"])
                    ext_item.setFont(strong_font)
                elif row.shipped and row.decode != "none":
                    ext_item.setBackground(colors["warn_bg"])
                    ext_item.setForeground(colors["warn"])
                    ext_item.setFont(normal_font)
                else:
                    ext_item.setData(Qt.ItemDataRole.BackgroundRole, None)
                    ext_item.setData(Qt.ItemDataRole.ForegroundRole, None)
                    ext_item.setFont(normal_font)
            read_item = self.table.item(index, 3)
            if read_item is not None:
                tone = _read_tone(row)
                read_item.setForeground(colors[tone])
                read_item.setFont(strong_font if tone != "muted" else normal_font)
            write_item = self.table.item(index, 4)
            if write_item is not None:
                tone = _write_tone(row)
                write_item.setForeground(colors[tone])
                write_item.setFont(strong_font if tone != "muted" else normal_font)

    def _measure_column_widths(self) -> None:
        header = self.table.horizontalHeader()
        h_metrics = header.fontMetrics()
        c_metrics = self.table.fontMetrics()
        bold_font = QFont(self.table.font())
        bold_font.setWeight(QFont.Weight.DemiBold)
        b_metrics = QFontMetrics(bold_font)
        caps = (120, 86, 210, 116, 120, 320)
        measured: list[int] = []
        for column in range(self.table.columnCount()):
            header_text = self.table.horizontalHeaderItem(column).text() if self.table.horizontalHeaderItem(column) else ""
            width = h_metrics.horizontalAdvance(header_text) + 28
            if column == 5:
                for row_index in range(self.table.rowCount()):
                    label = self.table.cellWidget(row_index, 5)
                    if isinstance(label, QLabel):
                        location = localized_tool_location(str(label.property("sourceLocation") or ""))
                        width = max(width, b_metrics.horizontalAdvance(location) + 26)
            else:
                metrics = b_metrics if column in (0, 3, 4) else c_metrics
                for row_index in range(self.table.rowCount()):
                    item = self.table.item(row_index, column)
                    if item is not None:
                        width = max(width, metrics.horizontalAdvance(item.text()) + 32)
            measured.append(min(width, caps[column]))
        self._natural_column_widths = tuple(measured)
        self._apply_column_widths()

    def _apply_column_widths(self) -> None:
        if self._applying_column_widths or len(self._natural_column_widths) != self.table.columnCount():
            return
        widths = list(self._natural_column_widths)
        header = self.table.horizontalHeader()
        h_metrics = header.fontMetrics()
        where_header = self.table.horizontalHeaderItem(5).text() if self.table.horizontalHeaderItem(5) else "Where to use it"
        min_where = max(h_metrics.horizontalAdvance(where_header) + 24, 210)
        widths[5] = max(widths[5], min_where)
        available = max(0, self.table.viewport().width())
        slack = available - sum(widths)
        if slack > 0:
            what_extra = round(slack * 0.25)
            widths[2] += what_extra
            widths[5] += slack - what_extra
        elif available > 0 and slack < 0:
            deficit = -slack
            shrink_what = min(deficit, max(0, widths[2] - 140))
            widths[2] -= shrink_what
            deficit -= shrink_what
            if deficit > 0:
                shrink_where = min(deficit, max(0, widths[5] - min_where))
                widths[5] -= shrink_where
        self._applying_column_widths = True
        try:
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
        palette = _active_palette(self.table)
        colors = _semantic_colors(palette)
        # Unified table selection uses accent_soft + text_strong (ButtonText in app palette)
        # for both active and inactive rows, so selected links stay high-contrast in every theme.
        selected_text = palette.color(QPalette.ButtonText).name()
        selected_link = selected_text
        normal_link = palette.color(QPalette.Link).name()
        muted_text = colors["muted"].name()
        for row_index in range(self.table.rowCount()):
            label = self.table.cellWidget(row_index, 5)
            if not isinstance(label, QLabel):
                continue
            location = str(label.property("sourceLocation") or "")
            is_selected = row_index == selected
            if is_selected:
                html = linked_tool_location(
                    location,
                    link_color=selected_link,
                    text_color=selected_text,
                    bold_links=True,
                )
            else:
                has_link = any(
                    alt.strip() in _TOOL_KEYS
                    for seg in location.split(" > ")
                    for alt in seg.split(" / ")
                )
                html = linked_tool_location(
                    location,
                    link_color=normal_link,
                    text_color="" if has_link else muted_text,
                )
            label.setText(html)

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
            self.detail.clear()
            return
        self._refresh_tool_link_colors()
        link_color = _active_palette(self.detail).color(QPalette.Link).name()
        remaining = row.remaining.strip() or NO_REMAINING_NOTE
        if row.files is None:
            presence = translate_active_ui_text("Application format; archive count does not apply.")
        else:
            presence = translate_active_ui_text(
                "{count} file(s) in the stored archive inventory."
            ).format(count=f"{row.files:,}")
        operations = "".join(
            f"<li><b>{escape(translate_active_ui_text(OPERATION_LABELS[operation.kind]))}:</b> "
            f"{escape(localized_detail_text(operation.description))}</li>"
            for operation in row.workflow.operations
        )
        limits = "".join(
            f"<li>{escape(localized_detail_text(note))}</li>"
            for note in row.workflow.limits
        )
        workflow_html = (
            f"<p><b>{translate_active_ui_text('Supported workflows')}</b></p><ul>{operations}</ul>"
            if operations else ""
        )
        prerequisites_html = (
            f"<p><b>{translate_active_ui_text('Before using this format')}</b><br>"
            f"{escape(localized_detail_text(row.workflow.prerequisites))}</p>"
            if row.workflow.prerequisites else ""
        )
        limits_html = (
            f"<p><b>{translate_active_ui_text('Editing limits')}</b></p><ul>{limits}</ul>"
            if limits else ""
        )
        self.detail.setHtml(
            f"<h3>{escape(row.extension)}: {escape(translate_active_ui_text(row.read_label))}, "
            f"{escape(translate_active_ui_text(row.write_label))}</h3>"
            f"<p>{escape(presence)}</p>"
            f"<p><b>{translate_active_ui_text('Where to use it')}:</b> {linked_tool_location(row.tool, link_color=link_color)}</p>"
            f"{workflow_html}{prerequisites_html}{limits_html}"
            f"<p><b>{translate_active_ui_text('What this rests on:')}</b> {escape(localized_detail_text(row.evidence))}</p>"
            f"<p><b>{translate_active_ui_text('What is left:')}</b> {escape(localized_detail_text(remaining))}</p>"
        )
