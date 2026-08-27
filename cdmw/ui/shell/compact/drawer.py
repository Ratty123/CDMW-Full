"""Collapsed-by-default Activity and Current Tool Log drawer."""

from __future__ import annotations

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QFont, QTextDocument
from PySide6.QtWidgets import (
    QApplication,
    QFrame,
    QHBoxLayout,
    QLabel,
    QPlainTextEdit,
    QPlainTextDocumentLayout,
    QPushButton,
    QStackedWidget,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from cdmw.ui.shell.compact.activity import ActivityHistory, ToolLogAdapter


class CompactActivityDrawer(QFrame):
    def __init__(self, history: ActivityHistory, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("CompactActivityDrawer")
        self.setMinimumHeight(168)
        self.setMaximumHeight(280)
        self._history = history
        self._tool_adapter = ToolLogAdapter("", "")
        self._connected_document: QTextDocument | None = None
        self._log_font: QFont | None = None
        self._empty_document = QTextDocument(self)
        self._empty_document.setDocumentLayout(QPlainTextDocumentLayout(self._empty_document))
        self._refresh_timer = QTimer(self)
        self._refresh_timer.setSingleShot(True)
        self._refresh_timer.setInterval(40)
        self._refresh_timer.timeout.connect(self._refresh_activity_text)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 6, 10, 8)
        layout.setSpacing(6)
        top_row = QHBoxLayout()
        top_row.setContentsMargins(0, 0, 0, 0)
        top_row.setSpacing(6)
        self.title_label = QLabel("Workspace Activity")
        self.title_label.setObjectName("CompactDrawerTitle")
        top_row.addWidget(self.title_label)
        top_row.addStretch(1)
        self.clear_button = QPushButton("Clear")
        self.clear_button.setObjectName("CompactDrawerClearButton")
        self.copy_button = QPushButton("Copy")
        self.copy_button.setObjectName("CompactDrawerCopyButton")
        top_row.addWidget(self.clear_button)
        top_row.addWidget(self.copy_button)
        layout.addLayout(top_row)

        self.tabs = QTabWidget()
        self.tabs.setObjectName("CompactDrawerTabs")
        self.activity_view = QPlainTextEdit()
        self.activity_view.setObjectName("CompactActivityView")
        self.activity_view.setReadOnly(True)
        self.activity_view.setPlaceholderText("Activity will appear here as tools report status.")
        self.tabs.addTab(self.activity_view, "Activity")

        self.tool_log_stack = QStackedWidget()
        self.tool_log_empty_label = QLabel("No log is available for this tool.")
        self.tool_log_empty_label.setObjectName("CompactToolLogEmptyState")
        self.tool_log_empty_label.setWordWrap(True)
        self.tool_log_empty_label.setAlignment(Qt.AlignCenter)
        self.tool_log_view = QPlainTextEdit()
        self.tool_log_view.setObjectName("CompactCurrentToolLogView")
        self.tool_log_view.setReadOnly(True)
        self.tool_log_stack.addWidget(self.tool_log_empty_label)
        self.tool_log_stack.addWidget(self.tool_log_view)
        self.tabs.addTab(self.tool_log_stack, "Current Tool Log")
        layout.addWidget(self.tabs, stretch=1)

        self.clear_button.clicked.connect(self._clear_current_view)
        self.copy_button.clicked.connect(self._copy_current_view)
        self.tabs.currentChanged.connect(self._update_action_state)
        history.changed.connect(self._schedule_activity_refresh)
        history.cleared.connect(self._refresh_activity_text)
        self._refresh_activity_text()
        self._update_action_state()

    def _schedule_activity_refresh(self, _event: object) -> None:
        if self.isVisible():
            self._refresh_timer.stop()
            self._refresh_activity_text()
            return
        self._refresh_timer.start()

    def _refresh_activity_text(self) -> None:
        self.activity_view.setPlainText(self._history.formatted_text())
        scrollbar = self.activity_view.verticalScrollBar()
        scrollbar.setValue(scrollbar.maximum())
        self._update_action_state()

    def _disconnect_document(self) -> None:
        if self._connected_document is None:
            return
        try:
            self._connected_document.contentsChanged.disconnect(self._update_tool_log_empty_state)
        except (RuntimeError, TypeError):
            pass
        self._connected_document = None

    def set_tool_log(self, adapter: ToolLogAdapter) -> None:
        self._disconnect_document()
        self._tool_adapter = adapter
        document = adapter.document or self._empty_document
        self.tool_log_view.setDocument(document)
        if self._log_font is not None:
            self.tool_log_view.setFont(self._log_font)
            self.tool_log_view.setProperty("_cdmw_global_font_managed", False)
            document.setDefaultFont(self._log_font)
        if adapter.document is not None:
            self._connected_document = adapter.document
            adapter.document.contentsChanged.connect(self._update_tool_log_empty_state)
        self._update_tool_log_empty_state()

    def apply_log_font(self, font: QFont) -> None:
        self._log_font = QFont(font)
        for view in (self.activity_view, self.tool_log_view):
            view.setFont(self._log_font)
            view.setProperty("_cdmw_global_font_managed", False)
            view.document().setDefaultFont(self._log_font)

    def _update_tool_log_empty_state(self) -> None:
        adapter = self._tool_adapter
        if not adapter.available:
            self.tool_log_empty_label.setText("No log is available for this tool.")
            self.tool_log_stack.setCurrentWidget(self.tool_log_empty_label)
        elif not adapter.text().strip():
            self.tool_log_empty_label.setText("This tool's log is empty.")
            self.tool_log_stack.setCurrentWidget(self.tool_log_empty_label)
        else:
            self.tool_log_stack.setCurrentWidget(self.tool_log_view)
        self._update_action_state()

    def _clear_current_view(self) -> None:
        if self.tabs.currentIndex() == 0:
            self._history.clear()
        else:
            self._tool_adapter.clear()
            self._update_tool_log_empty_state()

    def _copy_current_view(self) -> None:
        if self.tabs.currentIndex() == 0:
            text = self._history.formatted_text()
            app = QApplication.instance()
            if app is not None:
                app.clipboard().setText(text)
        else:
            self._tool_adapter.copy()

    def _update_action_state(self, *_args: object) -> None:
        if self.tabs.currentIndex() == 0:
            has_text = bool(self._history.events)
            self.clear_button.setEnabled(has_text)
            self.copy_button.setEnabled(has_text)
            return
        available = self._tool_adapter.available
        has_text = bool(self._tool_adapter.text())
        self.clear_button.setEnabled(available and has_text)
        self.copy_button.setEnabled(available and has_text)


__all__ = ["CompactActivityDrawer"]
