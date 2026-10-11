"""Thin UI for reviewed portable-item operations on the shared worker lane."""
from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QFileDialog, QGroupBox, QHBoxLayout, QHeaderView, QInputDialog, QLabel, QMessageBox, QPlainTextEdit, QPushButton, QSplitter, QToolButton, QTreeWidget, QTreeWidgetItem, QVBoxLayout, QWidget

from cdmw.domain.new_item.independent import IndependentItemInstallPlan
from cdmw.ui.new_item.review_model import ReviewTextWriter


class IndependentItemsPage(QWidget):
    activity = Signal(str)

    def __init__(self, controller, root, mutations, parent=None):
        super().__init__(parent)
        self.controller, self.package_root, self.mutations = controller, str(root), mutations
        self._closed = self._working = self._applying = False
        self._queued = None
        self._generation = 0
        self._comparison = None
        self._columns_sized = False
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)
        self.setToolTip('Inspect installed item IDs or move them with your saves. Add new mods from the Mods list.')
        toolbar = QHBoxLayout()
        toolbar.addWidget(QLabel('Saved item identities'), 1)
        self.profile_toggle = QToolButton()
        self.profile_toggle.setObjectName('independent_profile_toggle')
        self.profile_toggle.setText('Identity profile')
        self.profile_toggle.setCheckable(True)
        self.profile_toggle.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        self.profile_toggle.setArrowType(Qt.ArrowType.RightArrow)
        toolbar.addWidget(self.profile_toggle)
        self.refresh_button = QPushButton('Refresh')
        self.refresh_button.clicked.connect(self.refresh)
        toolbar.addWidget(self.refresh_button)
        layout.addLayout(toolbar)
        self.identity_splitter = QSplitter(Qt.Orientation.Horizontal)
        self.identity_splitter.setObjectName('independent_identity_splitter')
        self.identity_splitter.setChildrenCollapsible(False)
        packages = QWidget()
        package_layout = QVBoxLayout(packages)
        package_layout.setContentsMargins(0, 0, 0, 0)
        identity = self.profile_panel = QGroupBox('Identity profile')
        identity_layout = QVBoxLayout(identity)
        self.identity_splitter.addWidget(packages)
        self.identity_splitter.addWidget(identity)
        self.identity_splitter.setStretchFactor(0, 1)
        self.identity_splitter.setStretchFactor(1, 0)
        self.identity_splitter.setSizes([900, 320])
        layout.addWidget(self.identity_splitter, 1)
        self.items = QTreeWidget()
        self.items.setObjectName('independent_item_packages')
        self.items.setHeaderLabels(["Item", "Game ID", "Status"])
        self.items.setRootIsDecorated(False)
        self.items.setUniformRowHeights(True)
        self.items.setMinimumHeight(150)
        self.items.header().setSectionResizeMode(QHeaderView.ResizeMode.Interactive)
        self.items.header().setStretchLastSection(False)
        self.items.setSortingEnabled(True)
        self.items.sortByColumn(0, Qt.SortOrder.AscendingOrder)
        self.items.setSelectionMode(QTreeWidget.SelectionMode.SingleSelection)
        self.items.itemSelectionChanged.connect(self._buttons)
        self.items.setAccessibleDescription('No item packages installed.')
        package_layout.addWidget(self.items, 1)
        row = QHBoxLayout()
        self.import_button = QPushButton("Install into game archives…")
        self.import_button.setToolTip("Advanced installation of .cditem packages into CDMW's managed archives. For the normal Apply and Launch workflow, add packages from Mods.")
        self.import_button.clicked.connect(self._import)
        self.remove_button = QPushButton("Remove selected item...")
        self.remove_button.clicked.connect(self._remove)
        self.rebuild_button = QPushButton("Rebuild selected item…")
        self.rebuild_button.setToolTip("Regenerate this item from its saved package while keeping the same item IDs. Review the changes before applying them.")
        self.rebuild_button.clicked.connect(self._rebuild)
        row.addWidget(self.rebuild_button)
        row.addWidget(self.remove_button)
        row.addStretch(1)
        row.addWidget(self.import_button)
        package_layout.addLayout(row)
        identity.setToolTip('Keep this profile with your saves when moving computers.')
        profiles = QVBoxLayout()
        self.export_profile_button = QPushButton("Export identity profile...")
        self.export_profile_button.clicked.connect(self._export_profile)
        self.import_profile_button = QPushButton("Import identity profile...")
        self.import_profile_button.clicked.connect(self._import_profile)
        profiles.addWidget(self.export_profile_button)
        profiles.addWidget(self.import_profile_button)
        identity_layout.addLayout(profiles)
        identity_layout.addStretch(1)
        identity.hide()
        self.profile_toggle.toggled.connect(identity.setVisible)
        self.profile_toggle.toggled.connect(lambda expanded: self.profile_toggle.setArrowType(
            Qt.ArrowType.DownArrow if expanded else Qt.ArrowType.RightArrow))
        self.shared_page = QWidget(self)
        self.shared_page.setObjectName('independent_shared_files')
        self.shared_page.setToolTip('Check shared data used by installed items before rebuilding it or exporting a combined mod.')
        compatibility_layout = QVBoxLayout(self.shared_page)
        compatibility_layout.setContentsMargins(0, 0, 0, 0)
        compatibility_layout.setSpacing(8)
        compatibility_layout.addWidget(QLabel('Installed shared files'))
        compare = QHBoxLayout()
        self.scan_button = QPushButton("Scan installed mods")
        self.scan_button.clicked.connect(lambda: self._scan())
        self.scan_folder_button = QPushButton("Scan mod folder...")
        self.scan_folder_button.clicked.connect(self._scan_folder)
        self.compose_button = QPushButton("Rebuild installed shared files…")
        self.compose_button.setToolTip('Updates the installed shared files after review and a verified backup.')
        self.compose_button.clicked.connect(self._compose_shared)
        self.export_merge_button = QPushButton("Export installed items…")
        self.export_merge_button.setToolTip('Writes a separate combined package from the installed item set and any scanned folder.')
        self.export_merge_button.clicked.connect(self._export_merge)
        for button in (self.scan_button, self.scan_folder_button):
            compare.addWidget(button)
        compare.addStretch(1)
        compatibility_layout.addLayout(compare)
        self.comparison = QPlainTextEdit()
        self.comparison.setReadOnly(True)
        self.comparison.setPlaceholderText("Scan for shared files, required records and unsupported mod data before merging.")
        self._comparison_writer = ReviewTextWriter(self.comparison)
        compatibility_layout.addWidget(self.comparison, 1)
        actions = QHBoxLayout()
        actions.addWidget(self.compose_button)
        actions.addWidget(self.export_merge_button)
        actions.addStretch(1)
        compatibility_layout.addLayout(actions)
        self.status = QLabel("")
        self.status.setWordWrap(True)
        self.status.setTextFormat(Qt.TextFormat.PlainText)
        layout.addWidget(self.status)
        self.shared_status = QLabel('')
        self.shared_status.setWordWrap(True)
        self.shared_status.setTextFormat(Qt.TextFormat.PlainText)
        compatibility_layout.addWidget(self.shared_status)
        controller.busy_changed.connect(self._busy_changed)
        controller.install_finished.connect(lambda _result: self._queue_refresh())
        self._buttons()

    def _set_status(self, text):
        self.status.setText(text)
        self.shared_status.setText(text)

    def _buttons(self):
        ready = not (self._closed or self._working or self.controller.busy)
        selected = self.items.currentItem()
        status = selected.data(0, Qt.ItemDataRole.UserRole + 1) if selected else None
        removed = status == 'Removed / reserved'
        self.import_button.setEnabled(ready and self.mutations is not None)
        self.remove_button.setText(self.tr('Delete saved identity…') if removed else self.tr('Remove selected item...'))
        self.remove_button.setToolTip(
            self.tr('Permanently free this removed item’s reserved IDs after review and a backup. Old saves may still need them.') if removed else
            self.tr('Remove this package from Mods, then choose Apply changes.') if status == 'Virtual profile' else
            self.tr('Remove the installed item after review and a backup. Its IDs remain reserved until you delete the saved identity.'))
        self.remove_button.setEnabled(ready and self.mutations is not None and status in ('Installed', 'Disabled', 'Removed / reserved'))
        self.rebuild_button.setEnabled(ready and self.mutations is not None and status == 'Installed')
        self.refresh_button.setEnabled(ready)
        self.export_profile_button.setEnabled(ready)
        self.import_profile_button.setEnabled(ready and self.mutations is not None)
        self.scan_button.setEnabled(ready)
        self.scan_folder_button.setEnabled(ready)
        compatible = (self._comparison is not None and self._comparison.compatible
                      and not self._comparison.virtual_profile)
        self.compose_button.setEnabled(ready and compatible and not self._comparison.folders and self.mutations is not None)
        self.export_merge_button.setEnabled(ready and compatible)

    def set_game_root(self, root):
        root = str(root)
        if root != self.package_root:
            self.package_root = root
            self._generation += 1
            self._queued = None
            self.items.clear()
            self._comparison = None
            self._comparison_writer.set_text('')
            if self._working and not self._applying:
                self.controller.cancel_operation('independent_items')
            self._buttons()

    def _run(self, task, done, *, applying=False, publishes_result=False):
        if self._closed or self.controller.busy:
            return False
        generation, root = self._generation, self.package_root
        if not root:
            self._set_status(self.tr("Choose the game archive folder first."))
            return False
        self._working, self._applying = True, applying
        self._buttons()
        def completed(result):
            self._working = self._applying = False
            if applying:
                self.controller.install_finished.emit(result)
            if not self._closed and generation == self._generation and root == self.package_root:
                done(result)
                self._buttons()
                self._resume()
        def failed(message):
            self._working = self._applying = False
            self._comparison = None
            self.controller.log_message.emit(str(message))
            if not self._closed and generation == self._generation:
                self._set_status(str(message))
                self.activity.emit(str(message))
                self._buttons()
        started = self.controller._run('independent_items', task, completed, failed,
                                       publishes_result=applying or publishes_result)
        if not started:
            self._working = self._applying = False
            self._buttons()
        return started

    def _queue_refresh(self):
        if not self._closed:
            self._comparison = None
            self._queued = ('refresh', None)
            self._resume()

    def refresh(self):
        if self._closed:
            return
        if self.controller.busy or self._working:
            self._queued = ('refresh', None)
            return
        from cdmw.services.independent_item_install import inventory
        root = self.package_root
        self._run(lambda log, stop: inventory(root), self._loaded)

    def _loaded(self, rows):
        selected = self.items.currentItem()
        identity = selected.data(0, Qt.ItemDataRole.UserRole) if selected else None
        self.items.setSortingEnabled(False)
        self.items.clear()
        for key, title, game_id, status in rows:
            shown = {"Installed": self.tr("Installed"), "Virtual profile": self.tr("Virtual profile"), "Disabled": self.tr("Disabled"), "Removed / reserved": self.tr("Removed / reserved")}[status]
            item = QTreeWidgetItem([title, '', shown])
            if game_id is not None:
                item.setData(1, Qt.ItemDataRole.DisplayRole, int(game_id))
            item.setData(0, Qt.ItemDataRole.UserRole, key)
            item.setData(0, Qt.ItemDataRole.UserRole + 1, status)
            self.items.addTopLevelItem(item)
            if key == identity:
                self.items.setCurrentItem(item)
        self.items.setSortingEnabled(True)
        if rows and not self._columns_sized:
            for column in range(self.items.columnCount()):
                self.items.resizeColumnToContents(column)
            self._columns_sized = True
        self._set_status(self.tr("Removed items keep their IDs reserved. Select one and choose Delete saved identity to permanently free its IDs."))
        self._buttons()

    def _import(self):
        paths, _ = QFileDialog.getOpenFileNames(self, self.tr("Import independent items"), "", self.tr("Independent items (*.cditem)"))
        if not paths:
            return
        from cdmw.services.independent_item_install import prepare_install
        root = self.package_root
        self._set_status(self.tr("Checking packages and preparing the installation..."))
        self._run(lambda log, stop: prepare_install(paths, root, stop_event=stop, on_log=log), self._review)

    def _scan_folder(self):
        folder = QFileDialog.getExistingDirectory(self, self.tr("Select a mod folder to compare"))
        if folder:
            self._scan((folder,))

    def _scan(self, folders=()):
        from cdmw.services.independent_item_compatibility import scan_independent_conflicts
        root, folders = self.package_root, tuple(folders)
        self._comparison = None
        self._comparison_writer.set_text('')
        self._set_status(self.tr("Comparing independent items with other mods..."))
        def task(log, stop):
            report = scan_independent_conflicts(root, folders=folders, stop_event=stop, on_log=log)
            return report, report.text()
        def completed(result):
            report, text = result
            self._comparison = report
            self._comparison_writer.set_text(text)
            self._set_status(self.tr("Comparison complete.") if report.virtual_profile else
                             self.tr("Comparison complete. Review the results before merging."))
        self._run(task, completed)

    def _compose_shared(self):
        if (self._comparison is None or not self._comparison.compatible
                or self._comparison.virtual_profile or self._comparison.folders):
            return
        from cdmw.services.archive_overlay_rebuild import prepare_overlay_rebuild
        root = self.package_root
        # Always prepare from current data again. The report is never authority
        # to apply a cached result after another manager changes the installation.
        self._run(lambda log, stop: prepare_overlay_rebuild(root, stop_event=stop, on_log=log), self._review)

    def _export_merge(self):
        if self._comparison is None or not self._comparison.compatible or self._comparison.virtual_profile:
            return
        from pathlib import Path
        from cdmw.services.independent_item_compatibility import prepare_independent_mod_merge
        from cdmw.services.mod_merge_service import export_merged_mod
        root, folders, generation = self.package_root, self._comparison.folders, self._generation
        parent = QFileDialog.getExistingDirectory(self, self.tr("Choose a parent folder for the merged mod"))
        if not parent:
            return
        title, accepted = QInputDialog.getText(self, self.tr("Write merged mod"), self.tr("Mod folder name:"), text="Combined items")
        if not accepted or not title.strip() or self._closed or generation != self._generation:
            return
        title = title.strip()
        if title in ('.', '..') or any(char in title for char in '<>:"/\\|?*') or title.endswith(('.', ' ')):
            self._set_status(self.tr("Choose a simple folder name without path separators."))
            return
        destination = Path(parent) / title
        def task(log, stop):
            plan = prepare_independent_mod_merge(root, folders=folders, stop_event=stop, on_log=log)
            return export_merged_mod(plan, destination, title=title, stop_event=stop, on_log=log)
        def completed(result):
            self._comparison = None
            self._set_status(self.tr("Merged mod written:") + ' ' + str(result.package_root))
            if result.manager == 'CDMW':
                self.comparison.appendPlainText(self.tr("Import cdmw-semantic.cditem through CDMW. Its contributors keep their own identities and removal controls. Keep the identity profile with your saves."))
            else:
                self.comparison.appendPlainText(self.tr("Use the merged package instead of its source mods and the composed CDMW overlay. Keep the identity profile with your saves."))
        self._run(task, completed, publishes_result=True)

    def _remove(self):
        item = self.items.currentItem()
        if item is None or not self.remove_button.isEnabled():
            return
        if item.data(0, Qt.ItemDataRole.UserRole + 1) == 'Removed / reserved':
            from cdmw.services.independent_item_install import prepare_identity_deletion
            identity, root = item.data(0, Qt.ItemDataRole.UserRole), self.package_root
            self._run(lambda log, stop: prepare_identity_deletion(identity, root, stop_event=stop), self._review_identity_deletion)
            return
        from cdmw.services.independent_item_install import prepare_remove
        identity, root = item.data(0, Qt.ItemDataRole.UserRole), self.package_root
        self._run(lambda log, stop: prepare_remove(identity, root, stop_event=stop, on_log=log), self._review)

    def _review_identity_deletion(self, prepared):
        generation, root = self._generation, self.package_root
        warning = self.tr('This permanently deletes the saved identity and frees its reserved IDs. Old saves may stop recognizing this item or refer to another item if an ID is reused. Reinstalling the package may assign different IDs. Saves are not edited.')
        box = QMessageBox(QMessageBox.Icon.Warning, self.tr('Delete saved identity'),
            prepared.title + (f' ({prepared.game_id})' if prepared.game_id is not None else '')
            + '\n\n' + warning + '\n\n' + self.tr('A verified backup will be created first. Close the game before continuing.')
            + '\n\n' + self.tr('Permanently delete this saved identity?'),
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No, self)
        box.setDetailedText(self.tr('Game folder:') + ' ' + str(prepared.package_root) + '\n\n'
            + self.tr('Files to update:') + '\n' + '\n'.join(path for path, _ in prepared.writes))
        box.setDefaultButton(QMessageBox.StandardButton.No)
        if (box.exec() == QMessageBox.StandardButton.Yes and not self._closed
                and generation == self._generation and root == self.package_root):
            self._queued = ('delete_identity', prepared)

    def _delete_identity(self, prepared):
        from cdmw.services.independent_item_install import apply_identity_deletion
        mutations = self.mutations
        def task(log, stop):
            return apply_identity_deletion(prepared, confirmed=True, mutations=mutations, stop_event=stop, on_log=log)
        def finished(result):
            self.activity.emit(self.tr('Saved identity deleted. Backup:') + ' ' + str(result.backup_dir))
            self._queued = ('refresh', None)
        self._run(task, finished, applying=True)

    def _rebuild(self):
        item = self.items.currentItem()
        if item is None:
            return
        from cdmw.services.independent_item_install import prepare_rebuild
        identity, root = item.data(0, Qt.ItemDataRole.UserRole), self.package_root
        self._run(lambda log, stop: prepare_rebuild(identity, root, stop_event=stop, on_log=log), self._review)

    def _review(self, result):
        generation, root = self._generation, self.package_root
        if isinstance(result, IndependentItemInstallPlan):
            summary, prepared = '\n'.join(result.summary), result.preparation
        else:
            summary, prepared = result.label, result
        if prepared is None:
            self._set_status(summary)
            return
        detail = (summary + '\n\n' + self.tr("Game folder:") + ' ' + str(prepared.package_root)
                  + '\n\n' + self.tr("Files to update:") + '\n'
                  + '\n'.join((*dict(prepared.writes), *prepared.deletes))
                  + '\n\n' + self.tr("CDMW will create a verified backup before applying this change. Close the game first. Removed items may still be referenced by saves; their identities remain reserved."))
        box = QMessageBox(QMessageBox.Icon.Question, self.tr("Review independent item changes"),
                          '\n'.join(summary.splitlines()[:4]) + '\n\n' + str(prepared.package_root) + '\n\n'
                          + self.tr("A verified backup will be created first. Close the game before continuing.")
                          + '\n\n' + self.tr("Apply these changes?"),
                          QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No, self)
        box.setDetailedText(detail)
        box.setDefaultButton(QMessageBox.StandardButton.No)
        if (box.exec() == QMessageBox.StandardButton.Yes and not self._closed
                and generation == self._generation and root == self.package_root):
            self._queued = ('apply', prepared)

    def _apply(self, prepared):
        from cdmw.services.archive_overlay_manager import apply_overlay_change
        mutations = self.mutations
        def task(log, stop):
            return apply_overlay_change(prepared, confirmed=True,
                backup=lambda paths, label: mutations.backup_files(paths, description=label, on_log=log),
                restore_backup=lambda path: mutations.restore_backup(path, confirmed=True, on_log=log),
                on_log=log, stop_event=stop)
        def finished(result):
            self.activity.emit(self.tr("Independent item changes applied. Backup:") + ' ' + str(result.backup_dir))
            self._queued = ('refresh', None)
        self._run(task, finished, applying=True)

    def _export_profile(self):
        path, _ = QFileDialog.getSaveFileName(self, self.tr("Export identity profile"), "", self.tr("Identity profile (*.cdprofile)"))
        if path:
            from cdmw.services.independent_item_install import export_profile
            root = self.package_root
            if not path.lower().endswith('.cdprofile'):
                path += '.cdprofile'
            self._run(lambda log, stop: export_profile(root, path, stop_event=stop),
                      lambda result: self._set_status(self.tr("Identity profile written:") + ' ' + str(result)),
                      publishes_result=True)

    def _import_profile(self):
        path, _ = QFileDialog.getOpenFileName(self, self.tr("Import identity profile"), "", self.tr("Identity profile (*.cdprofile)"))
        if path:
            from cdmw.services.independent_item_install import prepare_profile_import
            root = self.package_root
            self._run(lambda log, stop: prepare_profile_import(path, root, stop_event=stop, on_log=log), self._review)

    def _resume(self):
        if self._closed or self._working or self.controller.busy or self._queued is None:
            return
        action, value = self._queued
        self._queued = None
        if action == 'apply':
            self._apply(value)
        elif action == 'delete_identity':
            self._delete_identity(value)
        else:
            self.refresh()

    def _busy_changed(self, busy):
        if not busy:
            self._working = self._applying = False
        if not self._closed:
            self._buttons()
            self._resume()

    def request_shutdown(self):
        self._closed = True
        self._comparison_writer.timer.stop()
        self._queued = None
        self._generation += 1
        if self._working and not self._applying:
            self.controller.cancel_operation('independent_items')
