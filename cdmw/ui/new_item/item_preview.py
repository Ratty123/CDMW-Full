"""New Item Studio: the item as it will be, in the resident viewport, inline.

`ItemPreviewFrame` shows the item (the imported model, else the template's own) in the
resident .NET viewport the Model Library uses, textured the way that library and the
Builder show it: orbit, zoom, and a capture of the frame at 512 x 512 with the grid and
gizmo hidden (the icon route). It takes a `ModelPreviewData` (the archive or import
preview decode, textures resolved), a bare `ParsedMesh`, or a callable that produces
either off the UI thread; starts the viewport only when first asked to show something,
rebuilds its package when the source changes, and is what the Model and icon step embeds
and the icon capture dialog wraps.
"""

from __future__ import annotations

import shutil
import tempfile
import threading
import time
from pathlib import Path
from typing import Any, Callable, Hashable, Optional

from PySide6.QtCore import QThread, Qt, QTimer, Signal
from PySide6.QtGui import QImage
from PySide6.QtWidgets import QLabel, QSizePolicy, QVBoxLayout, QWidget

from cdmw.modding.mesh_parser import ParsedMesh
from cdmw.workers.utility_workers import UtilityWorker

__all__ = ["ItemPreviewFrame", "build_item_preview_package", "default_host_factory", "package_cleanup_root"]


def build_item_preview_package(source: Any, *, token: Hashable, output_root: Path, stop_event: threading.Event) -> Path:
    """Build the viewport package for `source` off the UI thread and return its directory.
    `source` is a `ModelPreviewData` (the archive or import preview decode, textures
    resolved: it goes the Model Library's route and comes out textured), a bare
    `ParsedMesh`, or a callable `(stop_event) -> one of those`."""

    item = source(stop_event) if callable(source) else source
    if item is None:
        raise ValueError("there is nothing to show")
    if getattr(item, "meshes", None) is not None and not hasattr(item, "submeshes"):
        from cdmw.services.mesh_dotnet_preview_package import build_or_lookup_dotnet_preview_package_from_model

        output_root.mkdir(parents=True, exist_ok=True)
        package = build_or_lookup_dotnet_preview_package_from_model(
            item, cache_root=output_root, archive_identity=f"new_item_preview:{token!r}", cache_mode="off",
            cancelled=stop_event.is_set,
        )
    else:
        from cdmw.services.mesh_dotnet_experiment import build_mesh_dotnet_experiment_package

        package = build_mesh_dotnet_experiment_package(
            item, output_root=output_root, reference_mesh=None, comparison_mode="side_by_side", interaction_mode="placement",
            cancelled=stop_event.is_set,
        )
    return Path(package.package_dir)


def package_cleanup_root(package_dir: Path, output_root: Path) -> Path:
    """The directory to remove for a package under `output_root`: the model route writes
    `<root>/cdmw_dotnet_preview_*/package`, the mesh route `<root>/<package>`."""

    parent = package_dir.parent
    if parent != output_root and parent.parent == output_root and parent.name.startswith("cdmw_dotnet_preview_"):
        return parent
    return package_dir


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
        #: (token, source) of the newest request; the build in flight may be older
        self._pending: Optional[tuple[Hashable, Any]] = None
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
        """Show the bare `mesh` (None clears the view); a build already running is superseded."""

        self.show(mesh, token=id(mesh) if mesh is not None else None)

    def show(self, source: Any, *, token: Hashable = None) -> None:
        """Show `source`: a `ModelPreviewData` (textures resolved), a `ParsedMesh`, or a
        callable `(stop_event) -> one of those` run off the UI thread. None clears the
        view. `token` names the source; the same token while a build of it is running or
        shown asks for nothing new. A build already running for something else is
        superseded when it finishes."""

        if self._closed:
            return
        if source is None:
            self._pending = None
            self.is_ready = False
            if self.host is None:
                self.placeholder.setText("The viewport starts when there is a mesh to show.")
            return
        if not self._ensure_host():
            return
        if self._pending is not None and self._pending[0] == token and (self._thread is not None or self.is_ready):
            return
        self._pending = (token, source)
        if self._thread is None:
            self._start_package(self._pending)

    def _start_package(self, request: tuple[Hashable, Any]) -> None:
        root = self._output_root
        token, source = request
        self.is_ready = False
        self.status_changed.emit("Preparing the viewport...")

        def task(_log, stop_event: threading.Event) -> Path:
            return build_item_preview_package(source, token=token, output_root=root, stop_event=stop_event)

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
            # a newer source arrived while this one was building
            newer = self._pending
            if newer is not None and newer[0] != token and not self._closed:
                QTimer.singleShot(0, lambda: self._start_package(newer))

        worker.finished.connect(finish)
        thread.started.connect(worker.run)
        thread.start()

    def _package_ready(self, result: object) -> None:
        if self._closed or not isinstance(result, Path) or self.host is None:
            return
        previous, self._package_dir = self._package_dir, result
        if previous is not None and previous != result:
            shutil.rmtree(self._package_cleanup_root(previous), ignore_errors=True)
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
            shutil.rmtree(self._package_cleanup_root(self._package_dir), ignore_errors=True)
            self._package_dir = None

    def _package_cleanup_root(self, package_dir: Path) -> Path:
        return package_cleanup_root(package_dir, self._output_root)
