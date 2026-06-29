"""Mesh Editor bridge methods owned by the shell MainWindow."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Optional, Sequence

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication, QDialog, QMessageBox, QWidget

from cdmw.core.archive_modding import ARCHIVE_MESH_EXTENSIONS
from cdmw.models import ArchiveEntry
from cdmw.modding.scene_importer import SceneImportResult
from cdmw.ui.mesh_editor.session import MeshEditorSessionRequest, mesh_editor_source_skeleton


class MeshEditorShellBridgeMixin:
    """Route shell/archive actions into Mesh Editor sessions."""
    def _export_current_archive_mesh(self, export_format: str) -> None:
        current_entry = self._current_archive_mesh_entry()
        if current_entry is None:
            self.set_status_message("Select a supported archive mesh to export.", error=True)
            return
        self._start_archive_mesh_export(current_entry, export_format)

    def _open_mesh_editor_for_entry(
        self,
        entry: ArchiveEntry,
        *,
        mode: str = "modify_original",
        source_path: Optional[Path] = None,
        source_entry: Optional[ArchiveEntry] = None,
        source_skeleton: object | None = None,
        supplemental_files: Sequence[Path] = (),
        scene_import_result: Optional[SceneImportResult] = None,
        activate: bool = True,
        ) -> Optional[MeshEditorSessionRequest]:
        if not isinstance(entry, ArchiveEntry) or entry.extension not in ARCHIVE_MESH_EXTENSIONS:
            self.set_status_message("Select a supported archive mesh before opening Mesh Editor.", error=True)
            return None
        self._strip_archive_preview_heavy_payloads_for_mesh_editor(entry)
        request_supplemental_files = tuple(path for path in tuple(supplemental_files or ()) if isinstance(path, Path))
        request = MeshEditorSessionRequest(
            target_entry=entry,
            mode=str(mode or "modify_original").strip() or "modify_original",
            source_path=source_path,
            source_entry=source_entry,
            source_skeleton=mesh_editor_source_skeleton(
                source_skeleton=source_skeleton,
                source_path=source_path,
                supplemental_files=request_supplemental_files,
                scene_import_result=scene_import_result,
            ),
            supplemental_files=request_supplemental_files,
            scene_import_result=scene_import_result,
        )
        self._reset_mesh_editor_d3d11_view_state_for_session(self._mesh_editor_session_request_key(request))
        if not hasattr(self, "mesh_editor_tab"):
            return request
        self.mesh_editor_tab.open_session(request)
        if activate:
            self._activate_tool_widget(self.mesh_editor_tab)
        return request

    def _mesh_editor_session_request_key(self, request: object) -> str:
        if request is None:
            return ""
        target_entry = getattr(request, "target_entry", None)
        source_entry = getattr(request, "source_entry", None)
        source_path = getattr(request, "source_path", None)
        source_skeleton = getattr(request, "source_skeleton", None)
        try:
            source_path_key = str(Path(source_path).expanduser().resolve()).replace("\\", "/").lower() if source_path else ""
        except Exception:
            source_path_key = str(source_path or "").replace("\\", "/").strip().lower()
        supplemental = []
        for path in tuple(getattr(request, "supplemental_files", ()) or ()):
            try:
                supplemental.append(str(Path(path).expanduser().resolve()).replace("\\", "/").lower())
            except Exception:
                supplemental.append(str(path or "").replace("\\", "/").strip().lower())
        parts = {
            "target": self._archive_entry_identity_key(target_entry) if isinstance(target_entry, ArchiveEntry) else self._mesh_editor_entry_key(target_entry),
            "mode": str(getattr(request, "mode", "") or "").strip().lower(),
            "source_entry": self._archive_entry_identity_key(source_entry) if isinstance(source_entry, ArchiveEntry) else self._mesh_editor_entry_key(source_entry),
            "source_path": source_path_key,
            "source_skeleton": str(getattr(source_skeleton, "path", "") or "") if source_skeleton is not None else "",
            "has_source_skeleton": source_skeleton is not None,
            "supplemental": tuple(sorted(value for value in supplemental if value)),
            "has_scene_import": bool(getattr(request, "scene_import_result", None) is not None),
        }
        encoded = json.dumps(parts, sort_keys=True, separators=(",", ":"), default=str).encode("utf-8", "replace")
        return hashlib.sha256(encoded).hexdigest()

    def _reset_mesh_editor_d3d11_view_state_for_session(self, session_key: str) -> None:
        normalized = str(session_key or "").strip()
        if not normalized:
            return
        if str(getattr(self, "mesh_editor_d3d11_session_key", "") or "") == normalized:
            return
        self.mesh_editor_d3d11_session_key = normalized
        self.mesh_editor_d3d11_view_state_reset_generation = int(
            getattr(self, "mesh_editor_d3d11_view_state_reset_generation", 0) or 0
        ) + 1

    def _mesh_editor_entry_key(self, entry: object) -> str:
        return str(getattr(entry, "path", "") or getattr(entry, "name", "") or "").replace("\\", "/").strip().lower()

    def _mesh_editor_active_builder(self) -> Optional[QWidget]:
        if not hasattr(self, "mesh_editor_tab"):
            return None
        try:
            return self.mesh_editor_tab.active_builder()
        except RuntimeError:
            return None

    def _mesh_editor_active_builder_entry_key(self) -> str:
        active_builder = self._mesh_editor_active_builder()
        if active_builder is not None:
            for key, dialog in list(self._modeless_alignment_dialogs.items()):
                try:
                    if dialog is active_builder:
                        return str(key or "").split("|", 1)[0]
                except RuntimeError:
                    self._modeless_alignment_dialogs.pop(str(key or ""), None)
        if not hasattr(self, "mesh_editor_tab"):
            return ""
        active_request = getattr(self.mesh_editor_tab, "current_request", None)
        active_entry = getattr(active_request, "target_entry", None)
        return self._mesh_editor_entry_key(active_entry)

    def _prepare_mesh_editor_archive_launch(self, entry: ArchiveEntry) -> bool:
        if not isinstance(entry, ArchiveEntry):
            return False
        if not hasattr(self, "mesh_editor_tab"):
            return True
        active_builder = self._mesh_editor_active_builder()
        if active_builder is None:
            return True
        if self._mesh_editor_active_builder_entry_key() == self._mesh_editor_entry_key(entry):
            self._activate_tool_widget(self.mesh_editor_tab)
            self.set_status_message("Mesh Editor is already open for this target.")
            return False
        result = QMessageBox.question(
            self,
            "Replace Mesh Editor Workflow",
            "Mesh Editor already has an active workflow.\n\n"
            "Close the current Mesh Editor workflow and open the selected archive mesh?\n\n"
            "Any alignment or mesh edits that have not been built/exported will be discarded.",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )
        if result != QMessageBox.Yes:
            self._activate_tool_widget(self.mesh_editor_tab)
            return False
        try:
            if isinstance(active_builder, QDialog):
                active_builder.reject()
            else:
                self.mesh_editor_tab.show_empty_state("Previous Mesh Editor workflow closed.")
            QApplication.processEvents()
        except RuntimeError:
            pass
        return True

    def _launch_archive_mesh_editor_for_entry(self, entry: ArchiveEntry) -> None:
        if not isinstance(entry, ArchiveEntry) or entry.extension not in ARCHIVE_MESH_EXTENSIONS:
            self.set_status_message("Select a supported archive mesh before opening Mesh Editor.", error=True)
            return
        if not self._prepare_mesh_editor_archive_launch(entry):
            return
        self._mesh_editor_modify_original_requested(entry)

    def _open_current_archive_mesh_editor(self) -> None:
        current_entry = self._current_archive_mesh_entry()
        if current_entry is None:
            self.set_status_message("Select a supported archive mesh before opening Mesh Editor.", error=True)
            return
        self._launch_archive_mesh_editor_for_entry(current_entry)

    def _mesh_editor_modify_original_requested(self, entry: object) -> None:
        if not isinstance(entry, ArchiveEntry):
            self.set_status_message("Mesh Editor has no valid target mesh.", error=True)
            return
        self._open_mesh_editor_for_entry(entry, mode="modify_original", activate=True)
        self._set_last_active_operation(
            "mesh_replacement_modify_original",
            path=getattr(entry, "path", ""),
            package=str(getattr(entry, "pamt_path", "") or ""),
        )
        QTimer.singleShot(0, lambda current_entry=entry: self._start_archive_modify_original_workspace(current_entry))

    def _mesh_editor_import_replacement_requested(self, entry: object) -> None:
        if not isinstance(entry, ArchiveEntry):
            self.set_status_message("Mesh Editor has no valid target mesh.", error=True)
            return
        self._open_mesh_editor_for_entry(entry, mode="external_import", activate=True)
        self._start_archive_mesh_patch(entry)

    def _mesh_editor_import_preview_requested(self, entry: object) -> None:
        if not isinstance(entry, ArchiveEntry):
            self.set_status_message("Mesh Editor has no valid target mesh.", error=True)
            return
        self._open_mesh_editor_for_entry(entry, mode="external_import", activate=True)
        self._start_archive_mesh_import_preview(entry)

    def _mesh_editor_in_game_swap_requested(self, entry: object) -> None:
        if not isinstance(entry, ArchiveEntry):
            self.set_status_message("Mesh Editor has no valid target mesh.", error=True)
            return
        self._open_mesh_editor_for_entry(entry, mode="in_game_swap", activate=True)
        self._handle_archive_in_game_mesh_swap_entry(entry)

    def _mesh_editor_show_archive_target_requested(self, entry: object) -> None:
        if not isinstance(entry, ArchiveEntry):
            return
        self._show_archive_browser_from_texture_editor(entry.path)

    def _mesh_editor_route_active_builder_action(self, action: object) -> Optional[bool]:
        active_builder = self._mesh_editor_active_builder()
        if active_builder is None:
            return None
        handler = getattr(active_builder, "_mesh_editor_action_bar_action_requested", None)
        if not callable(handler):
            return None
        return bool(handler(action))

    def _mesh_editor_action_requested(self, action: object) -> None:
        key = str(getattr(action, "key", "") or "").strip()
        text = str(getattr(action, "text", "") or key or "tool").strip()
        command = str(getattr(action, "command", "") or "").strip()
        mode = str(getattr(action, "mode", "") or "").strip()
        selection_mode = str(getattr(action, "selection_mode", "") or "").strip()
        routed = self._mesh_editor_route_active_builder_action(action)
        if routed is not False and hasattr(self, "mesh_editor_tab"):
            self.mesh_editor_tab.set_active_tool_state(
                mode=mode if command == "set_mode" else "",
                active_selection_mode=selection_mode,
            )
        if routed is True:
            self.set_status_message(f"Mesh Editor action sent: {text}.")
        elif routed is False:
            self.set_status_message(f"Mesh Editor action is not available in the embedded builder yet: {text}.")
        else:
            self.set_status_message(f"Mesh Editor tool selected: {text}.")

    def _modify_current_archive_original_mesh(self) -> None:
        current_entry = self._current_archive_mesh_entry()
        if current_entry is None:
            self.set_status_message("Select a supported archive mesh to modify.", error=True)
            return
        self._open_mesh_editor_for_entry(current_entry, mode="modify_original", activate=True)
        self._set_last_active_operation(
            "mesh_replacement_modify_original",
            path=getattr(current_entry, "path", ""),
            package=str(getattr(current_entry, "pamt_path", "") or ""),
        )
        QTimer.singleShot(
            0,
            lambda current_entry=current_entry: self._start_archive_modify_original_workspace(current_entry),
        )

__all__ = ["MeshEditorShellBridgeMixin"]
