"""Utilities entry for existing mod merge, update and overlay workflows."""
from pathlib import Path

from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtWidgets import (
    QHBoxLayout, QLabel, QMessageBox, QPlainTextEdit, QProgressBar,
    QPushButton, QTabWidget, QToolButton, QVBoxLayout, QWidget,
)

from cdmw.ui.new_item.controller import NewItemStudioController


class ModManagementTab(QWidget):
    status_message_requested = Signal(str, bool)

    def __init__(self, parent=None, *, window=None, service=None, controller=None,
                 get_package_root=None, preview_context=None):
        super().__init__(parent)
        self._window = window
        self._get_package_root = get_package_root or (lambda: "")
        self.controller = controller or NewItemStudioController(service=service, parent=self)
        context = dict(getattr(self.controller, '_template_preview_context', None) or {})
        context.update(preview_context or {})
        self.controller._template_preview_context = context
        self._migration_preview_lane = self.controller.create_lookup_lane()
        self._migration_preview_lane.completed.connect(self._confirm_overlay_migration)
        self._migration_preview_lane.failed.connect(self._migration_preview_failed)
        self._closed = False
        self._refresh_needed = True
        layout = QVBoxLayout(self)
        heading = QLabel("Mod Management")
        layout.addWidget(heading)
        help_text = QLabel("Manage installed overlays, preview their items, and review changes against the current game.")
        help_text.setWordWrap(True)
        layout.addWidget(help_text)
        self.pages = QTabWidget()
        self.pages.setObjectName('mod_management_pages')
        from cdmw.ui.new_item.overlay_manager_dialog import OverlayManagerDialog
        from cdmw.ui.new_item.mod_merge_dialog import ModMergeDialog
        from cdmw.ui.new_item.mod_update_dialog import ModUpdateDialog
        services = getattr(getattr(window, 'app_context', None), 'services', None)
        mutations = getattr(services, 'require_archive_mutations', None)
        root = str(self._get_package_root() or '')
        self.inventory = OverlayManagerDialog(self.controller, root, mutations() if callable(mutations) else None,
                                              self, embedded=True)
        self.merge_page = ModMergeDialog(self.controller, root, self, embedded=True)
        self.update_page = ModUpdateDialog(self.controller, root, self, installed=True, embedded=True)
        self.pages.addTab(self.inventory, 'Installed overlays')
        self.pages.addTab(self.merge_page, 'Merge mod folders')
        self.pages.addTab(self.update_page, 'Compare updates / export')
        recovery_page = QWidget()
        recovery_layout = QVBoxLayout(recovery_page)
        self.pages.addTab(recovery_page, 'Recovery')
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
        recovery_layout.addWidget(QLabel('Archive recovery'))
        recovery_help = QLabel('Rebuild / reapply in Installed overlays compares saved changes with the current game and preserves individual installs. '
                              'Start fresh retires an unmounted set. Use migration below only for items previously written into shipped archives.')
        recovery_help.setWordWrap(True)
        recovery_layout.addWidget(recovery_help)
        recovery_layout.addWidget(self.recovery)
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
        recovery_layout.addWidget(self.overlay_migration_button)
        recovery_layout.addStretch(1)
        self.operation_bar = QWidget()
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
        self.controller.log_message.connect(self._operation_log)
        self.controller.status_message.connect(self._operation_status)
        self.controller.operation_progress.connect(self._operation_progress)
        self.controller.install_finished.connect(self._installed)
        self.controller.busy_changed.connect(self._busy_changed)
        self._busy_changed(self.controller.busy)

    def _owns_operation(self):
        return getattr(self.controller, '_lane', '') in {'overlay_manager', 'mod_merge', 'mod_update', 'overlay'}

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
        if lane in {'overlay_manager', 'mod_merge', 'mod_update', 'overlay'}:
            self.progress.setRange(0, max(0, total))
            self.progress.setValue(current)
            self.status.setText(str(message))
            self._status_changed(message)

    def _cancel(self):
        if self._owns_operation() and not self.inventory._applying:
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
        if root != str(self.inventory.package_root):
            self.inventory.package_root = root
            self.merge_page.game_root.setText(root)
            self.update_page.game_root.setText(root)
        self.inventory.refresh()

    def _status_changed(self, message, error=False):
        self.status_message_requested.emit(str(message), bool(error))

    def _busy_changed(self, busy):
        busy = self.controller.busy  # A completed review may already have queued its confirmed apply.
        for button in (self.overlay_removal_button, self.merge_button, self.update_button,
                       self.overlay_migration_button):
            button.setEnabled(not busy)
        own = bool(busy and self._owns_operation())
        self.operation_bar.setVisible(own)
        self.progress.setVisible(own)
        self.cancel_button.setVisible(own)
        self.cancel_button.setEnabled(own and not self.inventory._applying)
        if not busy:
            for page in (self.merge_page, self.update_page):
                if page._working:
                    page._working = False
                    page.status.setText('Operation finished or cancelled. Review the results before continuing.')
                    page._buttons()
            QTimer.singleShot(0, self, self._refresh_inventory)

    def _installed(self, result):
        from cdmw.services.archive_overlay_install import OverlayInstallResult
        if isinstance(result, OverlayInstallResult):
            self._refresh_needed = True
            QTimer.singleShot(0, self, self._refresh_inventory)
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
        self.pages.setCurrentWidget(self.merge_page)

    def _update_mods(self) -> None:
        self.pages.setCurrentWidget(self.update_page)

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
        self.pages.setCurrentWidget(self.inventory)
        self.inventory.refresh()

    def iter_shutdown_workers(self):
        from cdmw.ui.new_item.overlay_manager_dialog import OverlayManagerDialog
        workers = list(self.controller.iter_shutdown_workers())
        for dialog in self.findChildren(OverlayManagerDialog):
            workers.extend(dialog.iter_shutdown_workers())
        return tuple(workers)

    def request_shutdown(self):
        if self._closed:
            return
        self._closed = True
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
