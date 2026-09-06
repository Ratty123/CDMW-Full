"""Mesh Editor bridge methods owned by the shell MainWindow."""

from __future__ import annotations

import copy
import hashlib
import json
from collections.abc import Mapping
from pathlib import Path
from typing import Optional, Sequence

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication, QDialog, QMessageBox, QWidget

from cdmw.domain.archives.filters import archive_entry_identity_key
from cdmw.domain.archives.constants import ARCHIVE_MESH_EXTENSIONS
from cdmw.domain.mesh.session import MeshImportSetupSelection
from cdmw.models import ArchiveEntry
from cdmw.services.mesh_workflow_service import SceneImportResult
from cdmw.services.mesh_rust_preview_cache import native_material_package_for_rust_preview
from cdmw.services.preview_rendering_service import (
    acquire_dotnet_preview_package_cache_lease_for_path,
)
from cdmw.ui.archive_browser.workflow_dependencies import (
    ArchiveWorkflowDependenciesUnavailable,
    archive_workflow_dependency_context,
)
from cdmw.ui.mesh_editor.replace_from_archive_flow import ReplaceFromArchiveFlowController
from cdmw.ui.mesh_editor.session import MeshEditorSessionRequest


def _exact_archive_identity_matches(declared_identity: object, entry, normalized_path, normalized_file_path) -> bool:
    identity = entry.identity
    expected_paz = normalized_file_path(entry.paz_file)
    if isinstance(declared_identity, Mapping):
        declared_path = normalized_path(
            declared_identity.get("normalized_path", "")
            or declared_identity.get("path", "")
        )
        declared_pamt = normalized_file_path(
            declared_identity.get("source_pamt", "")
            or declared_identity.get("pamt_path", "")
        )
        declared_paz = normalized_file_path(
            declared_identity.get("paz_file", "")
            or declared_identity.get("source_paz", "")
        )
        try:
            declared_paz_index = int(declared_identity["paz_index"])
            declared_offset = int(
                declared_identity.get(
                    "entry_offset",
                    declared_identity.get("offset"),
                )
            )
        except (KeyError, TypeError, ValueError, OverflowError):
            return False
        return bool(
            declared_path == identity.normalized_path
            and declared_pamt == identity.source_pamt
            and declared_paz == expected_paz
            and declared_paz_index == identity.paz_index
            and declared_offset == identity.entry_offset
        )

    raw = str(declared_identity or "").strip()
    if not raw:
        return False
    parts = raw.split("::")
    # Reference-preview packages retain this explicit archive identity.
    if len(parts) == 5:
        pamt, paz, offset, comp_size, source_path = parts
        try:
            return bool(
                normalized_file_path(pamt) == identity.source_pamt
                and normalized_file_path(paz) == expected_paz
                and int(offset) == identity.entry_offset
                and int(comp_size) == int(entry.comp_size)
                and normalized_path(source_path) == identity.normalized_path
            )
        except (TypeError, ValueError, OverflowError):
            return False
    # Archive Browser's durable Python-preview cache key begins with
    # the complete selected-entry identity before renderer settings.
    if len(parts) >= 12 and parts[6].startswith("quality:"):
        try:
            return bool(
                normalized_path(parts[0]) == identity.normalized_path
                and normalized_file_path(parts[1]) == identity.source_pamt
                and normalized_file_path(parts[3]) == expected_paz
                and int(parts[7]) == identity.entry_offset
                and int(parts[8]) == int(entry.comp_size)
                and int(parts[9]) == int(entry.orig_size)
                and int(parts[10]) == int(entry.flags)
                and int(parts[11]) == identity.paz_index
            )
        except (TypeError, ValueError, OverflowError):
            return False
    return False


