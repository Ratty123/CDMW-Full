"""Utilities entry for existing mod merge, update and overlay workflows."""
from pathlib import Path

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QLabel, QMessageBox, QPlainTextEdit, QPushButton, QToolButton, QVBoxLayout, QWidget,
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
        layout = QVBoxLayout(self)
        heading = QLabel("Mod Management")
        layout.addWidget(heading)
        help_text = QLabel("Merge mods, check them after a game update, manage installed overlays, or open archive recovery.")
        help_text.setWordWrap(True)
        layout.addWidget(help_text)
        self.overlay_removal_button = QPushButton("Installed overlays...")
        self.overlay_removal_button.setToolTip("View CDMW's installed overlays and remove an individual install while preserving the others.")
        self.overlay_removal_button.clicked.connect(self._remove_overlay)
        layout.addWidget(self.overlay_removal_button)
        self.merge_button = QPushButton("Merge mods...")
        self.merge_button.clicked.connect(self._merge_mods)
        layout.addWidget(self.merge_button)
        self.update_button = QPushButton("Check mods for game updates...")
        self.update_button.clicked.connect(self._update_mods)
        layout.addWidget(self.update_button)
        self.recovery = QToolButton()
        self.recovery.setText("Archive recovery")
        self.recovery.setCheckable(True)
        self.recovery.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        self.recovery.setArrowType(Qt.ArrowType.RightArrow)
        layout.addWidget(self.recovery)
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
        layout.addWidget(self.overlay_migration_button)
        self.status = QLabel("Choose a mod management tool.")
        self.status.setTextFormat(Qt.TextFormat.PlainText)
        self.status.setWordWrap(True)
        layout.addWidget(self.status)
        self.log = QPlainTextEdit()
        self.log.setReadOnly(True)
        self.log.setProperty("followTail", True)
        layout.addWidget(self.log, 1)
        self.controller.log_message.connect(self.log.appendPlainText)
        self.controller.status_message.connect(self._status_changed)
        self.controller.install_finished.connect(self._installed)
        self.controller.install_failed.connect(lambda message: self._status_changed(message, True))
        self.controller.busy_changed.connect(self._busy_changed)
        self._busy_changed(self.controller.busy)

    def _status_changed(self, message, error=False):
        self.status.setText(str(message))
        self.status_message_requested.emit(str(message), bool(error))

    def _busy_changed(self, busy):
        for button in (self.overlay_removal_button, self.merge_button, self.update_button,
                       self.overlay_migration_button):
            button.setEnabled(not busy)

    def _installed(self, result):
        from cdmw.services.archive_overlay_install import OverlayInstallResult
        if isinstance(result, OverlayInstallResult):
            return  # Create New Item owns the completion of its installation.
        from cdmw.ui.new_item.panels_output import install_result_report
        title, message = install_result_report(result)
        self.log.appendPlainText(message)
        self._status_changed(message)
        if not hasattr(result, 'removed_overlay_id'):
            QMessageBox.information(self, title, message)

    def _merge_mods(self) -> None:
        from cdmw.ui.new_item.mod_merge_dialog import ModMergeDialog

        dialog = ModMergeDialog(self.controller, self._get_package_root(), self)
        dialog.setWindowModality(Qt.WindowModality.WindowModal)
        dialog.show()

    def _update_mods(self) -> None:
        from cdmw.ui.new_item.mod_update_dialog import ModUpdateDialog

        dialog = ModUpdateDialog(self.controller, self._get_package_root(), self)
        dialog.setWindowModality(Qt.WindowModality.WindowModal)
        dialog.show()

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
        title = "Installed overlays"
        found = self._overlay_services(title)
        if found is None:
            return
        mutations, root = found
        from cdmw.ui.new_item.overlay_manager_dialog import OverlayManagerDialog
        existing = self.findChild(OverlayManagerDialog)
        if existing is not None and not existing._closed:
            existing.raise_()
            existing.activateWindow()
            return
        dialog = OverlayManagerDialog(self.controller, root, mutations, self)
        dialog.open()

    def iter_shutdown_workers(self):
        from cdmw.ui.new_item.overlay_manager_dialog import OverlayManagerDialog
        workers = list(self.controller.iter_shutdown_workers())
        for dialog in self.findChildren(OverlayManagerDialog):
            workers.extend(dialog.iter_shutdown_workers())
        return tuple(workers)

    def request_shutdown(self):
        from cdmw.ui.new_item.overlay_manager_dialog import OverlayManagerDialog
        for dialog in self.findChildren(OverlayManagerDialog):
            dialog.request_shutdown()
        self.controller.request_shutdown()

    def shutdown(self):
        self.request_shutdown()
        self.controller.shutdown()

    def closeEvent(self, event):
        self.request_shutdown()
        super().closeEvent(event)
