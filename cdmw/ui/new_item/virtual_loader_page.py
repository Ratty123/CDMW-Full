"""Selectable startup profiles sharing the existing serialized controller lane."""
from pathlib import Path

from PySide6.QtCore import Qt, QTimer, Signal, QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import QFileDialog, QHBoxLayout, QLabel, QMessageBox, QPlainTextEdit, QPushButton, QTreeWidget, QTreeWidgetItem, QVBoxLayout, QWidget

from cdmw.domain.virtual_loader import VirtualProfile


class VirtualLoaderPage(QWidget):
    activity = Signal(str)

    def __init__(self, controller, root, parent=None):
        super().__init__(parent)
        self.setObjectName('virtual_loader_page')
        self.controller, self.package_root = controller, str(root)
        self._generation = 0
        self._closed = self._working = self._applying = self._draft_loaded = False
        self._prepared = self._runtime = self._queued = None
        self._saved_selection = None
        self._session = None
        self._session_timer = QTimer(self)
        self._session_timer.setInterval(1500)
        self._session_timer.timeout.connect(self._poll_session)
        layout = QVBoxLayout(self)
        help_label = QLabel(self.tr('Prepare items and supported mods for a separate startup profile. Original game archives stay unchanged.'))
        help_label.setWordWrap(True)
        layout.addWidget(help_label)
        notice = QLabel(self.tr('Experimental: item and effect compatibility varies. A verified save backup is required before each launch.'))
        notice.setWordWrap(True)
        notice.setProperty('managementRole', 'notice')
        layout.addWidget(notice)
        self.selection = QTreeWidget()
        self.selection.setObjectName('virtual_loader_selection')
        self.selection.setHeaderLabels([self.tr('Type'), self.tr('Package or folder')])
        self.selection.setRootIsDecorated(False)
        self.selection.setSelectionMode(QTreeWidget.ExtendedSelection)
        self.selection.itemSelectionChanged.connect(self._buttons)
        layout.addWidget(self.selection)
        choose = QHBoxLayout()
        self.add_items = self._button(choose, self.tr('Add item packages…'), 'virtual_add_items', self._add_items)
        self.add_mod = self._button(choose, self.tr('Add mod folder…'), 'virtual_add_mod', self._add_mod)
        self.remove_selected = self._button(choose, self.tr('Remove selected'), 'virtual_remove', self._remove)
        choose.addStretch(1)
        layout.addLayout(choose)
        actions = QHBoxLayout()
        self.prepare_button = self._button(actions, self.tr('Inspect and prepare'), 'virtual_prepare', self._prepare)
        self.save_button = self._button(actions, self.tr('Save virtual profile'), 'virtual_save', self._save)
        self.launch_button = self._button(actions, self.tr('Launch with virtual profile'), 'virtual_launch', self._launch)
        self.cancel_button = self._button(actions, self.tr('Cancel'), 'virtual_cancel', self._cancel)
        layout.addLayout(actions)
        runtime = QHBoxLayout()
        self.refresh_button = self._button(runtime, self.tr('Refresh status'), 'virtual_refresh', self.refresh)
        self.setup_button = self._button(runtime, self.tr('Review runtime setup…'), 'virtual_setup', self._setup)
        self.recover_button = self._button(runtime, self.tr('Recover interrupted profile'), 'virtual_recover', self._recover)
        layout.addLayout(runtime)
        diagnostics = QHBoxLayout()
        self.trace_button = self._button(diagnostics, self.tr('Review startup trace…'), 'virtual_trace', self._trace)
        self.remove_runtime_button = self._button(diagnostics, self.tr('Remove CDMW runtime…'), 'virtual_remove_runtime', self._remove_runtime)
        self.backups_button = self._button(diagnostics, self.tr('Open save backups'), 'virtual_backups', self._open_backups)
        diagnostics.addStretch(1)
        layout.addLayout(diagnostics)
        self.status = QLabel(self.tr('Prepare a profile to review its contents.'))
        self.status.setObjectName('virtual_loader_status')
        self.status.setTextFormat(Qt.TextFormat.PlainText)
        self.status.setWordWrap(True)
        layout.addWidget(self.status)
        self.review = QPlainTextEdit()
        self.review.setReadOnly(True)
        self.review.setMaximumBlockCount(2000)
        self.review.setObjectName('virtual_loader_review')
        layout.addWidget(self.review, 1)
        controller.busy_changed.connect(self._busy_changed)
        self._buttons()

    def _button(self, layout, text, name, action):
        button = QPushButton(text)
        button.setObjectName(name)
        button.clicked.connect(action)
        layout.addWidget(button)
        return button

    def _buttons(self):
        ready = not (self._closed or self._working or self.controller.busy)
        for button in (self.add_items, self.add_mod, self.prepare_button, self.refresh_button, self.setup_button, self.recover_button,
                       self.trace_button, self.remove_runtime_button, self.backups_button):
            button.setEnabled(ready and bool(self.package_root))
        self.selection.setEnabled(ready)
        self.remove_selected.setEnabled(ready and bool(self.selection.selectedItems()))
        self.save_button.setEnabled(ready and self._prepared is not None)
        self.launch_button.setEnabled(ready and self._runtime is not None and self._runtime.state == 'ready'
                                      and self._prepared is None and self._profile() == self._saved_selection)
        self.cancel_button.setEnabled(not self._closed and self._working and not self._applying)
        if self._session:
            for button in (self.save_button, self.launch_button, self.trace_button, self.setup_button, self.remove_runtime_button, self.recover_button):
                button.setEnabled(False)

    def _changed(self):
        self._generation += 1
        self._prepared = self._runtime = None
        self._draft_loaded = True
        self.review.clear()
        self.status.setText(self.tr('Selection changed. Inspect and prepare it again.'))
        self._buttons()

    def _append_selection(self, kind, paths):
        existing = {self.selection.topLevelItem(i).data(0, Qt.UserRole) for i in range(self.selection.topLevelItemCount())}
        for raw in paths:
            value = (kind, str(Path(raw).resolve()))
            if value in existing:
                continue
            item = QTreeWidgetItem([self.tr('Item package') if kind == 'item' else self.tr('Mod folder'), value[1]])
            item.setData(0, Qt.UserRole, value)
            self.selection.addTopLevelItem(item)
            existing.add(value)
        self._changed()

    def _add_items(self):
        files, _ = QFileDialog.getOpenFileNames(self, self.tr('Add item packages…'), '', self.tr('Independent items (*.cditem)'))
        if files:
            self._append_selection('item', files)

    def _add_mod(self):
        folder = QFileDialog.getExistingDirectory(self, self.tr('Add mod folder…'))
        if folder:
            self._append_selection('mod', (folder,))

    def _remove(self):
        for item in self.selection.selectedItems():
            self.selection.takeTopLevelItem(self.selection.indexOfTopLevelItem(item))
        self._changed()

    def _profile(self):
        rows = [self.selection.topLevelItem(i).data(0, Qt.UserRole) for i in range(self.selection.topLevelItemCount())]
        return VirtualProfile(tuple(Path(path) for kind, path in rows if kind == 'item'), tuple(Path(path) for kind, path in rows if kind == 'mod'))

    def _run(self, task, done, *, applying=False):
        if self._closed or self.controller.busy or not self.package_root:
            return False
        generation, root = self._generation, self.package_root
        self._working, self._applying = True, applying
        self._buttons()
        def completed(result):
            self._working = self._applying = False
            if not self._closed and generation == self._generation and root == self.package_root:
                done(result)
                self._buttons()
        def failed(message):
            self._working = self._applying = False
            if not self._closed and generation == self._generation:
                self.status.setText(str(message))
                self.activity.emit(str(message))
                self._buttons()
        started = self.controller._run('virtual_loader', task, completed, failed)
        if not started:
            self._working = self._applying = False
            self._buttons()
        return started

    def _prepare(self):
        from cdmw.services.virtual_loader_composition import prepare_profile
        root, profile = self.package_root, self._profile()
        self._prepared = None
        self.status.setText(self.tr('Preparing virtual profile…'))
        def done(result):
            self._prepared = result
            self.review.setPlainText('\n'.join(result.summary))
            self.status.setText(self.tr('Prepared for review. Save the profile to retain its item identities.'))
        self._run(lambda log, stop: prepare_profile(profile, root, stop_event=stop, on_log=log), done)

    def _save(self):
        from cdmw.services.virtual_loader_state import publish_profile
        prepared, generation = self._prepared, self._generation
        if prepared is None:
            return
        detail = self.tr('Save this virtual profile and its retained item identities?') + '\n\n' + str(prepared.root) + '\n\n' + '\n'.join(prepared.summary)
        if QMessageBox.question(self, self.tr('Save virtual profile'), detail) != QMessageBox.Yes or generation != self._generation or self._closed:
            return
        def done(_result):
            self._prepared = None
            self.status.setText(self.tr('Virtual profile saved. Removed items keep their identities for existing saves.'))
            self._queued = self.refresh
            QTimer.singleShot(0, self, self._resume)
        self._run(lambda log, stop: publish_profile(prepared, stop_event=stop), done, applying=True)

    def refresh(self):
        from cdmw.services.virtual_loader_runtime import runtime_status
        from cdmw.services.virtual_loader_state import load_profile
        if self.controller.busy or self._working:
            self._queued = self.refresh
            return
        root = self.package_root
        def done(result):
            state, profile = result
            self._saved_selection = VirtualProfile(tuple(Path(p) for p in profile['packages']),
                                                   tuple(Path(p) for p in profile['mods'])) if profile else None
            self._runtime = state
            if not self._draft_loaded:
                self.selection.clear()
                if profile:
                    self._append_selection('item', profile['packages'])
                    self._append_selection('mod', profile['mods'])
                self._draft_loaded = True
                self._runtime = state
            self.status.setText(self.tr(state.detail))
        def task(log, stop):
            state = runtime_status(root, experimental=True, stop_event=stop)
            profile = None if 'Recover' in state.detail else load_profile(root)
            return state, profile
        self._run(task, done)

    def _setup(self):
        from cdmw.services.virtual_loader_runtime import prepare_runtime_setup, apply_runtime_setup, RUNTIME_PATH
        root = self.package_root
        def done(plan):
            generation = self._generation
            detail = self.tr('Install the CDMW virtual runtime at this exact path?') + '\n\n' + str(plan.root / RUNTIME_PATH) + '\nSHA-256: ' + plan.checksum
            detail += '\n\n' + self.tr('Existing ASI loaders and plugins are preserved. Virtual items are active only when launched through CDMW.')
            def installed(_value):
                self._queued = self.refresh
                QTimer.singleShot(0, self, self._resume)
            if QMessageBox.question(self, self.tr('Review runtime setup…'), detail) == QMessageBox.Yes and generation == self._generation and not self._closed:
                self._queued = lambda: self._run(lambda log, stop: apply_runtime_setup(plan, confirmed=True, stop_event=stop),
                                                installed, applying=True)
                QTimer.singleShot(0, self, self._resume)
        self._run(lambda log, stop: prepare_runtime_setup(root, stop_event=stop), done)

    def _recover(self):
        from cdmw.services.virtual_loader_state import recover_profile
        root = self.package_root
        self._run(lambda log, stop: recover_profile(root), lambda _value: self.status.setText(self.tr('Virtual profile recovery completed. Refresh its status.')), applying=True)

    def _launch(self):
        from cdmw.services.virtual_loader_runtime import prepare_experimental_launch, launch_experimental
        if self._profile() != self._saved_selection:
            return
        root, generation = self.package_root, self._generation
        self.status.setText(self.tr('Preparing launch and save backup…'))
        def done(review):
            detail = self.tr('Launch this experimental virtual profile?') + '\n\n' + str(review.plan.root)
            detail += '\n\n' + self.tr('Backup: {value_0}').format(value_0=review.backup.directory)
            detail += '\n\n' + self.tr('Your saves have been backed up and will not be edited by CDMW. Load and save only while the intended profile is active.')
            if QMessageBox.question(self, self.tr('Launch with virtual profile'), detail) != QMessageBox.Yes:
                return
            def start():
                if not self._closed and generation == self._generation and root == self.package_root:
                    self.status.setText(self.tr('Starting the virtual session…'))
                    self._run(lambda log, stop: launch_experimental(review, confirmed=True, stop_event=stop), self._started)
            if generation == self._generation and root == self.package_root and not self._closed:
                self._queued = start
                QTimer.singleShot(0, self, self._resume)
        self._run(lambda log, stop: prepare_experimental_launch(root, stop_event=stop), done)

    def _cancel(self):
        if not self._working or self._applying:
            return
        self._generation += 1
        self._queued = None
        self.controller.cancel_operation('virtual_loader')
        self.status.setText(self.tr('Processing stopped by user.'))

    def _open_backups(self):
        from cdmw.services.virtual_loader_saves import BACKUP_PATH
        from cdmw.services.virtual_loader_state import target
        try:
            folder = target(self.package_root, BACKUP_PATH)
            if folder.is_dir():
                QDesktopServices.openUrl(QUrl.fromLocalFile(str(folder)))
            else:
                self.status.setText(self.tr('Prepare a launch to create a save backup.'))
        except (ValueError, OSError) as exc:
            self.status.setText(str(exc))

    def _started(self, result):
        self._session = (self.package_root, result.detail, result.pid)
        self.status.setText(self.tr('Starting the virtual session…'))
        self._session_timer.start()

    def _poll_session(self):
        if not self._session or self.controller.busy or self._closed:
            return
        from cdmw.services.virtual_loader_runtime import session_status
        root, token, host_pid = self._session
        def done(state):
            self.status.setText(self.tr(state.detail))
            if state.state in ('stopped', 'blocked'):
                self._session_timer.stop()
                self._session = None
        self._run(lambda log, stop: session_status(root, token, host_pid=host_pid), done)

    def _trace(self):
        from cdmw.services.virtual_loader_runtime import prepare_diagnostic_trace, start_diagnostic_trace
        root = self.package_root
        def done(plan):
            generation = self._generation
            detail = self.tr('Start a diagnostic game session using original game files? Virtual items will not be active. Leave the game at its title screen without loading a save, then close it.')
            detail += '\n\n' + str(plan.executable) + '\nSHA-256: ' + plan.executable_sha256
            if QMessageBox.question(self, self.tr('Review startup trace…'), detail) == QMessageBox.Yes and generation == self._generation and not self._closed:
                self._queued = lambda: self._run(lambda log, stop: start_diagnostic_trace(root, confirmed=True, expected_plan=plan, stop_event=stop), self._started)
                QTimer.singleShot(0, self, self._resume)
        self._run(lambda log, stop: prepare_diagnostic_trace(root, stop_event=stop), done)

    def _remove_runtime(self):
        from cdmw.services.virtual_loader_runtime import remove_runtime, RUNTIME_PATH, OWNER_PATH
        from cdmw.services.virtual_loader_state import decode, target
        root = self.package_root
        def done(checksum):
            generation = self._generation
            detail = self.tr('Remove only the owned CDMW runtime? Profiles, reservations and recovery files will be retained.')
            detail += '\n\n' + str(Path(root) / RUNTIME_PATH) + '\nSHA-256: ' + checksum
            if QMessageBox.question(self, self.tr('Remove CDMW runtime…'), detail) == QMessageBox.Yes and generation == self._generation and not self._closed:
                self._queued = lambda: self._run(lambda log, stop: remove_runtime(root, expected_sha256=checksum, confirmed=True, stop_event=stop),
                                                lambda _result: self.status.setText(self.tr('CDMW runtime removed. Retained profiles and identities are unchanged.')), applying=True)
                QTimer.singleShot(0, self, self._resume)
        self._run(lambda log, stop: decode(target(root, OWNER_PATH).read_bytes())['sha256'], done)

    def _resume(self):
        if not self._closed and not self.controller.busy and not self._working and self._queued:
            task, self._queued = self._queued, None
            task()

    def _busy_changed(self, busy):
        if not busy:
            self._working = self._applying = False
        if not self._closed:
            self._buttons()
            QTimer.singleShot(0, self, self._resume)

    def set_game_root(self, root):
        if str(root) == self.package_root:
            return
        if self._working and not self._applying:
            self.controller.cancel_operation('virtual_loader')
        self.package_root = str(root)
        self._generation += 1
        self._queued = self._prepared = self._runtime = None
        self._saved_selection = None
        self._session = None
        self._session_timer.stop()
        self._draft_loaded = False
        self.selection.clear()
        self.review.clear()
        self._buttons()

    def request_shutdown(self):
        self._closed = True
        self._generation += 1
        self._queued = None
        self._session_timer.stop()
        if self._working and not self._applying:
            self.controller.cancel_operation('virtual_loader')
