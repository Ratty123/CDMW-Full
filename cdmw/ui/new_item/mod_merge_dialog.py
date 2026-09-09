"""Review selected mod folders and export one combined DMM package."""
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDialog, QDialogButtonBox, QFileDialog, QFormLayout, QHBoxLayout, QLabel,
    QLineEdit, QListWidget, QPlainTextEdit, QProgressBar, QPushButton, QVBoxLayout,
)

from cdmw.workers.mod_merge_workers import mod_merge_export_task, mod_merge_scan_task


class ModMergeDialog(QDialog):
    def __init__(self, controller, game_root="", parent=None):
        super().__init__(parent)
        self.controller = controller
        self._closed, self._working, self._generation = False, False, 0
        self._plan = None
        self.setWindowTitle("Merge mods")
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
        self.resize(780, 590)
        layout = QVBoxLayout(self)
        intro = QLabel("Combine selected mod folders into one DMM package. Independent changes are merged; conflicting records and unsupported changes must be resolved first.")
        intro.setWordWrap(True)
        layout.addWidget(intro)
        self.folders = QListWidget()
        self.folders.setMinimumHeight(90)
        layout.addWidget(self.folders)
        row = QHBoxLayout()
        self.add_button = QPushButton("Add mod folder...")
        self.add_button.clicked.connect(self._add)
        row.addWidget(self.add_button)
        self.remove_button = QPushButton("Remove selected")
        self.remove_button.clicked.connect(self._remove)
        row.addWidget(self.remove_button)
        row.addStretch(1)
        layout.addLayout(row)
        form = QFormLayout()
        self.game_root = QLineEdit(str(game_root or ""))
        self.game_browse = QPushButton("Folder...")
        self.game_browse.clicked.connect(lambda: self._browse(self.game_root, "Choose the game folder used to create these mods"))
        game_row = QHBoxLayout()
        game_row.addWidget(self.game_root, 1)
        game_row.addWidget(self.game_browse)
        form.addRow("Game baseline:", game_row)
        self.title = QLineEdit("Combined mod")
        form.addRow("Package name:", self.title)
        self.destination = QLineEdit()
        self.destination.setPlaceholderText("Choose a new or empty output folder")
        self.output_browse = QPushButton("Folder...")
        self.output_browse.clicked.connect(lambda: self._browse(self.destination, "Choose an empty folder for the combined mod"))
        output_row = QHBoxLayout()
        output_row.addWidget(self.destination, 1)
        output_row.addWidget(self.output_browse)
        form.addRow("Output folder:", output_row)
        layout.addLayout(form)
        self.status = QLabel("Add at least two mod folders, then check compatibility.")
        self.status.setTextFormat(Qt.TextFormat.PlainText)
        self.status.setWordWrap(True)
        layout.addWidget(self.status)
        self.progress = QProgressBar()
        self.progress.setRange(0, 0)
        self.progress.setTextVisible(False)
        self.progress.setMaximumHeight(6)
        layout.addWidget(self.progress)
        self.review = QPlainTextEdit()
        self.review.setReadOnly(True)
        self.review.setPlaceholderText("The merge summary and any conflicts appear here.")
        layout.addWidget(self.review, 1)
        row = QHBoxLayout()
        self.scan_button = QPushButton("Check compatibility")
        self.scan_button.clicked.connect(self._scan)
        row.addWidget(self.scan_button)
        self.export_button = QPushButton("Write merged mod")
        self.export_button.clicked.connect(self._export)
        row.addWidget(self.export_button)
        row.addStretch(1)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        buttons.rejected.connect(self.reject)
        row.addWidget(buttons)
        layout.addLayout(row)
        self.game_root.textChanged.connect(self._invalidate)
        self.destination.textChanged.connect(self._buttons)
        self.folders.currentRowChanged.connect(self._buttons)
        self.finished.connect(self._finished)
        controller.busy_changed.connect(self._buttons)
        self._buttons()

    def _browse(self, edit, title):
        path = QFileDialog.getExistingDirectory(self, title, edit.text())
        if path:
            edit.setText(path)

    def _add(self):
        path = QFileDialog.getExistingDirectory(self, "Choose a mod folder", "")
        if path:
            self.add_folder(path)

    def add_folder(self, path):
        path = str(Path(path).expanduser().resolve())
        if path not in self._folder_paths():
            self.folders.addItem(path)
            self._invalidate()

    def _folder_paths(self):
        return tuple(self.folders.item(i).text() for i in range(self.folders.count()))

    def _remove(self):
        self.folders.takeItem(self.folders.currentRow())
        self._invalidate()

    def _invalidate(self, *_args):
        self._generation += 1
        self._plan = None
        self.review.clear()
        self.status.setText("Selection changed. Check compatibility before exporting.")
        self._buttons()

    def _buttons(self, *_args):
        if self._closed:
            return
        available = not self._working and not self.controller.busy
        for widget in (self.folders, self.add_button, self.game_root, self.game_browse,
                       self.destination, self.output_browse, self.title):
            widget.setEnabled(available)
        self.remove_button.setEnabled(available and self.folders.currentRow() >= 0)
        self.scan_button.setEnabled(available and self.folders.count() >= 2 and bool(self.game_root.text().strip()))
        self.export_button.setEnabled(available and self._plan is not None and not self._plan.conflicts
                                      and bool(self.destination.text().strip()))
        self.progress.setVisible(self._working)

    def _run(self, task, completed, status):
        if self._closed:
            return
        generation = self._generation
        self._working = True
        self.status.setText(status)
        self._buttons()
        def done(value):
            self._working = False
            if not self._closed and generation == self._generation:
                completed(value)
                self._buttons()
        def failed(message):
            self._working = False
            if not self._closed and generation == self._generation:
                self._plan = None
                self.status.setText(str(message))
                self._buttons()
        if not self.controller._run("mod_merge", task, done, failed):
            failed("Wait for the current operation to finish, then try again.")

    def _scan(self):
        self._plan = None
        self._run(mod_merge_scan_task(self._folder_paths(), self.game_root.text().strip()),
                  self._scanned, "Checking mod contents and their game baseline...")

    def _scanned(self, plan):
        self._plan = plan
        if plan.conflicts:
            self.status.setText(f"{len(plan.conflicts)} conflict(s). No package can be written yet.")
            self.review.setPlainText("\n\n".join(plan.conflicts) +
                "\n\nRemove an incompatible mod from this selection, or rebuild it with different item IDs, asset names or conflicting edits; then check again.")
        else:
            self.status.setText(f"Ready to combine {len(plan.folders)} mods into one DMM package.")
            self.review.setPlainText(f"{len(plan.files)} files; {len(plan.items)} recorded item(s).\n\n" +
                "\n".join(path for path, _data, _flags in plan.files))

    def _export(self):
        if self._plan is None or self._plan.conflicts:
            return
        self._run(mod_merge_export_task(self._plan, self.destination.text().strip(), self.title.text()),
                  self._exported, "Writing the combined mod...")

    def _exported(self, result):
        self._plan = None
        self.status.setText(f"Merged mod written to {result.package_root}.")
        self.review.appendPlainText("\nEnable the combined package in DMM instead of the original selected packages.")

    def _finished(self, _result):
        self._closed = True
        self._generation += 1
        self._plan = None
        if self._working:
            self.controller.cancel_operation("mod_merge")
