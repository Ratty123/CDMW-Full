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
from cdmw.ui.log_view import LiveLogBinding


class CompactActivityDrawer(QFrame):
    def __init__(self, history: ActivityHistory, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("CompactActivityDrawer")
        self.setMinimumHeight(168)
        self.setMaximumHeight(280)
        self._history = history
        self._activity_dirty = True
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
        self._tool_log_binding = LiveLogBinding(self.tool_log_view)
        self.tool_log_stack.addWidget(self.tool_log_empty_label)
        self.tool_log_stack.addWidget(self.tool_log_view)
        self.tabs.addTab(self.tool_log_stack, "Current Tool Log")
        layout.addWidget(self.tabs, stretch=1)

        self.clear_button.clicked.connect(self._clear_current_view)
        self.copy_button.clicked.connect(self._copy_current_view)
        self.tabs.currentChanged.connect(self._activity_tab_changed)
        history.changed.connect(self._schedule_activity_refresh)
        history.cleared.connect(self._clear_activity_text)
        self._update_action_state()

    def _schedule_activity_refresh(self, _event: object) -> None:
        self._activity_dirty = True
        self._update_action_state()
        # Status bursts can contain hundreds of messages in a single GUI turn.
        # Keep the full history, but render it at most once per refresh interval
        # and only while the Activity page is actually on screen.
        if self.isVisible() and self.tabs.currentIndex() == 0 and not self._refresh_timer.isActive():
            self._refresh_timer.start()

    def _refresh_activity_text(self) -> None:
        self._refresh_timer.stop()
        if not self._activity_dirty or not self.isVisible() or self.tabs.currentIndex() != 0:
            return
        self.activity_view.setPlainText(self._history.formatted_text())
        self._activity_dirty = False
        scrollbar = self.activity_view.verticalScrollBar()
        scrollbar.setValue(scrollbar.maximum())
        self._update_action_state()

    def _clear_activity_text(self) -> None:
        self._refresh_timer.stop()
        self._activity_dirty = False
        self.activity_view.clear()
        self._update_action_state()

    def _activity_tab_changed(self, _index: int) -> None:
        self._refresh_timer.stop()
        self._refresh_activity_text()
        self._update_action_state()

    def showEvent(self, event) -> None:  # noqa: N802
        super().showEvent(event)
        self._refresh_activity_text()

    def hideEvent(self, event) -> None:  # noqa: N802
        self._refresh_timer.stop()
        super().hideEvent(event)

    def _disconnect_document(self) -> None:
        if self._connected_document is None:
            return
        try:
            self._connected_document.contentsChanged.disconnect(self._update_tool_log_empty_state)
        except (RuntimeError, TypeError):
            pass
        self._connected_document = None

    def set_tool_log(self, adapter: ToolLogAdapter) -> None:
        self._tool_adapter = adapter
        document = adapter.document or self._empty_document
        if self._tool_log_binding.source_document is document:
            self._update_tool_log_empty_state()
            return
        self._disconnect_document()
        self._tool_log_binding.set_document(document)
        if self._log_font is not None:
            self.tool_log_view.setFont(self._log_font)
            self.tool_log_view.setProperty("_cdmw_global_font_managed", False)
            self.tool_log_view.document().setDefaultFont(self._log_font)
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
        elif not self._document_has_content(adapter.document):
            self.tool_log_empty_label.setText("This tool's log is empty.")
            self.tool_log_stack.setCurrentWidget(self.tool_log_empty_label)
        else:
            self.tool_log_stack.setCurrentWidget(self.tool_log_view)
        self._update_action_state()

    @staticmethod
    def _document_has_content(document) -> bool:
        # Navigation and every appended line reach this check. Stop at the
        # first nonblank block instead of copying the complete tool log twice.
        block = document.begin()
        while block.isValid():
            if block.text().strip():
                return True
            block = block.next()
        return False

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
        has_text = available and not self._tool_adapter.document.isEmpty()
        self.clear_button.setEnabled(available and has_text)
        self.copy_button.setEnabled(available and has_text)


__all__ = ["CompactActivityDrawer"]
