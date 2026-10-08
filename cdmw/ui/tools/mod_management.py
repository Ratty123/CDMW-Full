"""Utilities entry for existing mod merge, update and overlay workflows."""
from pathlib import Path

from PySide6.QtCore import Qt, QTimer, QSignalBlocker, Signal
from PySide6.QtWidgets import (
    QFileDialog, QGroupBox, QHBoxLayout, QLabel, QLineEdit, QMessageBox, QPlainTextEdit, QProgressBar,
    QPushButton, QTabWidget, QToolButton, QVBoxLayout, QWidget,
)

from cdmw.ui.new_item.controller import NewItemStudioController


class ModManagementTab(QWidget):
    status_message_requested = Signal(str, bool)

    def __init__(self, parent=None, *, window=None, service=None, controller=None,
                 get_package_root=None, set_package_root=None, preview_context=None, repackage_owner=None):
        super().__init__(parent)
        self.setObjectName('mod_management_workspace')
        self._window = window
        self._get_package_root = get_package_root or (lambda: "")
        self._set_package_root = set_package_root
        self._repackage_owner = repackage_owner or getattr(window, 'archive', None)
        self.repackage_ui = None
        self.controller = controller or NewItemStudioController(service=service, parent=self)
        context = dict(getattr(self.controller, '_template_preview_context', None) or {})
        context.update(preview_context or {})
        self.controller._template_preview_context = context
        self._migration_preview_lane = self.controller.create_lookup_lane()
        self._migration_preview_lane.completed.connect(self._confirm_overlay_migration)
        self._migration_preview_lane.failed.connect(self._migration_preview_failed)
        self._closed = False
        self._refresh_needed = True
        self._overview_refresh_needed = False
        layout = QVBoxLayout(self)
        heading = QLabel("Mod Management")
        heading.setObjectName('SectionTitle')
        layout.addWidget(heading)
        source_row = QHBoxLayout()
        source_label = QLabel('Game folder')
        source_label.setObjectName('mod_management_game_label')
        source_row.addWidget(source_label)
        self.game_folder = QLineEdit(str(self._get_package_root() or ''))
        self.game_folder.setObjectName('mod_management_game_folder')
        self.game_folder.setReadOnly(True)
        source_row.addWidget(self.game_folder, 1)
        self.choose_game = QPushButton('Change…')
        self.choose_game.setObjectName('mod_management_choose_game')
        self.choose_game.setToolTip('Choose the Crimson Desert game folder.')
        self.choose_game.setEnabled(callable(self._set_package_root))
        self.choose_game.clicked.connect(self._choose_game)
        source_row.addWidget(self.choose_game)
        layout.addLayout(source_row)
        self.pages = QTabWidget()
        self.pages.setObjectName('mod_management_pages')
        self.advanced_pages = QTabWidget()
        self.advanced_pages.setObjectName('mod_management_advanced_pages')
        from cdmw.ui.new_item.overlay_manager_dialog import OverlayManagerDialog
        from cdmw.ui.new_item.mod_merge_dialog import ModMergeDialog
        from cdmw.ui.new_item.mod_update_dialog import ModUpdateDialog
        services = getattr(getattr(window, 'app_context', None), 'services', None)
        mutations = getattr(services, 'require_archive_mutations', None)
        root = str(self._get_package_root() or '')
        self.inventory = OverlayManagerDialog(self.controller, root, mutations() if callable(mutations) else None,
                                              self, embedded=True, catalogue_service=getattr(
                                                  getattr(window, 'archive', None), 'archive_catalogue_service', None))
        self.merge_page = ModMergeDialog(self.controller, root, self, embedded=True)
        self.update_page = ModUpdateDialog(self.controller, root, self, installed=True, embedded=True)
        from cdmw.ui.tools.mod_management_overview import ModManagementOverview
        self.overview = ModManagementOverview(self.controller, self, mutations=self.inventory.mutations)
        self.advanced_pages.addTab(self.overview, 'Overview')
        self.advanced_pages.addTab(self.inventory, 'Installed mod details')
        from cdmw.ui.new_item.independent_items_page import IndependentItemsPage
        self.independent_page = IndependentItemsPage(self.controller, root, mutations() if callable(mutations) else None, self)
        self.advanced_pages.addTab(self.independent_page, 'Item package tools')
        self.independent_page.activity.connect(self._append_activity)
        from cdmw.ui.tools.mod_management_list import ModManagementList
        self.virtual_page = ModManagementList(self.controller, root, self.inventory, self.independent_page, self)
        self.pages.addTab(self.virtual_page, 'Mods')
        self.pages.addTab(self.advanced_pages, 'Advanced')
        self.virtual_page.details_requested.connect(self._show_mod_details)
        self.virtual_page.activity.connect(self._append_activity)
        from cdmw.ui.tools.mod_package_retrofit_tasks import ModPackageRetrofitToolWidget
        self.repackage_page = ModPackageRetrofitToolWidget()
        self.advanced_pages.addTab(self.repackage_page, 'Repackage')
        self.advanced_pages.addTab(self.merge_page, 'Merge')
        self.advanced_pages.addTab(self.update_page, 'Game updates')
        recovery_page = QWidget()
        recovery_layout = QVBoxLayout(recovery_page)
        self.advanced_pages.addTab(recovery_page, 'Recovery')
        self._page_by_key = {'mods': self.virtual_page, 'overview': self.overview, 'installed': self.inventory, 'independent': self.independent_page, 'virtual': self.virtual_page,
                             'repackage': self.repackage_page, 'merge': self.merge_page, 'updates': self.update_page,
                             'recovery': recovery_page}
        self.pages.currentChanged.connect(self._page_changed)
        self.advanced_pages.currentChanged.connect(self._page_changed)
        self.overview.page_requested.connect(self.open_page)
        self.overview.refresh_requested.connect(self.refresh)
        self.inventory.inventory_changed.connect(self.overview.set_entries)
        layout.addWidget(self.pages, 1)
        self.inventory.updates_requested.connect(self._update_mods)
        self.inventory.activity.connect(self._append_activity)
        # Preserve existing entry-point attributes for callers; navigation is now
        # through the inline pages, not launcher buttons and child windows.
        self.overlay_removal_button = QPushButton('Installed overlays', self)
        self.overlay_removal_button.clicked.connect(self._remove_overlay)
        self.overlay_removal_button.hide()
        self.merge_button = QPushButton('Merge mods', self)
        self.merge_button.clicked.connect(self._merge_mods)
        self.merge_button.hide()
        self.update_button = QPushButton('Check mods for game updates', self)
        self.update_button.clicked.connect(self._update_mods)
        self.update_button.hide()
        self.recovery = QToolButton()
        self.recovery.setText("Archive recovery")
        self.recovery.setCheckable(True)
        self.recovery.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        self.recovery.setArrowType(Qt.ArrowType.RightArrow)
        saved = QGroupBox('Saved installs')
        saved_layout = QVBoxLayout(saved)
        recovery_layout.addWidget(saved)
        recovery_help = QLabel('Review saved installs against the current game.')
        recovery_help.setToolTip('Rebuild / reapply compares saved changes with the current game and preserves individual installs. '
                                'Start fresh retires an unmounted set.')
        recovery_help.setWordWrap(True)
        saved_layout.addWidget(recovery_help)
        repair_row = QHBoxLayout()
        repair_row.addWidget(self.inventory.rebuild_button)
        repair_row.addWidget(self.inventory.start_fresh_button)
        repair_row.addStretch(1)
        saved_layout.addLayout(repair_row)
        legacy = QGroupBox('Archive recovery')
        legacy_layout = QVBoxLayout(legacy)
        legacy_help = QLabel('For items previously written into shipped archives.')
        legacy_help.setWordWrap(True)
        legacy_layout.addWidget(legacy_help)
        legacy_layout.addWidget(self.recovery)
        recovery_layout.addWidget(legacy)
        self.overlay_migration_button = QPushButton("Move installed items into the overlay...")
        self.overlay_migration_button.setToolTip(
            "For items already written into the shipped archives. Every archive entry that differs from the oldest "
            "backup of it is carried into the overlay directory, and the archives themselves go back to that backup, "
            "so the game reads the same thing while the files it shipped are its own again.")
        self.overlay_migration_button.clicked.connect(self._migrate_overlay)
        self.overlay_migration_button.hide()
        self.recovery.toggled.connect(self.overlay_migration_button.setVisible)
        self.recovery.toggled.connect(lambda expanded: self.recovery.setArrowType(
            Qt.ArrowType.DownArrow if expanded else Qt.ArrowType.RightArrow))
        legacy_layout.addWidget(self.overlay_migration_button)
        recovery_layout.addStretch(1)
        self.operation_bar = QWidget()
        self.operation_bar.setObjectName('mod_management_operation_bar')
        activity_row = QHBoxLayout(self.operation_bar)
        activity_row.setContentsMargins(0, 0, 0, 0)
        self.status = QLabel('')
        self.status.setTextFormat(Qt.TextFormat.PlainText)
        self.status.setWordWrap(True)
        activity_row.addWidget(self.status, 1)
        self.progress = QProgressBar()
        self.progress.setRange(0, 0)
        activity_row.addWidget(self.progress)
        self.cancel_button = QPushButton('Cancel')
        self.cancel_button.clicked.connect(self._cancel)
        activity_row.addWidget(self.cancel_button)
        layout.addWidget(self.operation_bar)
        # The shell's Activity drawer owns history, copy and clear. Keep its
        # document here without projecting another log below every page.
        self.log = QPlainTextEdit(self)
        self.log.setReadOnly(True)
        self.log.setProperty("followTail", True)
        self.log.setMaximumBlockCount(2000)
        self.log.hide()
        self.overview.activity.connect(self._append_activity)
        self.controller.log_message.connect(self._operation_log)
        self.controller.status_message.connect(self._operation_status)
        self.controller.operation_progress.connect(self._operation_progress)
        self.controller.install_finished.connect(self._installed)
        self.controller.busy_changed.connect(self._busy_changed)
        self._busy_changed(self.controller.busy)

    def open_page(self, key):
        page = self._page_by_key.get(key)
        if page is not None and not self._closed:
            with QSignalBlocker(self.pages), QSignalBlocker(self.advanced_pages):
                if page is self.virtual_page:
                    self.pages.setCurrentWidget(page)
                else:
                    self.advanced_pages.setCurrentWidget(page)
                    self.pages.setCurrentWidget(self.advanced_pages)
            self._page_changed(0)

    def _current_page(self):
        return self.advanced_pages.currentWidget() if self.pages.currentWidget() is self.advanced_pages else self.pages.currentWidget()

    def _show_mod_details(self, identity):
        self.open_page('installed')
        for row, entry in enumerate(self.inventory._entries):
            if entry.id == identity:
                self.inventory.search.clear()
                self.inventory.table.selectRow(row)
                break

    def _page_changed(self, _index):
        self._update_operation_bar()
        if self._current_page() is self.independent_page:
            self.independent_page.refresh()
        if self.pages.currentWidget() is self.virtual_page:
            self.virtual_page.refresh()
        if self._current_page() is not self.repackage_page or self.repackage_ui is not None:
            return
        if self._repackage_owner is None:
            if self.repackage_page.layout() is None:
                layout = QVBoxLayout(self.repackage_page)
                layout.addWidget(QLabel(self.tr('Open Mod Management from the main window to repackage mods.')))
                layout.addStretch(1)
            return
        from cdmw.ui.tools.mod_package_retrofit_widget import build_mod_package_retrofit_tool
        self.repackage_ui = build_mod_package_retrofit_tool(self._repackage_owner, self.repackage_page,
                                                          run_initial_scan=False)
        tasks = self.repackage_ui.task_controller
        tasks.progress.connect(lambda _kind, _current, _total, detail: self._append_activity(detail))
        tasks.failed.connect(lambda _kind, message: self._append_activity(message))
        tasks.conversion_completed.connect(lambda _result: self._append_activity(self.repackage_ui.status_label.text()))

    def _choose_game(self):
        if self.controller.busy or not callable(self._set_package_root):
            return
        root = QFileDialog.getExistingDirectory(self, 'Choose the game archive folder', self.game_folder.text())
        if root:
            self._set_package_root(root)
            self.refresh()

    def refresh(self):
        self._refresh_needed = True
        self._refresh_inventory()

    def _owns_operation(self):
        return getattr(self.controller, '_lane', '') in {'overlay_manager', 'mod_merge', 'mod_update', 'overlay', 'independent_items', 'virtual_loader'}

    def _append_activity(self, message):
        if str(message).strip():
            self.log.appendPlainText(str(message))
            self._status_changed(message)

    def _operation_log(self, message):
        if self._owns_operation():
            self._append_activity(message)

    def _operation_status(self, message, error=False):
        if self._owns_operation():
            self.status.setText(str(message))
            self._status_changed(message, error)

    def _operation_progress(self, lane, current, total, message):
        if lane in {'overlay_manager', 'mod_merge', 'mod_update', 'overlay', 'independent_items', 'virtual_loader'}:
            self.progress.setRange(0, max(0, total))
            self.progress.setValue(current)
            self.status.setText(str(message))
            self._status_changed(message)

    def _cancel(self):
        if self._owns_operation() and not self.inventory._applying and not self.independent_page._applying and not self.virtual_page._applying and not self.overview._applying:
            self.controller.cancel_operation(self.controller._lane)

    def showEvent(self, event):
        super().showEvent(event)
        if not self._closed:
            self._refresh_needed = True
            QTimer.singleShot(0, self, self._refresh_inventory)

    def _refresh_inventory(self):
        if self._closed or not self._refresh_needed or self.inventory._inventory_blocked() or not self.isVisible():
            return
        self._refresh_needed = False
        root = str(self._get_package_root() or '').strip()
        self.game_folder.setText(root)
        self.overview.refresh(root)
        if root != str(self.inventory.package_root):
            self.overview.set_entries(())
            self.inventory._loaded(())
            self.inventory.package_root = root
            self.merge_page.game_root.setText(root)
            self.update_page.game_root.setText(root)
        self.inventory.refresh()
        self.independent_page.set_game_root(root)
        self.virtual_page.set_game_root(root)
        if self._current_page() is self.independent_page:
            self.independent_page.refresh()
        if self.pages.currentWidget() is self.virtual_page:
            self.virtual_page.refresh()

    def _status_changed(self, message, error=False):
        self.status_message_requested.emit(str(message), bool(error))

    def _update_operation_bar(self):
        # The virtual workspace already owns its status, percentage and Cancel.
        # Keep the shared controls available when navigating to another page.
        local_controls = (self.pages.currentWidget() is self.virtual_page
                          and self.controller._lane == 'virtual_loader')
        self.operation_bar.setVisible(self.controller.busy and self._owns_operation() and not local_controls)

    def _busy_changed(self, busy):
        busy = self.controller.busy  # A completed review may already have queued its confirmed apply.
        if busy and self.controller._lane != 'snapshot':
            self.overview.cancel_read()
            self._overview_refresh_needed = True
        self.choose_game.setEnabled(not busy and callable(self._set_package_root))
        self.overview.refresh_button.setEnabled(not busy)
        for button in (self.overlay_removal_button, self.merge_button, self.update_button,
                       self.overlay_migration_button):
            button.setEnabled(not busy)
        own = bool(busy and self._owns_operation())
        self._update_operation_bar()
        self.progress.setVisible(own)
        self.cancel_button.setVisible(own)
        self.cancel_button.setEnabled(own and not self.inventory._applying and not self.independent_page._applying and not self.virtual_page._applying and not self.overview._applying)
        if not busy:
            if self._overview_refresh_needed and not self._closed:
                self._overview_refresh_needed = False
                self.overview.refresh(self._get_package_root())
            for page in (self.merge_page, self.update_page):
                if page._working:
                    page._working = False
                    page.status.setText('Operation finished or cancelled. Review the results before continuing.')
                    page._buttons()
            QTimer.singleShot(0, self, self._refresh_inventory)

    def _installed(self, result):
        self._refresh_needed = True
        QTimer.singleShot(0, self, self._refresh_inventory)
        from cdmw.services.archive_overlay_install import OverlayInstallResult
        if isinstance(result, OverlayInstallResult):
            return  # Create New Item owns the completion of its installation.
        if hasattr(result, 'removed_overlay_id') or hasattr(result, 'retired_inventory'):
            return  # The inventory owns this result and refreshes itself.
        from cdmw.ui.new_item.panels_output import install_result_report
        title, message = install_result_report(result)
        self.log.appendPlainText(message)
        self._status_changed(message)
        if not hasattr(result, 'removed_overlay_id'):
            QMessageBox.information(self, title, message)

    def _merge_mods(self) -> None:
        self.open_page('merge')

    def _update_mods(self) -> None:
        self.open_page('updates')

    def _overlay_services(self, title: str):
        """The mutation service (for the backup) and the package root, or None with a word."""

        services = getattr(getattr(self._window, "app_context", None), "services", None)
        mutations = getattr(services, "require_archive_mutations", None)
        if not callable(mutations):
            QMessageBox.warning(self, title, "The archive mutation service is not available in this window.")
            return None
        root = str(self._get_package_root() or "").strip()
        if not root:
            QMessageBox.warning(self, title, "Point the workbench at the game folder first.")
            return None
        return mutations(), Path(root)

    def _migrate_overlay(self) -> None:
        title = "Move installed items into the overlay"
        found = self._overlay_services(title)
        if found is None:
            return
        mutations, root = found
        from cdmw.services.archive_overlay_migration import plan_migration

        self.controller.status_message.emit("Reading installed items for recovery…", False)
        self._migration_preview_lane.request((mutations, root), lambda stop: plan_migration(root, stop_event=stop))

    def _migration_preview_failed(self, _key, message):
        QMessageBox.warning(self, "Move installed items into the overlay", f"The archives could not be read: {message}")

    def _confirm_overlay_migration(self, key, preview):
        title = "Move installed items into the overlay"
        mutations, root = key
        current = self._overlay_services(title)
        if current is None or current[0] is not mutations or current[1] != root:
            self.controller.status_message.emit("Recovery cancelled because the archive source changed.", True)
            return
        if preview.is_empty:
            QMessageBox.information(self, title, "Nothing in the shipped archives differs from the oldest backup of it, so there is nothing to move.")
            return
        listed = "\n".join(f"- {item.path}" for item in preview.entries[:12])
        more = f"\n- ... {len(preview.entries) - 12} more" if len(preview.entries) > 12 else ""
        confirmation = QMessageBox.question(
            self,
            title,
            (
                f"Move {len(preview.entries)} archive entrie(s) into the overlay and put the shipped archives back?\n\n"
                f"{listed}{more}\n\n"
                f"{len(preview.restore)} archive file(s) go back to their oldest backup ({len(preview.backups)} backup(s) read). "
                "The game must not be running."
            ),
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )
        if confirmation != QMessageBox.Yes:
            return
        self.controller.start_overlay_migration(mutations, root)

    def _remove_overlay(self) -> None:
        self.open_page('installed')
        self.inventory.refresh()

    def iter_shutdown_workers(self):
        from cdmw.ui.new_item.overlay_manager_dialog import OverlayManagerDialog
        workers = list(self.controller.iter_shutdown_workers())
        workers.extend(self.repackage_page.iter_shutdown_workers())
        for dialog in self.findChildren(OverlayManagerDialog):
            workers.extend(dialog.iter_shutdown_workers())
        return tuple(workers)

    def request_shutdown(self):
        if self._closed:
            return
        self._closed = True
        self.overview.request_shutdown()
        self.repackage_page.request_shutdown()
        self.independent_page.request_shutdown()
        self.virtual_page.request_shutdown()
        from cdmw.ui.new_item.overlay_manager_dialog import OverlayManagerDialog
        for dialog in self.findChildren(OverlayManagerDialog):
            dialog.request_shutdown()
        for page in (self.merge_page, self.update_page):
            page._finished(0)
        self.controller.request_shutdown()

    def shutdown(self):
        self.request_shutdown()
        self.controller.shutdown()

    def closeEvent(self, event):
        self.request_shutdown()
        super().closeEvent(event)
