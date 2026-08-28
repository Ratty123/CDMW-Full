"""Mesh Editor bridge methods owned by the shell MainWindow."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Optional, Sequence

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication, QDialog, QMessageBox, QWidget

from cdmw.domain.archives.filters import archive_entry_identity_key
from cdmw.domain.archives.constants import ARCHIVE_MESH_EXTENSIONS
from cdmw.domain.mesh.session import MeshImportSetupSelection
from cdmw.models import ArchiveEntry
from cdmw.services.mesh_workflow_service import SceneImportResult
from cdmw.services.preview_rendering_service import (
    acquire_dotnet_preview_package_cache_lease_for_path,
)
from cdmw.ui.mesh_editor.session import MeshEditorSessionRequest


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
            source_skeleton=source_skeleton,
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
        except (OSError, RuntimeError, TypeError, ValueError):
            source_path_key = str(source_path or "").replace("\\", "/").strip().lower()
        supplemental = []
        for path in tuple(getattr(request, "supplemental_files", ()) or ()):
            try:
                supplemental.append(str(Path(path).expanduser().resolve()).replace("\\", "/").lower())
            except (OSError, RuntimeError, TypeError, ValueError):
                supplemental.append(str(path or "").replace("\\", "/").strip().lower())
        parts = {
            "target": archive_entry_identity_key(target_entry) if isinstance(target_entry, ArchiveEntry) else self._mesh_editor_entry_key(target_entry),
            "mode": str(getattr(request, "mode", "") or "").strip().lower(),
            "source_entry": archive_entry_identity_key(source_entry) if isinstance(source_entry, ArchiveEntry) else self._mesh_editor_entry_key(source_entry),
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
        has_standalone = bool(self.mesh_editor_tab.has_active_standalone_session())
        if active_builder is None and not has_standalone:
            return True
        if has_standalone:
            current_target = self.mesh_editor_tab._current_target_entry()
            if self._mesh_editor_entry_key(current_target) == self._mesh_editor_entry_key(entry):
                self._activate_tool_widget(self.mesh_editor_tab)
                self.set_status_message("Mesh Editor is already open for this target.")
                return False
            controller = getattr(self.mesh_editor_tab, "standalone_controller", None)
            try:
                revision = int(controller.session_view().revision) if controller is not None else 0
            except (AttributeError, KeyError, RuntimeError, TypeError, ValueError):
                revision = 0
            result = QMessageBox.question(
                self,
                "Replace Mesh Editor Session",
                "Mesh Editor already has an active mesh.\n\n"
                "Close it and open the selected archive mesh?\n\n"
                + (
                    "The current mesh has edits that have not been exported or built."
                    if revision > 0
                    else "The current mesh has no committed geometry edits."
                ),
                QMessageBox.Yes | QMessageBox.No,
                QMessageBox.No,
            )
            if result != QMessageBox.Yes:
                self._activate_tool_widget(self.mesh_editor_tab)
                return False
            self.mesh_editor_tab.close_standalone_session()
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
        current_preview = getattr(self, "current_archive_preview_result", None)
        material_preview_model = getattr(current_preview, "preview_model", None)
        material_package_path = str(
            getattr(current_preview, "dotnet_preview_package_path", "") or ""
        ).strip()
        material_package_lease = (
            acquire_dotnet_preview_package_cache_lease_for_path(
                Path(material_package_path)
            )
            if material_package_path
            else None
        )
        material_companion_entry = self._find_archive_preview_companion_entry(entry)
        self._strip_archive_preview_heavy_payloads_for_mesh_editor(entry)
        self.mesh_editor_tab.open_archive_session(
            entry,
            material_preview_model=material_preview_model,
            material_companion_entry=material_companion_entry,
            material_package_path=material_package_path,
            material_package_lease=material_package_lease,
        )
        self._activate_tool_widget(self.mesh_editor_tab)
        self.set_status_message(f"Opening {entry.basename} directly in Mesh Editor.")

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
        self._set_last_active_operation(
            "mesh_replacement_modify_original",
            path=getattr(entry, "path", ""),
            package=str(getattr(entry, "pamt_path", "") or ""),
        )
        recorder = getattr(self, "_record_runtime_event", None)
        if callable(recorder):
            recorder(
                "mesh_editor_archive_open_requested",
                path=str(entry.path or ""),
                package=str(entry.pamt_path or ""),
                source="archive_browser",
                mode="modify_original",
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

    def _mesh_editor_rebuilt_asset_setup(self, output_path: object, *, action: str) -> Optional[MeshImportSetupSelection]:
        rebuilt_path = Path(output_path)
        if not rebuilt_path.is_file():
            self.set_status_message(f"Rebuilt mesh asset is missing: {rebuilt_path}", error=True)
            return None
        return MeshImportSetupSelection(
            scene_path=rebuilt_path,
            import_mode="static_replacement",
            source_label=f"Rebuilt asset: {rebuilt_path.name}",
            placement_review_title=f"{action} rebuilt asset",
            placement_context_note=f"{action} the Mesh Editor rebuilt asset through the existing archive workflow.",
        )

    def _mesh_editor_preview_rebuilt_asset_requested(self, entry: object, output_path: object) -> None:
        if not isinstance(entry, ArchiveEntry):
            self.set_status_message("Mesh Editor has no valid target mesh.", error=True)
            return
        setup = self._mesh_editor_rebuilt_asset_setup(output_path, action="Preview")
        if setup is None:
            return
        self._start_archive_mesh_import_preview(entry, preset_setup=setup)

    def _mesh_editor_package_rebuilt_asset_requested(self, entry: object, output_path: object) -> None:
        if not isinstance(entry, ArchiveEntry):
            self.set_status_message("Mesh Editor has no valid target mesh.", error=True)
            return
        setup = self._mesh_editor_rebuilt_asset_setup(output_path, action="Package")
        if setup is None:
            return
        self._start_archive_mesh_patch(entry, preset_setup=setup)

    def _mesh_editor_in_game_swap_requested(self, entry: object) -> None:
        if not isinstance(entry, ArchiveEntry):
            self.set_status_message("Mesh Editor has no valid target mesh.", error=True)
            return
        self._handle_archive_in_game_mesh_swap_entry(entry)
        if self.pending_in_game_mesh_swap_target is not None:
            # Armed, not fired: the source is picked in Archive Browser.
            self._show_archive_browser_from_texture_editor(entry.path)

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
        # The descriptor declares an element kind, never a drag gesture. Passing
        # it as the gesture is what reset a reader's Lasso to Brush the moment
        # they picked an edge tool.
        element_type = str(getattr(action, "element_type", "") or "").strip()
        routed = self._mesh_editor_route_active_builder_action(action)
        if routed is not False and hasattr(self, "mesh_editor_tab"):
            self.mesh_editor_tab.set_active_tool_state(
                mode=mode if command == "set_mode" else "",
                active_element_type=element_type,
                active_tool_key=key if command in {"brush", "select"} or key == "transform_move" else "",
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
