"""Archive failure controls shared by opening and background indexing."""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QApplication, QDialog, QFrame, QHBoxLayout, QLabel, QPlainTextEdit, QPushButton, QVBoxLayout

from cdmw.domain.archives.catalogue_operations import ArchiveBackendError
from cdmw.services.archive_failure_report import archive_failure_report


class ArchiveFailurePanel(QFrame):
    retryRequested = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.report = ""
        layout = QVBoxLayout(self)
        self.message = QLabel()
        self.message.setTextFormat(Qt.PlainText)
        self.message.setWordWrap(True)
        layout.addWidget(self.message)
        controls = QHBoxLayout()
        self.retry_button = QPushButton("Retry")
        self.copy_button = QPushButton("Copy error report")
        self.details_button = QPushButton("Details")
        self.details_button.setCheckable(True)
        self.close_button = QPushButton("Close")
        for button in (self.retry_button, self.copy_button, self.details_button, self.close_button):
            controls.addWidget(button)
        controls.addStretch()
        layout.addLayout(controls)
        self.details = QPlainTextEdit()
        self.details.setReadOnly(True)
        self.details.setVisible(False)
        layout.addWidget(self.details)
        self.retry_button.clicked.connect(self.retryRequested.emit)
        self.copy_button.clicked.connect(lambda: QApplication.clipboard().setText(self.report))
        self.details_button.toggled.connect(self.details.setVisible)
        self.close_button.clicked.connect(self.hide)
        self.hide()

    def clear(self):
        self.report = ""
        self.details.clear()
        self.retry_button.setEnabled(True)
        self.hide()

    def show_failure(self, title, error, *, operation="archive", package_root=""):
        report = getattr(error, "report", "")
        if not report:
            typed = ArchiveBackendError(getattr(error, "code", "unknown_error"), getattr(error, "message", str(error)), getattr(error, "detail", None))
            report = archive_failure_report(typed, operation=operation, backend="standalone archive worker", attempts=1,
                phase="", completed=0, total=0, elapsed=0, current_item="", progress=(), diagnostic_tail="", package_root=package_root)
        self.report = report
        self.message.setText(f"{title}\n{getattr(error, 'message', str(error))}")
        self.details.setPlainText(report)
        self.details_button.setChecked(False)
        self.show()


class ArchiveFailureDialog(QDialog):
    retryRequested = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setAttribute(Qt.WA_DeleteOnClose)
        self.setWindowTitle("Archive operation failed")
        self.resize(640, 250)
        layout = QVBoxLayout(self)
        self.panel = ArchiveFailurePanel(self)
        layout.addWidget(self.panel)
        self.panel.retryRequested.connect(self.retryRequested.emit)
        self.panel.close_button.clicked.connect(self.close)
