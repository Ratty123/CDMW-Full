"""Mods page when CDMW only prepares items for DMM: a list of CDMW packages and Send to DMM.

DMM loads the items into the game. CDMW keeps the list, combines the packages for the
installed game and writes them as one DMM mod; nothing here installs a runtime, applies a
profile or starts the game.
"""
from __future__ import annotations

import json
from pathlib import Path

from PySide6.QtCore import QSettings, Qt, QTimer, Signal
from PySide6.QtWidgets import (QFileDialog, QHBoxLayout, QHeaderView, QLabel, QMenu, QMessageBox, QProgressBar,
                               QPushButton, QTreeWidget, QTreeWidgetItem, QVBoxLayout, QWidget)

from cdmw import constants
from cdmw.services.settings_service import resolve_settings_file_path
from cdmw.ui.widgets import request_settings_sync

PACKAGES_SETTING = "mod_management/dmm_packages"
DMM_MOD_TITLE = "CDMW items"


class DmmPackagesPage(QWidget):
    activity = Signal(str)
    details_requested = Signal(str)

    def __init__(self, controller, root, parent=None, *, settings: QSettings | None = None):
        super().__init__(parent)
        self.setObjectName("mod_management_dmm_packages")
        self.controller = controller
        self.package_root = str(root or "")
        self._settings = settings
        self._closed = False
        self._working = False
        self._queued = None
        self._applying = False  # The tab's cancel logic reads this; a send never applies anything.
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        toolbar = QHBoxLayout()
        self.add_items = QPushButton(self.tr("Add item packages…"))
        self.add_items.setObjectName("mod_management_add_items")
        self.add_items.setToolTip(self.tr("Add .cdmw item packages made with Create New Item."))
        self.add_items.clicked.connect(self._add_items)
        toolbar.addWidget(self.add_items)
        self.send_dmm_button = QPushButton(self.tr("Send to DMM…"))
        self.send_dmm_button.setObjectName("mod_management_send_dmm")
        self.send_dmm_button.setProperty("newItemPrimary", True)
        self.send_dmm_button.setToolTip(self.tr("Write the selected item packages, or all of them when none is selected, "
                                                "as one DMM mod named CDMW items. Sending again replaces it."))
        self.send_dmm_button.clicked.connect(self._send_to_dmm)
        toolbar.addWidget(self.send_dmm_button)
        toolbar.addStretch(1)
        layout.addLayout(toolbar)
        self.selection = QTreeWidget()
        self.selection.setObjectName("mod_management_dmm_list")
        self.selection.setHeaderLabels([self.tr("Package"), self.tr("Folder")])
        self.selection.setRootIsDecorated(False)
        self.selection.setUniformRowHeights(True)
        self.selection.setSelectionMode(QTreeWidget.ExtendedSelection)
        self.selection.setSortingEnabled(True)
        self.selection.sortItems(0, Qt.AscendingOrder)
        self.selection.header().setSectionResizeMode(0, QHeaderView.Interactive)
        self.selection.header().setStretchLastSection(True)
        self.selection.setColumnWidth(0, 340)
        self.selection.setAccessibleDescription(self.tr("Add .cdmw item packages to begin."))
        self.selection.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.selection.customContextMenuRequested.connect(self._context_menu)
        self.selection.itemSelectionChanged.connect(self._buttons)
        layout.addWidget(self.selection, 1)
        row = QHBoxLayout()
        self.details_button = QPushButton(self.tr("Details…"))
        self.details_button.setObjectName("mod_management_mod_details")
        self.details_button.clicked.connect(self._details)
        row.addWidget(self.details_button)
        self.remove_selected = QPushButton(self.tr("Remove from list"))
        self.remove_selected.setObjectName("mod_management_remove_selected")
        self.remove_selected.setToolTip(self.tr("Take the selected packages off this list. The files stay where they are."))
        self.remove_selected.clicked.connect(self._remove)
        row.addWidget(self.remove_selected)
        self.count = QLabel()
        row.addWidget(self.count, 1)
        layout.addLayout(row)
        self.status = QLabel(self.tr("DMM loads these items. Send them to DMM, then enable CDMW items in DMM and click Mount."))
        self.status.setObjectName("mod_management_dmm_status")
        self.status.setTextFormat(Qt.TextFormat.PlainText)
        self.status.setWordWrap(True)
        layout.addWidget(self.status)
        self.progress = QProgressBar()
        self.progress.setRange(0, 0)
        self.progress.hide()
        layout.addWidget(self.progress)
        self._load()
        controller.busy_changed.connect(self._busy_changed)
        self._buttons()

    # ------------------------------------------------------------------ list

    def _settings_store(self) -> QSettings:
        if self._settings is None:
            self._settings = QSettings(str(resolve_settings_file_path()), QSettings.Format.IniFormat)
        return self._settings

    def _load(self):
        try:
            paths = json.loads(str(self._settings_store().value(PACKAGES_SETTING, "[]") or "[]"))
        except ValueError:
            paths = []
        self._append([str(path) for path in paths if isinstance(path, str)], save=False)

    def _save(self):
        settings = self._settings_store()
        settings.setValue(PACKAGES_SETTING, json.dumps(self.packages()))
        request_settings_sync(settings)

    def packages(self) -> list[str]:
        return [self.selection.topLevelItem(i).data(0, Qt.UserRole) for i in range(self.selection.topLevelItemCount())]

    def _append(self, paths, *, save=True):
        known = {path.casefold() for path in self.packages()}
        for path in paths:
            if path.casefold() in known:
                continue
            known.add(path.casefold())
            item = QTreeWidgetItem([Path(path).name, str(Path(path).parent)])
            item.setData(0, Qt.UserRole, path)
            item.setToolTip(0, path)
            if not Path(path).is_file():
                item.setText(0, Path(path).name + " " + self.tr("(missing)"))
            self.selection.addTopLevelItem(item)
        if save:
            self._save()
        self._buttons()

    def _add_items(self):
        patterns = " ".join("*" + extension for extension in constants.PACKAGE_EXTENSIONS)
        files, _ = QFileDialog.getOpenFileNames(self, self.tr("Add item packages…"), "",
                                                self.tr("Item packages") + f" ({patterns})")
        if files:
            self._append([str(Path(file)) for file in files])

    def _remove(self):
        for item in self.selection.selectedItems():
            self.selection.takeTopLevelItem(self.selection.indexOfTopLevelItem(item))
        self._save()
        self._buttons()

    def _chosen(self) -> tuple[str, ...]:
        """The selected packages, or every package when none is selected."""
        selected = [item.data(0, Qt.UserRole) for item in self.selection.selectedItems()]
        return tuple(selected or self.packages())

    def _buttons(self):
        if self._closed:
            return
        # The list needs no worker. Work started while the shared worker is busy (it reads
        # the game archives after startup) waits for it instead of disabling the page.
        ready = not (self._working or self._queued)
        selected = self.selection.selectedItems()
        self.add_items.setEnabled(True)
        self.send_dmm_button.setEnabled(ready and bool(self.package_root) and bool(self._chosen()))
        self.details_button.setEnabled(ready and len(selected) == 1)
        self.remove_selected.setEnabled(bool(selected) and not self._working)
        total = self.selection.topLevelItemCount()
        self.count.setText(self.tr("{value_0} selected · {value_1} packages").format(value_0=len(selected), value_1=total)
                           if selected else self.tr("{value_0} packages").format(value_0=total))

    def _context_menu(self, position):
        item = self.selection.itemAt(position)
        if item is None:
            return
        if not item.isSelected():
            self.selection.setCurrentItem(item)
        self._buttons()
        menu = QMenu(self.selection)
        for button in (self.details_button, self.remove_selected, self.send_dmm_button):
            action = menu.addAction(button.text())
            action.setEnabled(button.isEnabled())
            action.setToolTip(button.toolTip())
            action.triggered.connect(button.click)
        menu.setToolTipsVisible(True)
        menu.aboutToHide.connect(menu.deleteLater)
        menu.popup(self.selection.viewport().mapToGlobal(position))

    # ------------------------------------------------------------------ work

    def _busy_changed(self, _busy):
        if not self._closed:
            self._buttons()
            QTimer.singleShot(0, self, self._resume)

    def _resume(self):
        if not self._closed and not self.controller.busy and not self._working and self._queued:
            task, self._queued = self._queued, None
            task()

    def _when_idle(self, task):
        if self.controller.busy:
            self.status.setText(self.tr("Waiting for the game archives to finish loading…"))
            self._queued = task
            self._buttons()
        else:
            task()

    def _run(self, task, done):
        if self._closed or self.controller.busy:
            return False
        self._working = True
        self.progress.show()
        self._buttons()

        def finish():
            self._working = False
            if not self._closed:
                self.progress.hide()
                self._buttons()

        def completed(result):
            finish()
            if not self._closed:
                done(result)

        def failed(message):
            finish()
            if not self._closed:
                self.status.setText(self.tr(str(message)))
                self.activity.emit(str(message))

        def cancelled():
            finish()
            if not self._closed:
                self.status.setText(self.tr("Processing stopped by user."))

        started = self.controller._run("mod_management_dmm", task, completed, failed, on_cancel=cancelled)
        if not started:
            finish()
        return started

    def _details(self):
        if not self.details_button.isEnabled():
            return
        path = self.selection.selectedItems()[0].data(0, Qt.UserRole)
        from cdmw.services.mod_management_inventory import item_package_details

        def loaded(details):
            title, identity, version, assets, digest = details
            text = "\n".join((title, self.tr("Package identity:") + " " + identity,
                              self.tr("Format:") + f" {Path(path).suffix.lower()} v{version}",
                              self.tr("Assets:") + " " + str(assets), self.tr("Content digest:") + " " + digest, "", path))
            box = QMessageBox(QMessageBox.Icon.Information, self.tr("Mod details"), text, QMessageBox.StandardButton.Ok, self)
            box.setTextFormat(Qt.TextFormat.PlainText)
            box.exec()
        self._when_idle(lambda: self._run(lambda log, stop: item_package_details(path, stop_event=stop), loaded))

    def _send_to_dmm(self):
        from cdmw.services import dmm_send
        from cdmw.ui.new_item import dmm_send_ui
        packages = self._chosen()
        if not packages or not self.send_dmm_button.isEnabled():
            return
        mods = dmm_send_ui.choose_dmm_mods_folder(self)
        if mods is None:
            return
        root = self.package_root
        self.status.setText(self.tr("Sending {value_0} item package(s) to DMM…").format(value_0=len(packages)))

        def sent(result):
            message = self.tr("Sent {value_0} item package(s) to DMM as one mod. In DMM, enable it and click Mount.").format(value_0=len(packages))
            self.status.setText(message)
            self.activity.emit(f"Sent to DMM: {result.folder}")
            if result.replaced:
                message += "\n" + self.tr("It replaced the copy CDMW sent earlier.")
            QMessageBox.information(self, self.tr("Send to DMM"), message + "\n\n" + str(result.folder))
        self._when_idle(lambda: self._run(
            lambda log, stop: dmm_send.send_item_packages(packages, root, mods, DMM_MOD_TITLE, stop_event=stop, on_log=log), sent))

    # ------------------------------------------------------------------ tab interface

    def set_game_root(self, root):
        self.package_root = str(root or "")
        self._buttons()

    def refresh(self):
        self._buttons()

    def request_shutdown(self):
        self._closed = True
        self._queued = None
