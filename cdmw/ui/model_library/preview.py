"""Inline preview and icon generation for Model Library."""

from __future__ import annotations

import re
import tempfile
import threading
import time
from pathlib import Path
from typing import Callable, Optional

from PySide6.QtCore import QTimer
from PySide6.QtGui import QImage

from cdmw.domain.library.models import is_importable_model_path
from cdmw.services.model_library_preview import (
    prepare_model_library_inline_preview,
)
from cdmw.ui.model_library.icon_output import ModelLibraryIconOutputMixin
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
        return "d3d11_vortice_shader"

    def _inline_d3d11_process_running(self) -> bool:
        controller = getattr(getattr(self, "inline_d3d11_preview_host", None), "controller", None)
        return bool(controller is not None and getattr(controller, "is_running", False))

    def _start_inline_d3d11_status_timer(self) -> None:
        return None

    def _stop_inline_d3d11_status_timer(self) -> None:
        return None

    def _remove_inline_d3d11_package_dir(self, package_dir: Optional[Path]) -> None:
        remove_model_library_preview_package_dir(package_dir)

    def _cleanup_inline_d3d11_packages(self, *, include_active: bool = False) -> None:
        packages = list(getattr(self, "_inline_d3d11_retired_packages", []) or [])
        self._inline_d3d11_retired_packages = []
        if include_active and self._inline_d3d11_active_package is not None:
            packages.append(Path(self._inline_d3d11_active_package))
            self._inline_d3d11_active_package = None
        for package_dir in packages:
            self._remove_inline_d3d11_package_dir(package_dir)

    def _start_inline_d3d11_process(self, package_dir: Path, *, render_settings: object) -> bool:
        package_dir = Path(package_dir)
        previous_package = self._inline_d3d11_active_package
        self._record_model_library_preview_event(
            "model_library_dotnet_load",
            package_dir=str(package_dir),
            resident=bool(self._inline_d3d11_process_running()),
        )
        if previous_package is not None and Path(previous_package) != package_dir:
            self._inline_d3d11_retired_packages.append(Path(previous_package))
        self._inline_d3d11_active_package = package_dir
        self.inline_d3d11_preview_host.show()
        self.inline_d3d11_preview_host.update()
        if not self.inline_d3d11_preview_host.load_package(
            package_dir,
            reset_view=previous_package is None,
        ):
            self._set_inline_preview_status(".NET/Vortice Preview rejected the prepared package.", error=True)
            self._cleanup_inline_d3d11_packages(include_active=True)
            return False
        self.inline_d3d11_preview_host.set_render_tuning(render_settings)
        self.inline_preview_stack.setCurrentWidget(self.inline_d3d11_preview_host)
        self._record_model_library_preview_event(
            "model_library_dotnet_package_requested",
            package_dir=str(package_dir),
        )
        return True

    def _poll_inline_d3d11_status(self) -> None:
        return None

    def _handle_inline_dotnet_state(self, state: str, message: str) -> None:
        if str(state) == "ready":
            self._cleanup_inline_d3d11_packages(include_active=False)
            self.inline_preview_stack.setCurrentWidget(self.inline_d3d11_preview_host)
            self._set_inline_preview_status(".NET/Vortice Model Library preview ready.")
            self._record_model_library_preview_event("model_library_dotnet_ready")
            if int(self._pending_icon_generation_request_id) == int(self._inline_preview_request_id):
                self._pending_icon_generation_request_id = 0
                QTimer.singleShot(180, self._capture_inline_preview_icon)
        elif str(state) == "error":
            self._set_inline_preview_status(str(message or ".NET/Vortice Preview failed."), error=True)
            self._record_model_library_preview_event(
                "model_library_dotnet_error",
                message=str(message or ""),
            )
        elif str(state) not in {"empty", "inactive", "closed"}:
            self._set_inline_preview_status(str(message or ".NET/Vortice Preview"))

    def _stop_inline_d3d11_process(
        self,
        *,
        cleanup_packages: bool = False,
    ) -> None:
        controller = getattr(getattr(self, "inline_d3d11_preview_host", None), "controller", None)
        if cleanup_packages:
            if controller is not None:
                controller.shutdown()
            self._cleanup_inline_d3d11_packages(include_active=True)
        elif controller is not None:
            controller.clear_preview()

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
        if str(self._inline_preview_loaded_renderer_backend or "").strip().lower() == "d3d11_vortice_shader":
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
        self.inline_d3d11_preview_host.clear_preview()
        self.inline_preview_stack.setCurrentWidget(self.inline_d3d11_preview_host)
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
            active_renderer = str(result.get("renderer_backend", "") or "").strip().lower()
            renderer_note = " | renderer: .NET/Vortice Preview"
            loaded_renderer_backend = active_renderer or "d3d11_vortice_shader"
            dotnet_preview_started = False
            if active_renderer == "d3d11_vortice_shader" and str(result.get("dotnet_preview_package_path", "") or "").strip():
                package_dir = Path(str(result.get("dotnet_preview_package_path", "") or ""))
                self._record_model_library_preview_event(
                    "model_library_preview_prepared",
                    request_id=request_id,
                    import_path=str(result.get("import_path", "") or source_path),
                    renderer_backend=active_renderer,
                    dotnet_preview_package_path=str(package_dir),
                    vertices=int(result.get("vertices", 0) or 0),
                    faces=int(result.get("faces", 0) or 0),
                    textures=int(result.get("textures", 0) or 0),
                    dotnet_package_ms=float(result.get("dotnet_package_ms", 0.0) or 0.0),
                    high_quality_textures=bool(result.get("high_quality_textures", high_quality_textures)),
                )
                if self._start_inline_d3d11_process(package_dir, render_settings=preview_render_settings):
                    dotnet_preview_started = True
                    loaded_renderer_backend = "d3d11_vortice_shader"
                    renderer_note = f" | renderer: .NET/Vortice package ({float(result.get('dotnet_package_ms', 0.0) or 0.0):.1f} ms)"
                else:
                    self._set_inline_preview_status(".NET/Vortice Preview failed to load.", error=True)
                    return
            else:
                self._set_inline_preview_status("Canonical .NET/Vortice preview package was not built; no legacy fallback is available.", error=True)
                return
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
                if not dotnet_preview_started:
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
        dotnet_capture = self.inline_preview_stack.currentWidget() is self.inline_d3d11_preview_host
        if not dotnet_capture:
            self._set_inline_preview_status("The .NET/Vortice preview is not render-ready yet.", error=True)
            return
        capture_path = (
            Path(tempfile.gettempdir())
            / "cdmw_model_library_captures"
            / f"capture_{self._inline_preview_request_id}_{time.time_ns()}.png"
        )
        self._pending_dotnet_icon_capture = (
            dict(self._inline_preview_loaded_payload or payload),
            Path(loaded_path),
            capture_path,
        )
        if not self.inline_d3d11_preview_host.capture_replacement_icon(capture_path):
            self._pending_dotnet_icon_capture = None
            self._set_inline_preview_status("Icon capture failed: .NET/Vortice Preview rejected the capture request.", error=True)
            return
        self._set_inline_preview_status("Capturing deterministic .NET/Vortice preview icon...")

    def _handle_inline_dotnet_capture_completed(self, result: object) -> None:
        pending = self._pending_dotnet_icon_capture
        if pending is None:
            return
        self._pending_dotnet_icon_capture = None
        payload, loaded_path, capture_path = pending
        status = str(result.get("status", "") or "") if isinstance(result, dict) else ""
        image = QImage(str(capture_path)) if status == "captured" else QImage()
        try:
            capture_path.unlink(missing_ok=True)
        except OSError:
            pass
        if image.isNull() or image.width() <= 0 or image.height() <= 0:
            message = str(result.get("message", "") or "") if isinstance(result, dict) else ""
            self._set_inline_preview_status(
                f"Icon capture failed: {message or '.NET/Vortice preview framebuffer is empty.'}",
                error=True,
            )
            return
        self._queue_inline_preview_icon_output(
            image,
            payload=payload,
            loaded_path=loaded_path,
            native_capture=True,
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
