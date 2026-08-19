"""New Item Studio: the item as it will be, in the resident viewport, inline.

`ItemPreviewFrame` shows a mesh (the imported model, else the template's own) in the
resident .NET viewport the Model Library uses: orbit, zoom, and a capture of the frame at
512 x 512 with the grid and gizmo hidden (the icon route). It starts the viewport only
when first asked to show something, rebuilds its package when the mesh changes, and is
what the Model and icon step embeds and the icon capture dialog wraps.
"""

from __future__ import annotations

import shutil
import tempfile
import threading
import time
from pathlib import Path
from typing import Callable, Optional

from PySide6.QtCore import QThread, Qt, QTimer, Signal
from PySide6.QtGui import QImage
from PySide6.QtWidgets import QLabel, QSizePolicy, QVBoxLayout, QWidget

from cdmw.modding.mesh_parser import ParsedMesh
from cdmw.workers.utility_workers import UtilityWorker

__all__ = ["ItemPreviewFrame", "default_host_factory"]


def default_host_factory(parent: QWidget):
    from cdmw.ui.preview.dotnet_host import DotNetPreviewHostFrame
    from cdmw.ui.preview.profile import DotNetPreviewProfile

    return DotNetPreviewHostFrame(parent, profile=DotNetPreviewProfile.PREVIEW, terminate_on_close=True)


