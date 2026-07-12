from __future__ import annotations

import shutil
from pathlib import Path

from PySide6.QtCore import QThread



from cdmw.ui.mesh_editor.tab_compat import facade_globals as _tab


class MeshEditorNativePreviewMixin:
    def write_standalone_native_preview_package(self, output_root: Path | None = None) -> Path:
        controller = self.standalone_controller
        if controller is None:
            raise RuntimeError("Mesh Editor has no standalone edit session.")
        display_mode = "original_only" if self.standalone_compare_mode == "source" else ("overlay" if self.standalone_compare_mode == "ghost" else "replacement_only")
        pose_native_context = self._standalone_pose_native_preview_context()
        if pose_native_context is not None:
            mesh, pose_skeleton, pose_rotations = pose_native_context
            reference_mesh = None
            prepared = _tab.mesh_pose_to_native_preview(
                mesh,
                skeleton=pose_skeleton,
                pose_rotations=pose_rotations,
            )
            package_dir = _tab.mesh_editor_write_prepared_native_preview_package(
                mesh,
                prepared,
                output_root=output_root,
                display_mode=display_mode,
                skeleton_overlay=controller.skeleton_overlay_data(),
                use_textures=True,
                high_quality_textures=True,
            )
        else:
            mesh = self._standalone_preview_mesh_snapshot()
            reference_mesh = self._standalone_reference_mesh_snapshot()
            package_dir = _tab.mesh_editor_write_native_preview_package(
                mesh,
                reference_mesh=reference_mesh,
                output_root=output_root,
                display_mode=display_mode,
                skeleton_overlay=controller.skeleton_overlay_data(),
                use_textures=True,
                high_quality_textures=True,
            )
        self.standalone_native_package_dir = package_dir
        self.standalone_native_status_file = package_dir / "host_status.json"
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
            self._reset_standalone_native_status_tracking()
            self.standalone_native_status_timer.start()
            if host is getattr(self, "standalone_native_host_frame", None):
                self.standalone_preview_stack.setCurrentWidget(self.standalone_native_host_frame)
            self._request_standalone_native_part_picking(True, retries=3)
            self._sync_standalone_native_mesh_edit_state(force=True)
            self.standalone_status_label.setText(f"Native D3D11 preview loading: {package_path}")
        return ok
    def _launch_standalone_native_preview_package(self, package_dir: Path, *, reset_view: bool = True) -> bool:
        package_dir = Path(package_dir)
        status_file = package_dir / "host_status.json"
        self.standalone_native_package_dir = package_dir
        self.standalone_native_status_file = status_file
        try:
            status_file.unlink(missing_ok=True)
        except OSError:
            pass
        if self._standalone_native_process_running():
            if self.load_standalone_native_preview_package(package_dir, status_file, reset_view=reset_view):
                return True
            self._stop_standalone_native_preview_process()
        host = self.standalone_native_host or getattr(self, "standalone_native_host_frame", None)
        try:
            program, arguments = _tab.mesh_editor_native_preview_command(package_dir, status_file, host_widget=host)
        except Exception as exc:
            self.standalone_status_label.setText(f"Native D3D11 preview unavailable: {exc}")
            self.status_message_requested.emit(f"Native D3D11 preview unavailable: {exc}", True)
            return False
        process = _tab.QProcess(self)
        self.standalone_native_stdout_tail = ""
        self.standalone_native_stderr_tail = ""
        process.setProgram(program)
        process.setArguments(arguments)
        try:
            process.setWorkingDirectory(str(Path(__file__).resolve().parents[3]))
        except (OSError, RuntimeError):
            # Best effort: QProcess can still start with its inherited working directory.
            pass
        process.setProcessChannelMode(_tab.QProcess.SeparateChannels)
        try:
            process.finished.connect(lambda *_args, target=process: self._handle_standalone_native_preview_finished(target))
            process.errorOccurred.connect(lambda _error, target=process: self._handle_standalone_native_preview_error(target))
            process.readyReadStandardOutput.connect(
                lambda target=process: self._handle_standalone_native_process_stream(target, stderr=False)
            )
            process.readyReadStandardError.connect(
                lambda target=process: self._handle_standalone_native_process_stream(target, stderr=True)
            )
        except (AttributeError, RuntimeError, TypeError):
            pass
        self.standalone_native_process = process
        track_process = getattr(host, "track_renderer_process", None)
        if callable(track_process):
            track_process(process)
        if host is getattr(self, "standalone_native_host_frame", None):
            self.standalone_preview_stack.setCurrentWidget(self.standalone_native_host_frame)
        self.standalone_status_label.setText(f"Native D3D11 preview launching: {package_dir}")
        self._reset_standalone_native_status_tracking()
        self.standalone_native_status_timer.start()
        process.start()
        self._request_standalone_native_part_picking(True, retries=3)
        self._sync_standalone_native_mesh_edit_state(force=True)
        return True
    def start_standalone_native_preview(self, output_root: Path | None = None, *, reset_view: bool = True) -> bool:
        del output_root, reset_view
        self.status_message_requested.emit(
            "Legacy native Mesh Editor preview is disabled; the .NET/Vortice viewport is authoritative.",
            True,
        )
        return False
    def start_standalone_native_preview_async(self, output_root: Path | None = None, *, reset_view: bool = True) -> bool:
        del output_root, reset_view
        self.status_message_requested.emit(
            "Legacy native Mesh Editor preview is disabled; the .NET/Vortice viewport is authoritative.",
            True,
        )
        return False

    def _handle_standalone_native_package_ready(self, request_id: int, package_dir_object: object, elapsed_ms: float) -> None:
        try:
            package_dir = Path(package_dir_object)
        except TypeError:
            return
        if int(request_id) != int(self.standalone_native_package_request_id):
            shutil.rmtree(package_dir, ignore_errors=True)
            return
        if not self.has_active_standalone_session():
            shutil.rmtree(package_dir, ignore_errors=True)
            return
        if self._launch_standalone_native_preview_package(
            package_dir,
            reset_view=self.standalone_native_package_reset_view,
        ):
            self.standalone_native_package_has_reference = bool(self.standalone_native_package_pending_has_reference)
            self.standalone_native_package_compare_mode = self.standalone_native_package_pending_compare_mode
            self.status_message_requested.emit(f"Native D3D11 preview started after package build ({float(elapsed_ms):.1f} ms).", False)
    def _handle_standalone_native_package_error(self, request_id: int, message: str) -> None:
        if int(request_id) != int(self.standalone_native_package_request_id):
            return
        self.standalone_status_label.setText(f"Native D3D11 preview package failed: {message}")
        self.status_message_requested.emit(f"Native D3D11 preview package failed: {message}", True)
    def _cleanup_standalone_native_package_worker(
        self,
        thread: QThread,
        worker: _tab.MeshNativePreviewPackageWorker,
    ) -> None:
        if self.standalone_native_package_thread is thread:
            self.standalone_native_package_thread = None
        if self.standalone_native_package_worker is worker:
            self.standalone_native_package_worker = None
    def _cancel_standalone_native_package_worker(self) -> None:
        worker = self.standalone_native_package_worker
        thread = self.standalone_native_package_thread
        if worker is None and thread is None:
            return
        self.standalone_native_package_request_id += 1
        if worker is not None:
            try:
                worker.stop()
            except RuntimeError:
                pass
        if thread is not None:
            try:
                thread.requestInterruption()
                thread.quit()
            except RuntimeError:
                pass
    def _standalone_editable_package_task_active(self) -> bool:
        return (
            self.standalone_editable_export_thread is not None
            or self.standalone_editable_export_worker is not None
            or self.standalone_editable_import_thread is not None
            or self.standalone_editable_import_worker is not None
        )
