"""Archive failure controls shared by opening and background indexing."""

from __future__ import annotations

from pathlib import PurePath

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QApplication, QDialog, QFrame, QHBoxLayout, QLabel, QPlainTextEdit, QPushButton, QVBoxLayout

from cdmw.domain.archives.catalogue_operations import ArchiveBackendError
from cdmw.domain.archives.discovery import suggested_archive_exclusion
from cdmw.services.archive_failure_report import archive_failure_report, redact_archive_paths


class ArchiveFailurePanel(QFrame):
    retryRequested = Signal()
    excludeFolderRequested = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.report = ""
        self.excluded_folder = ""
        layout = QVBoxLayout(self)
        self.message = QLabel()
        self.message.setTextFormat(Qt.PlainText)
        self.message.setWordWrap(True)
        layout.addWidget(self.message)
        self.source_label = QLabel()
        self.guidance_label = QLabel()
        self.folder_label = QLabel()
        for label in (self.source_label, self.guidance_label, self.folder_label):
            label.setTextFormat(Qt.PlainText)
            label.setWordWrap(True)
            label.setTextInteractionFlags(Qt.TextSelectableByMouse)
            layout.addWidget(label)
        controls = QHBoxLayout()
        self.exclude_button = QPushButton("Exclude folder and refresh")
        self.retry_button = QPushButton("Retry")
        self.copy_button = QPushButton("Copy error report")
        self.details_button = QPushButton("Details")
        self.details_button.setCheckable(True)
        self.close_button = QPushButton("Close")
        for button in (self.exclude_button, self.retry_button, self.copy_button, self.details_button, self.close_button):
            controls.addWidget(button)
        controls.addStretch()
        layout.addLayout(controls)
        self.details = QPlainTextEdit()
        self.details.setReadOnly(True)
        self.details.setVisible(False)
        layout.addWidget(self.details)
        self.retry_button.clicked.connect(self.retryRequested.emit)
        self.exclude_button.clicked.connect(self._exclude_folder)
        self.copy_button.clicked.connect(lambda: QApplication.clipboard().setText(self.report))
        self.details_button.toggled.connect(self.details.setVisible)
        self.close_button.clicked.connect(self.hide)
        self.hide()

    def _exclude_folder(self):
        if self.excluded_folder:
            self.exclude_button.setEnabled(False)
            self.excludeFolderRequested.emit(self.excluded_folder)

    def clear(self):
        self.report = ""
        self.excluded_folder = ""
        self.details.clear()
        self.retry_button.setEnabled(True)
        self.hide()

    def show_failure(self, title, error, *, operation="archive", package_root=""):
        report = getattr(error, "report", "")
        if not report:
            typed = ArchiveBackendError(getattr(error, "code", "unknown_error"), getattr(error, "message", str(error)),
                getattr(error, "detail", None), getattr(error, "source_path", None))
            report = archive_failure_report(typed, operation=operation, backend="standalone archive worker", attempts=1,
                phase="", completed=0, total=0, elapsed=0, current_item="", progress=(), diagnostic_tail="", package_root=package_root)
        self.report = report
        self.message.setText(f"{title}\n{getattr(error, 'message', str(error))}")
        source = getattr(error, "source_path", None)
        self.source_label.setText(f"Affected file: {redact_archive_paths(source, package_root)}" if source else "")
        self.source_label.setVisible(bool(source))
        self.excluded_folder = ""
        if (getattr(error, "code", "") == "invalid_archive" and source
                and operation in {"open", "open_archive", "refresh_archive"}
                and (not getattr(error, "package_root", "")
                     or PurePath(error.package_root) == PurePath(package_root))):
            self.excluded_folder = suggested_archive_exclusion(package_root, source) or ""
        self.folder_label.setText(f"Folder to exclude: {self.excluded_folder}")
        self.folder_label.setVisible(bool(self.excluded_folder))
        self.exclude_button.setVisible(bool(self.excluded_folder))
        self.exclude_button.setEnabled(True)
        guidance = ""
        if self.excluded_folder:
            guidance = "This file is inside a mod or backup folder. Excluding the folder below skips its archives and refreshes the catalogue. No files are deleted."
        elif getattr(error, "code", "") == "invalid_archive":
            guidance = "CDMW could not read this archive. For an original game file, verify the installation through your game launcher. For a mod-generated copy, review Ignored folders in Settings."
        self.guidance_label.setText(guidance)
        self.guidance_label.setVisible(bool(guidance))
        self.details.setPlainText(report)
        self.details_button.setChecked(False)
        self.show()


class ArchiveFailureDialog(QDialog):
    retryRequested = Signal()
    excludeFolderRequested = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setAttribute(Qt.WA_DeleteOnClose)
        self.setWindowTitle("Archive operation failed")
        self.resize(640, 250)
        layout = QVBoxLayout(self)
        self.panel = ArchiveFailurePanel(self)
        layout.addWidget(self.panel)
        self.panel.retryRequested.connect(self.retryRequested.emit)
        self.panel.excludeFolderRequested.connect(self.excludeFolderRequested.emit)
        self.panel.close_button.clicked.connect(self.close)
