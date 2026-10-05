"""Installation overview and navigation for the shared Mod Management workspace."""
from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QAbstractItemView, QCheckBox, QGridLayout, QGroupBox, QHBoxLayout, QHeaderView,
    QLabel, QPushButton, QTreeWidget, QTreeWidgetItem, QVBoxLayout, QWidget,
)

from cdmw.services.overlay_inventory_details import mounted_archive_status


class ModManagementOverview(QWidget):
    page_requested = Signal(str)
    refresh_requested = Signal()

    def __init__(self, controller, parent=None):
        super().__init__(parent)
        self._closed = False
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
            box = QGroupBox(title)
            body = QVBoxLayout(box)
            value = QLabel('—')
            font = value.font()
            font.setPointSize(font.pointSize() + 8)
            font.setBold(True)
            value.setFont(font)
            body.addWidget(value)
            self.counts[key] = value
            summary.addWidget(box, 1)
        layout.addLayout(summary)
        actions = QGroupBox('What would you like to do?')
        grid = QGridLayout(actions)
        self.actions = {}
        choices = {
            'independent': ('Install item packages', 'Install or update .cditem files and keep their save identities.'),
            'installed': ('Manage installed mods', 'Preview items, enable or disable mods, and remove selected installs.'),
            'repackage': ('Repackage Mods', 'Convert folders or ZIPs for another mod manager.'),
            'merge': ('Merge mods', 'Combine compatible mod folders into one package.'),
            'updates': ('Check game updates', 'Compare recorded changes with your current game files.'),
            'recovery': ('Recovery', 'Rebuild saved installs or review an installation that needs attention.'),
        }
        for index, (key, (title, detail)) in enumerate(choices.items()):
            button = QPushButton(title)
            button.setObjectName('mod_management_open_' + key)
            button.setToolTip(detail)
            button.clicked.connect(lambda _checked=False, page=key: self.page_requested.emit(page))
            caption = QLabel(detail)
            caption.setWordWrap(True)
            caption.setObjectName('HintLabel')
            column, row = index % 2, (index // 2) * 2
            grid.addWidget(button, row, column)
            grid.addWidget(caption, row + 1, column)
            self.actions[key] = button
        grid.setColumnStretch(0, 1)
        grid.setColumnStretch(1, 1)
        layout.addWidget(actions)
        toolbar = QHBoxLayout()
        title = QLabel('Archive folders')
        font = title.font()
        font.setBold(True)
        title.setFont(font)
        toolbar.addWidget(title)
        toolbar.addStretch(1)
        self.show_game = QCheckBox('Show game archives')
        self.show_game.toggled.connect(self._render_mounts)
        toolbar.addWidget(self.show_game)
        self.refresh_button = QPushButton('Refresh')
        self.refresh_button.clicked.connect(self.refresh_requested.emit)
        toolbar.addWidget(self.refresh_button)
        layout.addLayout(toolbar)
        self.mounts = QTreeWidget()
        self.mounts.setHeaderLabels(['Folder', 'Managed by', 'Status'])
        self.mounts.setRootIsDecorated(False)
        self.mounts.setSelectionMode(QAbstractItemView.SelectionMode.NoSelection)
        self.mounts.setMinimumHeight(90)
        self.mounts.header().setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
        self.mounts.header().setStretchLastSection(True)
        layout.addWidget(self.mounts, 1)
        self.status = QLabel('Choose a game folder, then refresh.')
        self.status.setWordWrap(True)
        self.status.setTextFormat(Qt.TextFormat.PlainText)
        layout.addWidget(self.status)

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
        self._root = str(root or '').strip()
        self._mounts = ()
        self._render_mounts()
        self._lookup.cancel()
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
        if broken_game:
            self.status.setText(self.tr('Required game archives are missing: {value_0}. Verify the game files before continuing.').format(value_0=', '.join(broken_game)))
        elif missing:
            self.status.setText(self.tr('Missing mod folders: {value_0}. Their archive-list entries remain after deletion. Available game data can still be read. Restore the mod through its manager if you need it.').format(value_0=', '.join(missing)))
        else:
            self.status.setText(self.tr('Archive folders are present. Use Game updates to check mod compatibility.'))

    def _failed(self, key, message):
        if not self._closed and key == (self._generation, self._root):
            self.status.setText(str(message))

    def _render_mounts(self, *_args):
        self.mounts.clear()
        owned = {entry.directory for entry in self._entries}
        for row in self._mounts:
            if row.game and not self.show_game.isChecked():
                continue
            owner = self.tr('Game') if row.game else 'CDMW' if row.name in owned else self.tr('Other manager')
            status = self.tr('Found') if row.present else self.tr('Not installed') if row.game and row.optional else self.tr('Missing files')
            self.mounts.addTopLevelItem(QTreeWidgetItem([row.name, owner, status]))

    def request_shutdown(self):
        self._closed = True
        self.cancel_read()
        self._lookup.request_shutdown()

    def cancel_read(self):
        self._generation += 1
        self._lookup.cancel()
