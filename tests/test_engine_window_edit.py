"""P4 V5: the Mesh Editor tab's editor in a window of Browse's process, not a process of its own."""
from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

from PySide6.QtCore import QObject, QProcess, Signal
from PySide6.QtWidgets import QApplication

from cdmw.services import engine_capture
from cdmw.services.engine_capture import EngineCaptureRouter
from cdmw.services.mesh_rust_contract import RUST_MESH_EDITOR_PROTOCOL
from cdmw.ui.preview.engine_channel import (
    EDIT_IN_PLACE_CAPABILITY, OWN_VIEWPORT_EDIT_CAPABILITY, EngineEditChannel,
)
from tests.test_dotnet_preview_shared_host import _make_ready, _start_controller
from tests.test_edit_in_place import _emit_stdout, _line

_APP = QApplication.instance() or QApplication([])


def _ready_controller(tmp_path: Path, capabilities=(EDIT_IN_PLACE_CAPABILITY, OWN_VIEWPORT_EDIT_CAPABILITY)):
    controller, process, package = _start_controller(tmp_path)
    controller._test_handshake_capabilities = set(capabilities)  # noqa: SLF001
    _make_ready(controller)
    controller._pending_package_generation = 0  # noqa: SLF001 - the package is shown
    return controller, process


def test_a_process_without_the_capability_holds_no_editor_window(tmp_path: Path) -> None:
    controller, _process = _ready_controller(tmp_path, capabilities=(EDIT_IN_PLACE_CAPABILITY,))
    try:
        assert controller.window_edit_blocker()
        assert controller.borrow_for_window_edit() is None
    finally:
        controller.shutdown()


def test_the_tab_s_window_takes_the_editor_lines_and_browse_keeps_previewing(tmp_path: Path) -> None:
    controller, process = _ready_controller(tmp_path)
    try:
        channel = controller.borrow_for_window_edit()
        assert channel is not None and channel.own_window and controller.editing_in_own_window
        # One edit per process: neither another window nor Browse's viewport now.
        assert controller.borrow_for_window_edit() is None and controller.borrow_for_edit() is None
        assert "Mesh Editor tab" in controller.edit_in_place_blocker()
        assert not controller.editing_in_place  # Browse's own loads are not held back
        heard = []
        channel.readyReadStandardOutput.connect(lambda: heard.append(bytes(channel.readAllStandardOutput())))
        hello = {"event": "hello", "protocol": RUST_MESH_EDITOR_PROTOCOL, "child_hwnd": 9}
        _emit_stdout(process, _line(hello))
        assert heard and json.loads(heard[0]) == hello
        channel.terminate()
        assert process.writes[-1] == {"event": "leave_edit", "protocol": RUST_MESH_EDITOR_PROTOCOL}
        assert not controller.editing_in_own_window and controller.window_edit_blocker() == ""
    finally:
        controller.shutdown()


def test_browse_exiting_is_a_crash_of_the_tab_s_edit(tmp_path: Path) -> None:
    controller, process = _ready_controller(tmp_path)
    try:
        channel = controller.borrow_for_window_edit()
        finished = []
        channel.finished.connect(lambda code, status: finished.append((code, status)))
        controller._process_finished(process, controller.process_generation, 5,  # noqa: SLF001
                                     QProcess.ExitStatus.CrashExit)
        QApplication.processEvents()
        assert finished == [(5, QProcess.ExitStatus.CrashExit)] and not controller.editing_in_own_window
    finally:
        controller.shutdown()


class _Resident(QObject):
    protocol_event = Signal(object)
    state_changed = Signal(str, str)

    def __init__(self) -> None:
        super().__init__()
        self.is_running = True
        self.capabilities = frozenset()
        self.writes: list[dict] = []
        self.channel = None

    def borrow_for_window_edit(self, parent=None):
        def write(data: bytes) -> int:
            self.writes.append(json.loads(bytes(data)))
            return len(data)

        self.channel = EngineEditChannel(write, lambda: 4321, lambda _channel: None, parent)
        self.channel.own_window = True
        return self.channel


def test_only_a_resident_running_process_is_offered_for_the_tab() -> None:
    router = EngineCaptureRouter()
    dialog, browse = _Resident(), _Resident()
    router.register(browse, resident=True)
    router.register(dialog)
    assert router.resident_controller() is browse
    browse.is_running = False
    assert router.resident_controller() is None


def test_the_tab_opens_its_editor_in_browse_s_process_and_falls_back_once_refused(tmp_path: Path, monkeypatch) -> None:
    from tests.test_mesh_rust_editor_selection import _dispose, _tab

    router = EngineCaptureRouter()
    browse = _Resident()
    router.register(browse, resident=True)
    monkeypatch.setattr(engine_capture, "engine_capture_router", lambda: router)
    tab = _tab(tmp_path)
    live = tab.live_edit
    session = SimpleNamespace(manifest_path=tmp_path / "manifest.json", closed=False, theme=None)
    launched = []
    monkeypatch.setattr(live, "_launch_rust_editor_process", lambda current: launched.append(current))
    try:
        live.standalone_rust_authoring_session = session
        assert live._open_in_engine_window(session, 777)
        opened = browse.writes[-1]
        assert opened["event"] == "open_session" and opened["viewport"] == "own"
        assert opened["parent_hwnd"] == 777 and opened["manifest"] == str(session.manifest_path)
        assert live.standalone_rust_process is browse.channel
        # Browse's process cannot hold it: the same session opens in a process of its own.
        browse.channel.feed(_line({"event": "edit_refused", "protocol": RUST_MESH_EDITOR_PROTOCOL,
                                   "reason": "an edit is already open in this viewport"}))
        QApplication.processEvents()
        assert launched == [session]
        assert not live._open_in_engine_window(session, 777)  # not asked again
    finally:
        _dispose(tab)


def test_no_spare_editor_is_started_while_browse_s_process_can_hold_the_window(tmp_path: Path, monkeypatch) -> None:
    from cdmw.ui.mesh_editor import tab_rust_process
    from tests.test_mesh_rust_editor_selection import _dispose, _tab

    router = EngineCaptureRouter()
    browse = _Resident()
    browse.capabilities = frozenset({OWN_VIEWPORT_EDIT_CAPABILITY})
    router.register(browse, resident=True)
    monkeypatch.setattr(engine_capture, "engine_capture_router", lambda: router)
    monkeypatch.setenv(tab_rust_process.EDITOR_SPARE_ENV, "1")
    tab = _tab(tmp_path)
    live = tab.live_edit
    started = []
    monkeypatch.setattr(live, "_rust_editor_spare",
                        lambda: started.append(True) or SimpleNamespace(matches=lambda *_args: True))
    try:
        live._ensure_rust_editor_spare("C:/helper.exe", "signature")
        assert started == []
        browse.is_running = False  # Browse's process is gone: the spare is worth starting again
        live._ensure_rust_editor_spare("C:/helper.exe", "signature")
        host = getattr(live, "standalone_native_host_frame", None)
        if host is not None and int(host.host_hwnd() or 0) > 0:
            assert started == [True]
    finally:
        _dispose(tab)
