"""The Workspace Activity drawer's AI Connection tab: what a connected AI app is doing, live.

It shows the app's ``AiActivityModel``: a status line (off, waiting, or
which AI app is connected and since when) and one row per call, newest at
the bottom. A call repeated with the same arguments and result is one row
with a count. Failed calls are marked. Rows are rendered only while the tab
is on screen, at most once per ``_REFRESH_MS``.
"""

from __future__ import annotations

from PySide6.QtCore import QTimer, QUrl, Qt
from PySide6.QtGui import QBrush, QColor, QDesktopServices, QIcon
from PySide6.QtWidgets import (
    QAbstractItemView,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QStyle,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from cdmw.services.active_ui_translation import translate_active_ui_text
from cdmw.ui.ai_connections.activity_model import (
    CALL,
    CONNECTED,
    DISCONNECTED,
    REFUSED,
    ActivityRow,
    AiActivityModel,
)

_REFRESH_MS = 50
_ERROR_COLOR = QColor("#d9534f")
COLUMN_TIME, COLUMN_TOOL, COLUMN_ARGUMENTS, COLUMN_RESULT, COLUMN_DURATION, COLUMN_JOB = range(6)


def _log_path(model: AiActivityModel):
    if model.log_path is not None:
        return model.log_path
    try:
        from cdmw.mcp.audit import audit_log_path

        return audit_log_path()
    except Exception:
        return None


class AiConnectionView(QWidget):
    def __init__(self, model: AiActivityModel, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("CompactAiConnectionView")
        self.model = model
        self._items: dict[int, tuple[QTreeWidgetItem, int]] = {}
        self._dirty = True
        self._refresh_timer = QTimer(self)
        self._refresh_timer.setSingleShot(True)
        self._refresh_timer.setInterval(_REFRESH_MS)
        self._refresh_timer.timeout.connect(self.refresh)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 4, 0, 0)
        layout.setSpacing(4)
        top = QHBoxLayout()
        top.setContentsMargins(0, 0, 0, 0)
        top.setSpacing(6)
        self.status_label = QLabel()
        self.status_label.setObjectName("CompactAiConnectionStatus")
        self.status_label.setTextFormat(Qt.TextFormat.PlainText)
        self.status_label.setWordWrap(True)
        top.addWidget(self.status_label, stretch=1)
        self.open_log_button = QPushButton("Open Log File")
        self.open_log_button.setObjectName("CompactAiConnectionOpenLogButton")
        self.open_log_button.setToolTip("Open ai-calls.log, the AI call log this tab shows.")
        top.addWidget(self.open_log_button)
        layout.addLayout(top)

        self.calls_view = QTreeWidget()
        self.calls_view.setObjectName("CompactAiConnectionCalls")
        self.calls_view.setRootIsDecorated(False)
        self.calls_view.setUniformRowHeights(True)
        self.calls_view.setAlternatingRowColors(True)
        self.calls_view.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.calls_view.setHeaderLabels(["Time", "Tool", "Arguments", "Result", "Duration", "Job"])
        header = self.calls_view.header()
        header.setStretchLastSection(True)
        for column, width in ((COLUMN_TIME, 70), (COLUMN_TOOL, 190), (COLUMN_ARGUMENTS, 260),
                              (COLUMN_RESULT, 220), (COLUMN_DURATION, 70)):
            header.resizeSection(column, width)
        layout.addWidget(self.calls_view, stretch=1)
        self.empty_label = QLabel("No AI app has called a tool yet.")
        self.empty_label.setObjectName("CompactAiConnectionEmptyState")
        self.empty_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.empty_label.setWordWrap(True)
        layout.addWidget(self.empty_label)

        self.open_log_button.clicked.connect(self.open_log_file)
        model.changed.connect(self._schedule_refresh)
        self._show_status()
        self._show_empty_state()

    # ----- rendering -------------------------------------------------------------
    def _schedule_refresh(self) -> None:
        self._dirty = True
        self._show_status()
        if self.isVisible() and not self._refresh_timer.isActive():
            self._refresh_timer.start()

    def showEvent(self, event) -> None:  # noqa: N802
        super().showEvent(event)
        self.refresh()

    def hideEvent(self, event) -> None:  # noqa: N802
        self._refresh_timer.stop()
        super().hideEvent(event)

    def refresh(self) -> None:
        """Bring the rows up to the model's (also called directly by tests and Copy)."""

        self._refresh_timer.stop()
        self._show_status()
        if not self._dirty:
            return
        self._dirty = False
        rows = self.model.rows
        view = self.calls_view
        scrollbar = view.verticalScrollBar()
        at_bottom = scrollbar.value() >= scrollbar.maximum() - 2
        first = rows[0].serial if rows else None
        keep = {row.serial for row in rows}
        for serial in [s for s in self._items if s not in keep]:
            item, _revision = self._items.pop(serial)
            index = view.indexOfTopLevelItem(item)
            if index >= 0:
                view.takeTopLevelItem(index)
        if first is None:
            view.clear()
            self._items.clear()
        for row in rows:
            known = self._items.get(row.serial)
            if known is None:
                item = QTreeWidgetItem()
                self._fill(item, row)
                view.addTopLevelItem(item)
                self._items[row.serial] = (item, row.revision)
            elif known[1] != row.revision:
                self._fill(known[0], row)
                self._items[row.serial] = (known[0], row.revision)
        self._show_empty_state()
        if at_bottom:
            view.scrollToBottom()

    def _fill(self, item: QTreeWidgetItem, row: ActivityRow) -> None:
        item.setText(COLUMN_TIME, row.time)
        if row.kind == CALL:
            count = f" ×{row.count}" if row.count > 1 else ""
            item.setText(COLUMN_TOOL, row.tool + count)
            item.setText(COLUMN_ARGUMENTS, row.arguments)
            item.setToolTip(COLUMN_ARGUMENTS, row.arguments_full)
            item.setText(COLUMN_RESULT, row.result_text())
            item.setToolTip(COLUMN_RESULT, row.result_text())
            item.setText(COLUMN_DURATION, f"{row.duration_ms} ms")
            job = translate_active_ui_text(row.job_text()) if row.job else ""
            item.setText(COLUMN_JOB, job)
            item.setToolTip(COLUMN_JOB, job)
            if row.count > 1:
                item.setToolTip(COLUMN_TOOL, translate_active_ui_text(
                    f"Called {row.count} times in a row with the same arguments and result, last at {row.last_time}."))
        elif row.kind == CONNECTED:
            client = row.client
            if client:
                item.setText(COLUMN_TOOL, translate_active_ui_text(f"Connected: {client}"))
            else:
                item.setText(COLUMN_TOOL, translate_active_ui_text("An AI app connected"))
        elif row.kind == DISCONNECTED:
            client = row.client
            if client:
                item.setText(COLUMN_TOOL, translate_active_ui_text(f"Disconnected: {client}"))
            else:
                item.setText(COLUMN_TOOL, translate_active_ui_text("The AI app disconnected"))
        elif row.kind == REFUSED:
            item.setText(COLUMN_TOOL, translate_active_ui_text(
                "Another AI app was refused: one AI app at a time can connect."))
        error = row.is_error
        brush = QBrush(_ERROR_COLOR) if error else QBrush()
        for column in range(self.calls_view.columnCount()):
            item.setForeground(column, brush)
        icon = self.style().standardIcon(QStyle.StandardPixmap.SP_MessageBoxWarning) if error else QIcon()
        item.setIcon(COLUMN_RESULT if row.kind == CALL else COLUMN_TOOL, icon)
        item.setData(COLUMN_TIME, Qt.ItemDataRole.UserRole, row.serial)
        item.setData(COLUMN_RESULT, Qt.ItemDataRole.UserRole, "error" if error else "")

    def _show_status(self) -> None:
        model = self.model
        if model.connected:
            client = model.client
            since = model.since
            if client:
                self.status_label.setText(translate_active_ui_text(f"Connected: {client}, since {since}."))
            else:
                self.status_label.setText(translate_active_ui_text(f"An AI app is connected, since {since}."))
        elif model.listening:
            self.status_label.setText(translate_active_ui_text("Not connected. Waiting for an AI app to connect."))
        else:
            self.status_label.setText(translate_active_ui_text(
                "Not connected. AI connections are off; turn them on in Settings > AI connections."))
        dropped = model.dropped
        if dropped:
            self.status_label.setToolTip(translate_active_ui_text(
                f"{dropped} events came faster than this tab could show them and were left out. "
                "The AI call log has every call."))
        else:
            self.status_label.setToolTip("")
        path = _log_path(model)
        self.open_log_button.setEnabled(path is not None and path.is_file())

    def _show_empty_state(self) -> None:
        empty = not self.model.rows
        self.empty_label.setVisible(empty)
        self.calls_view.setVisible(not empty)

    # ----- actions -------------------------------------------------------------------
    def open_log_file(self) -> bool:
        path = _log_path(self.model)
        if path is None or not path.is_file():
            self._show_status()
            return False
        return bool(QDesktopServices.openUrl(QUrl.fromLocalFile(str(path))))

    def has_rows(self) -> bool:
        return bool(self.model.rows)

    def clear(self) -> None:
        self.model.clear()
        self.refresh()

    def text(self) -> str:
        return self.model.formatted_text()


__all__ = ["AiConnectionView"]