class MeshEditorShellBridgeMixin:
    """Route shell/archive actions into Mesh Editor sessions."""
    def _export_current_archive_mesh(self, export_format: str) -> None:
        current_entry = self.archive._current_archive_mesh_entry()
        if current_entry is None:
            self.set_status_message("Select a supported archive mesh to export.", error=True)
            return
        self.archive._start_archive_mesh_export(current_entry, export_format)

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
        self.archive._strip_archive_preview_heavy_payloads_for_mesh_editor(entry)
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

    def _mesh_editor_selected_backend_is_rust(self) -> bool:
        """Compatibility query for callers that still name the retired selector."""

        return True

    @staticmethod
    def _mesh_editor_package_matches_archive_entry(
        package_path: Path,
        entry: ArchiveEntry,
    ) -> bool:
        package = Path(package_path)
        expected_path = entry.identity.normalized_path

        def normalized_path(value: object) -> str:
            return str(value or "").replace("\\", "/").strip().strip("/").casefold()

        def load_mapping(name: str) -> Mapping[str, object] | None:
            try:
                payload = json.loads((package / name).read_text(encoding="utf-8-sig"))
            except (OSError, TypeError, ValueError):
                return None
            return payload if isinstance(payload, Mapping) else None

        def load_path_mapping(path: Path) -> Mapping[str, object] | None:
            try:
                payload = json.loads(Path(path).read_text(encoding="utf-8-sig"))
            except (OSError, TypeError, ValueError):
                return None
            return payload if isinstance(payload, Mapping) else None

        def normalized_file_path(value: object) -> str:
            return str(value or "").replace("\\", "/").strip().casefold()

        def declared_identity_matches(declared_identity: object) -> bool:
            if not isinstance(declared_identity, Mapping):
                return False
            identity = entry.identity
            declared_identity_path = normalized_path(
                declared_identity.get("normalized_path", "")
                or declared_identity.get("path", "")
            )
            declared_pamt = normalized_file_path(
                declared_identity.get("source_pamt", "")
                or declared_identity.get("pamt_path", "")
            )
            if (
                not declared_identity_path
                or declared_identity_path != identity.normalized_path
                or not declared_pamt
                or declared_pamt != identity.source_pamt
                or "paz_index" not in declared_identity
            ):
                return False
            offset_key = (
                "entry_offset"
                if "entry_offset" in declared_identity
                else "offset"
                if "offset" in declared_identity
                else ""
            )
            if not offset_key:
                return False
            try:
                return bool(
                    int(declared_identity["paz_index"]) == identity.paz_index
                    and int(declared_identity[offset_key]) == identity.entry_offset
                )
            except (TypeError, ValueError, OverflowError):
                return False

        def cache_dependency_identity_matches(cache_metadata: object) -> bool:
            if not isinstance(cache_metadata, Mapping):
                return False
            diagnostics = cache_metadata.get("diagnostics")
            if not isinstance(diagnostics, Mapping):
                return False
            dependencies = diagnostics.get("cache_dependency_entries")
            if not isinstance(dependencies, Sequence) or isinstance(
                dependencies,
                (str, bytes, bytearray),
            ):
                return False
            return any(
                _exact_archive_identity_matches(dependency, entry, normalized_path, normalized_file_path)
                for dependency in dependencies
            )

        manifest_path = package / "manifest.json"
        if manifest_path.is_file():
            manifest = load_mapping("manifest.json")
            if manifest is None:
                return False
            if normalized_path(manifest.get("source_path", "")) != expected_path:
                return False
            if "source_identity" in manifest:
                return declared_identity_matches(manifest.get("source_identity"))
            return cache_dependency_identity_matches(
                load_path_mapping(package.parent / "cache_entry.json")
            )

        # Resident Vortice packages compiled from the Python preview model do
        # not retain preview-core's manifest.json.  Their public identity is
        # the source mesh named by net_materials.json; the launch manifest
        # binds that material payload and scene state into one package.
        launch = load_mapping("dotnet_launch.json")
        scene = load_mapping("dotnet_scene.json")
        materials = load_mapping("net_materials.json")
        if launch is None or scene is None or materials is None:
            return False
        launch_input = launch.get("input")
        if (
            launch.get("format") != "cdmw_mesh_dotnet_experiment_handoff_v1"
            or not isinstance(launch_input, Mapping)
            or normalized_path(launch_input.get("scene_state", "")) != "dotnet_scene.json"
            or normalized_path(launch_input.get("materials", "")) != "net_materials.json"
            or scene.get("renderer_authority") != "dotnet_vortice_resident_scene"
            or materials.get("renderer_authority") != "dotnet_mesh_editor"
        ):
            return False
        if normalized_path(materials.get("source_mesh", "")) != expected_path:
            return False
        scene_identity = scene.get("source_identity")
        cache_metadata = load_path_mapping(package.parent / "cache_entry.json")
        cache_identity = None
        if cache_metadata is not None:
            cache_identity = cache_metadata.get(
                "source_identity"
            ) or cache_metadata.get("archive_identity")
        if not (
            _exact_archive_identity_matches(scene_identity, entry, normalized_path, normalized_file_path)
            or _exact_archive_identity_matches(cache_identity, entry, normalized_path, normalized_file_path)
        ):
            return False
        launch_signature = str(launch_input.get("material_signature", "") or "").strip()
        material_signature = str(materials.get("material_signature", "") or "").strip()
        return bool(launch_signature) and launch_signature == material_signature

    def _mesh_editor_active_textured_package_for_entry(
        self,
        entry: ArchiveEntry,
    ) -> Path | None:
        package_path = getattr(
            self.archive,
            "archive_isolated_renderer_active_package",
            None,
        )
        has_textures = getattr(self.archive, "_archive_active_package_has_textures", None)
        if package_path is None or not callable(has_textures):
            return None
        try:
            package = Path(package_path)
            if not bool(has_textures()):
                return None
            package = native_material_package_for_rust_preview(package) or package
        except (OSError, RuntimeError, TypeError, ValueError):
            return None
        return (
            package
            if self._mesh_editor_package_matches_archive_entry(package, entry)
            else None
        )

    def _defer_rust_mesh_editor_for_archive_textures(
        self,
        entry: ArchiveEntry,
    ) -> bool:
        """Wait for Archive Browser's exact native material package before Rust."""
        identity = archive_entry_identity_key(entry)
        if getattr(self, "_mesh_editor_rust_texture_bypass_identity", None) == identity:
            self._mesh_editor_rust_texture_bypass_identity = None
            return False
        if self._mesh_editor_active_textured_package_for_entry(entry) is not None:
            return False

        pending = getattr(self, "_mesh_editor_pending_rust_texture_launch", None)
        if isinstance(pending, Mapping):
            if (
                pending.get("identity") == identity
                and int(pending.get("request_id", 0) or 0)
                == int(getattr(self.archive, "_archive_texture_request_id", 0) or 0)
                and bool(getattr(self.archive, "_archive_texture_request_loading", False))
            ):
                return True
            self._mesh_editor_pending_rust_texture_launch = None

        current_entry = getattr(self.archive, "_current_archive_entry", lambda: None)()
        if not isinstance(current_entry, ArchiveEntry) or current_entry.identity != identity:
            return False
        request_textures = getattr(self.archive, "_request_archive_preview_textures", None)
        if not callable(request_textures):
            return False
        request_textures(automatic=True)
        request_id = int(getattr(self.archive, "_archive_texture_request_id", 0) or 0)
        if not request_id or not bool(
            getattr(self.archive, "_archive_texture_request_loading", False)
        ):
            return False
        generation = int(
            getattr(self, "_mesh_editor_rust_texture_launch_generation", 0) or 0
        ) + 1
        self._mesh_editor_rust_texture_launch_generation = generation
        self._mesh_editor_pending_rust_texture_launch = {
            "generation": generation,
            "request_id": request_id,
            "identity": identity,
            "entry": copy.deepcopy(entry),
        }
        self.set_status_message(
            "Resolving this mesh's textures before Mesh Editor opens..."
        )
        return True

    def _finish_pending_rust_mesh_editor_texture_launch(
        self,
        *,
        request_id: int,
        success: bool,
        message: str = "",
    ) -> None:
        failure_reason = str(message or "").strip()
        pending = getattr(self, "_mesh_editor_pending_rust_texture_launch", None)
        if not isinstance(pending, Mapping):
            return
        if int(pending.get("request_id", 0) or 0) != int(request_id or 0):
            return
        generation = int(pending.get("generation", 0) or 0)
        if generation != int(
            getattr(self, "_mesh_editor_rust_texture_launch_generation", 0) or 0
        ):
            return
        self._mesh_editor_pending_rust_texture_launch = None
        if bool(getattr(self, "_shutting_down", False)):
            return
        entry = pending.get("entry")
        identity = pending.get("identity")
        current_entry = getattr(self.archive, "_current_archive_entry", lambda: None)()
        if (
            not isinstance(entry, ArchiveEntry)
            or not isinstance(current_entry, ArchiveEntry)
            or current_entry.identity != identity
        ):
            return
        textured_package = self._mesh_editor_active_textured_package_for_entry(entry)
        failed = not bool(success) or textured_package is None
        if failed:
            self._mesh_editor_rust_texture_bypass_identity = identity
        self._launch_archive_mesh_editor_for_entry(entry)
        if failed and failure_reason:
            tab = getattr(self, "mesh_editor_tab", None)
            if tab is not None:
                tab.standalone_rust_texture_unavailable_reason = failure_reason
            self.set_status_message(
                "Texture loading failed; the untextured model remains available: "
                f"{failure_reason}",
                error=True,
            )

    def _refresh_active_rust_material_context_from_archive(
        self,
        entry: ArchiveEntry,
    ) -> bool:
        tab = getattr(self, "mesh_editor_tab", None)
        replace_lease = getattr(
            tab,
            "_replace_archive_material_context_package_lease",
            None,
        )
        package = self._mesh_editor_active_textured_package_for_entry(entry)
        if package is None or not callable(replace_lease):
            return False
        material_source_identity = getattr(
            tab, "archive_material_context_source_identity", None
        )
        if material_source_identity != entry.identity:
            tab.archive_material_context_verified_for_rust = False
            return False
        lease = acquire_dotnet_preview_package_cache_lease_for_path(package)
        if lease is None:
            return False
        try:
            replace_lease(lease)
            tab.archive_material_context_package_path = str(package)
            preview_model = getattr(
                tab,
                "standalone_archive_material_preview_model",
                None,
            )
            model_ready = getattr(
                tab,
                "_archive_material_preview_model_ready",
                None,
            )
            tab.archive_material_context_verified_for_rust = bool(
                callable(model_ready) and model_ready(preview_model)
            )
            tab.standalone_rust_texture_unavailable_reason = ""
        except RuntimeError:
            release = getattr(lease, "release", None)
            if callable(release):
                release()
            return False
        return True

    def _relaunch_idle_rust_editor_for_active_session(
        self,
        entry: ArchiveEntry | None = None,
    ) -> bool:
        """Redispatch an exited Rust child without replacing its edit session."""
        tab = getattr(self, "mesh_editor_tab", None)
        controller = getattr(tab, "standalone_controller", None)
        rust_task_active = getattr(tab, "_rust_editor_task_active", None)
        launch_selected = getattr(tab, "_start_selected_mesh_editor", None)
        if (
            controller is None
            or not callable(rust_task_active)
            or not callable(launch_selected)
        ):
            return False
        try:
            if bool(rust_task_active()):
                queue_relaunch = getattr(
                    tab,
                    "_queue_rust_relaunch_after_dispose",
                    None,
                )
                if callable(queue_relaunch) and bool(queue_relaunch(controller)):
                    if isinstance(entry, ArchiveEntry):
                        self._refresh_active_rust_material_context_from_archive(entry)
                    self.set_status_message("Launching Mesh Editor...")
                    return True
                return False
        except RuntimeError:
            return False
        if isinstance(entry, ArchiveEntry):
            self._refresh_active_rust_material_context_from_archive(entry)
        self.set_status_message("Launching Mesh Editor...")
        launch_selected(controller)
        return True

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
                if self._relaunch_idle_rust_editor_for_active_session(entry):
                    return False
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
        tab = getattr(self, "mesh_editor_tab", None)
        preflight = getattr(tab, "_rust_open_preflight_reason", None)
        if callable(preflight):
            try:
                preflight_reason = str(preflight() or "").strip()
            except RuntimeError as exc:
                preflight_reason = str(exc or "Mesh Editor preflight failed").strip()
            if preflight_reason:
                sync_controls = getattr(tab, "_sync_mesh_editor_backend_controls", None)
                if callable(sync_controls):
                    sync_controls()
                self._activate_tool_widget(tab)
                self.set_status_message(
                    f"Mesh Editor cannot open: {preflight_reason}.",
                    error=True,
                )
                return
        if self._defer_rust_mesh_editor_for_archive_textures(entry):
            return
        archive_dependencies = None
        remote_bridge = getattr(self.archive, "archive_remote_bridge", None)
        if remote_bridge is not None and bool(getattr(remote_bridge, "displays_v2", False)):
            try:
                archive_dependencies = archive_workflow_dependency_context(self, entry)
            except ArchiveWorkflowDependenciesUnavailable as exc:
                self.set_status_message(str(exc), error=True)
                return
            entry = archive_dependencies.selected_entry
        if not self._prepare_mesh_editor_archive_launch(entry):
            return
        current_preview = getattr(self.archive, "current_archive_preview_result", None)
        material_preview_model = getattr(current_preview, "preview_model", None)
        current_entry_getter = getattr(self.archive, "_current_archive_entry", None)
        current_preview_entry = (
            current_entry_getter() if callable(current_entry_getter) else entry
        )
        preview_matches_entry = bool(
            isinstance(current_preview_entry, ArchiveEntry)
            and archive_entry_identity_key(current_preview_entry)
            == archive_entry_identity_key(entry)
        )
        if not preview_matches_entry:
            material_preview_model = None
        material_package_path = str(
            getattr(current_preview, "dotnet_preview_package_path", "") or ""
        ).strip()
        if not preview_matches_entry:
            material_package_path = ""
        material_source_identity = (
            entry.identity if material_preview_model is not None else None
        )
        material_context_verified_for_rust = False
        textured_package = self._mesh_editor_active_textured_package_for_entry(entry)
        if textured_package is not None:
            # Keep the Archive Browser's resolved PAC/PAC_XML material model.
            # The native package owns the immutable DDS lease, while rebuilding
            # from flattened batch rows would drop dye/layer parameters.
            material_package_path = str(textured_package)
            material_context_verified_for_rust = bool(
                material_preview_model is not None
                and material_source_identity == entry.identity
            )
        material_package_lease = (
            acquire_dotnet_preview_package_cache_lease_for_path(
                Path(material_package_path)
            )
            if material_package_path
            else None
        )
        material_companion_entry = self.archive._find_archive_preview_companion_entry(entry)
        self.archive._strip_archive_preview_heavy_payloads_for_mesh_editor(entry)
        self.mesh_editor_tab.open_archive_session(
            entry,
            material_preview_model=material_preview_model,
            material_companion_entry=material_companion_entry,
            material_package_path=material_package_path,
            material_package_lease=material_package_lease,
            material_context_verified_for_rust=material_context_verified_for_rust,
            material_source_identity=material_source_identity,
            archive_dependencies=archive_dependencies,
        )
        self._activate_tool_widget(self.mesh_editor_tab)
        self.set_status_message(f"Opening {entry.basename} directly in Mesh Editor.")

    def _open_current_archive_mesh_editor(self) -> None:
        current_entry = self.archive._current_archive_mesh_entry()
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
        QTimer.singleShot(0, lambda current_entry=entry: self.archive._start_archive_modify_original_workspace(current_entry))

    def _mesh_editor_import_replacement_requested(self, entry: object) -> None:
        if not isinstance(entry, ArchiveEntry):
            self.set_status_message("Mesh Editor has no valid target mesh.", error=True)
            return
        self._open_mesh_editor_for_entry(entry, mode="external_import", activate=True)
        self.archive._start_archive_mesh_patch(entry)

    def _mesh_editor_import_preview_requested(self, entry: object) -> None:
        if not isinstance(entry, ArchiveEntry):
            self.set_status_message("Mesh Editor has no valid target mesh.", error=True)
            return
        self._open_mesh_editor_for_entry(entry, mode="external_import", activate=True)
        self.archive._start_archive_mesh_import_preview(entry)

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
        self.archive._start_archive_mesh_import_preview(entry, preset_setup=setup)

    def _mesh_editor_package_rebuilt_asset_requested(self, entry: object, output_path: object) -> None:
        if not isinstance(entry, ArchiveEntry):
            self.set_status_message("Mesh Editor has no valid target mesh.", error=True)
            return
        setup = self._mesh_editor_rebuilt_asset_setup(output_path, action="Package")
        if setup is None:
            return
        self.archive._start_archive_mesh_patch(entry, preset_setup=setup)

    def _mesh_editor_in_game_swap_requested(self, entry: object) -> None:
        """Compatibility entry point for the retired target-arming swap surface."""

        self._mesh_editor_replace_from_archive_requested(entry)

    def _mesh_editor_replace_from_archive_requested(self, entry: object) -> None:
        if not isinstance(entry, ArchiveEntry):
            self.set_status_message("Mesh Editor has no valid target mesh.", error=True)
            return
        controller = getattr(self, "_replace_from_archive_flow_controller", None)
        if not isinstance(controller, ReplaceFromArchiveFlowController):
            controller = ReplaceFromArchiveFlowController(self)
            self._replace_from_archive_flow_controller = controller
        controller.start(entry)

    def _mesh_editor_show_archive_target_requested(self, entry: object) -> None:
        if not isinstance(entry, ArchiveEntry):
            return
        self.textures._show_archive_browser_from_texture_editor(entry.path)

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
        current_entry = self.archive._current_archive_mesh_entry()
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
            lambda current_entry=current_entry: self.archive._start_archive_modify_original_workspace(current_entry),
        )

__all__ = ["MeshEditorShellBridgeMixin"]
