"""Installed overlay inventory and reviewed removal on the Studio worker lane."""
from datetime import datetime

from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import (
    QAbstractItemView, QDialog, QDialogButtonBox, QHeaderView, QLabel,
    QMessageBox, QPushButton, QTableWidget, QTableWidgetItem, QVBoxLayout, QHBoxLayout,
)

from cdmw.services.archive_overlay_manager import list_installed_overlays, prepare_overlay_removal, apply_overlay_change


class OverlayManagerDialog(QDialog):
    def __init__(self, controller, package_root, mutation_service, parent=None):
        super().__init__(parent)
        self.controller, self.package_root, self.mutations = controller, package_root, mutation_service
        self._closed, self._working, self._applying = False, False, False
        self._queued = None
        self._entries = ()
        self.setWindowTitle('Installed overlays')
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
        self.resize(900, 430)
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
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        for column in range(1, 7):
            self.table.horizontalHeader().setSectionResizeMode(column, QHeaderView.ResizeMode.ResizeToContents)
        self.table.itemSelectionChanged.connect(self._selection_changed)
        layout.addWidget(self.table, 1)
        self.details = QLabel('')
        self.details.setWordWrap(True)
        self.details.setTextFormat(Qt.TextFormat.PlainText)
        layout.addWidget(self.details)
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
        self.remove_button.setEnabled(available and 0 <= self.table.currentRow() < len(self._entries))

    def _selection_changed(self):
        index = self.table.currentRow()
        entry = self._entries[index] if 0 <= index < len(self._entries) else None
        self.details.setText('This earlier install has no separate ownership history. Its contents are managed as one bundle.'
                             if entry and entry.legacy else 'Removing one overlay preserves the shared tables and files used by the remaining overlays.')
        if entry and entry.compatibility_status != 'same':
            self.details.setText(self.details.text() + ' Check game updates before changing this installed set.')
        self._buttons()

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
        self._entries = tuple(entries)
        self.table.setRowCount(len(entries))
        for row, entry in enumerate(entries):
            check = {'changed': self.tr('Needs comparison'), 'same': self.tr('Same build'), 'unknown': self.tr('Unknown')}[entry.compatibility_status]
            values = (entry.label, ', '.join(map(str, entry.item_keys)) or '—', entry.directory,
                      str(entry.file_count), datetime.fromtimestamp(entry.created_at).strftime('%Y-%m-%d %H:%M'), entry.game_build, check)
            for column, value in enumerate(values):
                self.table.setItem(row, column, QTableWidgetItem(value))
        if entries:
            self.table.selectRow(0)
        self.status.setText(f'{len(entries)} installed overlay(s).' if entries else 'No CDMW overlays are installed.')
        self._selection_changed()

    def _check_updates(self):
        from cdmw.ui.new_item.mod_update_dialog import ModUpdateDialog
        dialog = ModUpdateDialog(self.controller, self.package_root, self, installed=True)
        dialog.setWindowModality(Qt.WindowModality.WindowModal)
        dialog.show()

    def _remove(self):
        index = self.table.currentRow()
        if not 0 <= index < len(self._entries):
            return
        identity = self._entries[index].id
        self._run(lambda log, stop: prepare_overlay_removal(self.package_root, identity, on_log=log, stop_event=stop),
                  self._review_removal, 'Preparing removal and checking the remaining overlays…')

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
