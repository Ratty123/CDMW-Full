"""Installed overlay inventory and reviewed removal on the Studio worker lane."""
from datetime import datetime

from PySide6.QtCore import Qt, QTimer, QSignalBlocker
from PySide6.QtWidgets import (
    QAbstractItemView, QDialog, QDialogButtonBox, QHeaderView, QLabel,
    QMessageBox, QPushButton, QTableWidget, QTableWidgetItem, QVBoxLayout, QHBoxLayout,
    QComboBox, QSplitter, QWidget,
)

from cdmw.services.archive_overlay_manager import (
    list_installed_overlays, prepare_overlay_removal, apply_overlay_change,
    prepare_overlay_retirement, apply_overlay_retirement,
)


class OverlayManagerDialog(QDialog):
    def __init__(self, controller, package_root, mutation_service, parent=None):
        super().__init__(parent)
        self.controller, self.package_root, self.mutations = controller, package_root, mutation_service
        self._closed, self._working, self._applying = False, False, False
        self._queued = None
        self._entries = ()
        self._preview_entry = None
        self._preview_revision = 0
        self.setWindowTitle('Installed overlays')
        # Deletion waits nonblockingly for the preview workers/process cleanup.
        self.resize(1200, 620)
        layout = QVBoxLayout(self)
        self.status = QLabel('Reading installed overlays…')
        self.status.setTextFormat(Qt.TextFormat.PlainText)
        self.status.setWordWrap(True)
        layout.addWidget(self.status)
        self.table = QTableWidget(0, 7)
        self.table.setHorizontalHeaderLabels(['Overlay', 'Items', 'Folder', 'Files', 'Installed', 'Built for', 'Game check'])
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.setAlternatingRowColors(True)
        self.table.verticalHeader().hide()
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Interactive)
        self.table.horizontalHeader().resizeSection(0, 240)
        for column in range(1, 7):
            self.table.horizontalHeader().setSectionResizeMode(column, QHeaderView.ResizeMode.ResizeToContents)
        for column in (2, 3, 5):
            self.table.setColumnHidden(column, True)
        self.table.itemSelectionChanged.connect(self._selection_changed)
        self.table.currentCellChanged.connect(self._selection_changed)
        split = QSplitter(Qt.Orientation.Horizontal)
        split.setChildrenCollapsible(False)
        split.addWidget(self.table)
        preview_panel = QWidget()
        preview_layout = QVBoxLayout(preview_panel)
        preview_layout.setContentsMargins(4, 0, 0, 0)
        self.preview_item = QComboBox()
        self.preview_item.setToolTip('Choose an item from the selected installed overlay.')
        self.preview_item.currentIndexChanged.connect(self._show_preview)
        preview_layout.addWidget(self.preview_item)
        from cdmw.ui.new_item.item_preview import ItemPreviewFrame
        context = dict(getattr(controller, '_template_preview_context', None) or {})
        self.preview = ItemPreviewFrame(
            output_root=context.get('output_root'),
            native_preview_core_cache_root=context.get('native_preview_core_cache_root'))
        self.preview.set_render_settings(context.get('render_settings'))
        self.preview.set_cache_mode(context.get('cache_mode'))
        self.preview.set_gizmo_enabled(False)
        self.preview.gizmo_visible.hide()
        self.preview.placeholder.setText('Select an overlay to preview its installed items.')
        self.preview.status_changed.connect(controller.log_message.emit)
        preview_layout.addWidget(self.preview, 1)
        self.preview_empty = QLabel('Select an overlay to preview its installed items.')
        self.preview_empty.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.preview_empty.setWordWrap(True)
        preview_layout.addWidget(self.preview_empty, 1)
        self.preview.setVisible(False)
        split.addWidget(preview_panel)
        split.setSizes([700, 500])
        layout.addWidget(split, 1)
        self._preview_cleanup = QTimer(self)
        self._preview_cleanup.setInterval(25)
        self._preview_cleanup.timeout.connect(self._delete_when_ready)
        self.details = QLabel('')
        self.details.setWordWrap(True)
        self.details.setTextFormat(Qt.TextFormat.PlainText)
        self.details.setParent(self)
        self.details.hide()
        row = QHBoxLayout()
        self.remove_button = QPushButton('Remove selected…')
        self.remove_button.clicked.connect(self._remove)
        row.addWidget(self.remove_button)
        self.refresh_button = QPushButton('Refresh')
        self.refresh_button.clicked.connect(self.refresh)
        row.addWidget(self.refresh_button)
        self.update_button = QPushButton('Check game updates...')
        self.update_button.clicked.connect(self._check_updates)
        row.addWidget(self.update_button)
        self.start_fresh_button = QPushButton('Start fresh...')
        self.start_fresh_button.clicked.connect(self._start_fresh)
        row.addWidget(self.start_fresh_button)
        row.addStretch(1)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        buttons.rejected.connect(self.reject)
        row.addWidget(buttons)
        layout.addLayout(row)
        self.finished.connect(self._finished)
        controller.busy_changed.connect(self._busy_changed)
        self._buttons()
        QTimer.singleShot(0, self, self.refresh)

    def _buttons(self):
        available = not self._working and not self.controller.busy
        self.table.setEnabled(available)
        self.refresh_button.setEnabled(available)
        self.update_button.setEnabled(available and bool(self._entries))
        selected = self._selected_entry()
        self.remove_button.setEnabled(available and selected is not None and selected.compatibility_status != 'unmounted')
        self.remove_button.setToolTip('This overlay is no longer mounted. Use Check game updates or Start fresh.'
                                     if selected and selected.compatibility_status == 'unmounted'
                                     else 'Review removal of the selected overlay before applying it.')
        self.start_fresh_button.setEnabled(available and bool(self._entries)
                                          and all(entry.compatibility_status == 'unmounted' for entry in self._entries))

    def _selected_entry(self):
        rows = self.table.selectionModel().selectedRows()
        return self._entries[rows[0].row()] if rows and rows[0].row() < len(self._entries) else None

    def _selection_changed(self, *_args):
        entry = self._selected_entry()
        self.details.setText('This earlier install has no separate ownership history. Its contents are managed as one bundle.'
                             if entry and entry.legacy else 'Removing one overlay preserves the shared tables and files used by the remaining overlays.')
        if entry and entry.compatibility_status == 'unmounted':
            self.details.setText('The overlay is recorded in CDMW history, but its folder is not mounted by the game. '
                                 'Check game updates to review recovery, or choose Start fresh to retire the old set and install new items.')
        elif entry and entry.compatibility_status != 'same':
            self.details.setText(self.details.text() + ' Check game updates before changing this installed set.')
        self.table.setToolTip(self.details.text())
        self._buttons()
        if entry != self._preview_entry:
            self._preview_entry = entry
            with QSignalBlocker(self.preview_item):
                self.preview_item.clear()
                for key in entry.item_keys if entry else ():
                    self.preview_item.addItem(str(key), key)
            self.preview_item.setEnabled(bool(entry and entry.item_keys))
            self._show_preview()

    def _show_preview(self, *_args):
        if self._closed:
            return
        entry, key, snapshot = self._preview_entry, self.preview_item.currentData(), self.controller.snapshot
        if entry is None or key is None or snapshot is None or entry.compatibility_status == 'unmounted':
            self.preview.show(None)
            self.preview.setVisible(False)
            self.preview_empty.setText('No mounted item model is available for this overlay.')
            self.preview_empty.setVisible(True)
            return
        from cdmw.services.new_item_overlay_preview import overlay_item_preview_models
        root, directory = self.package_root, entry.directory
        render_settings = self.preview._render_settings

        def build(stop):
            from cdmw.ui.new_item.item_preview_materials import as_parsed_mesh, placement_reference_mesh, prepare_preview_model
            models = overlay_item_preview_models(snapshot, root, directory, key, stop_event=stop)
            if len(models) == 1:
                return models[0]
            mesh = None
            for model in models:
                prepared = prepare_preview_model(model, render_settings=render_settings, stop_event=stop)
                mesh = placement_reference_mesh(mesh, as_parsed_mesh(prepared))
            return mesh

        self.preview_empty.setVisible(False)
        self.preview.setVisible(True)
        self.preview.show(build, token=(entry.id, key, self._preview_revision), framing_key=(entry.id, key))

    def _run(self, task, done, status, *, applying=False):
        if self._closed:
            return
        self._working, self._applying = True, applying
        self.status.setText(status)
        self._buttons()
        def completed(value):
            self._working = self._applying = False
            if applying:
                # A committed change still reaches the Studio if its dialog closed.
                self.controller.install_finished.emit(value)
            if not self._closed:
                done(value)
                self._buttons()
                self._resume()
        def failed(message):
            self._working = self._applying = False
            if applying:
                self.controller.log_message.emit(str(message))
                self.controller.status_message.emit(str(message), True)
            if not self._closed:
                self.status.setText(message)
                self._buttons()
        if not self.controller._run('overlay_manager', task, completed, failed):
            failed('Wait for the current operation to finish, then refresh.')

    def refresh(self):
        self._run(lambda _log, stop: list_installed_overlays(self.package_root, stop_event=stop),
                  self._loaded, 'Reading installed overlays…')

    def _loaded(self, entries):
        self._preview_entry = object()
        self._preview_revision += 1
        self._entries = tuple(entries)
        self.table.setRowCount(len(entries))
        for row, entry in enumerate(entries):
            check = {'changed': self.tr('Needs comparison'), 'same': self.tr('Same build'),
                     'unknown': self.tr('Unknown'), 'unmounted': self.tr('Not mounted')}[entry.compatibility_status]
            values = (entry.label, ', '.join(map(str, entry.item_keys)) or '—', entry.directory,
                      str(entry.file_count), datetime.fromtimestamp(entry.created_at).strftime('%Y-%m-%d %H:%M'), entry.game_build, check)
            tooltip = '\n'.join(f'{self.table.horizontalHeaderItem(column).text()}: {value}'
                                for column, value in enumerate(values))
            for column, value in enumerate(values):
                item = QTableWidgetItem(value)
                item.setToolTip(tooltip)
                self.table.setItem(row, column, item)
        if entries:
            self.table.selectRow(0)
        unmounted = sum(entry.compatibility_status == 'unmounted' for entry in entries)
        if unmounted:
            self.status.setText(f'{len(entries)} recorded overlay(s); {unmounted} not mounted by the game.')
        else:
            self.status.setText(f'{len(entries)} installed overlay(s).' if entries else 'No CDMW overlays are installed.')
        self._selection_changed()

    def _check_updates(self):
        from cdmw.ui.new_item.mod_update_dialog import ModUpdateDialog
        dialog = ModUpdateDialog(self.controller, self.package_root, self, installed=True)
        dialog.setWindowModality(Qt.WindowModality.WindowModal)
        dialog.show()

    def _remove(self):
        entry = self._selected_entry()
        if entry is None:
            return
        identity = entry.id
        self._run(lambda log, stop: prepare_overlay_removal(self.package_root, identity, on_log=log, stop_event=stop),
                  self._review_removal, 'Preparing removal and checking the remaining overlays…')

    def _start_fresh(self):
        self._run(lambda _log, stop: prepare_overlay_retirement(self.package_root, stop_event=stop),
                  self._review_retirement, 'Checking the saved overlay set before starting fresh...')

    def _review_retirement(self, preparation):
        labels = '\n'.join('- ' + label for label in preparation.labels)
        if QMessageBox.question(self, 'Start fresh with overlays',
            f'Retire these saved overlays?\n\n{labels}\n\nGame folder: {preparation.package_root}\n\n'
            f'CDMW will back up and archive .cdmw/overlays.json. Folder {preparation.directory_name} and the old '
            'overlay journals stay on disk for recovery. The current mount list, texture registry and game archives stay unchanged.\n\n'
            'New installs will use a fresh inventory and an unused folder. Close Crimson Desert before continuing.',
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No) != QMessageBox.StandardButton.Yes:
            self.status.setText('Starting fresh cancelled. The saved overlay set is unchanged.')
            return
        self._queued = ('retire', preparation)

    def _apply_retirement(self, preparation):
        mutations = self.mutations
        def task(log, stop):
            return apply_overlay_retirement(preparation, confirmed=True,
                backup=lambda paths, label: mutations.backup_files(paths, description=label, on_log=log),
                restore_backup=lambda path: mutations.restore_backup(path, confirmed=True, on_log=log),
                on_log=log, stop_event=stop)
        self._run(task, self._retired, 'Backing up and retiring the unmounted overlay set...', applying=True)

    def _retired(self, result):
        self.status.setText(f'Retired {len(result.labels)} overlay(s). Ready for a fresh set. Backup: {result.backup_dir}')
        self._queued = ('refresh', None)

    def _review_removal(self, preparation):
        remaining = '\n'.join('- ' + label for label in preparation.remaining_labels) or 'None'
        targets = '\n'.join('- ' + path for path in dict.fromkeys((*dict(preparation.writes), *preparation.deletes))
                            if path.startswith(preparation.directory_name + '/') or path.startswith('meta/'))
        if QMessageBox.question(self, 'Remove selected overlay',
            f'Remove {preparation.label}?\n\nGame folder: {preparation.package_root}\n\n'
            f'Overlays that will remain:\n{remaining}\n\nFiles to update:\n{targets}\n\n'
            'A verified backup is created first. Close Crimson Desert before continuing.',
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No) != QMessageBox.StandardButton.Yes:
            self.status.setText('Removal cancelled. The installed overlays are unchanged.')
            return
        self._queued = ('apply', preparation)

    def _apply(self, preparation):
        mutations = self.mutations
        def task(log, stop):
            return apply_overlay_change(preparation, confirmed=True,
                backup=lambda paths, label: mutations.backup_files(paths, description=label, on_log=log),
                restore_backup=lambda path: mutations.restore_backup(path, confirmed=True, on_log=log),
                on_log=log, stop_event=stop)
        self._run(task, self._removed, 'Updating installed overlays…', applying=True)

    def _removed(self, result):
        self.status.setText(f'Removed {result.label}. {result.remaining} overlay(s) remain. Backup: {result.backup_dir}')
        self._queued = ('refresh', None)

    def _resume(self):
        if self._closed or self._working or self.controller.busy or self._queued is None:
            return
        action, preparation = self._queued
        self._queued = None
        if action == 'apply':
            self._apply(preparation)
        elif action == 'retire':
            self._apply_retirement(preparation)
        else:
            self.refresh()

    def _busy_changed(self, _busy):
        if not self._closed:
            self._buttons()
            self._resume()

    def _finished(self, _result):
        self._closed = True
        self._queued = None
        if self._working and not self._applying:
            self.controller.cancel_operation('overlay_manager')
        # An apply already has confirmation and owns its transaction; let it
        # finish or roll back and deliver the result to the persistent controller.
        self.request_shutdown()
        self._delete_when_ready()

    def iter_shutdown_workers(self):
        return self.preview.iter_shutdown_workers()

    def request_shutdown(self):
        self.preview.request_shutdown()

    def _delete_when_ready(self):
        processes = getattr(self.preview, '_preview_shutdown_ready', None)
        if self.iter_shutdown_workers() or (processes is not None and not processes.is_set()):
            self._preview_cleanup.start()
        else:
            self._preview_cleanup.stop()
            # A Rust viewport portal may have temporarily reparented this host
            # outside the dialog. It is still owned by this preview.
            if self.preview.host is not None:
                self.preview.host.deleteLater()
            self.deleteLater()
