"""Path-only export options and progress for the current archive catalogue."""

from dataclasses import replace
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QComboBox, QDialog, QFileDialog, QHBoxLayout, QLabel, QMessageBox, QProgressBar,
    QPushButton, QVBoxLayout,
)

from cdmw.domain.archives.catalogue import ArchiveQuery
from cdmw.domain.archives.catalogue_operations import ArchiveExportSelectionKind
from cdmw.services.active_ui_translation import translate_active_ui_text
from cdmw.ui.archive_browser.path_export_controller import ArchivePathExportController
from cdmw.ui.display_scaling import fit_window_to_screen

_SCOPE_KEYS = ("all", "filtered", "selected", "folder")


def path_export_scopes(archive):
    """Capture the applied query and explicit selection before opening the dialog."""
    bridge = archive.archive_remote_bridge
    session = bridge.current_session
    current = bridge.controller.current_query
    if session is None or current is None:
        return {}
    scopes = {"all": (ArchiveQuery(session.session_id), ""), "filtered": (current, "")}
    selection = bridge.selected_export_selection()
    if selection is not None:
        if selection.selection_kind is ArchiveExportSelectionKind.ENTRY_IDS:
            scopes["selected"] = (ArchiveQuery(session.session_id, entry_ids=selection.entry_ids), "")
        elif selection.selection_kind is ArchiveExportSelectionKind.FOLDER:
            scopes["folder"] = (replace(current), selection.folder_path)
    return scopes


class ArchivePathExportDialog(QDialog):
    def __init__(self, archive, *, default_scope="filtered"):
        super().__init__(archive)
        self.setWindowTitle("Export File Paths")
        self.setWindowFlag(Qt.WindowType.WindowContextHelpButtonHint, False)
        self.resize(600, 300)
        self._scopes = path_export_scopes(archive)
        self.controller = ArchivePathExportController(archive, self)
        self.controller.progress.connect(self._progress)
        self.controller.finished.connect(self._complete)
        self.controller.failed.connect(self._failed)
        self.finished.connect(lambda _code: self.controller.close())
        layout = QVBoxLayout(self)
        intro = QLabel("Save archive-relative paths without extracting files. TXT has one path per line; CSV also identifies the source archive. Duplicate paths are kept.")
        intro.setWordWrap(True)
        layout.addWidget(intro)
        self.scope = QComboBox()
        self.scope.addItem("All files")
        self.scope.addItem("Filtered results")
        self.scope.addItem("Selected files (up to 4,096)")
        self.scope.addItem("Selected folder (including subfolders)")
        for index, key in enumerate(_SCOPE_KEYS):
            self.scope.model().item(index).setEnabled(key in self._scopes)
        self.scope.setCurrentIndex(_SCOPE_KEYS.index(default_scope))
        layout.addWidget(self.scope)
        note = QLabel("Filtered results use the last applied Search, including rows not loaded on screen. Folder export keeps those filters. All files uses every archive in the loaded catalogue.")
        note.setWordWrap(True)
        layout.addWidget(note)
        self.status = QLabel("Ready")
        self.status.setTextFormat(Qt.TextFormat.PlainText)
        self.status.setWordWrap(True)
        layout.addWidget(self.status)
        self.progress = QProgressBar()
        self.progress.setRange(0, 1)
        self.progress.setValue(0)
        layout.addWidget(self.progress)
        buttons = QHBoxLayout()
        buttons.addStretch(1)
        self.export_button = QPushButton("Export...")
        self.export_button.setEnabled(bool(self._scopes))
        self.export_button.clicked.connect(self._export)
        self.close_button = QPushButton("Close")
        self.close_button.clicked.connect(self.reject)
        buttons.addWidget(self.export_button)
        buttons.addWidget(self.close_button)
        layout.addLayout(buttons)

    def showEvent(self, event):
        super().showEvent(event)
        fit_window_to_screen(self)

    def _export(self):
        scope = self._scopes.get(_SCOPE_KEYS[self.scope.currentIndex()])
        if scope is None or self.controller.active:
            return
        filename, chosen_filter = QFileDialog.getSaveFileName(
            self, translate_active_ui_text("Export File Paths"), "archive-paths.txt",
            translate_active_ui_text("Text files (*.txt);;CSV files (*.csv)"),
        )
        if not filename:
            return
        destination = Path(filename)
        if not destination.suffix:
            destination = destination.with_suffix(".csv" if "*.csv" in chosen_filter else ".txt")
            # The native save dialog confirmed the name before our suffix was added.
            if destination.exists() and QMessageBox.question(
                self, translate_active_ui_text("Overwrite Existing"), str(destination),
                QMessageBox.Yes | QMessageBox.No, QMessageBox.No,
            ) != QMessageBox.Yes:
                return
        if destination.suffix.lower() not in {".txt", ".csv"}:
            self._failed("Choose a TXT or CSV file.")
            return
        self.export_button.setEnabled(False)
        self.scope.setEnabled(False)
        self.close_button.setText(translate_active_ui_text("Cancel"))
        self.status.setText(translate_active_ui_text("Exporting file paths..."))
        self.progress.setRange(0, 0)
        query, folder = scope
        self.controller.start(query, destination, folder)

    def _progress(self, scanned, total):
        self.progress.setRange(0, max(1, total))
        self.progress.setValue(scanned)

    def _idle(self):
        self.export_button.setEnabled(True)
        self.scope.setEnabled(True)
        self.close_button.setText(translate_active_ui_text("Close"))
        self.progress.setRange(0, 1)
        self.progress.setValue(1)

    def _complete(self, result):
        self._idle()
        if result.cancelled:
            self.status.setText(translate_active_ui_text("Path export cancelled."))
        else:
            self.status.setText(translate_active_ui_text("Exported {count} paths to {path}.").format(count=result.count, path=result.destination))

    def _failed(self, message):
        self._idle()
        self.status.setText(translate_active_ui_text(message))


def open_archive_path_export(archive, default_scope="filtered"):
    if archive.shell._background_task_active() or not archive.archive_remote_actions_safe:
        return
    dialog = ArchivePathExportDialog(archive, default_scope=default_scope)
    try:
        dialog.exec()
    finally:
        dialog.controller.close()
        # The shell owns the writer thread until teardown; the dialog can close immediately.
        # Keep its signal emitter alive until that worker has stopped.
        from PySide6.QtCore import QTimer

        def release():
            if dialog.controller._tasks.active:
                QTimer.singleShot(25, release)
            else:
                dialog.deleteLater()

        release()
