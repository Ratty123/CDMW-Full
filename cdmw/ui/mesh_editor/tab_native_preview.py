from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QProcess

from cdmw.services.mesh_rust_preview_package import build_rust_preview_package

from cdmw.ui.mesh_editor.tab_compat import facade_globals as _tab


class MeshEditorNativePreviewMixin:
    def write_standalone_native_preview_package(self, output_root: Path | None = None) -> Path:
        controller = self.standalone_controller
        if controller is None:
            raise RuntimeError("Mesh Editor has no standalone edit session.")
        display_mode = "original_only" if self.standalone_compare_mode == "source" else ("overlay" if self.standalone_compare_mode == "ghost" else "replacement_only")
        mesh = self._standalone_preview_mesh_snapshot()
        reference_mesh = self._standalone_reference_mesh_snapshot()
        package = build_rust_preview_package(
            mesh,
            output_root=output_root,
            reference_mesh=reference_mesh,
            comparison_mode=display_mode,
            interaction_profile="static_replacement",
            scene_session_id=controller.session_view().session_id,
        )
        package_dir = package.package_dir
        self.standalone_native_package_dir = package_dir
        self.standalone_native_status_file = package.status_path
        self.standalone_native_package_has_reference = reference_mesh is not None
        self.standalone_native_package_pending_has_reference = reference_mesh is not None
        self.standalone_native_package_compare_mode = self.standalone_compare_mode
        self.standalone_native_package_pending_compare_mode = self.standalone_compare_mode
        return package_dir
    def load_standalone_native_preview_package(
        self,
        package_dir: Path | None = None,
        status_file: Path | None = None,
        *,
        reset_view: bool = True,
    ) -> bool:
        host = self.standalone_native_host
        loader = getattr(host, "load_package", None)
        if not callable(loader):
            return False
        selected_package = package_dir or self.standalone_native_package_dir
        if selected_package is None:
            return False
        package_path = Path(selected_package)
        status_path = Path(status_file or self.standalone_native_status_file or package_path / "host_status.json")
        ok = bool(loader(package_path, status_path, reset_view=bool(reset_view)))
        if ok:
            self.standalone_native_package_dir = package_path
            self.standalone_native_status_file = status_path
            if host is getattr(self, "standalone_native_host_frame", None):
                self.standalone_preview_stack.setCurrentWidget(self.standalone_native_host_frame)
            self._request_standalone_native_part_picking(False)
            self._sync_standalone_native_mesh_edit_state(force=True)
            self.standalone_status_label.setText(f"Rust preview loading: {package_path}")
        return ok
    def _launch_standalone_native_preview_package(self, package_dir: Path, *, reset_view: bool = True) -> bool:
        return self.load_standalone_native_preview_package(package_dir, reset_view=reset_view)
    def start_standalone_native_preview(self, output_root: Path | None = None, *, reset_view: bool = True) -> bool:
        return self.start_standalone_native_preview_async(output_root, reset_view=reset_view)
    def start_standalone_native_preview_async(self, output_root: Path | None = None, *, reset_view: bool = True) -> bool:
        del output_root, reset_view
        if self.standalone_controller is None:
            return False
        process = getattr(self, "standalone_rust_process", None)
        if process is not None and process.state() != QProcess.ProcessState.NotRunning:
            return True
        self._start_rust_editor_requested(self.standalone_controller)
        return True
    def _standalone_editable_package_task_active(self) -> bool:
        return (
            self.standalone_editable_export_thread is not None
            or self.standalone_editable_export_worker is not None
            or self.standalone_editable_import_thread is not None
            or self.standalone_editable_import_worker is not None
        )
