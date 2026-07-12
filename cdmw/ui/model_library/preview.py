"""Inline preview and icon generation for Model Library."""

from __future__ import annotations

import json
import os
import re
import threading
import time
from pathlib import Path
from typing import Callable, Optional

from PySide6.QtCore import QProcess, Qt, QTimer
from PySide6.QtGui import QImage

from cdmw.constants import MODEL_PREVIEW_BACKGROUND_COLOR, MODEL_PREVIEW_TEXT_COLOR
from cdmw.domain.library.models import is_importable_model_path
from cdmw.services.model_library_preview import (
    prepare_model_library_inline_preview,
)
from cdmw.services.workspace_layout import workspace_paths
from cdmw.ui.model_library.icon_output import ModelLibraryIconOutputMixin
from cdmw.ui.native_d3d11_preview_host import native_d3d11_renderer_command
from cdmw.workers.model_library_workers import (
    prepare_model_library_preview_icon,
    remove_model_library_preview_package_dir,
)


class ModelLibraryInlinePreviewMixin(ModelLibraryIconOutputMixin):
    """Manage inline Model Library previews and generated icon captures."""

    def _record_model_library_preview_event(self, event: str, **fields: object) -> None:
        recorder = getattr(self, "_record_runtime_event", None)
        if not callable(recorder):
            return
        try:
            recorder(event, **fields)
        except Exception:
            pass

    def preview_selected_model_here(self) -> None:
        payload = self._selected_payload()
        if not payload:
            self._set_inline_preview_status("Select a model first.", error=True)
            return
        def resolved(source_path: Path) -> None:
            self._load_inline_model_preview(source_path, payload)

        def missing() -> None:
            if payload.get("kind") == "mirror":
                self._set_inline_preview_status("Download this mirror model first, then Preview Here.", error=True)
            else:
                self._set_inline_preview_status("This local item is not an importable model or ZIP.", error=True)

        self._request_payload_import_path(
            payload,
            status="Resolving model for inline preview...",
            on_resolved=resolved,
            on_missing=missing,
        )

    def _inline_preview_renderer_backend(self) -> str:
        return "native_d3d11"

    def _inline_d3d11_theme_payload(self) -> dict[str, str]:
        return {
            "background": MODEL_PREVIEW_BACKGROUND_COLOR,
            "text": MODEL_PREVIEW_TEXT_COLOR,
        }

    def _inline_d3d11_process_running(self) -> bool:
        process = self._inline_d3d11_process
        try:
            return process is not None and process.state() != QProcess.NotRunning
        except RuntimeError:
            return False

    def _start_inline_d3d11_status_timer(self) -> None:
        try:
            self._inline_d3d11_status_timer.start()
        except RuntimeError:
            pass

    def _stop_inline_d3d11_status_timer(self) -> None:
        try:
            self._inline_d3d11_status_timer.stop()
        except RuntimeError:
            pass

    def _inline_d3d11_diagnostic_paths(self) -> tuple[Path, Path]:
        crash_dir = Path(
            os.environ.get("CDMW_CRASH_DIR", "")
            or workspace_paths(self.base_dir)["crash_reports_dir"]
        )
        diagnostic_log = Path(
            os.environ.get("CDMW_NATIVE_DIAGNOSTIC_LOG", "")
            or crash_dir / "native_events_current.jsonl"
        )
        return crash_dir, diagnostic_log

    def _remove_inline_d3d11_package_dir(self, package_dir: Optional[Path]) -> None:
        remove_model_library_preview_package_dir(package_dir)

    def _cleanup_inline_d3d11_packages(self, *, include_active: bool = False) -> None:
        packages = list(getattr(self, "_inline_d3d11_retired_packages", []) or [])
        self._inline_d3d11_retired_packages = []
        if include_active and self._inline_d3d11_active_package is not None:
            packages.append(Path(self._inline_d3d11_active_package))
            self._inline_d3d11_active_package = None
            self._inline_d3d11_status_file = None
            self._inline_d3d11_status_mtime = 0.0
            self._inline_d3d11_status_request_id = 0
        for package_dir in packages:
            self._remove_inline_d3d11_package_dir(package_dir)

    def _start_inline_d3d11_process(self, package_dir: Path, *, render_settings: object) -> bool:
        package_dir = Path(package_dir)
        status_file = package_dir / "host_status.json"
        try:
            status_file.unlink(missing_ok=True)
        except OSError:
            pass
        previous_package = self._inline_d3d11_active_package
        reuse_process = self._inline_d3d11_process_running()
        self._record_model_library_preview_event(
            "model_library_d3d11_start",
            package_dir=str(package_dir),
            status_file=str(status_file),
            reuse_process=bool(reuse_process),
        )
        if previous_package is not None and Path(previous_package) != package_dir:
            self._inline_d3d11_retired_packages.append(Path(previous_package))
        self._inline_d3d11_active_package = package_dir
        self._inline_d3d11_status_file = status_file
        self._inline_d3d11_status_mtime = 0.0
        self._inline_d3d11_status_request_id = int(self._inline_preview_request_id)
        if reuse_process:
            if self.inline_d3d11_preview_host.load_package(package_dir, status_file, reset_view=True):
                self.inline_d3d11_preview_host.set_render_tuning(render_settings)
                self._start_inline_d3d11_status_timer()
                return True
            self._stop_inline_d3d11_process(cleanup_packages=True)
        self.inline_d3d11_preview_host.setAttribute(Qt.WidgetAttribute.WA_NativeWindow, True)
        self.inline_d3d11_preview_host.show()
        self.inline_d3d11_preview_host.update()
        try:
            crash_dir, diagnostic_log = self._inline_d3d11_diagnostic_paths()
            program, arguments = native_d3d11_renderer_command(
                package_dir,
                status_file,
                host_widget=self.inline_d3d11_preview_host,
                theme_payload=self._inline_d3d11_theme_payload(),
                crash_dir=crash_dir,
                diagnostic_log=diagnostic_log,
            )
        except Exception as exc:
            self._set_inline_preview_status(f"Native D3D11 preview unavailable: {exc}", error=True)
            self._cleanup_inline_d3d11_packages(include_active=True)
            return False
        process = QProcess(self)
        process.setProgram(program)
        process.setArguments(arguments)
        try:
            process.setWorkingDirectory(str(Path(__file__).resolve().parents[3]))
        except Exception:
            pass
        process.setProcessChannelMode(QProcess.SeparateChannels)
        process.started.connect(lambda: self._record_model_library_preview_event("model_library_d3d11_process_started"))
        process.readyReadStandardError.connect(lambda process=process: self._handle_inline_d3d11_stderr(process))
        process.finished.connect(lambda exit_code, _exit_status, process=process: self._handle_inline_d3d11_finished(process, exit_code))
        process.errorOccurred.connect(lambda error, process=process: self._handle_inline_d3d11_error(process, error))
        self._inline_d3d11_process = process
        self._start_inline_d3d11_status_timer()
        self._record_model_library_preview_event(
            "model_library_d3d11_process_configured",
            program=program,
            arguments=list(arguments),
            package_dir=str(package_dir),
            status_file=str(status_file),
        )
        process.start()
        QTimer.singleShot(10000, lambda expected_status=status_file, process=process: self._check_inline_d3d11_start_timeout(expected_status, process))
        return True

    def _check_inline_d3d11_start_timeout(self, expected_status: Path, process: QProcess) -> None:
        if self._inline_d3d11_status_file != expected_status or process is not self._inline_d3d11_process:
            return
        if expected_status.is_file():
            return
        if not self._inline_d3d11_process_running():
            self._set_inline_preview_status("Native D3D11 renderer did not start.", error=True)
            self._record_model_library_preview_event("model_library_d3d11_start_failed", status_file=str(expected_status))
            self._stop_inline_d3d11_process(cleanup_packages=True)
            return
        self._set_inline_preview_status("Native D3D11 renderer did not start in time.", error=True)
        self._record_model_library_preview_event("model_library_d3d11_start_timeout", status_file=str(expected_status))
        self._stop_inline_d3d11_process(cleanup_packages=True)

    def _handle_inline_d3d11_stderr(self, process: QProcess) -> None:
        if process is not self._inline_d3d11_process:
            return
        try:
            message = bytes(process.readAllStandardError()).decode("utf-8", errors="replace").strip()
        except RuntimeError:
            return
        if message:
            self._set_inline_preview_status(f"Native D3D11 preview stderr: {message[-600:]}", error=True)

    def _handle_inline_d3d11_error(self, process: QProcess, error: object) -> None:
        if process is self._inline_d3d11_process:
            self._inline_d3d11_process = None
            self._stop_inline_d3d11_status_timer()
            self._set_inline_preview_status(f"Native D3D11 preview process error: {error}", error=True)
            self._record_model_library_preview_event("model_library_d3d11_error", error=str(error))
            self._cleanup_inline_d3d11_packages(include_active=True)
            try:
                process.deleteLater()
            except RuntimeError:
                pass

    def _handle_inline_d3d11_finished(self, process: QProcess, exit_code: int = 0) -> None:
        if process is self._inline_d3d11_process:
            self._inline_d3d11_process = None
            self._stop_inline_d3d11_status_timer()
            if int(exit_code) != 0:
                self._set_inline_preview_status(f"Native D3D11 preview exited with code {int(exit_code)}.", error=True)
            self._record_model_library_preview_event("model_library_d3d11_finished", exit_code=int(exit_code))
            self._cleanup_inline_d3d11_packages(include_active=True)

    def _poll_inline_d3d11_status(self) -> None:
        status_file = self._inline_d3d11_status_file
        if status_file is None:
            return
        if int(self._inline_d3d11_status_request_id) != int(self._inline_preview_request_id):
            return
        try:
            stat = status_file.stat()
        except OSError:
            return
        mtime = float(getattr(stat, "st_mtime", 0.0) or 0.0)
        if mtime <= float(self._inline_d3d11_status_mtime):
            return
        self._inline_d3d11_status_mtime = mtime
        try:
            payload = json.loads(status_file.read_text(encoding="utf-8"))
        except Exception:
            return
        if not isinstance(payload, dict):
            return
        event = str(payload.get("event", "") or "").strip().lower()
        if event == "resources_loaded":
            # A reused renderer cannot draw its first frame while this host is
            # hidden behind the preparation page. Reveal it once GPU resources
            # are resident; the subsequent first frame publishes ``loaded``.
            self.inline_preview_stack.setCurrentWidget(self.inline_d3d11_preview_host)
            self._set_inline_preview_status("Native D3D11 resources loaded; drawing first frame...")
            self._record_model_library_preview_event("model_library_d3d11_resources_loaded")
            return
        if event == "loaded":
            batch_count = int(payload.get("batch_count", 0) or 0)
            vertex_count = int(payload.get("vertex_count", 0) or 0)
            native_manifest_ms = float(payload.get("native_manifest_ms", 0.0) or 0.0)
            native_geometry_ms = float(payload.get("native_geometry_ms", 0.0) or 0.0)
            native_texture_ms = float(payload.get("native_texture_ms", 0.0) or 0.0)
            first_frame_ms = float(payload.get("first_frame_ms", 0.0) or 0.0)
            png_fallback = int(payload.get("png_fallback", 0) or 0)
            texture_cache_hits = int(payload.get("texture_cache_hits", 0) or 0)
            texture_failures = int(payload.get("texture_failures", 0) or 0)
            self._cleanup_inline_d3d11_packages(include_active=False)
            self.inline_preview_stack.setCurrentWidget(self.inline_d3d11_preview_host)
            self._set_inline_preview_status(
                f"Native D3D11 Model Library preview ready: {batch_count:,} batch(es), {vertex_count:,} vertices "
                f"| load manifest {native_manifest_ms:.1f} ms, geometry {native_geometry_ms:.1f} ms, "
                f"textures {native_texture_ms:.1f} ms, first frame {first_frame_ms:.1f} ms, "
                f"PNG fallback {png_fallback}, cache hits {texture_cache_hits}."
            )
            self._record_model_library_preview_event(
                "model_library_d3d11_loaded",
                batch_count=batch_count,
                vertex_count=vertex_count,
                native_manifest_ms=native_manifest_ms,
                native_geometry_ms=native_geometry_ms,
                native_texture_ms=native_texture_ms,
                first_frame_ms=first_frame_ms,
                png_fallback=png_fallback,
                texture_cache_hits=texture_cache_hits,
                texture_failures=texture_failures,
            )
            if int(self._pending_icon_generation_request_id) == int(self._inline_preview_request_id):
                self._pending_icon_generation_request_id = 0
                QTimer.singleShot(180, self._capture_inline_preview_icon)
        elif event == "error":
            self._set_inline_preview_status(str(payload.get("message", "Native D3D11 preview failed.") or ""), error=True)
            self._record_model_library_preview_event(
                "model_library_d3d11_status_error",
                message=str(payload.get("message", "") or ""),
            )
            self._stop_inline_d3d11_process(cleanup_packages=True)

    def _stop_inline_d3d11_process(
        self,
        *,
        cleanup_packages: bool = False,
    ) -> None:
        process = self._inline_d3d11_process
        active_package = self._inline_d3d11_active_package if cleanup_packages else None
        self._inline_d3d11_process = None
        self._stop_inline_d3d11_status_timer()
        if cleanup_packages:
            self._cleanup_inline_d3d11_packages(include_active=True)
        if process is None:
            return
        try:
            if process.state() != QProcess.NotRunning:
                process.terminate()
                QTimer.singleShot(1200, lambda process=process: process.kill() if process.state() != QProcess.NotRunning else None)
                if active_package is not None:
                    QTimer.singleShot(7000, lambda package_dir=Path(active_package): self._remove_inline_d3d11_package_dir(package_dir))
        except RuntimeError:
            return

    def _prepare_inline_preview_orientation_for_load(self, *, reset_orientation: bool) -> None:
        if reset_orientation:
            self._set_inline_preview_flip_v_checked(False)
            self._apply_inline_preview_flip_v_render_setting(False)
        self._inline_preview_loaded_texture_count = 0
        self._inline_preview_loaded_renderer_backend = ""
        self._sync_inline_preview_orientation_controls()

    def _set_inline_preview_flip_v_checked(self, checked: bool) -> None:
        if not hasattr(self, "inline_preview_flip_v_checkbox"):
            return
        self.inline_preview_flip_v_checkbox.blockSignals(True)
        self.inline_preview_flip_v_checkbox.setChecked(bool(checked))
        self.inline_preview_flip_v_checkbox.blockSignals(False)

    def _apply_inline_preview_flip_v_render_setting(self, checked: bool) -> None:
        settings = self.inline_preview_widget.render_settings()
        settings.flip_texture_v = bool(checked)
        self.inline_preview_widget.set_render_settings(settings)

    def _sync_inline_preview_orientation_controls(self) -> None:
        if not hasattr(self, "inline_preview_flip_v_checkbox"):
            return
        enabled = bool(
            self._inline_preview_loaded_import_path is not None
            and int(self._inline_preview_loaded_texture_count) > 0
        )
        self.inline_preview_flip_v_checkbox.setEnabled(enabled)
        self.inline_preview_reset_orientation_button.setEnabled(enabled)

    def _reload_inline_preview_for_orientation(self) -> None:
        loaded_path = self._inline_preview_loaded_import_path
        payload = dict(self._inline_preview_loaded_payload or {})
        if loaded_path is None or not payload:
            return
        self._load_inline_model_preview(loaded_path, payload, reset_orientation=False)

    def _handle_inline_preview_flip_v_toggled(self, checked: bool) -> None:
        self._apply_inline_preview_flip_v_render_setting(bool(checked))
        self._sync_inline_preview_orientation_controls()
        if int(self._inline_preview_loaded_texture_count) <= 0:
            return
        if str(self._inline_preview_loaded_renderer_backend or "").strip().lower() == "native_d3d11":
            self._reload_inline_preview_for_orientation()
            return
        self._set_inline_preview_status("Flip V preview override applied." if checked else "Texture orientation preview reset.")

    def _handle_inline_preview_orientation_reset_clicked(self) -> None:
        if hasattr(self, "inline_preview_flip_v_checkbox") and self.inline_preview_flip_v_checkbox.isChecked():
            self.inline_preview_flip_v_checkbox.setChecked(False)
            return
        self._handle_inline_preview_flip_v_toggled(False)

    def _load_inline_model_preview(
        self,
        source_path: Path,
        payload: dict[str, object],
        *,
        reset_orientation: bool = True,
    ) -> None:
        if self._task_thread is not None and self._task_thread.isRunning():
            if bool(getattr(self, "_inline_preview_task_running", False)):
                self._inline_preview_request_id += 1
                self._pending_inline_preview_request = (Path(source_path), dict(payload), bool(reset_orientation))
                if self._stop_event is not None and hasattr(self._stop_event, "set"):
                    self._stop_event.set()
                self._set_inline_preview_status("Cancelling previous preview; queued latest selection...")
                return
            self._set_inline_preview_status("A model library task is already running.", error=True)
            return
        self._inline_preview_request_id += 1
        request_id = self._inline_preview_request_id
        source_path = Path(source_path)
        model_name = str(payload.get("name", "") or source_path.stem or "model")
        renderer_backend = self._inline_preview_renderer_backend()
        stop_event = threading.Event()
        self._stop_event = stop_event
        self._inline_preview_task_running = True
        self._prepare_inline_preview_orientation_for_load(reset_orientation=reset_orientation)
        self._set_inline_preview_status(f"Preparing preview for {model_name}...")
        self.inline_preview_widget.clear_model(f"Preparing preview for {model_name}...")
        self.inline_preview_stack.setCurrentWidget(self.inline_preview_widget)
        self._inline_preview_loaded_import_path = None
        self._inline_preview_loaded_payload = None
        preview_render_settings = self.inline_preview_widget.render_settings()
        high_quality_textures = bool(getattr(preview_render_settings, "high_quality_by_default", True))
        self._record_model_library_preview_event(
            "model_library_preview_start",
            request_id=request_id,
            source_path=str(source_path),
            model_name=model_name,
            renderer_backend=renderer_backend,
            kind=str(payload.get("kind", "") or ""),
        )

        def task(progress: Callable[[str], None]) -> object:
            extract_root = self._inline_preview_extract_root_for_source(source_path, payload)
            return prepare_model_library_inline_preview(
                source_path,
                payload=payload,
                extract_root=extract_root,
                render_settings=preview_render_settings,
                renderer_backend=renderer_backend,
                model_name=model_name,
                request_id=request_id,
                high_quality_textures=False,
                progress=progress,
                stop_event=stop_event,
            )

        def complete(result: object) -> None:
            if not isinstance(result, dict):
                self._set_inline_preview_status("Preview finished with an unexpected response.", error=True)
                return
            if int(result.get("request_id", -1)) != int(self._inline_preview_request_id):
                return
            preview_model = result.get("preview_model")
            prepared_preview = result.get("prepared_preview")
            active_renderer = str(result.get("renderer_backend", "") or "").strip().lower()
            renderer_note = " | renderer: Qt preview"
            loaded_renderer_backend = active_renderer or "qt"
            native_preview_started = False
            if active_renderer == "native_d3d11" and str(result.get("d3d11_package_dir", "") or "").strip():
                package_dir = Path(str(result.get("d3d11_package_dir", "") or ""))
                self._record_model_library_preview_event(
                    "model_library_preview_prepared",
                    request_id=request_id,
                    import_path=str(result.get("import_path", "") or source_path),
                    renderer_backend=active_renderer,
                    d3d11_package_dir=str(package_dir),
                    vertices=int(result.get("vertices", 0) or 0),
                    faces=int(result.get("faces", 0) or 0),
                    textures=int(result.get("textures", 0) or 0),
                    d3d11_package_ms=float(result.get("d3d11_package_ms", 0.0) or 0.0),
                    high_quality_textures=bool(result.get("high_quality_textures", high_quality_textures)),
                )
                if self._start_inline_d3d11_process(package_dir, render_settings=preview_render_settings):
                    native_preview_started = True
                    loaded_renderer_backend = "native_d3d11"
                    renderer_note = f" | renderer: native D3D11 package ({float(result.get('d3d11_package_ms', 0.0) or 0.0):.1f} ms)"
                else:
                    self._set_inline_preview_status("Native D3D11 preview failed to start.", error=True)
                    return
            else:
                if preview_model is None:
                    self._set_inline_preview_status("Qt preview data was not built.", error=True)
                    return
                self._record_model_library_preview_event(
                    "model_library_preview_prepared",
                    request_id=request_id,
                    import_path=str(result.get("import_path", "") or source_path),
                    renderer_backend=active_renderer or "qt",
                    vertices=int(result.get("vertices", 0) or 0),
                    faces=int(result.get("faces", 0) or 0),
                    textures=int(result.get("textures", 0) or 0),
                    high_quality_textures=bool(result.get("high_quality_textures", high_quality_textures)),
                )
                self._stop_inline_d3d11_process(cleanup_packages=True)
                self.inline_preview_stack.setCurrentWidget(self.inline_preview_widget)
                self.inline_preview_widget.set_prepared_model(preview_model, prepared_preview)
            resolved_import_path = Path(str(result.get("import_path", "") or source_path))
            self._invalidate_prepared_row_source(payload)
            self._inline_preview_loaded_import_path = resolved_import_path
            self._inline_preview_loaded_payload = dict(payload)
            self._inline_preview_loaded_renderer_backend = loaded_renderer_backend
            texture_count = int(result.get("textures", 0) or 0)
            self._inline_preview_loaded_texture_count = texture_count
            payload["import_path"] = str(resolved_import_path)
            payload["import_supported"] = True
            if source_path.suffix.lower() == ".zip":
                payload["archive_path"] = str(source_path)
            if payload.get("kind") == "mirror":
                payload["local_status"] = "Ready"
            payload["texture_status"] = f"Resolved ({texture_count})" if texture_count > 0 else "None resolved"
            audit_category = str(result.get("audit_category", "") or "")
            if audit_category:
                payload["audit_category"] = audit_category
                payload["audit_confidence"] = float(result.get("audit_confidence", 0.0) or 0.0)
                payload["audit_texture_slots"] = tuple(result.get("audit_texture_slots", ()) or ())
                payload["audit_workflows"] = tuple(result.get("audit_workflows", ()) or ())
                payload["audit_warnings"] = tuple(result.get("audit_warnings", ()) or ())
                payload["audit_false_positive"] = bool(result.get("audit_false_positive", False))
                payload["audit_mixed_model"] = bool(result.get("audit_mixed_model", False))
                payload["audit_material_classes"] = tuple(result.get("audit_material_classes", ()) or ())
                payload["audit_material_inventory"] = tuple(result.get("audit_material_inventory", ()) or ())
            self._refresh_result_row_status(payload)
            audit_text = ""
            if audit_category:
                audit_text = f" | audit: {audit_category} {float(result.get('audit_confidence', 0.0) or 0.0):.0%}"
            material_channel_summary = str(result.get("material_channel_summary", "") or "").strip()
            material_channel_text = f" | channels: {material_channel_summary}" if material_channel_summary else ""
            self._set_inline_preview_status(
                f"{result.get('model_name', 'Model')} | {int(result.get('meshes', 0)):,} mesh(es), "
                f"{int(result.get('vertices', 0)):,} vertices, {int(result.get('faces', 0)):,} faces, "
                f"{texture_count:,} resolved texture slot(s){audit_text}{material_channel_text}{renderer_note}."
            )
            self._sync_inline_preview_orientation_controls()
            self._update_selection_state()
            if int(self._pending_icon_generation_request_id) == int(request_id):
                if not native_preview_started:
                    self._pending_icon_generation_request_id = 0
                    QTimer.singleShot(180, self._capture_inline_preview_icon)

        def handle_error(message: str) -> None:
            if int(request_id) != int(self._inline_preview_request_id):
                return
            self._pending_icon_generation_request_id = 0
            self._sync_inline_preview_orientation_controls()
            self._record_model_library_preview_event(
                "model_library_preview_error",
                request_id=request_id,
                source_path=str(source_path),
                message=str(message),
            )
            self._set_inline_preview_status(f"Preview failed: {message}", error=True)

        self._run_task(
            f"Preparing model library preview for {model_name}...",
            task,
            complete,
            error_handler=handle_error,
        )

    def _after_model_library_task_finished(self) -> None:
        self._icon_output_active = False
        pending_action = self._pending_model_action_after_task
        self._pending_model_action_after_task = None
        if pending_action is not None:
            QTimer.singleShot(0, pending_action)
        if not bool(getattr(self, "_inline_preview_task_running", False)):
            return
        self._inline_preview_task_running = False
        pending = self._pending_inline_preview_request
        self._pending_inline_preview_request = None
        if pending is None:
            return
        source_path, payload, reset_orientation = pending
        QTimer.singleShot(
            0,
            lambda: self._load_inline_model_preview(
                source_path,
                payload,
                reset_orientation=reset_orientation,
            ),
        )

    def generate_icon_from_preview(self) -> None:
        payload = self._selected_payload()
        if not payload:
            self._set_inline_preview_status("Select a model first.", error=True)
            return
        if not self._inline_preview_matches_payload(payload):
            if self._task_thread is not None and self._task_thread.isRunning():
                self._set_inline_preview_status("A model library task is already running.", error=True)
                return
            self._pending_icon_generation_request_id = self._inline_preview_request_id + 1
            self.preview_selected_model_here()
            return
        self._capture_inline_preview_icon()

    def _inline_preview_matches_payload(self, payload: dict[str, object]) -> bool:
        loaded = self._inline_preview_loaded_payload
        if not isinstance(loaded, dict):
            return False
        keys = ("kind", "uid", "id", "archive_path", "path", "name")
        return tuple(str(payload.get(key, "") or "") for key in keys) == tuple(
            str(loaded.get(key, "") or "") for key in keys
        )

    def _capture_inline_preview_icon(self) -> None:
        payload = self._selected_payload()
        loaded_path = self._inline_preview_loaded_import_path
        if payload is None or loaded_path is None:
            self._set_inline_preview_status("Preview a model first, then generate an icon.", error=True)
            return
        if not self._inline_preview_matches_payload(payload):
            self._set_inline_preview_status("The selected model preview is no longer active.", error=True)
            return
        if self._task_thread is not None and self._task_thread.isRunning():
            self._set_inline_preview_status("A model library task is already running.", error=True)
            return
        native_capture = self.inline_preview_stack.currentWidget() is self.inline_d3d11_preview_host
        if native_capture:
            try:
                image = self.inline_d3d11_preview_host.capture_replacement_icon_image()
            except Exception as exc:
                self._set_inline_preview_status(f"Icon capture failed: {exc}", error=True)
                return
            if image.isNull() or image.width() <= 0 or image.height() <= 0:
                self._set_inline_preview_status("Icon capture failed: native D3D11 preview framebuffer is empty.", error=True)
                return
        else:
            if int(getattr(self.inline_preview_widget, "_vertex_count", 0) or 0) <= 0:
                self._set_inline_preview_status("The preview is not render-ready yet.", error=True)
                return
            try:
                self.inline_preview_widget.repaint()
                pixmap = self.inline_preview_widget.grab()
                image = pixmap.toImage().copy() if not pixmap.isNull() else QImage()
            except Exception as exc:
                self._set_inline_preview_status(f"Icon capture failed: {exc}", error=True)
                return
            if image.isNull() or image.width() <= 0 or image.height() <= 0:
                self._set_inline_preview_status("Icon capture failed: preview framebuffer is empty.", error=True)
                return
        self._queue_inline_preview_icon_output(
            image,
            payload=dict(self._inline_preview_loaded_payload or payload),
            loaded_path=loaded_path,
            native_capture=native_capture,
        )

    def closeEvent(self, event: object) -> None:  # type: ignore[override]
        self.request_shutdown()
        try:
            super().closeEvent(event)  # type: ignore[arg-type]
        except TypeError:
            return

    def _model_preview_icon_image(self, image: QImage, *, size: int = 512) -> QImage:
        return prepare_model_library_preview_icon(image, size=size)

    def _generated_icon_stem(self, payload: dict[str, object], import_path: Path) -> str:
        name = str(payload.get("name", "") or import_path.stem or "model_icon").strip()
        slug = re.sub(r"[^A-Za-z0-9._-]+", "-", name).strip("-._")
        if not slug:
            slug = "model_icon"
        slug = slug[:72].strip("-._") or "model_icon"
        uid = str(payload.get("uid", "") or "").strip()
        if uid:
            slug = f"{slug}-{re.sub(r'[^A-Za-z0-9]+', '', uid)[:12]}"
        return f"{slug}-{time.strftime('%Y%m%d-%H%M%S')}"

    def _payload_can_preview_here(self, payload: Optional[dict[str, object]]) -> bool:
        return self._inline_preview_source_path_for_payload(payload) is not None

    def _inline_preview_source_path_for_payload(self, payload: Optional[dict[str, object]]) -> Optional[Path]:
        if not payload:
            return None
        for key in ("import_path", "archive_path", "path"):
            path_text = str(payload.get(key, "") or "").strip()
            if not path_text:
                continue
            path = Path(path_text)
            if is_importable_model_path(path) or path.suffix.lower() == ".zip":
                return path
        if payload.get("kind") != "mirror":
            return None
        asset_dir = str(payload.get("asset_dir", "") or "").strip()
        return Path(asset_dir) if asset_dir else None

    def _inline_preview_extract_root_for_source(self, source_path: Path, payload: dict[str, object]) -> Optional[Path]:
        if source_path.suffix.lower() != ".zip":
            return None
        asset_dir_text = str(payload.get("asset_dir", "") or "").strip()
        asset_dir = Path(asset_dir_text) if asset_dir_text else source_path.parent
        if not asset_dir_text and not (asset_dir / "model_metadata.json").is_file():
            return None
        if not asset_dir.is_dir() or not self._path_is_under(source_path, asset_dir):
            return None
        extract_name = "source" if source_path.name.lower().endswith(".source.zip") else "gltf"
        return asset_dir / extract_name

    def _set_inline_preview_status(self, message: str, *, error: bool = False) -> None:
        if hasattr(self, "inline_preview_status_label"):
            self.inline_preview_status_label.setText(message)
        self.status_message_requested.emit(message, error)


__all__ = ["ModelLibraryInlinePreviewMixin"]