class ItemPreviewFrame(QWidget):
    """The resident viewport around one mesh, with an icon capture."""

    #: the viewport is showing the mesh last given
    ready = Signal()
    #: a capture landed: the PNG path and its image
    captured = Signal(object, object)
    #: something to say next to the view
    status_changed = Signal(str)

    def __init__(self, parent: Optional[QWidget] = None, *, output_root: Optional[Path] = None, host_factory: Optional[Callable[[QWidget], object]] = None) -> None:
        super().__init__(parent)
        self._output_root = Path(output_root) if output_root is not None else Path(tempfile.gettempdir()) / "cdmw_new_item_preview"
        self._host_factory = host_factory or default_host_factory
        self.host = None
        self._host_error = ""
        self._package_dir: Optional[Path] = None
        self._thread: Optional[QThread] = None
        self._worker: Optional[UtilityWorker] = None
        self._closed = False
        self._pending_mesh: Optional[ParsedMesh] = None
        self._pending_capture: Optional[Path] = None
        self._loaded = False
        self.is_ready = False
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(4)
        self.placeholder = QLabel("The viewport starts when there is a mesh to show.")
        self.placeholder.setAlignment(Qt.AlignCenter)
        self.placeholder.setWordWrap(True)
        self.placeholder.setMinimumHeight(240)
        layout.addWidget(self.placeholder, 1)
        self.hint = QLabel("Orbit: left-drag  |  Pan: Shift + left-drag, or middle / right-drag  |  Zoom: wheel")
        self.hint.setObjectName("new_item_intro")
        self.hint.setWordWrap(True)
        layout.addWidget(self.hint)
        self.hint.setVisible(False)

    # ------------------------------------------------------------------ host

    def _ensure_host(self) -> bool:
        if self.host is not None:
            return True
        try:
            self.host = self._host_factory(self)
        except Exception as exc:  # noqa: BLE001 - the viewport is optional; the rest of the step works
            self.host = None
            self._host_error = str(exc)
            self.placeholder.setText("The resident viewport is not available here." + (f" ({self._host_error})" if self._host_error else ""))
            return False
        self.host.setMinimumSize(420, 300)
        self.host.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.layout().insertWidget(0, self.host, 1)
        self.placeholder.setVisible(False)
        self.hint.setVisible(True)
        self.host.controller.state_changed.connect(self._host_state)
        self.host.controller.capture_completed.connect(self._capture_completed)
        return True

    def show_mesh(self, mesh: Optional[ParsedMesh]) -> None:
        """Show `mesh` (None clears the view); a build already running is superseded."""

        if self._closed:
            return
        if mesh is None:
            self._pending_mesh = None
            self.is_ready = False
            if self.host is None:
                self.placeholder.setText("The viewport starts when there is a mesh to show.")
            return
        if not self._ensure_host():
            return
        self._pending_mesh = mesh
        if self._thread is None:
            self._start_package(mesh)

    def _start_package(self, mesh: ParsedMesh) -> None:
        root = self._output_root
        self.is_ready = False
        self.status_changed.emit("Preparing the viewport...")

        def task(_log, stop_event: threading.Event) -> Path:
            from cdmw.services.mesh_dotnet_experiment import build_mesh_dotnet_experiment_package

            package = build_mesh_dotnet_experiment_package(
                mesh, output_root=root, reference_mesh=None, comparison_mode="side_by_side", interaction_mode="placement",
                cancelled=stop_event.is_set,
            )
            return Path(package.package_dir)

        worker = UtilityWorker(task, task_accepts_cancel=True)
        thread = QThread(self)
        worker.moveToThread(thread)
        self._thread, self._worker = thread, worker
        worker.completed.connect(self._package_ready)
        worker.error.connect(lambda message: self.status_changed.emit(f"The preview could not be built: {message}"))

        def finish() -> None:
            self._thread = None
            self._worker = None
            thread.quit()
            thread.wait(5000)
            worker.deleteLater()
            thread.deleteLater()
            # a newer mesh arrived while this one was building
            if self._pending_mesh is not None and self._pending_mesh is not mesh and not self._closed:
                QTimer.singleShot(0, lambda: self._start_package(self._pending_mesh))

        worker.finished.connect(finish)
        thread.started.connect(worker.run)
        thread.start()

    def _package_ready(self, result: object) -> None:
        if self._closed or not isinstance(result, Path) or self.host is None:
            return
        previous, self._package_dir = self._package_dir, result
        if previous is not None and previous != result:
            shutil.rmtree(previous, ignore_errors=True)
        if self.host.load_package(result, reset_view=True):
            self._loaded = True
            self.host.set_display_mode("replacement_only")
            self.status_changed.emit("Loading the viewport...")
        else:
            self.status_changed.emit("The resident viewport rejected the preview package.")

    def _host_state(self, state: str, message: str) -> None:
        if self._closed or self.host is None:
            return
        if str(state) == "ready" and self._package_dir is not None:
            self.host.set_display_mode("replacement_only")
            self.host.set_icon_capture_mode(True)
            self.is_ready = True
            self.status_changed.emit("")
            self.ready.emit()
        elif str(state) == "error":
            self.status_changed.emit(str(message or "The viewport reported an error."))

    # ------------------------------------------------------------------ capture

    def capture(self, path: Optional[Path] = None) -> bool:
        """Take the frame at 512 x 512; `captured` fires with the PNG when it lands."""

        if self.host is None or not self.is_ready:
            return False
        self._output_root.mkdir(parents=True, exist_ok=True)
        target = Path(path) if path is not None else self._output_root / f"icon_capture_{time.time_ns()}.png"
        if not self.host.capture_replacement_icon(target):
            self.status_changed.emit("The viewport rejected the capture request.")
            return False
        self._pending_capture = target
        self.status_changed.emit("Capturing...")
        return True

    def _capture_completed(self, payload: object) -> None:
        if self._closed:
            return
        pending, self._pending_capture = self._pending_capture, None
        status = str(payload.get("status", "") or "") if isinstance(payload, dict) else ""
        path = pending
        if isinstance(payload, dict):
            text = str(payload.get("requested_output_path", payload.get("output_path", "")) or "").strip()
            if text:
                path = Path(text)
        image = QImage(str(path)) if path is not None and status in ("", "captured") else QImage()
        if path is None or image.isNull():
            message = str(payload.get("message", "") or "") if isinstance(payload, dict) else ""
            self.status_changed.emit(f"The capture failed: {message or 'the viewport returned no image.'}")
            return
        self.status_changed.emit(f"Captured {image.width()} x {image.height()}.")
        self.captured.emit(path, image)

    # ------------------------------------------------------------------ lifecycle

    def shutdown(self) -> None:
        self._closed = True
        worker = self._worker
        if worker is not None:
            worker.stop()
        thread = self._thread
        if thread is not None:
            thread.quit()
            thread.wait(5000)
        if self.host is not None:
            try:
                self.host.set_icon_capture_mode(False)
                self.host.controller.shutdown()
            except Exception:  # noqa: BLE001
                pass
        if self._package_dir is not None:
            shutil.rmtree(self._package_dir, ignore_errors=True)
            self._package_dir = None
