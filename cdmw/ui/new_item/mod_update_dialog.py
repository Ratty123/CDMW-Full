"""Review game changes and write a separate updated mod package."""
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QComboBox, QDialog, QDialogButtonBox, QFileDialog, QFormLayout,
    QHBoxLayout, QLabel, QLineEdit, QPlainTextEdit, QProgressBar, QPushButton, QVBoxLayout)

from cdmw.core.mod_compatibility import build_label, build_status
from cdmw.workers.mod_update_workers import mod_update_export_task, mod_update_scan_task


class ModUpdateDialog(QDialog):
    def __init__(self, controller, game_root="", parent=None, *, installed=False):
        super().__init__(parent)
        self.controller, self._plan = controller, None
        self._working = self._closed = False
        self._generation = 0
        self.setWindowTitle("Check mods for game updates")
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
        self.resize(790, 570)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(18, 18, 18, 18)
        layout.setSpacing(12)
        intro = QLabel("Compare the mod's original data with the current game. Review the results, then write an updated DMM package to a separate folder.")
        intro.setWordWrap(True)
        layout.addWidget(intro)
        form = QFormLayout()
        form.setSpacing(10)
        self.source_kind = QComboBox()
        self.source_kind.addItem("Mod folder", False)
        self.source_kind.addItem("Installed CDMW overlays together", True)
        self.source_kind.setCurrentIndex(1 if installed else 0)
        form.addRow("Source:", self.source_kind)
        self.folder = QLineEdit()
        self.folder_browse = self._folder_row(form, "Mod folder:", self.folder, "Choose the original mod folder")
        self.game_root = QLineEdit(str(game_root))
        self.game_browse = self._folder_row(form, "Current game data:", self.game_root, "Choose the current game archive folder")
        self.title = QLineEdit()
        self.title.setPlaceholderText("Original name with an updated suffix")
        form.addRow("Package name:", self.title)
        self.destination = QLineEdit()
        self.destination.setPlaceholderText("Choose a new or empty output folder")
        self.output_browse = self._folder_row(form, "Output folder:", self.destination, "Choose an empty folder for the updated mod")
        layout.addLayout(form)
        self.status = QLabel("Disable the original mod in your mod manager before comparing. CDMW's own installed overlays are handled as a group.")
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
        self.review.setPlaceholderText("Original and current game builds, affected files, and conflicts appear here.")
        layout.addWidget(self.review, 1)
        buttons = QHBoxLayout()
        self.scan_button = QPushButton("Compare with current game")
        self.scan_button.clicked.connect(self._scan)
        self.export_button = QPushButton("Write updated mod")
        self.export_button.clicked.connect(self._export)
        buttons.addWidget(self.scan_button)
        buttons.addWidget(self.export_button)
        buttons.addStretch(1)
        close = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        close.rejected.connect(self.reject)
        buttons.addWidget(close)
        layout.addLayout(buttons)
        self.source_kind.currentIndexChanged.connect(self._invalidate)
        self.folder.textChanged.connect(self._invalidate)
        self.game_root.textChanged.connect(self._invalidate)
        self.destination.textChanged.connect(self._buttons)
        self.finished.connect(self._finished)
        controller.busy_changed.connect(self._buttons)
        self._buttons()

    def _folder_row(self, form, label, edit, title):
        button = QPushButton("Folder...")
        def browse():
            path = QFileDialog.getExistingDirectory(self, title, edit.text())
            if path:
                edit.setText(path)
        button.clicked.connect(browse)
        row = QHBoxLayout()
        row.addWidget(edit, 1)
        row.addWidget(button)
        form.addRow(label, row)
        return button

    def _buttons(self, *_args):
        if self._closed:
            return
        available = not self._working and not self.controller.busy
        installed = bool(self.source_kind.currentData())
        for widget in (self.source_kind, self.game_root, self.game_browse, self.title, self.destination, self.output_browse):
            widget.setEnabled(available)
        self.folder.setEnabled(available and not installed)
        self.folder_browse.setEnabled(available and not installed)
        self.scan_button.setEnabled(available and bool(self.game_root.text().strip()) and
                                    (installed or bool(self.folder.text().strip())))
        self.export_button.setEnabled(available and self._plan is not None and self._plan.can_update and
                                      bool(self.destination.text().strip()))
        self.progress.setVisible(self._working)

    def _invalidate(self, *_args):
        self._generation += 1
        self._plan = None
        if self._working:
            self.controller.cancel_operation("mod_update")
        self.review.clear()
        self.status.setText("Selection changed. Check compatibility before exporting.")
        self._buttons()

    def _run(self, task, completed, message):
        if self._closed:
            return
        generation = self._generation
        self._working = True
        self.status.setText(message)
        self._buttons()
        def done(value):
            self._working = False
            if not self._closed and generation == self._generation:
                completed(value)
            if not self._closed:
                self._buttons()
        def failed(error):
            self._working = False
            if not self._closed and generation == self._generation:
                self._plan = None
                self.status.setText(str(error))
            if not self._closed:
                self._buttons()
        if not self.controller._run("mod_update", task, done, failed):
            failed("Wait for the current operation to finish, then try again.")

    def _scan(self):
        self._plan = None
        self._run(mod_update_scan_task(self.folder.text(), self.game_root.text(),
            installed=bool(self.source_kind.currentData())), self._scanned, "Comparing the mod with current game data...")

    def _scanned(self, plan):
        self._plan = plan
        statuses = {"unchanged": "The compared source data is unchanged.",
                    "changed": "Independent game changes can be preserved in an updated package.",
                    "conflict": "Conflicts need review before this mod can be updated.",
                    "unknown": "The original baseline is incomplete. This mod cannot be updated automatically."}
        self.status.setText(statuses[plan.status])
        lines = [f"Built for: {build_label(plan.recorded_game)}", f"Current game: {build_label(plan.current_game)}"]
        if build_status(plan.recorded_game, plan.current_game) == "changed":
            lines.append("Game build changed. The file comparison below determines whether an update is possible.")
        if plan.conflicts:
            lines.extend(("", "Required review:", *plan.conflicts))
        labels = {"unknown": self.tr("Unknown baseline"), "unchanged": self.tr("Source data unchanged"),
                  "changed": self.tr("Updated data merged"), "conflict": self.tr("Conflict"),
                  "dependency_changed": self.tr("Referenced asset changed or missing")}
        lines.extend(("", "Compared files:", *(f"{labels[status]}: {path}" for path, status in plan.comparisons),
                      "", "This checks recorded data and merge conflicts. In-game behavior still needs testing."))
        self.review.setPlainText("\n".join(lines))

    def _export(self):
        if self._plan is not None and self._plan.can_update:
            self._run(mod_update_export_task(self._plan, self.destination.text(), self.title.text()),
                      self._exported, "Writing the updated mod...")

    def _exported(self, result):
        self._plan = None
        self.status.setText(f"Updated mod written to {result.package_root}.")
        self.review.appendPlainText("\nUse this package in place of the original mod. For installed overlays, review Archive recovery before replacing the installed set.")

    def _finished(self, _result):
        self._closed = True
        self._generation += 1
        self._plan = None
        if self._working:
            self.controller.cancel_operation("mod_update")
