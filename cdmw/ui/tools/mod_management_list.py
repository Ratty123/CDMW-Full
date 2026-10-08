"""One mod inventory, with the existing installation owners retaining authority."""
from pathlib import Path

from PySide6.QtCore import Qt, QSignalBlocker, QTimer, Signal
from PySide6.QtWidgets import QHBoxLayout, QHeaderView, QLabel, QLineEdit, QPushButton, QTreeWidgetItem

from cdmw.services.active_ui_translation import translate_active_ui_text as translate
from cdmw.ui.new_item.virtual_loader_page import VirtualLoaderPage


class ModManagementList(VirtualLoaderPage):
    details_requested = Signal(str)

    def __init__(self, controller, root, inventory, independent, parent=None):
        self.inventory, self.independent = inventory, independent
        self._source_generation = 0
        self._sources = None
        self._source_pending = False
        self._needs_apply = False
        super().__init__(controller, root, parent)
        self._source_lane = controller.create_lookup_lane()
        self._source_lane.completed.connect(self._sources_ready)
        self._source_lane.failed.connect(self._sources_failed)
        inventory.inventory_changed.connect(self._installed_changed)
        controller.install_finished.connect(self._installation_changed)
        self.profile_applied.connect(self._applied)

        # Reuse the Apply/launch owner and its controls, but give the combined
        # inventory the full width. Detailed preparation output stays optional.
        layout = self.layout()
        self.findChild(QLabel, 'virtual_loader_intro').hide()
        self._virtual_notice = self.findChild(QLabel, 'virtual_loader_notice')
        self._virtual_notice.setToolTip(self._virtual_notice.text())
        self._virtual_notice.setText(self.tr('Experimental'))
        toolbar = QHBoxLayout()
        for button in (self.add_items, self.add_mod, self.apply_button, self.launch_button):
            toolbar.addWidget(button)
        self.apply_button.setText(self.tr('Apply changes'))
        self.apply_button.setProperty('newItemPrimary', True)
        self.launch_button.setProperty('newItemPrimary', True)
        toolbar.addStretch(1)
        toolbar.addWidget(self.cancel_button)
        layout.addLayout(toolbar)
        self.search = QLineEdit()
        self.search.setObjectName('mod_management_search')
        self.search.setPlaceholderText(self.tr('Search mods…'))
        self.search.textChanged.connect(self._filter)
        layout.addWidget(self.search)
        self.selection.setHeaderLabels([self.tr('Mod'), self.tr('Type'), self.tr('Loads with'), self.tr('Status')])
        self.selection.header().setSectionResizeMode(QHeaderView.Interactive)
        self.selection.header().setStretchLastSection(True)
        for column, width in enumerate((340, 170, 180, 230)):
            self.selection.setColumnWidth(column, width)
        self.selection.setAccessibleDescription(self.tr('Add item packages or a mod folder to begin.'))
        layout.addWidget(self.selection, 1)
        row = QHBoxLayout()
        row.addWidget(self.remove_selected)
        self.toggle_installed = QPushButton(self.tr('Disable…'))
        self.toggle_installed.setObjectName('mod_management_toggle_selected')
        self.toggle_installed.clicked.connect(self._toggle_installed)
        row.addWidget(self.toggle_installed)
        self.details_button = QPushButton(self.tr('Details…'))
        self.details_button.setObjectName('mod_management_mod_details')
        self.details_button.clicked.connect(self._details)
        row.addWidget(self.details_button)
        row.addWidget(self.count, 1)
        row.addWidget(self.refresh_button)
        layout.addLayout(row)
        layout.addWidget(self.status)
        layout.addWidget(self.progress)
        self.tools_toggle.setText(self.tr('Loader details'))
        layout.addWidget(self.tools_toggle)
        self.tools.layout().addWidget(self.review)
        self.review.setMaximumHeight(180)
        layout.addWidget(self.tools)
        self.sort_choice.hide()  # Every visible column has a sortable heading.
        self.workspace.hide()
        self._buttons()

    def _installed_changed(self, _entries):
        self._render_sources()
        self.refresh_sources()

    def _installation_changed(self, _result):
        self._needs_apply = True
        self._buttons()

    def _applied(self):
        self._needs_apply = False

    def refresh_sources(self):
        if self._closed or not self.package_root:
            return
        self._source_pending = True
        if self.controller.busy:
            return
        from cdmw.services.mod_management_inventory import mod_sources
        self._source_pending = False
        self._source_generation += 1
        root, key = self.package_root, (self._source_generation, self.package_root)
        self._source_lane.request(key, lambda stop: mod_sources(root, stop_event=stop))

    def _sources_ready(self, key, sources):
        if not self._closed and key == (self._source_generation, self.package_root):
            self._sources = sources
            self._render_sources()
            self._buttons()
            if (sources[2] and not self._profile().packages and not self._profile().mods
                    and self._saved_selection is None and self._runtime is not None and not self._error
                    and self.status.text() in (self.tr('Apply the profile to use this selection.'), self.tr(self._runtime.detail))):
                self.status.setText(self.tr('Ready to launch.'))

    def _sources_failed(self, key, message):
        if not self._closed and key == (self._source_generation, self.package_root):
            self._sources = None
            self.status.setText(self.tr(str(message)))
            self.activity.emit(str(message))
            self._buttons()

    def _render_sources(self):
        if self._sources is None or not hasattr(self, 'toggle_installed'):
            return
        identities, mounts, _can_launch = self._sources
        wanted = {}
        owned = {entry.directory for entry in self.inventory._entries}
        selected_folders = set(self._profile().mods)
        for entry in self.inventory._entries:
            identity = identities.get(entry.id)
            state = translate({'mounted': self.tr('Enabled'), 'disabled': self.tr('Disabled'),
                               'unmounted': self.tr('Not mounted'), 'missing': self.tr('Missing files'),
                               'changed': self.tr('Needs review')}.get(entry.health, self.tr('Needs review')))
            if entry.health in ('mounted', 'disabled') and (entry.issue or entry.compatibility_status != 'same'):
                state += ' · ' + translate(self.tr('Needs review'))
            wanted[('installed', entry.id)] = (
                identity[1] if identity else entry.label,
                self.tr('Item package') if identity else self.tr('Archive mod'), self.tr('Game'), state,
                entry.issue or str(Path(self.package_root) / entry.directory))
        for mount in mounts:
            if mount.game or mount.name in owned or not mount.present or Path(self.package_root) / mount.name in selected_folders:
                continue
            wanted[('external', mount.name)] = (
                mount.name, self.tr('Archive mod'), self.tr('External manager'), self.tr('Enabled'),
                self.tr('Managed outside CDMW. Use its original manager to disable or remove it.')
                + '\n' + str(Path(self.package_root) / mount.name))
        wanted = {key: (values[0], *(translate(value) for value in values[1:])) for key, values in wanted.items()}
        existing = {item.data(0, Qt.UserRole): item
                    for index in range(self.selection.topLevelItemCount())
                    if (item := self.selection.topLevelItem(index)).data(0, Qt.UserRole)[0] in ('installed', 'external')}
        if (existing.keys() == wanted.keys() and all(
                tuple(existing[key].text(column) for column in range(4)) == values[:4]
                and existing[key].toolTip(0) == values[4] for key, values in wanted.items())):
            return
        blocker = QSignalBlocker(self.selection)
        self.selection.setSortingEnabled(False)
        current = {}
        for index in range(self.selection.topLevelItemCount() - 1, -1, -1):
            item = self.selection.topLevelItem(index)
            key = item.data(0, Qt.UserRole)
            if key[0] in ('installed', 'external'):
                if key not in wanted:
                    self.selection.takeTopLevelItem(index)
                else:
                    current[key] = item
        for key, values in wanted.items():
            item = current.get(key)
            if item is None:
                item = QTreeWidgetItem()
                item.setData(0, Qt.UserRole, key)
                item.setData(0, Qt.UserRole + 1, self._next_order)
                self._next_order += 1
                self.selection.addTopLevelItem(item)
            for column, text in enumerate(values[:4]):
                item.setText(column, text)
                item.setToolTip(column, values[4])
        self.selection.setSortingEnabled(True)
        blocker.unblock()
        self._filter()

    def _filter(self, *_args):
        query = self.search.text().strip().casefold()
        for index in range(self.selection.topLevelItemCount()):
            item = self.selection.topLevelItem(index)
            hidden = query not in ' '.join(item.text(column) for column in range(4)).casefold()
            if hidden:
                item.setSelected(False)
            item.setHidden(hidden)

    def _buttons(self):
        super()._buttons()
        if not hasattr(self, 'toggle_installed'):
            return
        self._render_sources()
        ready = not (self._closed or self._working or self.controller.busy or self._queued or self._session)
        selected = self.selection.selectedItems()
        draft = bool(selected) and all(item.data(0, Qt.UserRole)[0] in ('item', 'mod') for item in selected)
        entry = self._selected_install()
        mutable = bool(ready and entry and self._sources is not None and self.inventory.mutations is not None and not self.inventory._reading
                       and entry.health in ('mounted', 'disabled') and not entry.issue)
        self.remove_selected.setEnabled(ready and (draft or (mutable and entry.compatibility_status != 'unmounted')))
        self.remove_selected.setToolTip(self.tr('Review removal of the selected overlay before applying it.') if entry else
            self.tr('Remove selected entries from this draft. Files and retained item identities are kept.'))
        self.toggle_installed.setEnabled(mutable)
        self.details_button.setEnabled(ready and entry is not None)
        self.toggle_installed.setText(self.tr('Enable…') if entry and not entry.enabled else self.tr('Disable…'))
        profile = self._profile()
        self._virtual_notice.setVisible(bool(profile.packages or profile.mods or self._saved_selection))
        dirty = self._needs_apply or profile != self._saved_selection
        self.apply_button.setEnabled(ready and bool(self.package_root) and bool(profile.packages or profile.mods or self._saved_selection))
        # Ordinary installed mods do not need virtual runtime setup or a profile.
        if not profile.packages and not profile.mods and self._saved_selection is None:
            self.launch_button.setEnabled(ready and self._sources is not None and self._sources[2] and self._draft_loaded)
        elif self._needs_apply:
            self.launch_button.setEnabled(False)
            if ready and not self._error:
                self.status.setText(self.tr('Apply the profile to use this selection.'))
        for index in range(self.selection.topLevelItemCount()):
            item = self.selection.topLevelItem(index)
            if item.data(0, Qt.UserRole)[0] in ('item', 'mod'):
                item.setText(2, translate(self.tr('CDMW launch')))
                item.setText(3, translate(self.tr('Needs review') if self._error else self.tr('Pending changes') if dirty else self.tr('Applied')))
                item.setToolTip(3, translate(self.tr(self._error)))
                item.setToolTip(2, self.tr('Experimental virtual loading. Launch from CDMW to use this mod.'))
        self.count.setText(self.tr('{value_0} mods').format(value_0=self.selection.topLevelItemCount()))
        self._filter()

    def _selected_install(self):
        selected = self.selection.selectedItems()
        if len(selected) != 1 or selected[0].data(0, Qt.UserRole)[0] != 'installed':
            return None
        identity = selected[0].data(0, Qt.UserRole)[1]
        return next((entry for entry in self.inventory._entries if entry.id == identity), None)

    def _remove(self):
        if not self.remove_selected.isEnabled():
            return
        entry = self._selected_install()
        if entry is None:
            super()._remove()
            return
        identity = self._sources[0].get(entry.id)
        root = self.package_root
        if identity:
            from cdmw.services.independent_item_install import prepare_remove
            self.independent._run(lambda log, stop: prepare_remove(identity[0], root, stop_event=stop, on_log=log),
                                  self.independent._review)
        else:
            from cdmw.services.archive_overlay_manager import prepare_overlay_removal
            self.inventory._run(lambda log, stop: prepare_overlay_removal(root, entry.id, on_log=log, stop_event=stop),
                                self.inventory._review_removal, self.tr('Preparing removal and checking the remaining overlays…'))

    def _toggle_installed(self):
        entry = self._selected_install()
        if entry is None or not self.toggle_installed.isEnabled():
            return
        from cdmw.services.archive_overlay_manager import prepare_overlay_enabled
        root = self.package_root
        self.inventory._run(lambda log, stop: prepare_overlay_enabled(root, entry.id, not entry.enabled, on_log=log, stop_event=stop),
                            self.inventory._review_removal, self.tr('Checking dependencies and preparing the overlay change…'))

    def _details(self):
        entry = self._selected_install()
        if entry:
            self.details_requested.emit(entry.id)

    def refresh(self):
        super().refresh()
        self.refresh_sources()

    def _launch(self):
        profile = self._profile()
        if profile.packages or profile.mods or self._saved_selection is not None:
            super()._launch()
            return
        from cdmw.services.mod_management_inventory import launch_installed_game
        root = self.package_root
        self.status.setText(self.tr('Starting the game…'))
        self._run(lambda log, stop: launch_installed_game(root, stop_event=stop),
                  lambda _pid: self.status.setText(self.tr('Game launch requested.')))

    def _busy_changed(self, busy):
        super()._busy_changed(busy)
        if not hasattr(self, '_source_lane') or self._closed:
            return
        if busy:
            self._source_lane.cancel()
            self._source_generation += 1
            self._source_pending = True
        elif self._source_pending:
            QTimer.singleShot(0, self, self.refresh_sources)

    def set_game_root(self, root):
        if str(root) != self.package_root:
            self._source_generation += 1
            self._source_lane.cancel()
            self._sources = None
            self._needs_apply = False
        super().set_game_root(root)

    def request_shutdown(self):
        self._source_lane.request_shutdown()
        super().request_shutdown()
