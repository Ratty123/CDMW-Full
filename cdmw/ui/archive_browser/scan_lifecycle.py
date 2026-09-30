"""Opening orchestration for the sole standalone archive backend."""
from __future__ import annotations

from pathlib import Path
import threading

from PySide6.QtCore import QThreadPool, Qt, Slot

from cdmw.domain.archives.catalogue_operations import ArchiveBackendError
from cdmw.ui.archive_browser.failure_report import ArchiveFailureDialog
from cdmw.workers.game_executable_fingerprint import GameExecutableFingerprintTask


class ArchiveScanLifecycleMixin:
    def _archive_package_root_changed(self, _text: str) -> None:
        self.archive_game_fingerprint_stop.set()
        self.archive_open_generation += 1
        self.archive_open_game_fingerprints = None
        self._clear_archive_failure_display()
        bridge = self.archive_remote_bridge
        if bridge is not None:
            if not bridge.cancel_pending_update():
                bridge.controller.cancel_pending()
            bridge.cancel_preview_dependencies(clear_snapshot=True)
            self.archive_catalogue_service.invalidate_before(bridge.controller.generation)
        warmup = self.archive_item_finder_warmup_controller
        if warmup is not None:
            warmup.invalidate()
        character_warmup = self.archive_character_finder_warmup_controller
        if character_warmup is not None:
            character_warmup.invalidate()
        panel = getattr(self, "archive_item_names_failure_panel", None)
        if panel is not None:
            panel.clear()
        self.archive_remote_query_pending = False

    def _clear_archive_failure_display(self) -> None:
        dialog = getattr(self, "archive_backend_failure_dialog", None)
        if dialog is not None:
            dialog.close()
        self.archive_backend_failure_dialog = None

    def _handle_archive_backend_failure(self, kind: str, error: object) -> None:
        if self.shell._shutting_down:
            return
        self._clear_archive_failure_display()
        self.shell._release_startup_splash()
        dialog = ArchiveFailureDialog(self)
        self.archive_backend_failure_dialog = dialog
        generation = self.archive_open_generation
        bridge = self.archive_remote_bridge
        def retry():
            if self.shell._shutting_down or generation != self.archive_open_generation:
                dialog.close()
                return
            dialog.close()
            self.archive_backend_failure_dialog = None
            if bridge is not None:
                bridge.retry_failed_operation()
            else:
                self.scan_archives(activate_archive_tab=False)
        dialog.retryRequested.connect(retry)
        dialog.finished.connect(lambda _: setattr(self, "archive_backend_failure_dialog", None) if self.archive_backend_failure_dialog is dialog else None)
        dialog.panel.show_failure("The archive operation could not finish.", error, operation=kind,
                                  package_root=self.archive_package_root_edit.text().strip())
        dialog.open()

    def _handle_archive_item_names_failure(self, error: object) -> None:
        if not self.shell._shutting_down:
            self.archive_item_names_failure_panel.show_failure("Item names unavailable", error, operation="build_name_index",
                package_root=self.archive_package_root_edit.text().strip())

    def _publish_archive_game_update_fingerprints(self) -> None:
        if self.archive_open_game_fingerprints is not None:
            self.shell._save_game_executable_fingerprints(self.archive_open_game_fingerprints)
            self.archive_open_game_fingerprints = None

    def scan_archives(self, force_refresh: bool = False, *, activate_archive_tab: bool = True) -> None:
        bridge = self.archive_remote_bridge
        if self.shell._shutting_down:
            return
        if force_refresh and self.archive_remote_query_pending:
            self.archive_game_fingerprint_stop.set()
            self.archive_open_generation += 1
            if bridge is not None:
                bridge.cancel_pending_update()
            return
        if self.shell._background_task_active(block_on_archive_index=False):
            return
        root_text = self.archive_package_root_edit.text().strip()
        if not root_text:
            if not self.shell._prompt_for_archive_package_root_if_missing(reason="refresh" if force_refresh else "scan",
                after_autodetect=lambda: self.scan_archives(force_refresh, activate_archive_tab=activate_archive_tab)):
                return
            root_text = self.archive_package_root_edit.text().strip()
            if not root_text:
                return
        if bridge is None:
            self._handle_archive_backend_failure("open_archive", ArchiveBackendError("backend_unavailable", "The standalone archive backend is unavailable."))
            return
        self._clear_archive_failure_display()
        self.archive_item_names_failure_panel.clear()
        self.archive_game_fingerprint_stop.set()
        self.archive_game_fingerprint_stop = threading.Event()
        self.archive_open_generation += 1
        generation = self.archive_open_generation
        self.archive_open_game_fingerprints = None
        self._archive_open_options = (Path(root_text).expanduser(), force_refresh, activate_archive_tab)
        self.archive_remote_query_pending = True
        self.shell.clear_archive_scan_log()
        if self.archive_obsolete_backend_override is not None and not self.archive_obsolete_override_logged:
            self.archive_obsolete_override_logged = True
            self.shell.append_archive_log("CDMW_ARCHIVE_BACKEND is obsolete and ignored; using the standalone archive backend.")
        self.shell._set_archive_cache_health("building", "Cache Status: Building. Standalone archive catalogue is preparing a generation.", package_root=root_text)
        self._set_archive_load_progress("Checking game version...", phase="Preparing")
        task = GameExecutableFingerprintTask(generation, self._archive_open_options[0], self.shell._load_game_executable_fingerprints(), self.archive_game_fingerprint_stop)
        task.signals.completed.connect(self._archive_game_fingerprint_checked, Qt.QueuedConnection)
        self.archive_game_fingerprint_task = task
        QThreadPool.globalInstance().start(task)

    @Slot(int, object)
    def _archive_game_fingerprint_checked(self, generation: int, result: object) -> None:
        if self.shell._shutting_down or generation != self.archive_open_generation or self.archive_game_fingerprint_stop.is_set():
            return
        self.archive_game_fingerprint_task = None
        root, force_refresh, activate_tab = self._archive_open_options
        if str(root) != str(Path(self.archive_package_root_edit.text().strip()).expanduser()):
            self.archive_remote_query_pending = False
            return
        records, logs, changed = result
        self.archive_open_game_fingerprints = records
        for message in logs:
            self.shell.append_archive_log(message)
        self.shell._set_last_active_operation("archive_catalogue_refresh" if force_refresh or changed else "archive_catalogue_open", package_root=str(root), force_refresh=force_refresh or changed)
        self.archive_remote_bridge.open_archive(root, force_refresh=force_refresh or changed, activate_tab=activate_tab)
