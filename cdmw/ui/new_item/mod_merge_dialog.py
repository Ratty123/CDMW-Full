"""Review selected mod folders and export a compatible combined package."""
from pathlib import Path
from cdmw.domain.cancellation import raise_if_cancelled

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDialog, QDialogButtonBox, QFileDialog, QFormLayout, QHBoxLayout, QLabel,
    QGroupBox, QLineEdit, QListWidget, QPlainTextEdit, QProgressBar, QPushButton, QVBoxLayout,
)

from cdmw.workers.mod_merge_workers import mod_merge_export_task, mod_merge_scan_task
from cdmw.ui.new_item.review_model import ReviewTextWriter


class ModMergeDialog(QDialog):
    def __init__(self, controller, game_root="", parent=None, *, embedded=False):
        super().__init__(parent)
        if embedded:
            self.setWindowFlags(Qt.WindowType.Widget)
        self.controller = controller
        self._review_lookup = controller.create_lookup_lane()
        self._review_lookup.completed.connect(self._review_ready)
        self._review_lookup.failed.connect(self._review_failed)
        self._closed, self._working, self._generation = False, False, 0
        self._plan = None
        self.setWindowTitle("Merge mods")
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose, not embedded)
        self.resize(780, 590)
        layout = QVBoxLayout(self)
        self.setToolTip("Combine selected mod folders. Semantic exports retain their original packages for CDMW import; legacy exports use DMM. Conflicting or unsupported changes must be resolved first.")
        setup = QHBoxLayout()
        sources = QGroupBox('Mod folders')
        source_layout = QVBoxLayout(sources)
        output = QGroupBox('Output')
        output_layout = QVBoxLayout(output)
        setup.addWidget(sources, 1)
        setup.addWidget(output, 1)
        layout.addLayout(setup)
        self.folders = QListWidget()
        self.folders.setMinimumHeight(90)
        self.folders.setAccessibleDescription('Add at least two mod folders.')
        source_layout.addWidget(self.folders)
        row = QHBoxLayout()
        self.add_button = QPushButton("Add mod folder...")
        self.add_button.clicked.connect(self._add)
        row.addWidget(self.add_button)
        self.remove_button = QPushButton("Remove selected")
        self.remove_button.clicked.connect(self._remove)
        row.addWidget(self.remove_button)
        row.addStretch(1)
        source_layout.addLayout(row)
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
        output_layout.addLayout(form)
        results = QGroupBox('Compatibility')
        results_layout = QVBoxLayout(results)
        layout.addWidget(results, 1)
        self.status = QLabel("Add at least two mod folders, then check compatibility.")
        self.status.setTextFormat(Qt.TextFormat.PlainText)
        self.status.setWordWrap(True)
        results_layout.addWidget(self.status)
        self.progress = QProgressBar()
        self.progress.setRange(0, 0)
        self.progress.setTextVisible(False)
        self.progress.setMaximumHeight(6)
        results_layout.addWidget(self.progress)
        self.review = QPlainTextEdit()
        self._review_writer = ReviewTextWriter(self.review)
        self.review.setReadOnly(True)
        self.review.setPlaceholderText("The merge summary and any conflicts appear here.")
        results_layout.addWidget(self.review, 1)
        row = QHBoxLayout()
        self.scan_button = QPushButton("Check compatibility")
        self.scan_button.setProperty('newItemPrimary', True)
        self.scan_button.setToolTip(self.toolTip())
        self.scan_button.clicked.connect(self._scan)
        row.addWidget(self.scan_button)
        self.export_button = QPushButton("Write merged mod")
        self.export_button.clicked.connect(self._export)
        row.addWidget(self.export_button)
        row.addStretch(1)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        buttons.rejected.connect(self.reject)
        row.addWidget(buttons)
        buttons.setVisible(not embedded)
        results_layout.addLayout(row)
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
        self._review_lookup.cancel()
        self._review_writer.set_text("")
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

    def _run(self, task, completed, status, *, publishes_result=False):
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
        if not self.controller._run("mod_merge", task, done, failed, publishes_result=publishes_result):
            failed("Wait for the current operation to finish, then try again.")

    def _scan(self):
        self._plan = None
        self._review_lookup.cancel()
        self._review_writer.set_text("")
        self._run(mod_merge_scan_task(self._folder_paths(), self.game_root.text().strip()),
                  self._scanned, "Checking mod contents and their game baseline...")

    def _scanned(self, plan):
        self._plan = plan
        if plan.conflicts:
            self.status.setText(f"{len(plan.conflicts)} conflict(s). No package can be written yet.")
        else:
            destination = 'CDMW semantic .cditem' if plan.semantic_export is not None else 'DMM'
            self.status.setText(f"Ready to combine {len(plan.folders)} mods into one {destination} package.")
        def build(stop):
            lines = []
            if plan.conflicts:
                for conflict in plan.conflicts:
                    raise_if_cancelled(stop)
                    lines.append(conflict)
                lines.append("Remove an incompatible mod from this selection, or rebuild it with different item IDs, asset names or conflicting edits; then check again.")
                return "\n\n".join(lines)
            lines.extend((f"{len(plan.files)} files; {len(plan.items)} recorded item(s).", ""))
            for path, _data, _flags in plan.files:
                raise_if_cancelled(stop)
                lines.append(path)
            return "\n".join(lines)
        self._review_lookup.request((self._generation, id(plan)), build)

    def _review_ready(self, key, text):
        if not self._closed and key == (self._generation, id(self._plan)):
            self._review_writer.set_text(text)

    def _review_failed(self, key, message):
        self._review_ready(key, f"The review could not be prepared: {message}")

    def _export(self):
        if self._plan is None or self._plan.conflicts:
            return
        self._run(mod_merge_export_task(self._plan, self.destination.text().strip(), self.title.text()),
                  self._exported, "Writing the combined mod...", publishes_result=True)

    def _exported(self, result):
        self._plan = None
        self.status.setText(f"Merged mod written to {result.package_root}.")
        if result.manager == 'CDMW':
            self.review.appendPlainText("\nImport cdmw-semantic.cditem through CDMW. Its contributors keep their own identities and removal controls. Keep the identity profile with your saves.")
        else:
            self.review.appendPlainText("\nEnable the combined package in DMM instead of the original selected packages.")

    def _finished(self, _result):
        self._closed = True
        self._review_lookup.request_shutdown()
        self._review_writer.timer.stop()
        self._generation += 1
        self._plan = None
        if self._working:
            self.controller.cancel_operation("mod_merge")
