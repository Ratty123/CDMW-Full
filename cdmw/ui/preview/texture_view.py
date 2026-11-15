"""Shared read-only GPU texture view with cancellable PNG fallback."""
from __future__ import annotations

import json
import weakref
from pathlib import Path
from threading import Event

from PySide6.QtCore import QEvent, QObject, QProcess, QRunnable, QThreadPool, QTimer, Qt, Signal
from PySide6.QtGui import QImage
from PySide6.QtWidgets import QApplication, QCheckBox, QComboBox, QLabel, QPushButton, QStackedWidget, QVBoxLayout, QWidget
from shiboken6 import isValid

from cdmw.services.mesh_rust_contract import resolve_rust_mesh_editor, validate_rust_mesh_editor_package
from cdmw.ui.layout_utils import FlowLayout
from cdmw.ui.mesh_editor.process_io import register_owned_qprocess_for_exit, stop_qprocess_async
from cdmw.ui.native_window_clipping import ensure_native_host_clipping
from cdmw.ui.preview_widgets import PreviewLabel, PreviewScrollArea
from cdmw.workers.runnable_signals import application_owned, release


class _Signals(QObject):
    completed = Signal(int, object)


class _PrepareTexture(QRunnable):
    def __init__(self, generation, path, *, fallback=False, configured=None):
        super().__init__()
        self.generation, self.path = generation, Path(path)
        self.fallback, self.configured = fallback, configured
        self.stop = Event()
        # Owned by the application and deleted on the GUI thread after the result,
        # never on the pool thread with the finished task (REPORT-crash, item 1).
        self.signals = application_owned(_Signals)

    def run(self):
        try:
            self._run()
        finally:
            release(self.signals)

    def _run(self):
        result = {}
        try:
            if not self.fallback and self.path.suffix.lower() == ".dds":
                resolution = resolve_rust_mesh_editor(self.configured)
                if not validate_rust_mesh_editor_package(resolution):
                    result = {"executable": resolution.resolved_path}
            if not result and not self.stop.is_set():
                path = self.path
                if path.suffix.lower() == ".dds":
                    from cdmw.services.preview_workflow_service import ensure_dds_display_preview_png
                    path = ensure_dds_display_preview_png(path, stop_event=self.stop)
                image = QImage(str(path))
                if image.isNull():
                    raise ValueError("No image preview available.")
                result = {"image": image}
        except Exception as exc:
            result = {"error": str(exc)}
        if not self.stop.is_set():
            try:
                self.signals.completed.emit(self.generation, result)
            except RuntimeError:
                pass  # The owning widget was destroyed while the worker stopped.


