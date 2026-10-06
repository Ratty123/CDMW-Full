"""Installation overview and navigation for the shared Mod Management workspace."""
from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QAbstractItemView, QCheckBox, QGroupBox, QHBoxLayout, QHeaderView,
    QLabel, QMessageBox, QPushButton, QTreeWidget, QTreeWidgetItem, QVBoxLayout, QWidget,
)

from cdmw.services.overlay_inventory_details import mounted_archive_status


class ModManagementOverview(QWidget):
    page_requested = Signal(str)
    refresh_requested = Signal()
    activity = Signal(str)

    def __init__(self, controller, parent=None, *, mutations=None):
        super().__init__(parent)
        self.setObjectName('mod_management_overview')
        self.controller, self.mutations = controller, mutations
        self._closed = False
        self._working = self._applying = False
        self._queued = None
        self._operation_generation = 0
        self._generation = 0
        self._root = ''
        self._mounts = ()
        self._entries = ()
        self._lookup = controller.create_lookup_lane()
        self._lookup.completed.connect(self._loaded)
        self._lookup.failed.connect(self._failed)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(12)
        summary = QHBoxLayout()
        self.counts = {}
        for key, title in (('enabled', 'Enabled'), ('disabled', 'Disabled'), ('attention', 'Needs review')):
            value = QLabel('—')
            value.setObjectName('mod_management_count_' + key)
            font = value.font()
            font.setBold(True)
            value.setFont(font)
            caption = QLabel(title)
            caption.setObjectName('mod_management_count_label_' + key)
            summary.addWidget(value)
            summary.addWidget(caption)
            summary.addSpacing(16)
            self.counts[key] = value
        summary.addStretch(1)
        layout.addLayout(summary)
        groups = QHBoxLayout()
        self.actions = {}
        choices = {
            'independent': ('Install item package', 'Install or update .cditem files and keep their save identities.'),
            'installed': ('Installed mods', 'Preview items, enable or disable mods, and remove selected installs.'),
            'repackage': ('Repackage mods', 'Convert folders or ZIPs for another mod manager.'),
            'merge': ('Merge mods', 'Combine compatible mod folders into one package.'),
            'updates': ('Check game updates', 'Compare recorded changes with your current game files.'),
            'recovery': ('Recovery', 'Rebuild saved installs or review an installation that needs attention.'),
        }
        for name, title, keys in (
            ('installs', 'Install && manage', ('independent', 'installed')),
            ('packages', 'Package tools', ('repackage', 'merge')),
            ('maintenance', 'Maintenance', ('updates', 'recovery')),
        ):
            group = QGroupBox(title)
            group.setObjectName('mod_management_group_' + name)
            body = QVBoxLayout(group)
            for key in keys:
                label, detail = choices[key]
                button = QPushButton(label)
                button.setObjectName('mod_management_open_' + key)
                button.setToolTip(detail)
                button.setProperty('newItemPrimary', key == 'independent')
                button.clicked.connect(lambda _checked=False, page=key: self.page_requested.emit(page))
                body.addWidget(button)
                self.actions[key] = button
            groups.addWidget(group, 1)
        layout.addLayout(groups)
        toolbar = QHBoxLayout()
        title = QLabel('Archive folders')
        title.setObjectName('mod_management_archives_title')
        font = title.font()
        font.setBold(True)
        title.setFont(font)
        toolbar.addWidget(title)
        toolbar.addStretch(1)
        self.show_game = QCheckBox('Show game archives')
        self.show_game.setObjectName('mod_management_show_game')
        self.show_game.toggled.connect(self._render_mounts)
        toolbar.addWidget(self.show_game)
        self.show_missing = QCheckBox('Show missing references')
        self.show_missing.setObjectName('mod_management_show_missing')
        self.show_missing.setToolTip('Include archive-list entries whose files are no longer present.')
        self.show_missing.toggled.connect(self._render_mounts)
        toolbar.addWidget(self.show_missing)
        self.clean_missing = QPushButton('Clean missing references...')
        self.clean_missing.setObjectName('mod_management_clean_missing')
        self.clean_missing.setToolTip('Review and remove stale mod references from the archive list, with a verified backup. No mod folders or item identities are deleted.')
        self.clean_missing.clicked.connect(self._clean_missing)
        toolbar.addWidget(self.clean_missing)
        self.refresh_button = QPushButton('Refresh')
        self.refresh_button.setObjectName('mod_management_refresh')
        self.refresh_button.clicked.connect(self.refresh_requested.emit)
        toolbar.addWidget(self.refresh_button)
        layout.addLayout(toolbar)
        self.mounts = QTreeWidget()
        self.mounts.setObjectName('mod_management_archives')
        self.mounts.setHeaderLabels(['Folder', 'Managed by', 'Status'])
        self.mounts.setRootIsDecorated(False)
        self.mounts.setSelectionMode(QAbstractItemView.SelectionMode.NoSelection)
        self.mounts.setMinimumHeight(90)
        self.mounts.header().setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
        self.mounts.header().setStretchLastSection(True)
        layout.addWidget(self.mounts, 1)
        self.status = QLabel('Choose a game folder, then refresh.')
        self.status.setObjectName('mod_management_status')
        self.status.setWordWrap(True)
        self.status.setTextFormat(Qt.TextFormat.PlainText)
        layout.addWidget(self.status)
        controller.busy_changed.connect(self._busy_changed)
        self._cleanup_button()

    def set_entries(self, entries):
        self._entries = tuple(entries)
        self.counts['enabled'].setText(str(sum(entry.enabled for entry in entries)))
        self.counts['disabled'].setText(str(sum(not entry.enabled for entry in entries)))
        self.counts['attention'].setText(str(sum(bool(entry.issue) or entry.health not in {'mounted', 'disabled'}
                                               or entry.compatibility_status == 'changed' for entry in entries)))
        self._render_mounts()

    def refresh(self, root):
        if self._closed:
            return
        self._generation += 1
        root = str(root or '').strip()
        if root != self._root:
            self._operation_generation += 1
            self._queued = None
            if self._working and not self._applying:
                self.controller.cancel_operation('overlay_manager')
        self._root = root
        self._mounts = ()
        self._render_mounts()
        self._lookup.cancel()
        self.status.setToolTip('')
        self.status.setProperty('modManagementWarning', False)
        if not self._root:
            self.status.setText(self.tr('Choose a game folder, then refresh.'))
            return
        self.status.setText(self.tr('Reading archive folders…'))
        root, key = self._root, (self._generation, self._root)
        self._lookup.request(key, lambda stop: mounted_archive_status(root, stop_event=stop))

    def _loaded(self, key, mounts):
        if self._closed or key != (self._generation, self._root):
            return
        self._mounts = mounts
        self._render_mounts()
        missing = [row.name for row in mounts if not row.game and not row.present]
        broken_game = [row.name for row in mounts if row.game and not row.present and not row.optional]
        self.status.setToolTip('')
        if broken_game:
            self.status.setText(self.tr('Required game archives are missing: {value_0}. Verify the game files before continuing.').format(value_0=', '.join(broken_game)))
        elif missing:
            self.status.setText(self.tr('1 stale mod reference') if len(missing) == 1 else
                                self.tr('{value_0} stale mod references').format(value_0=len(missing)))
            self.status.setToolTip(self.tr('The archive list still references {value_0}, but their archive indexes are absent. These are not active mod folders.').format(value_0=', '.join(missing)))
        else:
            self.status.setText('')
        self.status.setProperty('modManagementWarning', bool(broken_game))

    def _failed(self, key, message):
        if not self._closed and key == (self._generation, self._root):
            self.status.setToolTip('')
            self.status.setProperty('modManagementWarning', True)
            self.status.setText(str(message))

    def _render_mounts(self, *_args):
        self.mounts.clear()
        states = {}
        owned = {entry.directory for entry in self._entries}
        for row in self._mounts:
            if row.game and not self.show_game.isChecked():
                continue
            if not row.game and not row.present and not self.show_missing.isChecked():
                continue
            owner = self.tr('Game') if row.game else 'CDMW' if row.name in owned else self.tr('Unknown')
            status = (self.tr('Found') if row.present else self.tr('Stale reference') if not row.game else
                      self.tr('Not installed') if row.optional else self.tr('Missing files'))
            states[row.name] = 'found' if row.present else 'optional' if row.game and row.optional else 'missing'
            self.mounts.addTopLevelItem(QTreeWidgetItem([row.name, owner, status]))
        self.mounts.setProperty('modManagementFolderStates', states)
        self._cleanup_button()

    def _cleanup_button(self):
        self.clean_missing.setEnabled(bool(
            not self._closed and not self._working and not self.controller.busy
            and self.mutations is not None and self._root
            and any(not row.game and not row.present for row in self._mounts)))

    def _clean_missing(self):
        if not self.clean_missing.isEnabled():
            return
        from cdmw.services.archive_reference_cleanup import prepare_missing_reference_cleanup
        root = self._root
        self.status.setText(self.tr('Checking missing archive references...'))
        self._run_cleanup(lambda _log, stop: prepare_missing_reference_cleanup(root, stop_event=stop),
                          self._review_cleanup)

    def _run_cleanup(self, task, done, *, applying=False):
        if self._closed or self._working or self.controller.busy:
            return
        generation, root = self._operation_generation, self._root
        self._working, self._applying = True, applying
        self._cleanup_button()

        def completed(result):
            self._working = self._applying = False
            if not self._closed and (generation, root) == (self._operation_generation, self._root):
                done(result)
                self._resume_cleanup()
                self._cleanup_button()

        def failed(message):
            self._working = self._applying = False
            self._queued = None
            self.activity.emit(str(message))
            if not self._closed and (generation, root) == (self._operation_generation, self._root):
                self.status.setText(str(message))
                self._cleanup_button()

        if not self.controller._run('overlay_manager', task, completed, failed):
            self._working = self._applying = False
            self._cleanup_button()

    def _review_cleanup(self, preparation):
        if not preparation.names:
            self.status.setText(self.tr('No missing mod references to clean.'))
            self.refresh_requested.emit()
            return
        generation, root = self._operation_generation, self._root
        box = QMessageBox(QMessageBox.Icon.Question, self.tr('Clean missing references'),
                          self.tr('Remove {value_0} stale mod references from the archive list?').format(value_0=len(preparation.names))
                          + '\n\n' + self.tr('Game folder:') + ' ' + str(preparation.package_root)
                          + '\n\n' + '\n'.join(preparation.names)
                          + '\n\n' + self.tr('Only meta/0.papgt will change. Game archives, mod folders and item identities are kept. A verified backup is created first. Close the game before continuing.'),
                          QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No, self)
        box.setTextFormat(Qt.TextFormat.PlainText)
        box.setDefaultButton(QMessageBox.StandardButton.No)
        accepted = box.exec() == QMessageBox.StandardButton.Yes
        if not self._closed and (generation, root) == (self._operation_generation, self._root):
            if accepted:
                self._queued = (generation, root, preparation)
            else:
                self.status.setText(self.tr('Cleanup cancelled. The archive list is unchanged.'))

    def _resume_cleanup(self):
        if self._closed or self._working or self.controller.busy or self._queued is None:
            return
        generation, root, preparation = self._queued
        self._queued = None
        if (generation, root) != (self._operation_generation, self._root):
            return
        from cdmw.services.archive_reference_cleanup import apply_missing_reference_cleanup
        mutations = self.mutations
        self.status.setText(self.tr('Cleaning missing archive references...'))

        def task(log, stop):
            return apply_missing_reference_cleanup(preparation, confirmed=True, mutations=mutations,
                                                   on_log=log, stop_event=stop)

        def completed(backup_dir):
            self.activity.emit(self.tr('Missing mod references cleaned. Backup:') + ' ' + str(backup_dir))
            self.refresh_requested.emit()

        self._run_cleanup(task, completed, applying=True)

    def _busy_changed(self, _busy):
        if not self.controller.busy:
            self._working = self._applying = False
            self._resume_cleanup()
        self._cleanup_button()

    def request_shutdown(self):
        self._closed = True
        self._operation_generation += 1
        self._queued = None
        if self._working and not self._applying:
            self.controller.cancel_operation('overlay_manager')
        self.cancel_read()
        self._lookup.request_shutdown()

    def cancel_read(self):
        self._generation += 1
        self._lookup.cancel()
