"""Thin UI for reviewed portable-item operations on the shared worker lane."""
from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QFileDialog, QHBoxLayout, QLabel, QMessageBox, QPushButton, QTreeWidget, QTreeWidgetItem, QVBoxLayout, QWidget

from cdmw.domain.new_item.independent import IndependentItemInstallPlan


class IndependentItemsPage(QWidget):
    activity = Signal(str)

    def __init__(self, controller, root, mutations, parent=None):
        super().__init__(parent)
        self.controller, self.package_root, self.mutations = controller, str(root), mutations
        self._closed = self._working = self._applying = False
        self._queued = None
        self._generation = 0
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

    def set_game_root(self, root):
        root = str(root)
        if root != self.package_root:
            self.package_root = root
            self._generation += 1
            self._queued = None
            self.items.clear()

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
                          summary + '\n\n' + str(prepared.package_root) + '\n\n'
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
        self._queued = None
        self._generation += 1
        if self._working and not self._applying:
            self.controller.cancel_operation('independent_items')
