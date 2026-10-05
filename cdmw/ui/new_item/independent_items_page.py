"""Thin UI for reviewed portable-item operations on the shared worker lane."""
from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QFileDialog, QHBoxLayout, QInputDialog, QLabel, QMessageBox, QPlainTextEdit, QPushButton, QTreeWidget, QTreeWidgetItem, QVBoxLayout, QWidget

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
        layout = QVBoxLayout(self)
        help_text = QLabel("Install separate .cditem packages here. CDMW assigns distinct identities and composes their shared files. Keep the identity profile with your saves when moving to another computer.")
        help_text.setWordWrap(True)
        layout.addWidget(help_text)
        validation = QLabel("Game and save compatibility is not yet verified.")
        validation.setWordWrap(True)
        layout.addWidget(validation)
        self.items = QTreeWidget()
        self.items.setHeaderLabels(["Item", "Game ID", "Status"])
        self.items.setRootIsDecorated(False)
        self.items.setSelectionMode(QTreeWidget.SelectionMode.SingleSelection)
        self.items.itemSelectionChanged.connect(self._buttons)
        layout.addWidget(self.items, 1)
        row = QHBoxLayout()
        self.import_button = QPushButton("Import packages...")
        self.import_button.clicked.connect(self._import)
        self.remove_button = QPushButton("Remove selected item...")
        self.remove_button.clicked.connect(self._remove)
        self.refresh_button = QPushButton("Refresh")
        self.refresh_button.clicked.connect(self.refresh)
        for button in (self.import_button, self.remove_button, self.refresh_button):
            row.addWidget(button)
        layout.addLayout(row)
        profiles = QHBoxLayout()
        self.export_profile_button = QPushButton("Export identity profile...")
        self.export_profile_button.clicked.connect(self._export_profile)
        self.import_profile_button = QPushButton("Import identity profile...")
        self.import_profile_button.clicked.connect(self._import_profile)
        profiles.addWidget(self.export_profile_button)
        profiles.addWidget(self.import_profile_button)
        layout.addLayout(profiles)
        compare = QHBoxLayout()
        self.scan_button = QPushButton("Scan installed mods")
        self.scan_button.clicked.connect(lambda: self._scan())
        self.scan_folder_button = QPushButton("Scan mod folder...")
        self.scan_folder_button.clicked.connect(self._scan_folder)
        self.compose_button = QPushButton("Merge shared files...")
        self.compose_button.clicked.connect(self._compose_shared)
        self.export_merge_button = QPushButton("Write merged mod...")
        self.export_merge_button.clicked.connect(self._export_merge)
        for button in (self.scan_button, self.scan_folder_button, self.compose_button, self.export_merge_button):
            compare.addWidget(button)
        layout.addLayout(compare)
        self.comparison = QPlainTextEdit()
        self.comparison.setReadOnly(True)
        self.comparison.setPlaceholderText("Scan for shared files, required records and unsupported mod data before merging.")
        self._comparison_writer = ReviewTextWriter(self.comparison)
        layout.addWidget(self.comparison, 1)
        self.status = QLabel("")
        self.status.setWordWrap(True)
        self.status.setTextFormat(Qt.TextFormat.PlainText)
        layout.addWidget(self.status)
        controller.busy_changed.connect(self._busy_changed)
        controller.install_finished.connect(lambda _result: self._queue_refresh())
        self._buttons()

    def _buttons(self):
        ready = not (self._closed or self._working or self.controller.busy)
        selected = self.items.currentItem()
        self.import_button.setEnabled(ready and self.mutations is not None)
        self.remove_button.setEnabled(ready and self.mutations is not None and selected is not None and selected.data(0, Qt.ItemDataRole.UserRole + 1) == 'Installed')
        self.refresh_button.setEnabled(ready)
        self.export_profile_button.setEnabled(ready)
        self.import_profile_button.setEnabled(ready and self.mutations is not None)
        self.scan_button.setEnabled(ready)
        self.scan_folder_button.setEnabled(ready)
        compatible = self._comparison is not None and self._comparison.compatible
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

    def _run(self, task, done, *, applying=False):
        if self._closed or self.controller.busy:
            return False
        generation, root = self._generation, self.package_root
        if not root:
            self.status.setText(self.tr("Choose the game archive folder first."))
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
                self.status.setText(str(message))
                self.activity.emit(str(message))
                self._buttons()
        started = self.controller._run('independent_items', task, completed, failed)
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
        self.items.clear()
        for key, title, game_id, status in rows:
            shown = {"Installed": self.tr("Installed"), "Disabled": self.tr("Disabled"), "Removed / reserved": self.tr("Removed / reserved")}[status]
            item = QTreeWidgetItem([title, str(game_id), shown])
            item.setData(0, Qt.ItemDataRole.UserRole, key)
            item.setData(0, Qt.ItemDataRole.UserRole + 1, status)
            self.items.addTopLevelItem(item)
            if key == identity:
                self.items.setCurrentItem(item)
        self.items.resizeColumnToContents(1)
        self.status.setText(self.tr("Identity reservations remain after removal. Saves are never edited automatically."))

    def _import(self):
        paths, _ = QFileDialog.getOpenFileNames(self, self.tr("Import independent items"), "", self.tr("Independent items (*.cditem)"))
        if not paths:
            return
        from cdmw.services.independent_item_install import prepare_install
        root = self.package_root
        self.status.setText(self.tr("Checking packages and preparing the installation..."))
        self._run(lambda log, stop: prepare_install(paths, root, stop_event=stop, on_log=log), self._review)

    def _scan_folder(self):
        folder = QFileDialog.getExistingDirectory(self, self.tr("Select a mod folder to compare"))
        if folder:
            self._scan((folder,))

    def _scan(self, folders=()):
        from cdmw.services.independent_item_compatibility import scan_independent_conflicts
        root, folders = self.package_root, tuple(folders)
        self._comparison = None
        self.status.setText(self.tr("Comparing independent items with other mods..."))
        def task(log, stop):
            report = scan_independent_conflicts(root, folders=folders, stop_event=stop, on_log=log)
            return report, report.text()
        def completed(result):
            report, text = result
            self._comparison = report
            self._comparison_writer.set_text(text)
            self.status.setText(self.tr("Comparison complete. Review the results before merging."))
        self._run(task, completed)

    def _compose_shared(self):
        if self._comparison is None or not self._comparison.compatible or self._comparison.folders:
            return
        from cdmw.services.archive_overlay_rebuild import prepare_overlay_rebuild
        root = self.package_root
        # Always prepare from current data again. The report is never authority
        # to apply a cached result after another manager changes the installation.
        self._run(lambda log, stop: prepare_overlay_rebuild(root, stop_event=stop, on_log=log), self._review)

    def _export_merge(self):
        if self._comparison is None or not self._comparison.compatible:
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
            self.status.setText(self.tr("Choose a simple folder name without path separators."))
            return
        destination = Path(parent) / title
        def task(log, stop):
            plan = prepare_independent_mod_merge(root, folders=folders, stop_event=stop, on_log=log)
            return export_merged_mod(plan, destination, title=title, stop_event=stop, on_log=log)
        def completed(result):
            self._comparison = None
            self.status.setText(self.tr("Merged mod written:") + ' ' + str(result.package_root))
            self.comparison.appendPlainText(self.tr("Use the merged package instead of its source mods and the composed CDMW overlay. Keep the identity profile with your saves."))
        self._run(task, completed)

    def _remove(self):
        item = self.items.currentItem()
        if item is None:
            return
        from cdmw.services.independent_item_install import prepare_remove
        identity, root = item.data(0, Qt.ItemDataRole.UserRole), self.package_root
        self._run(lambda log, stop: prepare_remove(identity, root, stop_event=stop, on_log=log), self._review)

    def _review(self, result):
        generation, root = self._generation, self.package_root
        if isinstance(result, IndependentItemInstallPlan):
            summary, prepared = '\n'.join(result.summary), result.preparation
        else:
            summary, prepared = result.label, result
        if prepared is None:
            self.status.setText(summary)
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
                      lambda result: self.status.setText(self.tr("Identity profile written:") + ' ' + str(result)))

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
        self._apply(value) if action == 'apply' else self.refresh()

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
