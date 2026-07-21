"""Mesh replacement builder dialog lifecycle helpers."""
from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path
from typing import Optional

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QDialog, QWidget

from cdmw.models import ArchiveEntry
from cdmw.ui.archive_browser.static_replacement_alignment_setup_state import (
    alignment_builder_archive_preview_pause_message,
    alignment_builder_window_title,
)


class ArchiveMeshBuilderLifecycleMixin:
    def _modeless_alignment_dialog_key(self, entry: ArchiveEntry, obj_path: Path, dialog_title: str) -> str:
        entry_key = str(getattr(entry, "path", "") or getattr(entry, "basename", "") or "").replace("\\", "/").strip().lower()
        try:
            source_key = str(obj_path.expanduser().resolve()).replace("\\", "/").lower()
        except Exception:
            source_key = str(obj_path).replace("\\", "/").strip().lower()
        title_key = str(dialog_title or alignment_builder_window_title()).strip().lower()
        return f"{entry_key}|{source_key}|{title_key}"

    def _mesh_replacement_builder_active(self) -> bool:
        for key, dialog in list(self._modeless_alignment_dialogs.items()):
            try:
                if dialog is not None:
                    dialog.windowTitle()
                    return True
            except RuntimeError:
                self._modeless_alignment_dialogs.pop(str(key or ""), None)
        return False

    def _defer_archive_preview_refresh_for_builder(
        self,
        entry: Optional[ArchiveEntry] = None,
        *,
        mark_deferred: bool = True,
    ) -> None:
        if mark_deferred:
            self.archive_preview_refresh_deferred_by_builder = True
        self.model_preview_refresh_timer.stop()
        self.archive_preview_debounce_timer.stop()
        message = alignment_builder_archive_preview_pause_message()
        self._set_archive_preview_health_message(message, visible=bool(entry), attention=True)
        self.set_status_message(message)

    def _resume_archive_preview_after_builder(self) -> None:
        if bool(getattr(self, "_shutting_down", False)):
            self.archive_preview_refresh_deferred_by_builder = False
            return
        if self._mesh_replacement_builder_active():
            return
        if not bool(getattr(self, "archive_preview_refresh_deferred_by_builder", False)):
            return
        self.archive_preview_refresh_deferred_by_builder = False
        self._refresh_current_model_preview_assets(force=True)

    def _activate_modeless_alignment_dialog(self, key: str) -> bool:
        dialog = self._modeless_alignment_dialogs.get(str(key or ""))
        if dialog is None:
            return False
        try:
            if not dialog.isVisible():
                self._modeless_alignment_dialogs.pop(str(key or ""), None)
                return False
            if hasattr(self, "mesh_editor_tab"):
                try:
                    builder_host = self.mesh_editor_tab.builder_host()
                except RuntimeError:
                    builder_host = None
                if isinstance(builder_host, QWidget) and dialog.parentWidget() is builder_host:
                    self._activate_tool_widget(self.mesh_editor_tab)
                    dialog.show()
                    dialog.raise_()
                    return True
            dialog.showNormal()
            dialog.raise_()
            dialog.activateWindow()
            return True
        except RuntimeError:
            self._modeless_alignment_dialogs.pop(str(key or ""), None)
            return False

    def _register_modeless_alignment_dialog(self, key: str, dialog: QDialog) -> None:
        self._modeless_alignment_dialogs[str(key or "")] = dialog
        self._defer_archive_preview_refresh_for_builder(
            self._current_archive_entry(),
            mark_deferred=False,
        )

    def _dispose_partial_alignment_builder(
        self,
        key: str,
        dialog: Optional[QDialog] = None,
        *,
        context: Optional[Mapping[str, object]] = None,
    ) -> bool:
        """Idempotently tear down a builder that failed before modeless handoff."""

        dialog = dialog or self._modeless_alignment_dialogs.get(str(key or ""))
        if dialog is None:
            return False
        try:
            if bool(getattr(dialog, "_cdmw_partial_builder_disposed", False)):
                return False
            setattr(dialog, "_cdmw_partial_builder_disposed", True)
        except RuntimeError:
            self._modeless_alignment_dialogs.pop(str(key or ""), None)
            return False

        cleanup_context = context
        if not isinstance(cleanup_context, Mapping):
            candidate = getattr(dialog, "_cdmw_builder_construction_context", None)
            cleanup_context = candidate if isinstance(candidate, Mapping) else {}

        for name, value in tuple(cleanup_context.items()):
            if not str(name).endswith("_timer") or value is None:
                continue
            stop = getattr(value, "stop", None)
            if callable(stop):
                try:
                    stop()
                except (RuntimeError, TypeError):
                    pass

        for callback_name in (
            "_stop_original_reference_texture_worker",
            "_alignment_d3d11_stop_worker",
            "_safe_shutdown_alignment_d3d11_preview",
        ):
            callback = cleanup_context.get(callback_name)
            if callable(callback):
                try:
                    callback()
                except Exception:
                    pass

        finish_progress = cleanup_context.get("_finish_alignment_startup_progress")
        if callable(finish_progress):
            try:
                finish_progress()
            except (RuntimeError, TypeError):
                pass
        else:
            startup_progress = getattr(dialog, "_cdmw_builder_startup_progress", None)
            if startup_progress is not None:
                try:
                    startup_progress.close()
                    startup_progress.deleteLater()
                except RuntimeError:
                    pass

        self.archive_preview_refresh_deferred_by_builder = True
        self._unregister_modeless_alignment_dialog(str(key or ""), dialog)
        try:
            dialog.hide()
            dialog.deleteLater()
        except RuntimeError:
            pass
        return True

    def _unregister_modeless_alignment_dialog(self, key: str, dialog: QDialog) -> None:
        current = self._modeless_alignment_dialogs.get(str(key or ""))
        if current is dialog:
            self._modeless_alignment_dialogs.pop(str(key or ""), None)
        if not self._mesh_replacement_builder_active():
            QTimer.singleShot(0, self._resume_archive_preview_after_builder)
