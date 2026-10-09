"""Selectable startup profiles sharing the existing serialized controller lane."""
from pathlib import Path

from PySide6.QtCore import Qt, QTimer, Signal, QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (QComboBox, QFileDialog, QHeaderView, QHBoxLayout, QLabel,
    QMessageBox, QPlainTextEdit, QProgressBar, QPushButton, QSplitter, QToolButton,
    QTreeWidget, QTreeWidgetItem, QVBoxLayout, QWidget)

from cdmw.domain.virtual_loader import VirtualProfile


class VirtualLoaderPage(QWidget):
    activity = Signal(str)
    profile_applied = Signal()

    def __init__(self, controller, root, parent=None):
        super().__init__(parent)
        self.setObjectName('virtual_loader_page')
        self.controller, self.package_root = controller, str(root)
        self._generation = 0
        self._closed = self._working = self._applying = self._draft_loaded = False
        self._prepared = self._runtime = self._queued = None
        self._saved_selection = None
        self._error = ''
        self._next_order = 0
        self._progress_generation = None
        self._session = None
        self._session_lookup = controller.create_lookup_lane()
        self._session_lookup.completed.connect(self._session_status_ready)
        self._session_lookup.failed.connect(self._session_status_failed)
        self._session_timer = QTimer(self)
        self._session_timer.setInterval(1500)
        self._session_timer.timeout.connect(self._poll_session)
        layout = QVBoxLayout(self)
        help_label = QLabel(self.tr('Add packages, apply the profile, then launch the game. Original game archives stay unchanged.'))
        help_label.setObjectName('virtual_loader_intro')
        help_label.setWordWrap(True)
        layout.addWidget(help_label)
        notice = QLabel(self.tr('Experimental: item and effect compatibility varies. A verified save backup is required before each launch.'))
        notice.setObjectName('virtual_loader_notice')
        notice.setWordWrap(True)
        notice.setProperty('managementRole', 'notice')
        layout.addWidget(notice)
        self.workspace = QSplitter(Qt.Horizontal)
        self.workspace.setObjectName('virtual_loader_workspace')
        self.workspace.setChildrenCollapsible(False)
        layout.addWidget(self.workspace, 1)
        packages = QWidget()
        packages.setObjectName('virtual_loader_packages')
        left = QVBoxLayout(packages)
        left.setContentsMargins(0, 0, 0, 0)
        self.workspace.addWidget(packages)
        details = QWidget()
        details.setObjectName('virtual_loader_details')
        right = QVBoxLayout(details)
        right.setContentsMargins(0, 0, 0, 0)
        self.workspace.addWidget(details)
        self.workspace.setSizes([560, 500])
        self.workspace.setStretchFactor(0, 1)
        self.workspace.setStretchFactor(1, 1)
        sort_row = QHBoxLayout()
        sort_row.addWidget(QLabel(self.tr('Selected packages')))
        sort_row.addStretch(1)
        self.sort_choice = QComboBox()
        self.sort_choice.setObjectName('virtual_loader_sort')
        self.sort_choice.addItems([self.tr('Name (A–Z)'), self.tr('Name (Z–A)'), self.tr('Type')])
        self.sort_choice.setToolTip(self.tr('Sort the list without changing the saved profile or item identities.'))
        self.sort_choice.currentIndexChanged.connect(self._sort_selection)
        sort_row.addWidget(self.sort_choice)
        left.addLayout(sort_row)
        self.selection = QTreeWidget()
        self.selection.setObjectName('virtual_loader_selection')
        self.selection.setHeaderLabels([self.tr('Package or folder'), self.tr('Type')])
        self.selection.setRootIsDecorated(False)
        self.selection.setUniformRowHeights(True)
        self.selection.setMinimumHeight(300)
        self.selection.setSortingEnabled(True)
        self.selection.sortItems(0, Qt.AscendingOrder)
        self.selection.header().setSectionResizeMode(0, QHeaderView.Stretch)
        self.selection.header().setSectionResizeMode(1, QHeaderView.ResizeToContents)
        self.selection.setToolTip(self.tr('Click a column heading to sort. Hover over a package to see its full path.'))
        self.selection.setAccessibleDescription(self.tr('Add .cditem packages or supported mod folders to begin.'))
        self.selection.setSelectionMode(QTreeWidget.ExtendedSelection)
        self.selection.itemSelectionChanged.connect(self._buttons)
        left.addWidget(self.selection, 1)
        choose = QHBoxLayout()
        self.add_items = self._button(choose, self.tr('Add item packages…'), 'virtual_add_items', self._add_items,
            self.tr('Select one or more .cditem files to add to this profile.'))
        self.add_mod = self._button(choose, self.tr('Add mod folder…'), 'virtual_add_mod', self._add_mod,
            self.tr('Add an external mod folder for compatibility checking and composition.'))
        left.addLayout(choose)
        remove_row = QHBoxLayout()
        self.remove_selected = self._button(remove_row, self.tr('Remove selected'), 'virtual_remove', self._remove,
            self.tr('Remove selected entries from this draft. Files and retained item identities are kept.'))
        self.count = QLabel()
        self.count.setObjectName('virtual_loader_count')
        remove_row.addWidget(self.count, 1)
        left.addLayout(remove_row)
        actions = QHBoxLayout()
        self.apply_button = self._button(actions, self.tr('Apply profile'), 'virtual_prepare', self._apply,
            self.tr('Check compatibility, prepare and save this selection, and update the virtual loader automatically.'))
        right.addLayout(actions)
        launch = QHBoxLayout()
        self.launch_button = self._button(launch, self.tr('Launch game'), 'virtual_launch', self._launch,
            self.tr('Verify the saved profile, back up saves, then launch the game with these items active.'))
        self.cancel_button = self._button(launch, self.tr('Cancel'), 'virtual_cancel', self._cancel,
            self.tr('Stop preparation before the profile is saved, or stop launch before the session host starts.'))
        right.addLayout(launch)
        self.status = QLabel(self.tr('Apply the profile to use this selection.'))
        self.status.setObjectName('virtual_loader_status')
        self.status.setTextFormat(Qt.TextFormat.PlainText)
        self.status.setWordWrap(True)
        right.addWidget(self.status)
        self.progress = QProgressBar()
        self.progress.setObjectName('virtual_loader_progress')
        self.progress.setRange(0, 100)
        self.progress.setValue(0)
        self.progress.setToolTip(self.tr('Progress follows completed stages and files. It is not an estimate of remaining time.'))
        self.progress.hide()
        right.addWidget(self.progress)
        self.review = QPlainTextEdit()
        self.review.setReadOnly(True)
        self.review.setMaximumBlockCount(2000)
        self.review.setObjectName('virtual_loader_review')
        self.review.setPlaceholderText(self.tr('The prepared items and compatibility results appear here.'))
        right.addWidget(self.review, 1)
        self.tools_toggle = QToolButton()
        self.tools_toggle.setObjectName('virtual_tools_toggle')
        self.tools_toggle.setText(self.tr('Advanced'))
        self.tools_toggle.setCheckable(True)
        self.tools_toggle.setToolButtonStyle(Qt.ToolButtonTextBesideIcon)
        self.tools_toggle.setArrowType(Qt.RightArrow)
        self.tools_toggle.setToolTip(self.tr('Show runtime setup, status, diagnostics and recovery tools.'))
        right.addWidget(self.tools_toggle)
        self.tools = QWidget()
        self.tools.setObjectName('virtual_loader_tools')
        tools_layout = QVBoxLayout(self.tools)
        tools_layout.setContentsMargins(0, 0, 0, 0)
        self.tools.hide()
        self.tools_toggle.toggled.connect(self.tools.setVisible)
        self.tools_toggle.toggled.connect(lambda checked: self.tools_toggle.setArrowType(Qt.DownArrow if checked else Qt.RightArrow))
        right.addWidget(self.tools)
        runtime = QHBoxLayout()
        self.refresh_button = self._button(runtime, self.tr('Refresh status'), 'virtual_refresh', self.refresh,
            self.tr('Recheck the runtime and saved profile without changing your selection.'))
        self.setup_button = self._button(runtime, self.tr('Loader setup…'), 'virtual_setup', self._setup,
            self.tr('Review installation or update of CDMW’s owned runtime files.'))
        tools_layout.addLayout(runtime)
        recovery = QHBoxLayout()
        self.recover_button = self._button(recovery, self.tr('Recover interrupted profile'), 'virtual_recover', self._recover,
            self.tr('Recover an interrupted profile save using its retained recovery data.'))
        self.backups_button = self._button(recovery, self.tr('Open save backups'), 'virtual_backups', self._open_backups,
            self.tr('Open the verified save copies created before virtual launches.'))
        tools_layout.addLayout(recovery)
        diagnostics = QHBoxLayout()
        self.trace_button = self._button(diagnostics, self.tr('Review startup trace…'), 'virtual_trace', self._trace,
            self.tr('Review a diagnostic launch using original game files. Virtual items are inactive during tracing.'))
        self.remove_runtime_button = self._button(diagnostics, self.tr('Remove CDMW runtime…'), 'virtual_remove_runtime', self._remove_runtime,
            self.tr('Review removal of CDMW’s runtime. Profiles, backups and item identities are retained.'))
        tools_layout.addLayout(diagnostics)
        controller.busy_changed.connect(self._busy_changed)
        controller.operation_progress.connect(self._operation_progress)
        self._buttons()

    def _button(self, layout, text, name, action, tooltip):
        button = QPushButton(text)
        button.setObjectName(name)
        button.setToolTip(tooltip)
        button.clicked.connect(action)
        layout.addWidget(button)
        return button

    def _buttons(self):
        ready = not (self._closed or self._working or self.controller.busy or self._queued)
        for button in (self.add_items, self.add_mod, self.apply_button, self.refresh_button, self.setup_button, self.recover_button,
                       self.trace_button, self.remove_runtime_button, self.backups_button):
            button.setEnabled(ready and bool(self.package_root))
        self.selection.setEnabled(ready)
        self.sort_choice.setEnabled(ready)
        self.remove_selected.setEnabled(ready and bool(self.selection.selectedItems()))
        self.launch_button.setEnabled(ready and self._runtime is not None
                                      and self._runtime.state in ('ready', 'setup_required', 'update_required')
                                      and self._prepared is None and self._profile() == self._saved_selection)
        self.cancel_button.setEnabled(not self._closed and self._working and not self._applying)
        if self._session:
            for button in (self.apply_button, self.launch_button, self.trace_button, self.setup_button, self.remove_runtime_button, self.recover_button):
                button.setEnabled(False)

    def _changed(self):
        self._generation += 1
        self._error = ''
        self._prepared = self._runtime = self._queued = None
        self._draft_loaded = True
        self.review.clear()
        self.progress.hide()
        profile = self._profile()
        self.count.setText(self.tr('{value_0} packages · {value_1} mod folders').format(value_0=len(profile.packages), value_1=len(profile.mods)))
        self.status.setText(self.tr('Apply the profile to use this selection.'))
        self._buttons()

    def _append_selection(self, kind, paths):
        existing = {self.selection.topLevelItem(i).data(0, Qt.UserRole) for i in range(self.selection.topLevelItemCount())}
        for raw in paths:
            value = (kind, str(Path(raw).resolve()))
            if value in existing:
                continue
            item = QTreeWidgetItem([Path(value[1]).name, self.tr('Item package') if kind == 'item' else self.tr('Mod folder')])
            item.setData(0, Qt.UserRole, value)
            item.setData(0, Qt.UserRole + 1, self._next_order)
            self._next_order += 1
            item.setToolTip(0, value[1])
            item.setToolTip(1, value[1])
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
        items = [self.selection.topLevelItem(i) for i in range(self.selection.topLevelItemCount())]
        # Display sorting must not change allocation order or invalidate a saved profile.
        rows = [item.data(0, Qt.UserRole) for item in sorted(items, key=lambda item: item.data(0, Qt.UserRole + 1))]
        return VirtualProfile(tuple(Path(path) for kind, path in rows if kind == 'item'), tuple(Path(path) for kind, path in rows if kind == 'mod'))

    def _sort_selection(self, index):
        self.selection.sortItems(1 if index == 2 else 0, Qt.DescendingOrder if index == 1 else Qt.AscendingOrder)

    def _run(self, task, done, *, applying=False, with_progress=False, publishes_result=False):
        if self._closed or self.controller.busy or not self.package_root:
            return False
        generation, root = self._generation, self.package_root
        self._working, self._applying = True, applying
        self._progress_generation = generation if with_progress else None
        if with_progress:
            self.progress.setRange(0, 100)
            self.progress.setValue(0)
            self.progress.show()
        self._buttons()
        def completed(result):
            self._working = self._applying = False
            if not self._closed and generation == self._generation and root == self.package_root:
                if with_progress:
                    self.progress.setValue(100)
                done(result)
                self._buttons()
        def failed(message):
            self._working = self._applying = False
            if not self._closed and generation == self._generation:
                self._queued = None
                self._error = str(message)
                self.status.setText(self.tr(str(message)))
                self.progress.hide()
                self.activity.emit(str(message))
                self._buttons()
        def cancelled():
            self._working = self._applying = False
            if not self._closed and generation == self._generation and root == self.package_root:
                self._queued = None
                self.status.setText(self.tr('Processing stopped by user.'))
                self.progress.hide()
                self._buttons()
        started = self.controller._run('virtual_loader', task, completed, failed, task_accepts_progress=with_progress,
                                       publishes_result=applying or publishes_result, on_cancel=cancelled)
        if not started:
            self._working = self._applying = False
            self.progress.hide()
            self._buttons()
        return started

    def _operation_progress(self, lane, current, total, detail):
        if (lane != 'virtual_loader' or self._closed or not self._working
                or self._progress_generation != self._generation):
            return
        if total > 0:
            self.progress.setValue(max(self.progress.value(), min(99, current * 100 // total)))
        if detail:
            self.status.setText(self.tr(detail))

    def _queue(self, task):
        generation, root = self._generation, self.package_root
        def current():
            if not self._closed and generation == self._generation and root == self.package_root:
                task()
        self._queued = current
        self._buttons()
        QTimer.singleShot(0, self, self._resume)

    def _apply(self):
        self._error = ''
        self._prepared = self._runtime = None
        self._ensure_runtime(self._prepare)

    def _prepare(self):
        from cdmw.services.virtual_loader_process import prepare_profile_in_subprocess
        root, profile = self.package_root, self._profile()
        self._prepared = None
        self.status.setText(self.tr('Preparing virtual profile…'))
        def done(result):
            self._prepared = result
            self.review.setPlainText('\n'.join(result.summary))
            self._queue(self._save)
        self._run(lambda log, progress, stop: prepare_profile_in_subprocess(
            profile, root, stop_event=stop, on_log=log, on_progress=progress), done, with_progress=True)

    def _save(self):
        from cdmw.services.virtual_loader_state import publish_profile
        prepared = self._prepared
        if prepared is None:
            return
        self.status.setText(self.tr('Saving profile…'))
        self.progress.setRange(0, 0)
        self.progress.show()
        def done(_result):
            self._prepared = None
            self.progress.hide()
            self.activity.emit(self.tr('Profile applied.'))
            self.profile_applied.emit()
            self._queue(self.refresh)
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
                self._next_order = 0
                if profile:
                    self._append_selection('item', profile['packages'])
                    self._append_selection('mod', profile['mods'])
                self._draft_loaded = True
                self._runtime = state
            self.progress.hide()
            self.status.setText(self.tr(state.detail) if self._profile() == self._saved_selection or state.state == 'blocked'
                                else self.tr('Apply the profile to use this selection.'))
        def task(log, stop):
            state = runtime_status(root, experimental=True, stop_event=stop)
            profile = None if 'Recover' in state.detail else load_profile(root)
            return state, profile
        self._run(task, done)

    def _setup(self):
        self._ensure_runtime(self.refresh)

    def _ensure_runtime(self, continuation):
        from cdmw.services.virtual_loader_runtime import prepare_runtime_setup, apply_runtime_setup, RUNTIME_PATH
        root = self.package_root
        self.status.setText(self.tr('Checking virtual loader…'))
        self.progress.hide()
        def done(plan):
            generation = self._generation
            confirmed = False
            if not plan.owned:
                detail = self.tr('Install CDMW’s virtual loader for this game? Future updates to this loader are automatic. Original game archives and other loaders stay unchanged.')
                detail += '\n\n' + str(plan.root / RUNTIME_PATH)
                confirmed = QMessageBox.question(self, self.tr('Set up virtual loader?'), detail) == QMessageBox.Yes
                if self._closed or generation != self._generation or root != self.package_root:
                    return
                if not confirmed:
                    self.status.setText(self.tr('Loader setup cancelled. Apply or launch to try again.'))
                    return
            def installed(_value):
                self.progress.hide()
                self._queue(continuation)
            def install():
                self.status.setText(self.tr('Checking virtual loader…') if plan.owned and plan.previous == plan.payload
                                    else self.tr('Updating virtual loader…'))
                self.progress.setRange(0, 0)
                self.progress.show()
                self._run(lambda log, stop: apply_runtime_setup(plan, confirmed=confirmed, stop_event=stop),
                          installed, applying=True)
            if generation == self._generation and root == self.package_root and not self._closed:
                self._queue(install)
        self._run(lambda log, stop: prepare_runtime_setup(root, stop_event=stop), done)

    def _recover(self):
        from cdmw.services.virtual_loader_state import recover_profile
        root = self.package_root
        self._run(lambda log, stop: recover_profile(root), lambda _value: self.status.setText(self.tr('Virtual profile recovery completed. Refresh its status.')), applying=True)

    def _launch(self):
        if self._profile() == self._saved_selection:
            self._ensure_runtime(self._prepare_launch)

    def _prepare_launch(self):
        from cdmw.services.virtual_loader_runtime import prepare_experimental_launch, launch_experimental
        if self._profile() != self._saved_selection:
            return
        root, generation = self.package_root, self._generation
        self.status.setText(self.tr('Preparing launch and save backup…'))
        def done(review):
            self.activity.emit(self.tr('Backup: {value_0}').format(value_0=review.backup.directory))
            def start():
                if not self._closed and generation == self._generation and root == self.package_root:
                    self.status.setText(self.tr('Starting the virtual session…'))
                    self._run(lambda log, progress, stop: launch_experimental(
                        review, confirmed=True, stop_event=stop, on_progress=progress), self._started,
                        with_progress=True, publishes_result=True)
            if generation == self._generation and root == self.package_root and not self._closed:
                self._queue(start)
        self._run(lambda log, progress, stop: prepare_experimental_launch(
            root, stop_event=stop, on_progress=progress), done, with_progress=True)

    def _cancel(self):
        if not self._working or self._applying:
            return
        self._queued = None
        self.controller.cancel_operation('virtual_loader')
        self.progress.hide()
        self.status.setText(self.tr('Cancelling…'))

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
        self._session_lookup.cancel()
        self._session = (self.package_root, result.detail, result.pid)
        self.status.setText(self.tr('Starting the virtual session…'))
        self.progress.setRange(0, 100)
        self.progress.setValue(0)
        self.progress.show()
        self._session_timer.start()
        self._poll_session()

    def _poll_session(self):
        if not self._session or self._session_lookup.busy or self._closed:
            return
        from cdmw.services.virtual_loader_runtime import session_status
        root, token, host_pid = self._session
        self._session_lookup.request(self._session,
            lambda stop: session_status(root, token, host_pid=host_pid))

    def _session_status_ready(self, key, state):
        if self._closed or key != self._session:
            return
        if not self._working:
            self.status.setText(self.tr(state.detail))
            if state.state == 'starting':
                self.progress.setRange(0, 100 if state.progress is not None else 0)
                if state.progress is not None:
                    self.progress.setValue(state.progress)
                self.progress.show()
            else:
                self.progress.hide()
        if state.state in ('stopped', 'blocked'):
            self._session_timer.stop()
            self._session = None
            self._buttons()

    def _session_status_failed(self, key, message):
        if not self._closed and key == self._session and not self._working:
            self.status.setText(self.tr(str(message)))

    def _trace(self):
        from cdmw.services.virtual_loader_runtime import prepare_diagnostic_trace, start_diagnostic_trace
        root = self.package_root
        def done(plan):
            generation = self._generation
            detail = self.tr('Start a diagnostic game session using original game files? Virtual items will not be active. Leave the game at its title screen without loading a save, then close it.')
            detail += '\n\n' + str(plan.executable) + '\nSHA-256: ' + plan.executable_sha256
            if QMessageBox.question(self, self.tr('Review startup trace…'), detail) == QMessageBox.Yes and generation == self._generation and not self._closed:
                self._queued = lambda: self._run(lambda log, stop: start_diagnostic_trace(root, confirmed=True, expected_plan=plan, stop_event=stop), self._started,
                                                publishes_result=True)
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
        self._error = ''
        self._session = None
        self._session_timer.stop()
        self._session_lookup.cancel()
        self._draft_loaded = False
        self.selection.clear()
        self._next_order = 0
        self.review.clear()
        self.count.clear()
        self.progress.hide()
        self._buttons()

    def request_shutdown(self):
        self._closed = True
        self._generation += 1
        self._queued = None
        self._session_timer.stop()
        self._session_lookup.request_shutdown()
        if self._working and not self._applying:
            self.controller.cancel_operation('virtual_loader')
