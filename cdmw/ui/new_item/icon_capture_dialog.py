"""New Item Studio: capture the item's icon from the resident viewport.

The Builder's Generate Icon renders the model offscreen at a fixed angle; this dialog
shows the item's mesh (the imported model, else the template's own) in the resident
.NET viewport, lets the reader orbit and zoom it, and captures the frame the way the
Model Library's icon capture does (`capture_replacement_icon`, 512 x 512, grid and gizmo
hidden). The captured PNG is what the studio's icon route then fits and encodes against
the template icon's DDS format.
"""

from __future__ import annotations

import shutil
import tempfile
import threading
import time
from pathlib import Path
from typing import Callable, Optional

from PySide6.QtCore import QThread, Qt, QTimer
from PySide6.QtGui import QImage, QPixmap
from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from cdmw.modding.mesh_parser import ParsedMesh
from cdmw.workers.utility_workers import UtilityWorker

__all__ = ["IconCaptureDialog"]


def _default_host_factory(parent: QWidget):
    from cdmw.ui.preview.dotnet_host import DotNetPreviewHostFrame
    from cdmw.ui.preview.profile import DotNetPreviewProfile

    return DotNetPreviewHostFrame(parent, profile=DotNetPreviewProfile.PREVIEW, terminate_on_close=True)