class GpuTexturePreview(QWidget):
    """One owned helper; stale preparation and process events cannot replace a newer file."""
    view_state_changed = Signal(float, bool)
    loaded = Signal(object)
    failed = Signal(str)

    def __init__(self, parent=None, *, zoom_controls=True, configured_executable=None):
        super().__init__(parent)
        self.setObjectName("GpuTexturePreview")
        self._configured = configured_executable
        self._path = ""
        self._generation = 0
        self._task = None
        self._process = None
        self._ready = False
        self._buffer = bytearray()
        self._gpu = False
        self._closed = False
        self._size = (1, 1)
        self._state = dict(channel=0, mip=0, reconstruct_z=False, fit=True, zoom=1.0, pan=[0.0, 0.0])
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        # The controls wrap when the preview is narrow, so they never set its minimum width.
        controls = QWidget()
        row = FlowLayout(controls)
        self.channels = QComboBox()
        self.channels.addItems(["RGB", "R", "G", "B", "A"])
        self.channels.setToolTip("Texture channels")
        self.mips = QComboBox()
        self.mips.addItem("0")
        self.normal_z = QCheckBox("Reconstruct normal Z")
        row.addWidget(self.channels)
        row.addWidget(QLabel("Mip"))
        row.addWidget(self.mips)
        row.addWidget(self.normal_z)
        if zoom_controls:
            for title, callback in (("-", lambda: self._zoom_step(-1)), ("Fit", lambda: self.set_fit_to_view(True)),
                                    ("100%", self._actual_size), ("+", lambda: self._zoom_step(1))):
                button = QPushButton(title)
                button.clicked.connect(callback)
                row.addWidget(button)
        layout.addWidget(controls)
        self.stack = QStackedWidget()
        self.viewport = QWidget()
        self.viewport.setAttribute(Qt.WA_DontCreateNativeAncestors, True)
        self.viewport.setAttribute(Qt.WA_NativeWindow, True)
        self.viewport.installEventFilter(self)
        ensure_native_host_clipping(self.viewport)
        self.image = PreviewLabel("Select a file to preview it here.")
        self.scroll = PreviewScrollArea()
        self.scroll.setWidgetResizable(False)
        self.scroll.setAlignment(Qt.AlignCenter)
        self.scroll.setWidget(self.image)
        self.image.attach_scroll_area(self.scroll)
        self.image.set_wheel_zoom_handler(self._zoom_step)
        self.stack.addWidget(self.scroll)
        self.stack.addWidget(self.viewport)
        layout.addWidget(self.stack, 1)
        self.status = QLabel()
        self.status.setWordWrap(True)
        layout.addWidget(self.status)
        self.channels.currentIndexChanged.connect(self._controls_changed)
        self.mips.currentIndexChanged.connect(self._controls_changed)
        self.normal_z.toggled.connect(self._controls_changed)
        self._set_gpu_controls(False)
        self._timeout = QTimer(self)
        self._timeout.setSingleShot(True)
        self._timeout.timeout.connect(self._fallback)
        QApplication.instance().aboutToQuit.connect(self.shutdown)

    def _set_gpu_controls(self, enabled):
        self.channels.setEnabled(enabled)
        self.mips.setEnabled(enabled)
        self.normal_z.setEnabled(enabled)

    def _reset_channel_controls(self):
        controls = (self.channels, self.mips, self.normal_z)
        for control in controls:
            control.blockSignals(True)
        try:
            self.channels.setCurrentIndex(0)
            self.mips.clear()
            self.mips.addItem("0")
            self.normal_z.setChecked(False)
            self._state.update(channel=0, mip=0, reconstruct_z=False)
        finally:
            for control in controls:
                control.blockSignals(False)
        self._set_gpu_controls(False)

    def load_path(self, path):
        self._cancel()
        self._closed = False
        self._path = str(Path(path).absolute())
        self._state = dict(channel=0, mip=0, reconstruct_z=False, fit=True, zoom=1.0, pan=[0.0, 0.0])
        self._gpu = False
        self._reset_channel_controls()
        self.stack.setCurrentWidget(self.scroll)
        self.image.clear_preview("Preparing preview...")
        if self.isVisible():
            self._prepare()

    def _prepare(self, *, fallback=False):
        if not self._path or self._closed:
            return
        self._task = _PrepareTexture(self._generation, self._path, fallback=fallback, configured=self._configured)
        self._task.signals.completed.connect(self._prepared, Qt.QueuedConnection)
        self.destroyed.connect(self._task.stop.set)
        QThreadPool.globalInstance().start(self._task)

    def _prepared(self, generation, result):
        if generation != self._generation or self._closed:
            return
        self._task = None
        if result.get("executable"):
            self._start_process(result["executable"])
        elif result.get("image") is not None:
            self.stack.setCurrentWidget(self.scroll)
            self.image.set_preview_image(result["image"], Path(self._path).name)
            self._apply_view()
            self.status.clear()
            self.loaded.emit({"backend": "image"})
        else:
            self.status.setText(str(result.get("error", "No image preview available.")))
            self.failed.emit(self.status.text())

    def _start_process(self, executable):
        process = QProcess(QApplication.instance())
        self._process = process
        generation = self._generation
        owner = weakref.ref(self)
        def dispatch(method):
            current = owner()
            if current is not None and isValid(current):
                getattr(current, method)(process, generation)
        process.setProgram(executable)
        process.setArguments(["--cdmw-texture-view", "--embedded-parent-hwnd", str(int(self.viewport.winId()))])
        process.readyReadStandardOutput.connect(lambda: dispatch("_stdout"))
        process.readyReadStandardError.connect(lambda: process.readAllStandardError())
        process.finished.connect(lambda *_: dispatch("_process_failed"))
        process.errorOccurred.connect(lambda *_: dispatch("_process_failed"))
        # The application owns QProcess so deleting the viewport never blocks waiting for it.
        self.destroyed.connect(lambda *_: stop_qprocess_async(process))
        register_owned_qprocess_for_exit(process)
        self._buffer.clear()
        self._timeout.start(15000)
        process.start()

    def _send(self, **payload):
        if self._process is not None and self._ready:
            self._process.write((json.dumps(payload, allow_nan=False) + "\n").encode("utf-8"))

    def _stdout(self, process, generation):
        data = bytes(process.readAllStandardOutput())
        if process is not self._process or generation != self._generation:
            return
        self._buffer.extend(data)
        if len(self._buffer) > 65536:
            self._fallback()
            return
        while b"\n" in self._buffer:
            line, _, self._buffer = self._buffer.partition(b"\n")
            try:
                event = json.loads(line)
                self._event(event)
            except (ValueError, TypeError, KeyError):
                self._fallback()
                return

    def _event(self, event):
        if not isinstance(event, dict):
            raise ValueError("Invalid DDS preview dimensions")
        kind = event.get("event")
        if kind == "ready":
            if event.get("protocol") != "cdmw_texture_view_v1":
                self._fallback()
                return
            self._ready = True
            self.stack.setCurrentWidget(self.viewport)
            self._resize_child()
            self._send(command="load", generation=self._generation, path=self._path)
        elif kind == "error" and event.get("generation") in (0, self._generation):
            self._fallback()
        elif event.get("generation") != self._generation:
            return
        elif kind == "loaded":
            self._timeout.stop()
            self._gpu = True
            metadata = event["metadata"]
            self._size = (int(metadata["width"]), int(metadata["height"]))
            mip_count = int(metadata["mip_count"])
            if not all(1 <= value <= 16384 for value in self._size) or not 1 <= mip_count <= 15:
                raise ValueError("Invalid DDS preview dimensions")
            self.mips.blockSignals(True)
            self.mips.clear()
            self.mips.addItems([str(i) for i in range(mip_count)])
            self.mips.blockSignals(False)
            self._set_gpu_controls(True)
            self.normal_z.setEnabled(metadata["format"] in ("Bc5Unorm", "Bc5Snorm", "Rg8Unorm"))
            self.stack.setCurrentWidget(self.viewport)
            self._resize_child()
            self.status.clear()
            self._apply_view()
            self.loaded.emit({"backend": "gpu", **event})
        elif kind == "view":
            self._state = {key: value for key, value in event["state"].items() if key != "pixel_ratio"}
            self.view_state_changed.emit(self.current_display_scale(), self._state["fit"])

    def _process_failed(self, process, generation):
        if process is self._process and generation == self._generation and not self._closed:
            self._fallback()

    def _fallback(self):
        self._cancel()
        self._gpu = False
        self._reset_channel_controls()
        self.stack.setCurrentWidget(self.scroll)
        self._prepare(fallback=True)

    def _cancel(self):
        self._generation += 1
        self._timeout.stop()
        if self._task is not None:
            self._task.stop.set()
            self._task = None
        process, self._process = self._process, None
        self._ready = False
        if process is not None:
            stop_qprocess_async(process)

    def shutdown(self):
        self._closed = True
        self._cancel()

    def clear_preview(self, message="Select a file to preview it here."):
        self.shutdown()
        self._path = ""
        self._gpu = False
        self.stack.setCurrentWidget(self.scroll)
        self.image.clear_preview(message)
        self._set_gpu_controls(False)

    def hideEvent(self, event):
        self._cancel()
        super().hideEvent(event)

    def showEvent(self, event):
        super().showEvent(event)
        if self._path and not self._closed and self._process is None and self._task is None:
            self._prepare()

    def closeEvent(self, event):
        self.shutdown()
        super().closeEvent(event)

    def eventFilter(self, watched, event):
        if watched is self.viewport and event.type() in (QEvent.Resize, QEvent.DevicePixelRatioChange):
            self._resize_child()
            if event.type() == QEvent.DevicePixelRatioChange:
                self._apply_view()
        elif watched is self.viewport and event.type() == QEvent.WinIdChange and self._process is not None:
            self._cancel()
            if self.isVisible():
                self._prepare()
        return super().eventFilter(watched, event)

    def _resize_child(self):
        ratio = self.viewport.devicePixelRatioF()
        self._send(command="resize", width=max(1, int(self.viewport.width() * ratio)), height=max(1, int(self.viewport.height() * ratio)))

    def _controls_changed(self, *_):
        self._state.update(channel=self.channels.currentIndex(), mip=max(0, self.mips.currentIndex()), reconstruct_z=self.normal_z.isChecked())
        self._apply_view()

    def _apply_view(self):
        if self._gpu:
            self._send(command="view", generation=self._generation,
                       state={**self._state, "pixel_ratio": self.viewport.devicePixelRatioF()})
        else:
            self.image.set_fit_to_view(self._state["fit"])
            self.image.set_zoom_factor(self._state["zoom"])
        self.view_state_changed.emit(self.current_display_scale(), self._state["fit"])

    def current_display_scale(self):
        if not self._state["fit"]:
            return self._state["zoom"]
        if not self._gpu:
            return self.image.current_display_scale()
        if self._state["fit"]:
            width, height = (max(1, v >> self._state["mip"]) for v in self._size)
            return min(self.viewport.width() / width, self.viewport.height() / height)
        return self._state["zoom"]

    def set_fit_to_view(self, fit):
        self._state["fit"] = bool(fit)
        if fit:
            self._state["pan"] = [0.0, 0.0]
        self._apply_view()

    def set_zoom_factor(self, zoom):
        self._state["zoom"] = min(16.0, max(0.1, float(zoom)))
        self._apply_view()

    def _actual_size(self):
        self._state.update(fit=False, zoom=1.0, pan=[0.0, 0.0])
        self._apply_view()

    def _zoom_step(self, step):
        scale = self.current_display_scale()
        steps = (0.1, 0.25, 0.5, 0.75, 1.0, 1.5, 2.0, 3.0, 4.0, 6.0, 8.0, 12.0, 16.0)
        index = min(range(len(steps)), key=lambda i: abs(steps[i] - scale))
        self._state.update(fit=False, zoom=steps[min(max(index + step, 0), len(steps) - 1)])
        self._apply_view()
