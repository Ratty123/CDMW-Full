"""Single-texture .cditem review on the existing shared, queued worker lane."""
from __future__ import annotations

from pathlib import Path
from uuid import uuid4

from PySide6.QtCore import QSignalBlocker, Qt
from PySide6.QtWidgets import (
    QComboBox, QDialog, QDialogButtonBox, QFileDialog, QFormLayout, QHBoxLayout,
    QLabel, QLineEdit, QPlainTextEdit, QProgressBar, QPushButton, QVBoxLayout,
)

from cdmw.services.texture_workflow_service import (
    find_existing_texture_targets, load_texture_package_update,
    prepare_texture_package, write_texture_package,
)


class IndependentTexturePackageDialog(QDialog):
    def __init__(self, controller, game_root='', parent=None):
        super().__init__(parent)
        self.controller = controller
        self._catalogue = self._plan = self._update = None
        self._identity = uuid4().hex
        self._generation = 0
        self._working = self._publishing = self._closed = False
        self.setObjectName('independentTexturePackage')
        self.setWindowTitle('Texture .cditem package')
        self.resize(790, 690)
        layout = QVBoxLayout(self)
        help_text = QLabel(
            'Replace one existing game texture with a prepared DDS that retains its complete layout. '
            'Review the target before writing a portable package.'
        )
        help_text.setWordWrap(True)
        layout.addWidget(help_text)
        actions = QHBoxLayout()
        self.new_button = QPushButton('New texture package')
        self.load_button = QPushButton('Load package to update...')
        self.new_button.clicked.connect(self._new)
        self.load_button.clicked.connect(self._load)
        actions.addWidget(self.new_button)
        actions.addWidget(self.load_button)
        actions.addStretch(1)
        layout.addLayout(actions)
        self.package_mode = QLabel('New standalone texture package')
        self.package_mode.setTextFormat(Qt.TextFormat.PlainText)
        self.package_mode.setWordWrap(True)
        layout.addWidget(self.package_mode)
        form = QFormLayout()
        form.setRowWrapPolicy(QFormLayout.RowWrapPolicy.WrapLongRows)
        layout.addLayout(form)
        self.game_root = QLineEdit(str(game_root))
        self.game_browse = self._path_row(form, 'Game archive folder:', self.game_root, self._browse_game)
        search = QHBoxLayout()
        self.texture_filter = QLineEdit()
        self.texture_filter.setPlaceholderText('Part of the existing texture path or filename')
        self.find_button = QPushButton('Find existing textures')
        self.find_button.clicked.connect(self._find)
        search.addWidget(self.texture_filter, 1)
        search.addWidget(self.find_button)
        form.addRow('Find target:', search)
        self.target = QComboBox()
        self.target.setMinimumContentsLength(48)
        self.target.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
        form.addRow('Existing texture:', self.target)
        self.replacement = QLineEdit()
        self.replacement_browse = self._path_row(form, 'Replacement DDS:', self.replacement, self._browse_replacement)
        self.title = QLineEdit('Texture replacements')
        self.release = QLineEdit('1')
        form.addRow('Package title:', self.title)
        form.addRow('Release:', self.release)
        self.destination = QLineEdit()
        self.destination.setPlaceholderText('Choose a .cditem file outside the game archive folder')
        self.destination_browse = self._path_row(form, 'Package file:', self.destination, self._browse_destination)
        self.status = QLabel('Choose the game archive folder and find an existing texture.')
        self.status.setTextFormat(Qt.TextFormat.PlainText)
        self.status.setWordWrap(True)
        layout.addWidget(self.status)
        self.progress = QProgressBar()
        self.progress.setRange(0, 0)
        layout.addWidget(self.progress)
        self.review = QPlainTextEdit()
        self.review.setReadOnly(True)
        self.review.setPlaceholderText('The affected path, package identity and verified source details appear here.')
        layout.addWidget(self.review, 1)
        buttons = QHBoxLayout()
        self.review_button = QPushButton('Review replacement')
        self.write_button = QPushButton('Write .cditem')
        self.cancel_button = QPushButton('Cancel operation')
        self.review_button.clicked.connect(self._prepare)
        self.write_button.clicked.connect(self._write)
        self.cancel_button.clicked.connect(self._cancel)
        buttons.addWidget(self.review_button)
        buttons.addWidget(self.write_button)
        buttons.addWidget(self.cancel_button)
        buttons.addStretch(1)
        close = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        close.rejected.connect(self.reject)
        buttons.addWidget(close)
        layout.addLayout(buttons)
        self.game_root.textChanged.connect(self._root_changed)
        self.target.currentIndexChanged.connect(self._invalidate)
        for edit in (self.replacement, self.title, self.release):
            edit.textChanged.connect(self._invalidate)
        self.destination.textChanged.connect(self._buttons)
        self.finished.connect(self._finished)
        self.controller.busy_changed.connect(self._buttons)
        self._buttons()

    def _path_row(self, form, label, edit, browse):
        button = QPushButton('Browse...')
        button.clicked.connect(browse)
        row = QHBoxLayout()
        row.addWidget(edit, 1)
        row.addWidget(button)
        form.addRow(label, row)
        return button

    def _browse_game(self):
        path = QFileDialog.getExistingDirectory(self, 'Choose the game archive folder', self.game_root.text())
        if path:
            self.game_root.setText(path)

    def _browse_replacement(self):
        path, _ = QFileDialog.getOpenFileName(self, 'Choose the prepared replacement DDS',
                                              self.replacement.text(), 'DDS textures (*.dds)')
        if path:
            self.replacement.setText(path)

    def _browse_destination(self):
        path, _ = QFileDialog.getSaveFileName(self, 'Write a new texture package',
                                              self.destination.text(), 'Independent packages (*.cditem)')
        if path:
            self.destination.setText(path)

    def _buttons(self, *_args):
        if self._closed:
            return
        available = not self._working and not self.controller.busy
        for widget in (self.new_button, self.load_button, self.game_root, self.game_browse,
                       self.texture_filter, self.replacement, self.replacement_browse,
                       self.title, self.release):
            widget.setEnabled(available)
        self.target.setEnabled(available and self._catalogue is not None)
        self.find_button.setEnabled(available and bool(self.game_root.text().strip()))
        self.destination.setEnabled(available)
        self.destination.setReadOnly(self._update is not None)
        self.destination_browse.setEnabled(available and self._update is None)
        target = self.target.currentText()
        compatible_target = self._update is None or target == self._update.target_path
        self.review_button.setEnabled(available and self._catalogue is not None and bool(target)
            and compatible_target and bool(self.replacement.text().strip())
            and bool(self.title.text().strip()) and bool(self.release.text().strip()))
        self.write_button.setEnabled(available and self._plan is not None and bool(self.destination.text().strip()))
        self.cancel_button.setEnabled(self._working)
        self.progress.setVisible(self._working)

    def _invalidate(self, *_args):
        self._generation += 1
        self._plan = None
        if self._working:
            self.controller.cancel_operation('independent_texture')
        self.review.clear()
        self._buttons()

    def _root_changed(self, *_args):
        self._catalogue = None
        self.target.clear()
        self._invalidate()

    def _new(self):
        if self._working or self.controller.busy:
            return
        self._update = None
        self._identity = uuid4().hex
        self.package_mode.setText('New standalone texture package')
        self.title.setText('Texture replacements')
        self.release.setText('1')
        self.destination.clear()
        self._invalidate()
        self.status.setText('Find an existing texture and choose its replacement DDS.')

    def _run(self, task, completed, status, *, publishing=False):
        if self._closed or self._working or self.controller.busy:
            return False
        generation = self._generation
        self._working, self._publishing = True, publishing
        self.status.setText(status)
        self._buttons()
        def done(value):
            self._working = self._publishing = False
            if not self._closed and (publishing or generation == self._generation):
                completed(value)
            self._buttons()
        def failed(message):
            self._working = self._publishing = False
            if not self._closed and generation == self._generation:
                self._plan = None
                self.status.setText(str(message))
            self._buttons()
        def cancelled():
            self._working = self._publishing = False
            if not self._closed and generation == self._generation:
                self.status.setText('Operation cancelled.')
            self._buttons()
        started = self.controller._run('independent_texture', task, done, failed,
            publishes_result=publishing, on_cancel=cancelled)
        if not started:
            failed('Wait for the current operation to finish, then try again.')
        return started

    def _find(self):
        root, query = self.game_root.text().strip(), self.texture_filter.text()
        service, read_entry = self.controller.service, self.controller._read_entry
        self._catalogue = self._plan = None
        self.target.clear()
        self.review.clear()
        self._run(lambda log, stop: find_existing_texture_targets(root, query, service=service,
            read_entry=read_entry, stop_event=stop, on_log=log),
            self._found, 'Finding existing game textures...')

    def _found(self, catalogue):
        self._catalogue = catalogue
        with QSignalBlocker(self.target):
            self.target.clear()
            self.target.addItems(catalogue.paths)
            if self._update is not None:
                self.target.setCurrentIndex(self.target.findText(self._update.target_path))
        if catalogue.total_matches > len(catalogue.paths):
            self.status.setText(f'Showing {len(catalogue.paths)} of {catalogue.total_matches} matches. Refine the filter to find another target.')
        elif not catalogue.paths:
            self.status.setText('No registered texture targets matched. Refine the filter or choose another game archive folder.')
        else:
            self.status.setText('Select the existing texture and a prepared replacement DDS, then review the replacement.')

    def _load(self):
        path, _ = QFileDialog.getOpenFileName(self, 'Load a texture package to update',
                                              self.destination.text(), 'Independent packages (*.cditem)')
        if not path:
            return
        self._plan = None
        self.review.clear()
        self._run(lambda _log, stop: load_texture_package_update(path, stop_event=stop),
                  self._loaded, 'Reading the selected texture package...')

    def _loaded(self, update):
        self._update, self._identity = update, update.identity
        self._catalogue = self._plan = None
        self.target.clear()
        self.texture_filter.setText(update.target_path)
        self.title.setText(update.title)
        self.release.setText(update.release)
        self.destination.setText(str(update.path))
        self.package_mode.setText(f'Updating package UUID: {update.identity}')
        self.status.setText('Package loaded. Find its existing texture in the current game archive folder before reviewing an update.')

    def _prepare(self):
        catalogue, target, replacement = self._catalogue, self.target.currentText(), self.replacement.text()
        title, release, identity, update = self.title.text(), self.release.text(), self._identity, self._update
        self._plan = None
        self.review.clear()
        self._run(lambda _log, stop: prepare_texture_package(catalogue, target, replacement,
            title=title, release=release, identity=identity, update=update, stop_event=stop),
            self._prepared, 'Validating the complete texture and its source...')

    def _prepared(self, plan):
        self._plan = plan
        self.review.setPlainText('\n'.join(plan.lines))
        self.status.setText('Review ready. Verify the target and package identity, then write the package.')

    def _write(self):
        if self._plan is None:
            return
        plan, destination = self._plan, self.destination.text()
        self._run(lambda log, stop: write_texture_package(plan, destination, stop_event=stop, on_log=log),
                  self._written, 'Writing the reviewed texture package...', publishing=True)

    def _written(self, result):
        self._plan = None
        if self._update is None:
            self._identity = uuid4().hex
        self.status.setText(f'Texture package written to {result.path}.')
        self.review.appendPlainText('Add this .cditem from Mods. Load the written package before making another update.')

    def _cancel(self):
        if self.controller.cancel_operation('independent_texture'):
            self.status.setText('Cancelling...')

    def _finished(self, _result=0):
        self._closed = True
        self._generation += 1
        self._catalogue = self._plan = None
        if self._working:
            self.controller.cancel_operation('independent_texture')

    def request_shutdown(self):
        self._finished()
