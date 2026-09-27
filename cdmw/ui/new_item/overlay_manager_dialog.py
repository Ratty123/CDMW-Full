"""Installed overlay inventory and reviewed removal on the Studio worker lane."""
from datetime import datetime
from uuid import uuid4

from PySide6.QtCore import Qt, QTimer, QSignalBlocker, Signal
from PySide6.QtWidgets import (
    QAbstractItemView, QDialog, QDialogButtonBox, QHeaderView, QLabel,
    QMessageBox, QPushButton, QTableWidget, QTableWidgetItem, QVBoxLayout, QHBoxLayout,
    QComboBox, QLineEdit, QPlainTextEdit, QSplitter, QTabWidget, QWidget,
)

from cdmw.services.archive_overlay_manager import (
    list_installed_overlays, prepare_overlay_removal, apply_overlay_change,
    prepare_overlay_retirement, apply_overlay_retirement, prepare_overlay_enabled,
)


class OverlayManagerDialog(QDialog):
    updates_requested = Signal()
    activity = Signal(str)

    def __init__(self, controller, package_root, mutation_service, parent=None, *, embedded=False,
                 catalogue_service=None):
        super().__init__(parent)
        self._embedded = embedded
        if embedded:
            self.setWindowFlags(Qt.WindowType.Widget)
        self.controller, self.package_root, self.mutations = controller, package_root, mutation_service
        self._catalogue_service = catalogue_service
        self._closed, self._working, self._applying = False, False, False
        self._reading = False
        self._inventory_lane = controller.create_lookup_lane()
        self._inventory_lane.completed.connect(self._inventory_ready)
        self._inventory_lane.failed.connect(self._inventory_failed)
        self._queued = None
        self._entries = ()
        self._preview_entry = None
        self._preview_revision = 0
        self._preview_session = uuid4().hex
        self._details_lane = controller.create_lookup_lane()
        self._details_lane.completed.connect(self._details_ready)
        self._details_lane.failed.connect(self._details_failed)
        self.setWindowTitle('Installed overlays')
        # Deletion waits nonblockingly for the preview workers/process cleanup.
        self.resize(1200, 620)
        layout = QVBoxLayout(self)
        self.status = QLabel('Reading installed overlays…')
        self.status.setTextFormat(Qt.TextFormat.PlainText)
        self.status.setWordWrap(True)
        layout.addWidget(self.status)
        self.search = QLineEdit()
        self.search.setPlaceholderText('Search overlays by name, item ID or state…')
        self.search.textChanged.connect(self._filter)
        layout.addWidget(self.search)
        self.table = QTableWidget(0, 8)
        self.table.setHorizontalHeaderLabels(['Overlay', 'Items', 'Folder', 'Files', 'Installed', 'Built for', 'Game check', 'State'])
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.setAlternatingRowColors(True)
        self.table.verticalHeader().hide()
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Interactive)
        self.table.horizontalHeader().resizeSection(0, 240)
        for column in range(1, 8):
            self.table.horizontalHeader().setSectionResizeMode(column, QHeaderView.ResizeMode.ResizeToContents)
        for column in (2, 3, 4, 5):
            self.table.setColumnHidden(column, True)
        self.table.itemSelectionChanged.connect(self._selection_changed)
        self.table.currentCellChanged.connect(self._selection_changed)
        split = QSplitter(Qt.Orientation.Horizontal)
        split.setObjectName('mod_management_inventory_splitter')
        split.setChildrenCollapsible(False)
        split.addWidget(self.table)
        preview_panel = QWidget()
        preview_layout = QVBoxLayout(preview_panel)
        preview_layout.setContentsMargins(4, 0, 0, 0)
        self.selected_title = QLabel('Select an overlay')
        self.selected_title.setTextFormat(Qt.TextFormat.PlainText)
        self.selected_title.setWordWrap(True)
        preview_layout.addWidget(self.selected_title)
        self.inspector = QTabWidget()
        preview_page = QWidget()
        preview_body = QVBoxLayout(preview_page)
        preview_body.setContentsMargins(0, 0, 0, 0)
        self.inspector.addTab(preview_page, 'Preview')
        preview_layout.addWidget(self.inspector, 1)
        self.preview_item = QComboBox()
        self.preview_item.setToolTip('Choose an item from the selected installed overlay.')
        self.preview_item.currentIndexChanged.connect(self._show_preview)
        preview_toolbar = QHBoxLayout()
        preview_toolbar.addWidget(self.preview_item, 1)
        preview_body.addLayout(preview_toolbar)
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
        self.preview.status_changed.connect(self._preview_status)
        preview_body.addWidget(self.preview, 1)
        self.preview_empty = QLabel('Select an overlay to preview its installed items.')
        self.preview_empty.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.preview_empty.setWordWrap(True)
        preview_body.addWidget(self.preview_empty, 1)
        self.preview_status = QLabel('Select an overlay to preview its installed items.')
        self.preview_status.setTextFormat(Qt.TextFormat.PlainText)
        self.preview_status.setWordWrap(True)
        preview_body.addWidget(self.preview_status)
        self.preview_retry = QPushButton('Reload preview')
        self.preview_retry.clicked.connect(self._retry_preview)
        preview_toolbar.addWidget(self.preview_retry)
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
        files_page = QWidget()
        files_layout = QVBoxLayout(files_page)
        files_layout.setContentsMargins(0, 0, 0, 0)
        files_layout.addWidget(self.details)
        self.files = QPlainTextEdit()
        self.files.setReadOnly(True)
        files_layout.addWidget(self.files, 1)
        self.inspector.addTab(files_page, 'Files and history')
        self.external = QLabel('')
        self.external.setTextFormat(Qt.TextFormat.PlainText)
        self.external.setWordWrap(True)
        layout.addWidget(self.external)
        row = QHBoxLayout()
        self.toggle_button = QPushButton('Disable…')
        self.toggle_button.clicked.connect(self._toggle)
        row.addWidget(self.toggle_button)
        self.remove_button = QPushButton('Remove selected…')
        self.remove_button.clicked.connect(self._remove)
        row.addWidget(self.remove_button)
        self.refresh_button = QPushButton('Refresh')
        self.refresh_button.clicked.connect(self.refresh)
        row.addWidget(self.refresh_button)
        self.update_button = QPushButton('Check game updates...')
        self.update_button.clicked.connect(self._check_updates)
        row.addWidget(self.update_button)
        self.rebuild_button = QPushButton('Rebuild / reapply…')
        self.rebuild_button.clicked.connect(self._rebuild)
        row.addWidget(self.rebuild_button)
        self.start_fresh_button = QPushButton('Start fresh...')
        self.start_fresh_button.clicked.connect(self._start_fresh)
        row.addWidget(self.start_fresh_button)
        row.addStretch(1)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        buttons.rejected.connect(self.reject)
        row.addWidget(buttons)
        buttons.setVisible(not embedded)
        layout.addLayout(row)
        self.finished.connect(self._finished)
        controller.busy_changed.connect(self._busy_changed)
        self._buttons()
        if not embedded:
            QTimer.singleShot(0, self, self.refresh)

    def _buttons(self):
        available = not self._working and not self._reading and not self.controller.busy
        browsing = not self._working and not self._reading and not self._inventory_blocked()
        self.table.setEnabled(browsing)
        self.refresh_button.setEnabled(browsing)
        self.update_button.setEnabled(available and bool(self._entries))
        selected = self._selected_entry()
        mutable = available and self.mutations is not None
        healthy = selected is not None and selected.health in {'mounted', 'disabled'} and not selected.issue
        self.remove_button.setEnabled(mutable and healthy and selected.compatibility_status != 'unmounted')
        self.toggle_button.setEnabled(mutable and healthy)
        self.toggle_button.setText('Disable…' if selected is None or selected.enabled else 'Enable…')
        self.rebuild_button.setEnabled(mutable and bool(self._entries))
        self.preview_retry.setEnabled(bool(selected and selected.enabled and selected.health == 'mounted'))
        self.remove_button.setToolTip('This overlay is no longer mounted. Use Check game updates or Start fresh.'
                                     if selected and selected.compatibility_status == 'unmounted'
                                     else 'Review removal of the selected overlay before applying it.')
        self.start_fresh_button.setEnabled(mutable and bool(self._entries)
                                          and all(entry.compatibility_status == 'unmounted' for entry in self._entries))

    def _selected_entry(self):
        rows = self.table.selectionModel().selectedRows()
        return self._entries[rows[0].row()] if rows and rows[0].row() < len(self._entries) else None

    def _selection_changed(self, *_args):
        entry = self._selected_entry()
        self.selected_title.setText(entry.label if entry else 'Select an overlay')
        self.details.setText('This earlier install has no separate ownership history. Its contents are managed as one bundle.'
                             if entry and entry.legacy else 'Removing one overlay preserves the shared tables and files used by the remaining overlays.')
        if entry and entry.compatibility_status == 'unmounted':
            self.details.setText('The overlay is recorded in CDMW history, but its folder is not mounted by the game. '
                                 'Check game updates to review recovery, or choose Start fresh to retire the old set and install new items.')
        elif entry and entry.compatibility_status != 'same':
            self.details.setText(self.details.text() + ' Check game updates before changing this installed set.')
        if entry and entry.issue:
            self.details.setText(entry.issue)
        elif entry and not entry.enabled:
            self.details.setText('Disabled. Its owned changes are removed from the mounted archive; its saved history can be enabled again.')
        self.table.setToolTip(self.details.text())
        self._buttons()
        if entry != self._preview_entry:
            self._preview_entry = entry
            with QSignalBlocker(self.preview_item):
                self.preview_item.clear()
                for key in entry.item_keys if entry else ():
                    self.preview_item.addItem(str(key), key)
            self.preview_item.setEnabled(bool(entry and entry.item_keys))
            self.files.setPlainText('Reading owned files and history…' if entry else '')
            self._details_lane.cancel()
            if entry:
                from cdmw.services.overlay_inventory_details import overlay_details
                root, identity = self.package_root, entry.id
                self._details_lane.request((self._preview_revision, identity),
                    lambda stop: overlay_details(root, identity, stop_event=stop))
            self._show_preview()

    def _details_ready(self, key, text):
        entry = self._selected_entry()
        if not self._closed and entry and key == (self._preview_revision, entry.id):
            self.files.setPlainText(text)

    def _details_failed(self, key, message):
        self._details_ready(key, f'Could not read overlay history: {message}')

    def _preview_status(self, message):
        if self._closed:
            return
        self.preview_status.setText(str(message) or 'Waiting for the viewport…')
        self.activity.emit(str(message))

    def _retry_preview(self):
        self._preview_session = uuid4().hex
        self._show_preview()

    def _filter(self, *_args):
        query = self.search.text().strip().casefold()
        visible = []
        for row in range(self.table.rowCount()):
            matches = not query or any(query in self.table.item(row, col).text().casefold()
                                       for col in range(self.table.columnCount()) if self.table.item(row, col))
            self.table.setRowHidden(row, not matches)
            if matches:
                visible.append(row)
        if self.table.currentRow() not in visible:
            self.table.clearSelection()
            self.table.setCurrentCell(-1, -1)
        self._selection_changed()

    def _show_preview(self, *_args):
        if self._closed:
            return
        entry, key, snapshot = self._preview_entry, self.preview_item.currentData(), self.controller.snapshot
        if entry is None or key is None or not entry.enabled or entry.health != 'mounted' or entry.compatibility_status == 'unmounted':
            self.preview.show(None)
            self.preview.setVisible(False)
            self.preview_empty.setText('Select an overlay to preview its installed items.' if entry is None else
                                       entry.issue or 'No mounted item model is available for this overlay.')
            self.preview_empty.setVisible(True)
            self.preview_status.setText('Select an enabled, mounted overlay with an item model.')
            return
        from cdmw.services.new_item_overlay_preview import overlay_item_preview_models
        from cdmw.core.archive_resident_index import ResidentArchiveSource
        root, directory = self.package_root, entry.directory
        resident_source = ResidentArchiveSource.capture(self._catalogue_service, root)
        render_settings = self.preview._render_settings

        def build(stop):
            from cdmw.ui.new_item.item_preview_materials import as_parsed_mesh, placement_reference_mesh, prepare_preview_model
            models = overlay_item_preview_models(snapshot, root, directory, key, stop_event=stop,
                                                 resident_source=resident_source)
            if len(models) == 1:
                return models[0]
            mesh = None
            for model in models:
                prepared = prepare_preview_model(model, render_settings=render_settings, stop_event=stop)
                mesh = placement_reference_mesh(mesh, as_parsed_mesh(prepared))
            return mesh

        self.preview_empty.setVisible(False)
        self.preview.setVisible(True)
        # Refresh/reopen must not reuse a durable package from older installed
        # bytes. Selection within this inventory generation can still reuse it.
        self.preview.show(build, token=('installed_overlay', self._preview_session, entry.id, key,
                                        self._preview_revision), framing_key=(entry.id, key))

    def _run(self, task, done, status, *, applying=False):
        if self._closed:
            return
        self._working, self._applying = True, applying
        self.status.setText(status)
        self.activity.emit(status)
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
                self.activity.emit(str(message))
                self._buttons()
        if not self.controller._run('overlay_manager', task, completed, failed):
            failed('Wait for the current operation to finish, then refresh.')

    def refresh(self):
        if self._closed:
            return
        if self._inventory_blocked():
            self._queued = ('refresh', None)
            return
        root = str(self.package_root or '').strip()
        self._inventory_lane.cancel()
        if not root:
            self._reading = False
            self._loaded(())
            self.status.setText('Choose the game archive folder, then refresh.')
            return
        from cdmw.services.overlay_inventory_details import external_overlay_summary
        def read(stop):
            return list_installed_overlays(root, stop_event=stop), external_overlay_summary(root, stop_event=stop)
        self._reading = True
        self.status.setText('Reading installed overlays…')
        self.activity.emit(self.status.text())
        self._buttons()
        self._inventory_lane.request(root, read)

    def _inventory_blocked(self):
        # Snapshot preparation is read-only and independent of the inventory.
        # Writes and management operations still use the shared operation lane.
        return self.controller.busy and self.controller._lane != 'snapshot'

    def _inventory_ready(self, root, result):
        if self._closed or root != str(self.package_root or '').strip():
            return
        self._reading = False
        self._inventory_loaded(result)
        self._buttons()

    def _inventory_failed(self, root, message):
        if self._closed or root != str(self.package_root or '').strip():
            return
        self._reading = False
        self.status.setText(message)
        self.activity.emit(str(message))
        self._buttons()

    def _inventory_loaded(self, result):
        entries, external = result
        self.external.setText(external)
        self._loaded(entries)

    def _loaded(self, entries):
        previous = self._selected_entry()
        previous_id = previous.id if previous else None
        self._preview_entry = object()
        self._preview_revision += 1
        self._entries = tuple(entries)
        selection_blocker = QSignalBlocker(self.table)
        self.table.clearSelection()
        self.table.setCurrentCell(-1, -1)
        self.table.setRowCount(len(entries))
        for row, entry in enumerate(entries):
            check = {'changed': self.tr('Needs comparison'), 'same': self.tr('Same build'),
                     'unknown': self.tr('Unknown'), 'unmounted': self.tr('Not mounted')}[entry.compatibility_status]
            state = {'mounted': self.tr('Enabled'), 'disabled': self.tr('Disabled'), 'unmounted': self.tr('Not mounted'),
                     'missing': self.tr('Missing files'), 'changed': self.tr('Needs review')}.get(entry.health, entry.health)
            values = (entry.label, ', '.join(map(str, entry.item_keys)) or '—', entry.directory,
                      str(entry.file_count), datetime.fromtimestamp(entry.created_at).strftime('%Y-%m-%d %H:%M'), entry.game_build, check, state)
            tooltip = '\n'.join(f'{self.table.horizontalHeaderItem(column).text()}: {value}'
                                for column, value in enumerate(values))
            for column, value in enumerate(values):
                item = QTableWidgetItem(value)
                item.setToolTip(tooltip)
                self.table.setItem(row, column, item)
        selected_row = next((i for i, entry in enumerate(entries) if entry.id == previous_id), None)
        if selected_row is not None:
            self.table.selectRow(selected_row)
        selection_blocker.unblock()
        unmounted = sum(entry.compatibility_status == 'unmounted' for entry in entries)
        if unmounted:
            self.status.setText(f'{len(entries)} recorded overlay(s); {unmounted} not mounted by the game.')
        else:
            enabled = sum(entry.enabled for entry in entries)
            self.status.setText(f'{enabled} enabled · {len(entries) - enabled} disabled' if entries else 'No CDMW overlays are installed. Create an item and install it as an overlay to get started.')
        self._filter()
        self.activity.emit(self.status.text())

    def _check_updates(self):
        if self._embedded:
            self.updates_requested.emit()
            return
        from cdmw.ui.new_item.mod_update_dialog import ModUpdateDialog
        dialog = ModUpdateDialog(self.controller, self.package_root, self, installed=True)
        dialog.setWindowModality(Qt.WindowModality.WindowModal)
        dialog.show()

    def _toggle(self):
        entry = self._selected_entry()
        if entry is not None:
            root, identity, enabled = self.package_root, entry.id, not entry.enabled
            self._run(lambda log, stop: prepare_overlay_enabled(root, identity, enabled, on_log=log, stop_event=stop),
                      self._review_removal, 'Checking dependencies and preparing the overlay change…')

    def _rebuild(self):
        from cdmw.services.archive_overlay_rebuild import prepare_overlay_rebuild
        root = self.package_root
        self._run(lambda log, stop: prepare_overlay_rebuild(root, on_log=log, stop_event=stop),
                  self._review_removal, 'Comparing saved changes with the current mounted game…')

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
        action = {'remove': 'Remove', 'enable': 'Enable', 'disable': 'Disable', 'rebuild': 'Rebuild / reapply'}[preparation.action]
        remaining = '\n'.join('- ' + label for label in preparation.remaining_labels) or 'None'
        targets = '\n'.join('- ' + path for path in dict.fromkeys((*dict(preparation.writes), *preparation.deletes))
                            if path.startswith(preparation.directory_name + '/') or path.startswith('meta/'))
        if QMessageBox.question(self, action + ' overlay',
            f'{action} {preparation.label}?\n\nGame folder: {preparation.package_root}\n\n'
            f'Overlays that will remain:\n{remaining}\n\nFiles to update:\n{targets}\n\n'
            'A verified backup is created first. Close Crimson Desert before continuing.',
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No) != QMessageBox.StandardButton.Yes:
            self.status.setText('Change cancelled. The installed overlays are unchanged.')
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
        action = {'remove': 'Removed', 'enable': 'Enabled', 'disable': 'Disabled', 'rebuild': 'Rebuilt'}[result.action]
        self.status.setText(f'{action} {result.label}. {result.remaining} overlay(s) enabled. Backup: {result.backup_dir}')
        self.activity.emit(self.status.text())
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
            if self._inventory_blocked() and self._reading:
                self._inventory_lane.cancel()
                self._reading = False
                self._queued = ('refresh', None)
            if not _busy and self._working:
                self._working = self._applying = False
                self.status.setText('Operation finished or cancelled. Refresh to read the installed state.')
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
        self._closed = True
        self._queued = None
        self._inventory_lane.request_shutdown()
        self._details_lane.request_shutdown()
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
