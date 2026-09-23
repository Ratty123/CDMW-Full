"""Opt-in Rust presentation with its intact Classic workflow available in-session."""

from __future__ import annotations

import hashlib
import json

from PySide6.QtCore import QElapsedTimer, QEvent, QProcess, QThread, QTimer, Qt, Signal, Slot
from PySide6.QtWidgets import QHBoxLayout, QLabel, QPushButton, QStackedWidget, QVBoxLayout, QWidget
from shiboken6 import isValid

from cdmw.services.new_item_rust_protocol import JsonLineReader, PROTOCOL, PresentationProtocolError, encode_message
from cdmw.services.new_item_rust_runtime import prepare_new_item_ui
from cdmw.services.active_ui_translation import active_ui_localizer
from cdmw.ui.mesh_editor.rust_host import RustMeshEditorHostFrame
from cdmw.ui.new_item.rust_ui_bridge import NewItemPresentationBridge
from cdmw.ui.new_item.rust_ui_dialogs import PresentationDialogs
from cdmw.ui.new_item.rust_ui_portals import PreviewPortals
from cdmw.ui.new_item.tab import NewItemStudioTab
from cdmw.workers.utility_workers import UtilityWorker


class RustNewItemStudioTab(QWidget):
    status_message_requested = Signal(str, bool)
    open_archive_entry_requested = Signal(str)
    _input_received = Signal(object)

    def __init__(self, parent=None, *, window=None, service=None, workflow=None):
        super().__init__(parent)
        self.setObjectName("new_item_rust_studio")
        self._window = window
        self.workflow = workflow or NewItemStudioTab(window=window, service=service)
        self.controller = self.workflow.controller
        self.log = self.workflow.log
        self.workflow.status_message_requested.connect(self.status_message_requested.emit)
        self.workflow.open_archive_entry_requested.connect(self.open_archive_entry_requested.emit)
        self._closed = False
        self._rust_mode = False
        self._process = None
        self._prepare_thread = None
        self._prepare_worker = None
        self._launch = None
        self._ready = False
        self._stopping = False
        self._restart_pending = False
        self._reader = JsonLineReader()
        self._stderr = ""
        self._sent_generation = 0
        self._received_generation = 0
        self._state_fingerprint = b""
        self._state_delivery = QElapsedTimer()
        self._bridge = None

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(6)
        bar = QHBoxLayout()
        self._mode_note = QLabel("Experimental interface · same item workflow")
        bar.addWidget(self._mode_note, 1)
        self._rust_button = QPushButton("Rust")
        self._classic_button = QPushButton("Classic")
        for button in (self._rust_button, self._classic_button):
            button.setCheckable(True)
            bar.addWidget(button)
        self._rust_button.clicked.connect(self.use_rust)
        self._classic_button.clicked.connect(self.use_classic)
        layout.addLayout(bar)
        self._pages = QStackedWidget()
        layout.addWidget(self._pages, 1)
        self._host = RustMeshEditorHostFrame()
        self._host.setObjectName("NewItemRustHost")
        self._host.show_loading("Preparing the Rust New Item interface…")
        self._host.retry_requested.connect(self._retry)
        self._pages.addWidget(self._host)
        self._classic_page = QWidget()
        self._classic_layout = QVBoxLayout(self._classic_page)
        self._classic_layout.setContentsMargins(0, 0, 0, 0)
        self._pages.addWidget(self._classic_page)
        self._portals = PreviewPortals(self._host)
        self._dialogs = PresentationDialogs(self.workflow, self)
        self._dialogs.changed.connect(self._publish_state)
        self._timer = QTimer(self)
        self._timer.setInterval(100)
        self._timer.timeout.connect(self._publish_state)
        self._startup_deadline = QTimer(self)
        self._startup_deadline.setSingleShot(True)
        self._startup_deadline.timeout.connect(lambda: self._fail("The Rust interface did not finish starting within 30 seconds."))
        self._stop_deadline = QTimer(self)
        self._stop_deadline.setSingleShot(True)
        self._stop_deadline.timeout.connect(self._kill_process)
        self._input_received.connect(self._dispatch_input, Qt.QueuedConnection)
        self._rust_button.setChecked(True)

    def prefill_template(self, key):
        self.workflow.prefill_template(key)

    def open_model_source(self, path):
        self.workflow.open_model_source(path)

    def showEvent(self, event):  # noqa: N802
        super().showEvent(event)
        if self._bridge is None and not self._closed:
            self.use_rust()
        elif self._rust_mode and not self._closed:
            self.workflow.show()
            if self._ready:
                self._timer.start()
                self._state_fingerprint = b""
                self._publish_state()

    def hideEvent(self, event):  # noqa: N802
        super().hideEvent(event)
        if self._rust_mode:
            self._timer.stop()
            self.workflow.hide()

    @Slot()
    def use_rust(self):
        if self._closed or self._dialogs.dialogs() or self._dialogs.native_modal():
            return
        if self._rust_mode and not self._stopping and (self._process is not None or self._prepare_thread is not None):
            return
        self._rust_mode = True
        self._rust_button.setChecked(True)
        self._classic_button.setChecked(False)
        self._pages.setCurrentWidget(self._host)
        self._classic_layout.removeWidget(self.workflow)
        self.workflow.setParent(None, Qt.Tool | Qt.FramelessWindowHint)
        localizer = active_ui_localizer()
        if localizer is not None:
            localizer.register_root(self.workflow)
        self.workflow.setAttribute(Qt.WA_DontShowOnScreen, True)
        self.workflow.resize(max(800, self.width()), max(600, self.height() - 40))
        self.workflow.setPalette(self.palette())
        self.workflow.setFont(self.font())
        self.workflow.show()
        self._dialogs.active = True
        if self._process is None and self._prepare_thread is None:
            self._start_prepare()
        elif self._stopping:
            self._restart_pending = True

    @Slot()
    def use_classic(self):
        if self._dialogs.dialogs() or self._dialogs.native_modal():
            self.status_message_requested.emit("Complete the open dialog before changing interface.", True)
            return
        self._rust_mode = False
        self._restart_pending = False
        self._rust_button.setChecked(False)
        self._classic_button.setChecked(True)
        self._dialogs.active = False
        self._portals.restore()
        self._stop_renderer()
        self.workflow.hide()
        self.workflow.setAttribute(Qt.WA_DontShowOnScreen, False)
        self.workflow.setParent(self._classic_page)
        self._classic_layout.addWidget(self.workflow)
        self._pages.setCurrentWidget(self._classic_page)
        self.workflow.show()

    def _start_prepare(self):
        self._stopping = False
        self._restart_pending = False
        self._bridge = NewItemPresentationBridge(self.workflow, dialogs=self._dialogs.dialogs,
                                                 native_modal=self._dialogs.native_modal)
        self._host.show_loading("Checking the Rust helper and preparing the interface…")
        session = self._bridge.session
        worker = UtilityWorker(lambda log, stop: prepare_new_item_ui(session, log, stop), task_accepts_cancel=True)
        thread = QThread(self)
        worker.moveToThread(thread)
        thread.started.connect(worker.run)
        worker.completed.connect(self._launch_ready)
        worker.error.connect(self._prepare_failed)
        worker.finished.connect(thread.quit, Qt.DirectConnection)
        worker.finished.connect(worker.deleteLater)
        thread.finished.connect(self._prepare_finished)
        thread.finished.connect(thread.deleteLater)
        self._prepare_thread, self._prepare_worker = thread, worker
        thread.start()

    @Slot(object)
    def _launch_ready(self, launch):
        if self._closed or not self._rust_mode or self._stopping:
            launch.cleanup()
            return
        self._launch = launch
        self._ready = False
        self._stopping = False
        self._reader = JsonLineReader()
        self._stderr = ""
        self._state_fingerprint = b""
        self._sent_generation = self._received_generation = 0
        process = QProcess(self)
        self._process = process
        process.setProcessChannelMode(QProcess.SeparateChannels)
        process.readyReadStandardOutput.connect(self._read_stdout)
        process.readyReadStandardError.connect(self._read_stderr)
        process.finished.connect(self._process_finished)
        process.errorOccurred.connect(self._process_error)
        parent_hwnd = self._host.prepare_launch()
        process.setProgram(launch.executable)
        process.setArguments(["--cdmw-new-item-session", str(launch.manifest), "--embedded-parent-hwnd", str(parent_hwnd)])
        process.start()
        self._startup_deadline.start(30000)

    @Slot(str)
    def _prepare_failed(self, message):
        if self._rust_mode and not self._closed and not self._stopping:
            self._fail(message)

    @Slot()
    def _prepare_finished(self):
        self._prepare_thread = self._prepare_worker = None
        self._restart_if_idle()

    def _restart_if_idle(self):
        if (self._restart_pending and self._rust_mode and not self._closed
                and self._process is None and self._prepare_thread is None):
            self._start_prepare()

    @Slot()
    def _read_stderr(self):
        if self._process is not None:
            self._stderr = (self._stderr + bytes(self._process.readAllStandardError()).decode("utf-8", errors="replace"))[-8000:]

    @Slot()
    def _read_stdout(self):
        if self._process is None:
            return
        try:
            for message in self._reader.feed(bytes(self._process.readAllStandardOutput())):
                self._handle_message(message)
        except (PresentationProtocolError, ValueError, TypeError) as error:
            self._fail(str(error))

    def _handle_message(self, message):
        if self._bridge is None or message.get("session") != self._bridge.session:
            raise PresentationProtocolError("The Rust interface reported a different session.")
        kind = message.get("type")
        if kind == "ready":
            attached, reason = self._host.attach_child_window(message.get("child_hwnd", 0),
                int(self._process.processId()), message.get("embedded_parent_hwnd", 0))
            if not attached:
                self._fail(reason)
                return
            self._ready = True
            self._startup_deadline.stop()
            self._timer.start()
            self._publish_state()
        elif kind == "input":
            self._input_received.emit(message)
        elif kind == "state_received":
            generation = message.get("generation")
            if type(generation) is not int or not self._received_generation <= generation <= self._sent_generation:
                raise PresentationProtocolError("Invalid presentation state acknowledgement.")
            self._received_generation = generation
        elif kind == "layout":
            if message.get("generation") == self._sent_generation and self._rust_mode and self.isVisible():
                self._portals.update(self._bridge.document, message)
        elif kind == "failed":
            self._fail(str(message.get("message", "The Rust renderer stopped.")))
        else:
            raise PresentationProtocolError("Unknown Rust presentation message.")

    @Slot(object)
    def _dispatch_input(self, message):
        if not self._rust_mode or self._closed or self._stopping or self._bridge is None:
            return
        bridge = self._bridge
        try:
            response = bridge.dispatch(message)
            self._send(response)
        except (PresentationProtocolError, ValueError, RuntimeError) as error:
            self._send({"type": "rejected", "request": message.get("request", 0), "message": str(error)})
        finally:
            self._state_fingerprint = b""
            self._publish_state()

    @Slot()
    def _publish_state(self):
        if (self._sent_generation > self._received_generation and self._state_delivery.isValid()
                and self._state_delivery.elapsed() > 10000 and self._ready and not self._stopping):
            self._fail("The Rust interface stopped acknowledging updates. Your item remains available in Classic.")
            return
        if (not self._ready or self._closed or not self._rust_mode or self._stopping or not self.isVisible()
                or self._sent_generation > self._received_generation or self._bridge is None):
            return
        try:
            state = self._bridge.snapshot()
            stable = {key: value for key, value in state.items() if key != "generation"}
            fingerprint = hashlib.blake2s(json.dumps(stable, ensure_ascii=False, sort_keys=True).encode("utf-8")).digest()
            if fingerprint == self._state_fingerprint:
                return
            self._send(state)
            self._state_fingerprint = fingerprint
            self._sent_generation = state["generation"]
            self._state_delivery.start()
        except (PresentationProtocolError, RuntimeError, ValueError) as error:
            self._fail(f"The Rust interface could not prepare this page: {error}")

    def _send(self, message):
        if self._process is None or self._process.state() != QProcess.Running or self._bridge is None:
            return
        payload = encode_message({"session": self._bridge.session, **message})
        if self._process.bytesToWrite() > 32 * 1024 * 1024:
            raise PresentationProtocolError("The Rust interface is not consuming state updates.")
        self._process.write(payload)

    @Slot(QProcess.ProcessError)
    def _process_error(self, error):
        if error == QProcess.FailedToStart:
            self._fail(f"The Rust interface could not start: {self._process.errorString()}")
            self._process_finished()

    @Slot()
    def _process_finished(self, *_args):
        self._startup_deadline.stop()
        self._stop_deadline.stop()
        self._timer.stop()
        self._ready = False
        self._portals.restore()
        self._host.detach_child_window()
        process, self._process = self._process, None
        if process is not None:
            process.deleteLater()
        if self._launch is not None:
            self._launch.cleanup()
            self._launch = None
        if not self._stopping and not self._closed and self._rust_mode:
            self._host.show_error("The Rust interface stopped. Your item remains available in Classic.\n" + self._stderr[-2000:])
        self._restart_if_idle()

    def _fail(self, message):
        self._restart_pending = False
        self._host.show_error(message)
        self.status_message_requested.emit(message, True)
        self._stop_renderer()

    @Slot()
    def _retry(self):
        if self._process is None and self._prepare_thread is None and self._rust_mode and not self._closed:
            self._start_prepare()
        elif self._rust_mode and not self._closed:
            self._restart_pending = True

    def _stop_renderer(self):
        self._timer.stop()
        self._startup_deadline.stop()
        self._stopping = True
        self._ready = False
        if self._prepare_worker is not None and isValid(self._prepare_worker):
            self._prepare_worker.stop()
        if self._process is not None and self._process.state() != QProcess.NotRunning:
            self._send({"type": "shutdown"})
            self._stop_deadline.start(2000)
        if self._bridge is not None:
            self._bridge.close()

    @Slot()
    def _kill_process(self):
        if self._process is not None and self._process.state() != QProcess.NotRunning:
            self._process.kill()

    def changeEvent(self, event):  # noqa: N802
        super().changeEvent(event)
        if hasattr(self, "workflow") and event.type() in (QEvent.PaletteChange, QEvent.FontChange):
            self.workflow.setPalette(self.palette())
            self.workflow.setFont(self.font())
            self._state_fingerprint = b""

    def resizeEvent(self, event):  # noqa: N802
        super().resizeEvent(event)
        if self._rust_mode:
            self.workflow.resize(max(800, self.width()), max(600, self.height() - 40))

    def iter_shutdown_workers(self):
        workers = list(self.workflow.iter_shutdown_workers())
        if self._prepare_thread is not None:
            workers.append(("new_item_rust_prepare", self._prepare_thread, self._prepare_worker))
        if self._process is not None and self._process.state() != QProcess.NotRunning:
            workers.append(("new_item_rust_process", self._process, self))
        return tuple(workers)

    def request_shutdown(self):
        if self._closed:
            return
        self._closed = True
        self._restart_pending = False
        self._dialogs.close()
        self._portals.restore()
        self._stop_renderer()
        self.workflow.request_shutdown()
        self.workflow.hide()
        # Rust mode uses an offscreen top-level QWidget. Return its ownership
        # before this container is destroyed after the shell drains its workers.
        self.workflow.setParent(self._classic_page)

    def shutdown(self):
        self.request_shutdown()

    def closeEvent(self, event):  # noqa: N802
        self.request_shutdown()
        super().closeEvent(event)