class IconCaptureDialog(QDialog):
    """Orbit the item, press Capture, accept: `captured_path` is the PNG."""

    def __init__(
        self,
        parent: Optional[QWidget] = None,
        *,
        item_mesh: Optional[ParsedMesh] = None,
        item_source: object = None,
        item_token: object = None,
        item_label: str = "",
        output_root: Optional[Path] = None,
        host_factory: Optional[Callable[[QWidget], object]] = None,
    ) -> None:
        """`item_source` (with `item_token`) is the textured route: what the controller's
        `item_preview_source` hands out; `item_mesh` is the bare mesh when there is no
        such source. One of the two is needed."""

        super().__init__(parent)
        self.setWindowTitle("Capture the icon from the viewport")
        self.resize(960, 640)
        if item_mesh is None and item_source is None:
            raise ValueError("IconCaptureDialog needs item_source or item_mesh")
        self._item_mesh = item_mesh
        self._item_source = item_source
        self._item_token = item_token
        self._output_root = Path(output_root) if output_root is not None else Path(tempfile.gettempdir()) / "cdmw_new_item_icons"
        self._package_dir: Optional[Path] = None
        self._thread: Optional[QThread] = None
        self._worker: Optional[UtilityWorker] = None
        self._closed = False
        self._pending_capture: Optional[Path] = None
        self.captured_path: Optional[Path] = None

        layout = QVBoxLayout(self)
        intro = QLabel(
            f"{item_label or 'The item'} in the resident viewport: orbit and zoom it until it looks like an icon, then Capture. "
            "The frame is taken at 512 x 512 with the grid and gizmo hidden and becomes the icon the studio encodes."
        )
        intro.setWordWrap(True)
        layout.addWidget(intro)
        body = QHBoxLayout()
        layout.addLayout(body, 1)

        self.host = None
        factory = host_factory or _default_host_factory
        try:
            self.host = factory(self)
        except Exception as exc:  # noqa: BLE001 - the viewport is optional; the dialog then only says so
            self.host = None
            self._host_error = str(exc)
        else:
            self._host_error = ""
        if self.host is not None:
            self.host.setMinimumSize(560, 420)
            self.host.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
            body.addWidget(self.host, 1)
        else:
            missing = QLabel("The resident viewport is not available here; pick an image file for the icon instead." + (f" ({self._host_error})" if self._host_error else ""))
            missing.setWordWrap(True)
            body.addWidget(missing, 1)

        side = QVBoxLayout()
        body.addLayout(side)
        self.capture_button = QPushButton("Capture")
        self.capture_button.setEnabled(False)
        self.capture_button.clicked.connect(self.capture)
        side.addWidget(self.capture_button)
        self.thumbnail = QLabel("")
        self.thumbnail.setFixedSize(192, 192)
        self.thumbnail.setAlignment(Qt.AlignCenter)
        self.thumbnail.setStyleSheet("border: 1px solid palette(mid);")
        side.addWidget(self.thumbnail)
        self.status = QLabel("Preparing the viewport...")
        self.status.setWordWrap(True)
        side.addWidget(self.status)
        side.addStretch(1)
        self.buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        self.buttons.button(QDialogButtonBox.Ok).setEnabled(False)
        self.buttons.accepted.connect(self.accept)
        self.buttons.rejected.connect(self.reject)
        side.addWidget(self.buttons)

        if self.host is not None:
            self.host.controller.state_changed.connect(self._host_state)
            self.host.controller.capture_completed.connect(self._capture_completed)
            QTimer.singleShot(0, self._start_package)
        else:
            self.status.setText("")

    # ------------------------------------------------------------------ package

    def _start_package(self) -> None:
        if self._closed:
            return
        mesh = self._item_mesh
        root = self._output_root

        source = self._item_source if self._item_source is not None else mesh
        token = self._item_token if self._item_source is not None else id(mesh)

        def task(_log, stop_event: threading.Event) -> Path:
            from cdmw.ui.new_item.item_preview import build_item_preview_package

            return build_item_preview_package(source, token=token, output_root=root, stop_event=stop_event)

        worker = UtilityWorker(task, task_accepts_cancel=True)
        thread = QThread(self)
        worker.moveToThread(thread)
        self._thread, self._worker = thread, worker
        worker.completed.connect(self._package_ready)
        worker.error.connect(lambda message: self.status.setText(f"The preview could not be built: {message}"))

        def finish() -> None:
            self._thread = None
            self._worker = None
            thread.quit()
            thread.wait(5000)
            worker.deleteLater()
            thread.deleteLater()

        worker.finished.connect(finish)
        thread.started.connect(worker.run)
        thread.start()

    def _package_ready(self, result: object) -> None:
        if self._closed or not isinstance(result, Path) or self.host is None:
            return
        self._package_dir = result
        if self.host.load_package(result, reset_view=True):
            self.host.set_display_mode("replacement_only")
            self.status.setText("Loading the viewport...")
        else:
            self.status.setText("The resident viewport rejected the preview package.")

    def _host_state(self, state: str, message: str) -> None:
        if self._closed or self.host is None:
            return
        if str(state) == "ready" and self._package_dir is not None:
            self.host.set_display_mode("replacement_only")
            self.host.set_icon_capture_mode(True)
            self.capture_button.setEnabled(True)
            self.status.setText("Orbit with the mouse, zoom with the wheel, then Capture. Capture again until you like it.")
        elif str(state) == "error":
            self.status.setText(str(message or "The viewport reported an error."))

    # ------------------------------------------------------------------ capture

    def capture(self) -> None:
        if self.host is None:
            return
        self._output_root.mkdir(parents=True, exist_ok=True)
        path = self._output_root / f"icon_capture_{time.time_ns()}.png"
        if not self.host.capture_replacement_icon(path):
            self.status.setText("The viewport rejected the capture request.")
            return
        self._pending_capture = path
        self.capture_button.setEnabled(False)
        self.status.setText("Capturing...")

    def _capture_completed(self, payload: object) -> None:
        if self._closed:
            return
        pending, self._pending_capture = self._pending_capture, None
        self.capture_button.setEnabled(True)
        status = str(payload.get("status", "") or "") if isinstance(payload, dict) else ""
        path = pending
        if isinstance(payload, dict):
            text = str(payload.get("requested_output_path", payload.get("output_path", "")) or "").strip()
            if text:
                path = Path(text)
        image = QImage(str(path)) if path is not None and status in ("", "captured") else QImage()
        if path is None or image.isNull():
            message = str(payload.get("message", "") or "") if isinstance(payload, dict) else ""
            self.status.setText(f"The capture failed: {message or 'the viewport returned no image.'}")
            return
        self.captured_path = path
        self.thumbnail.setPixmap(QPixmap.fromImage(image).scaled(self.thumbnail.size(), Qt.KeepAspectRatio, Qt.SmoothTransformation))
        self.buttons.button(QDialogButtonBox.Ok).setEnabled(True)
        self.status.setText(f"Captured {image.width()} x {image.height()}. Capture again, or accept.")

    # ------------------------------------------------------------------ lifecycle

    def done(self, result: int) -> None:  # noqa: A003 - Qt virtual
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
            from cdmw.ui.new_item.item_preview import package_cleanup_root

            shutil.rmtree(package_cleanup_root(self._package_dir, self._output_root), ignore_errors=True)
        super().done(result)
