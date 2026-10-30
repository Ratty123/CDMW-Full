"""Theme-native batch export options, progress and a copyable final report."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QApplication, QCheckBox, QDialog, QFileDialog, QHBoxLayout, QLabel,
    QLineEdit, QPlainTextEdit, QProgressBar, QPushButton, QVBoxLayout, QWidget,
)

from cdmw.ui.archive_browser.mesh_batch_export_controller import BatchMeshExportController
from cdmw.ui.display_scaling import fit_window_to_screen, scrollable_content
from cdmw.services.active_ui_translation import translate_active_ui_text


class BatchMeshExportDialog(QDialog):
    def __init__(self, archive, selections, export_format: str):
        super().__init__(archive)
        self.setWindowTitle("Batch OBJ Export" if export_format == "obj" else "Batch FBX Export")
        self.setWindowFlag(Qt.WindowType.WindowContextHelpButtonHint, False)
        self.resize(720, 560)
        self.export_format = export_format
        self.controller = BatchMeshExportController(archive, self, selections)
        self.controller.progress.connect(self._progress)
        self.controller.item_finished.connect(self._item_finished)
        self.controller.finished.connect(self._finished)
        self.finished.connect(lambda _code: self.controller.close())

        layout = QVBoxLayout(self)
        options = QWidget()
        options_layout = QVBoxLayout(options)
        options_layout.setContentsMargins(0, 0, 0, 0)
        self.intro = QLabel("Export selected PAC, PAM and PAMLOD models into separate folders. Resolved referenced files are included. Existing folders are preserved.")
        self.intro.setWordWrap(True)
        options_layout.addWidget(self.intro)
        options_layout.addWidget(QLabel("Output folder"))
        folder_row = QHBoxLayout()
        self.output_edit = QLineEdit(str(archive.shell.settings_file_path.parent / "mesh_export"))
        self.output_edit.setMinimumWidth(0)
        self.browse_button = QPushButton("Browse...")
        self.browse_button.clicked.connect(self._browse)
        folder_row.addWidget(self.output_edit, 1)
        folder_row.addWidget(self.browse_button)
        options_layout.addLayout(folder_row)
        self.mesh_only = QCheckBox("Allow FBX without a skeleton")
        self.mesh_only.setToolTip("When disabled, a PAC without a usable skeleton is reported as failed and the batch continues.")
        self.mesh_only.setVisible(export_format == "fbx")
        options_layout.addWidget(self.mesh_only)
        self.options_scroll = scrollable_content(options, self)
        layout.addWidget(self.options_scroll)
        self.status = QLabel("Ready")
        self.status.setWordWrap(True)
        self.status.setTextFormat(Qt.TextFormat.PlainText)
        layout.addWidget(self.status)
        self.progress_bar = QProgressBar()
        self.progress_bar.setRange(0, len(selections))
        self.progress_bar.setValue(0)
        self.progress_bar.setFormat("%v / %m")
        layout.addWidget(self.progress_bar)
        self.report = QPlainTextEdit()
        self.report.setReadOnly(True)
        self.report.setPlainText("\n".join(selection.entry.path for selection in selections))
        layout.addWidget(self.report, 1)
        buttons = QHBoxLayout()
        self.copy_button = QPushButton("Copy Report")
        self.copy_button.setEnabled(False)
        self.copy_button.clicked.connect(lambda: QApplication.clipboard().setText(self.report.toPlainText()))
        self.start_button = QPushButton("Export")
        self.start_button.setDefault(True)
        self.start_button.clicked.connect(self._start)
        self.cancel_button = QPushButton("Close")
        self.cancel_button.clicked.connect(self.reject)
        buttons.addWidget(self.copy_button)
        buttons.addStretch(1)
        buttons.addWidget(self.start_button)
        buttons.addWidget(self.cancel_button)
        layout.addLayout(buttons)

    def showEvent(self, event):
        super().showEvent(event)
        fit_window_to_screen(self)

    def _browse(self):
        folder = QFileDialog.getExistingDirectory(self, "Choose Output Folder", self.output_edit.text())
        if folder:
            self.output_edit.setText(folder)

    def _start(self):
        folder = self.output_edit.text().strip()
        if not folder:
            self.status.setText(translate_active_ui_text("Choose an output folder first."))
            self.status.setProperty("_i18n_source_text", "Choose an output folder first.")
            return
        self.options_scroll.setEnabled(False)
        self.start_button.setEnabled(False)
        self.cancel_button.setText(translate_active_ui_text("Cancel"))
        self.cancel_button.setProperty("_i18n_source_text", "Cancel")
        self.report.clear()
        self.controller.start(Path(folder).expanduser().absolute(), self.export_format, self.mesh_only.isChecked())

    def _progress(self, completed, total, stage, path):
        self.progress_bar.setValue(completed)
        self.status.setText(translate_active_ui_text(stage))
        self.status.setProperty("_i18n_source_text", stage)
        self.status.setToolTip(path)
        self.report.appendPlainText(f"{completed + 1} / {total}: {path}")

    def _item_finished(self, result):
        self.progress_bar.setValue(len(self.controller.results))
        self.report.appendPlainText({"exported": "Exported", "failed": "Failed", "cancelled": "Cancelled"}[result.status])
        self.report.appendPlainText(result.source_path)
        if result.output_directory is not None:
            self.report.appendPlainText(str(result.output_directory))
        for detail in result.details:
            self.report.appendPlainText(detail)
        self.report.appendPlainText("")

    def _finished(self):
        # Replace transient preparation/conversion messages with one result per model.
        self.report.clear()
        for result in self.controller.results:
            self._item_finished(result)
        counts = {status: sum(result.status == status for result in self.controller.results)
                  for status in ("exported", "failed", "cancelled")}
        summary = f"Exported: {counts['exported']} | Failed: {counts['failed']} | Cancelled: {counts['cancelled']}"
        self.status.setText(translate_active_ui_text(summary))
        self.status.setProperty("_i18n_source_text", summary)
        self.report.appendPlainText(summary)
        self.copy_button.setEnabled(True)
        self.cancel_button.setText(translate_active_ui_text("Close"))
        self.cancel_button.setProperty("_i18n_source_text", "Close")
        self.cancel_button.setEnabled(True)
        self.cancel_button.setDefault(True)

    def reject(self):
        if self.controller.active:
            self.status.setText(translate_active_ui_text("Cancelling... Completed exports will be kept."))
            self.status.setProperty("_i18n_source_text", "Cancelling... Completed exports will be kept.")
            self.cancel_button.setEnabled(False)
            self.controller.cancel()
            return
        super().reject()

    def closeEvent(self, event):
        if self.controller.active:
            self.reject()
            event.ignore()
        else:
            super().closeEvent(event)
