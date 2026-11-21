"""Post-tab startup restore and first-run scheduling."""

from __future__ import annotations

import importlib
import os
import sys
import threading
from typing import Callable

from PySide6.QtCore import QTimer


# Strictly Qt-free heavy authoring/mesh modules warmed on an idle daemon thread
# after the main window is shown so first-visit latency stays low without
# paying their import cost during startup. Never add QObject/QWidget modules.
_IDLE_PREIMPORT_MODULES: tuple[str, ...] = (
    "numpy",
    "cdmw.domain.mesh.validation",
    "cdmw.services.mesh_service",
    "cdmw.modding.scene_importer",
    "cdmw.core.archive_mesh_import_build",
    "cdmw.services.replace_from_archive_service",
    "cdmw.services.hkx_edit_service",
    "cdmw.services.mesh_workflow_service",
    "cdmw.services.preview_rendering_service",
    "cdmw.services.preview_workflow_service",
)


class ShellStartupRestoreMixin:
    """Restore persisted shell state once all tabs and widgets exist."""

    def _prepare_archive_preview_startup_state(self) -> None:
        self.archive._archive_preview_startup_state_pending = True
        tree = getattr(self.archive, "archive_tree", None)
        current_item = tree.currentItem() if tree is not None else None
        debounce_timer = getattr(self.archive, "archive_preview_debounce_timer", None)
        idle = bool(
            current_item is None
            and getattr(self.archive, "current_archive_preview_result", None) is None
            and getattr(self.archive, "archive_preview_thread", None) is None
            and getattr(self.archive, "archive_preview_worker", None) is None
            and getattr(self.archive, "pending_archive_preview_request", None) is None
            and getattr(self.archive, "scheduled_archive_preview_request", None) is None
            and getattr(self.archive, "model_preview_settings_dialog", None) is None
            and not tuple(getattr(self.archive, "_modal_model_preview_settings_dialogs", ()) or ())
            and not (debounce_timer is not None and debounce_timer.isActive())
        )
        if not idle:
            self._ensure_archive_preview_startup_state()

    def _ensure_archive_preview_startup_state(self) -> None:
        if not getattr(self.archive, "_archive_preview_startup_state_pending", False):
            return
        if getattr(self.archive, "_archive_preview_startup_state_applying", False):
            return
        self.archive._archive_preview_startup_state_applying = True
        try:
            if getattr(self, "_model_preview_settings_read_pending", False):
                self.archive._model_preview_render_settings = self.archive._read_model_preview_render_settings()
                self._model_preview_settings_read_pending = False
            self.archive._handle_model_preview_settings_changed(self.archive._model_preview_render_settings)
            self.archive._clear_archive_preview("Select an archive file to preview it here.")
            self.archive._archive_preview_startup_state_pending = False
        finally:
            self.archive._archive_preview_startup_state_applying = False

    def _restore_shell_startup_state(
        self,
        pump_startup_splash: Callable[[str], None],
        *,
        previous_session_unclean: bool,
    ) -> None:
        pump_startup_splash("Restoring saved workspace...")

        self._load_settings()
        self._connect_shell_signals()
        self._refresh_dashboard()
        self._apply_startup_benchmark_overrides()
        self._startup_texture_preview_defer_env = bool(
            self._startup_benchmark_enabled()
            or previous_session_unclean
            or self._startup_archive_autoload_expected()
        )
        if self._startup_texture_preview_defer_env:
            os.environ["CDMW_DEFER_TEXTURE_PREVIEW"] = "1"
        self._prepare_archive_preview_startup_state()
        self.archive._rebuild_archive_structure_filter_controls()
        self.textures._refresh_chainner_chain_info()
        self._apply_csv_log_enabled_state()
        self.textures._apply_upscale_backend_state()
        self.textures._apply_dds_staging_enabled_state()
        self.textures._apply_dds_output_state()
        self._cache_responsive_control_widgets()
        self.archive.archive_filters_dirty = False
        self.archive._update_archive_filter_button_state()
        if not self.archive._archive_preview_startup_state_pending:
            self.archive._update_archive_selection_state()
            self.archive._refresh_archive_preview_settings_status()
        self._apply_ui_language()
        self._settings_ready = True
        self.textures._schedule_workflow_match_refresh()

        geometry = self.settings.value("window/geometry")
        if geometry:
            self.restoreGeometry(geometry)
        from cdmw.ui.layout_persistence import install_layout_persistence

        self._layout_persistence = install_layout_persistence(self, self.settings)
        QTimer.singleShot(0, self._connect_responsive_screen_signals)
        QTimer.singleShot(0, self._apply_initial_responsive_window_defaults)
        QTimer.singleShot(140, self._schedule_column_autofit)
        if os.environ.get("CDMW_GUI_STARTUP_SMOKE") != "1":
            QTimer.singleShot(120, self._show_first_run_guide_if_needed)
            QTimer.singleShot(900, self._maybe_autoload_archive_on_startup)
            self._idle_preimport_stop_event = threading.Event()
            self._idle_preimport_thread = None
            self._idle_preimport_attempts = 0
            QTimer.singleShot(1800, self._maybe_start_idle_module_preimport)

    def _stop_idle_module_preimport(self) -> None:
        stop_event = getattr(self, "_idle_preimport_stop_event", None)
        if stop_event is not None:
            stop_event.set()

    def _maybe_start_idle_module_preimport(self) -> None:
        if getattr(self, "_shutting_down", False):
            return
        stop_event = getattr(self, "_idle_preimport_stop_event", None)
        if stop_event is None or stop_event.is_set():
            return
        if getattr(self, "_idle_preimport_thread", None) is not None:
            return
        if not self.isVisible():
            attempts = int(getattr(self, "_idle_preimport_attempts", 0) or 0) + 1
            self._idle_preimport_attempts = attempts
            if attempts <= 10:
                QTimer.singleShot(1000, self._maybe_start_idle_module_preimport)
            return
        self._start_idle_module_preimport()

    def _start_idle_module_preimport(
        self,
        modules: tuple[str, ...] = _IDLE_PREIMPORT_MODULES,
    ) -> threading.Thread | None:
        if getattr(self, "_shutting_down", False):
            return None
        stop_event = getattr(self, "_idle_preimport_stop_event", None)
        if stop_event is None:
            stop_event = threading.Event()
            self._idle_preimport_stop_event = stop_event
        if stop_event.is_set():
            return None
        archive = getattr(self, "archive", None)
        is_interactive = getattr(archive, "_archive_ui_interactive_active", None)

        def _preimport_worker() -> None:
            for module_name in modules:
                if stop_event.is_set():
                    return
                if module_name in sys.modules:
                    continue
                while callable(is_interactive) and is_interactive():
                    if stop_event.wait(0.25):
                        return
                try:
                    importlib.import_module(module_name)
                except Exception:
                    # Optional pre-warm must never surface errors; callers remain
                    # authoritative for any real import failure on demand.
                    pass
                if stop_event.wait(0.05):
                    return

        thread = threading.Thread(
            target=_preimport_worker,
            name="cdmw-idle-module-preimport",
            daemon=True,
        )
        self._idle_preimport_thread = thread
        thread.start()
        return thread


__all__ = ["ShellStartupRestoreMixin"]
