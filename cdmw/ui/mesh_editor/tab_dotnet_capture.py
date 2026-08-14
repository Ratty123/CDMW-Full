"""Resident icon capture over the .NET protocol.

Split out of :mod:`tab_dotnet_resources` to keep that module inside the
owned-file line cap. A capture is a request with a callback and a deadline:
the helper is asked for a frame, the answer arrives correlated by request id,
and every pending callback is settled on timeout or teardown so a caller is
never left waiting on a frame that is not coming.
"""

from __future__ import annotations

import os
from pathlib import Path
import sys
from typing import Mapping, Sequence

from PySide6.QtCore import QTimer
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import QComboBox

from cdmw.services.mesh_interaction_diagnostics import send_recorded_mesh_protocol_message
from cdmw.services.mesh_dotnet_material_state import (
    copy_dotnet_preview_material_bindings,
    defer_dotnet_preview_material_synthesis,
)
from cdmw.services.mesh_dotnet_material_compiler import (
    MeshDotNetMaterialCompileRequest,
    snapshot_mesh_dotnet_material_inputs,
)
from cdmw.ui.archive_browser.static_replacement_viewport_display_modes import (
    normalize_mesh_preview_display_mode,
    untextured_fallback_display_mode,
)
from cdmw.ui.mesh_editor import tab_dotnet_material_commit as _material_commit
from cdmw.ui.mesh_editor.tab_compat import facade_globals as _tab
from cdmw.ui.mesh_editor.tab_dotnet_material_compilation import (
    MeshEditorDotNetMaterialCompilationMixin,
)
from cdmw.ui.mesh_editor.tab_dotnet_payloads import MeshEditorDotNetPayloadMixin




class MeshEditorDotNetCaptureMixin(
    MeshEditorDotNetMaterialCompilationMixin,
    MeshEditorDotNetPayloadMixin,
):
    def request_resident_dotnet_icon_capture(self, on_captured: object) -> bool:
        package = self.standalone_dotnet_experiment_package
        controller = self._dotnet_target_controller()
        if (
            package is None
            or controller is None
            or not callable(on_captured)
            or not self.standalone_dotnet_target_embedded
            or not self._standalone_dotnet_editor_process_running()
        ):
            if callable(on_captured):
                on_captured(None)
            return False
        try:
            view = controller.session_view()
        except (AttributeError, RuntimeError, TypeError, ValueError):
            on_captured(None)
            return False
        self.standalone_dotnet_capture_request_id += 1
        request_id = self.standalone_dotnet_capture_request_id
        output_path = package.output_dir / f"icon_capture_{request_id}.png"
        timer = QTimer(self)
        timer.setSingleShot(True)
        timer.timeout.connect(lambda target=request_id: self._handle_dotnet_capture_timeout(target))
        self.standalone_dotnet_capture_callbacks[request_id] = (on_captured, output_path, timer)
        payload = {
            "event": "capture_request",
            "session_id": view.session_id,
            "request_id": request_id,
            "base_revision": view.revision,
            "process_generation": self.standalone_dotnet_process_generation,
            "protocol_version": 2,
            "output_path": output_path.relative_to(package.output_dir).as_posix(),
            "width": 1024,
            "height": 1024,
        }
        if not self._send_dotnet_protocol_message(payload):
            self._finish_dotnet_capture(request_id, None)
            return False
        timer.start(10_000)
        return True

    def _handle_dotnet_capture_result(self, payload: Mapping[str, object]) -> bool:
        try:
            request_id = int(payload.get("request_id", 0) or 0)
        except (TypeError, ValueError, OverflowError):
            return False
        pending = self.standalone_dotnet_capture_callbacks.get(request_id)
        if pending is None:
            return False
        _callback, expected_path, _timer = pending
        reported_path = Path(str(payload.get("output_path", "") or "")).expanduser()
        try:
            path_matches = reported_path.resolve() == Path(expected_path).resolve()
        except OSError:
            path_matches = False
        status = str(payload.get("status", "") or "").strip().lower()
        pixmap = QPixmap(str(expected_path)) if status == "captured" and path_matches else QPixmap()
        if pixmap.isNull():
            self._set_dotnet_status(
                str(
                    payload.get("message", "Deterministic .NET icon capture failed.")
                    or "Deterministic .NET icon capture failed."
                ),
                error=True,
            )
            self._finish_dotnet_capture(request_id, None)
            return False
        self._record_mesh_dotnet_event(
            "mesh_dotnet_icon_capture",
            request_id=request_id,
            output_path=str(expected_path),
            sha256=str(payload.get("sha256", "") or ""),
            visible_view_mutated=bool(payload.get("visible_view_mutated", True)),
        )
        self._finish_dotnet_capture(request_id, pixmap)
        return True

    def _handle_dotnet_capture_timeout(self, request_id: int) -> None:
        if int(request_id) not in self.standalone_dotnet_capture_callbacks:
            return
        self._set_dotnet_status("Deterministic .NET icon capture timed out.", error=True)
        self._finish_dotnet_capture(int(request_id), None)

    def _finish_dotnet_capture(self, request_id: int, pixmap: object) -> None:
        pending = self.standalone_dotnet_capture_callbacks.pop(int(request_id), None)
        if pending is None:
            return
        callback, output_path, timer = pending
        try:
            timer.stop()
            timer.deleteLater()
        except RuntimeError:
            pass
        if pixmap is None:
            try:
                Path(output_path).unlink(missing_ok=True)
            except OSError:
                pass
        callback(pixmap)

    def _cancel_pending_dotnet_captures(self) -> None:
        for request_id in tuple(self.standalone_dotnet_capture_callbacks):
            self._finish_dotnet_capture(request_id, None)
