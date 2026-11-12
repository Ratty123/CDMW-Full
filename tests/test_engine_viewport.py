"""P4 V5: other previews as windows of Browse's helper process, not processes of their own."""
from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

from PySide6.QtCore import QObject, QProcess
from PySide6.QtWidgets import QApplication

from cdmw.services import engine_capture
from cdmw.services.engine_capture import EngineCaptureRouter
from cdmw.services.mesh_rust_contract import RUST_PREVIEW_PROTOCOL
from cdmw.ui.preview.engine_viewport import (
    VIEWPORT_OPEN_CAPABILITY, EngineViewportChannel, engine_viewport_factory,
)
from tests.test_dotnet_preview_shared_host import _make_ready, _start_controller
from tests.test_edit_in_place import _emit_stdout, _line

_APP = QApplication.instance() or QApplication([])


def _browse(tmp_path: Path, capable: bool = True):
    controller, process, _package = _start_controller(tmp_path)
    if capable:
        controller._test_handshake_capabilities = {VIEWPORT_OPEN_CAPABILITY}  # noqa: SLF001
    _make_ready(controller)
    return controller, process


def _launched(channel: EngineViewportChannel, manifest="C:/cache/dialog/manifest.json", parent=4242):
    channel.setArguments(["--cdmw-preview-session", manifest, "--embedded-parent-hwnd", str(parent)])
    channel.start()
    QApplication.processEvents()


def test_a_dialog_window_opens_in_browse_s_process_and_its_lines_are_its_own(tmp_path: Path) -> None:
    browse, process = _browse(tmp_path)
    try:
        assert browse.viewport_blocker() == ""
        channel = EngineViewportChannel(browse)
        started = []
        channel.started.connect(lambda: started.append(True))
        _launched(channel)
        opened = process.writes[-1]
        assert opened == {"protocol": RUST_PREVIEW_PROTOCOL, "event": "viewport_open",
                          "viewport_id": channel.viewport_id, "manifest": "C:/cache/dialog/manifest.json",
                          "parent_hwnd": 4242}
        assert started == [True] and channel.processId() == browse.process_id
        # What the dialog's controller writes names its window.
        channel.write(_line({"event": "package_load_request", "session_id": "shared"}))
        assert process.writes[-1]["viewport_id"] == channel.viewport_id
        # The window's lines reach the dialog only; Browse's own handling never sees them.
        heard_browse, heard_dialog = [], []
        browse.protocol_event.connect(lambda payload: heard_browse.append(payload.get("event")))
        channel.readyReadStandardOutput.connect(lambda: heard_dialog.append(bytes(channel.readAllStandardOutput())))
        ready = {"event": "ready", "protocol": RUST_PREVIEW_PROTOCOL, "session_id": "shared",
                 "viewport_id": channel.viewport_id, "child_hwnd": 77}
        _emit_stdout(process, _line(ready) + _line({"event": "view_state_changed", "viewport_id": "closed-one"}))
        assert heard_dialog and json.loads(heard_dialog[0])["child_hwnd"] == 77
        # The dialog's controller reads it as its own process's line.
        assert "viewport_id" not in json.loads(heard_dialog[0])
        assert "ready" not in heard_browse and "view_state_changed" not in heard_browse
    finally:
        browse.shutdown()


def test_closing_the_dialog_closes_its_window_and_never_names_browse_s_process(tmp_path: Path) -> None:
    browse, process = _browse(tmp_path)
    try:
        channel = EngineViewportChannel(browse)
        _launched(channel)
        finished = []
        channel.finished.connect(lambda code, status: finished.append((code, status)))
        channel.terminate()
        assert process.writes[-1] == {"protocol": RUST_PREVIEW_PROTOCOL, "event": "close_request",
                                      "viewport_id": channel.viewport_id}
        assert channel.state() == channel.NotRunning and channel.processId() == 0
        assert browse.viewport_count == 0 and process.state() == QProcess.ProcessState.Running
        QApplication.processEvents()
        assert finished == [(0, QProcess.ExitStatus.NormalExit)]
        # The engine's own `viewport_closed` comes later and changes nothing.
        _emit_stdout(process, _line({"event": "viewport_closed", "viewport_id": channel.viewport_id}))
        QApplication.processEvents()
        assert len(finished) == 1
    finally:
        browse.shutdown()


def test_a_refused_window_and_browse_exiting_end_the_dialog_s_process_view(tmp_path: Path) -> None:
    browse, process = _browse(tmp_path)
    try:
        reasons = []
        refused = EngineViewportChannel(browse, on_refused=reasons.append)
        _launched(refused)
        finished = []
        refused.finished.connect(lambda code, status: finished.append(code))
        _emit_stdout(process, _line({"event": "viewport_refused", "viewport_id": refused.viewport_id,
                                     "reason": "the preview's renderer is not ready"}))
        QApplication.processEvents()
        assert reasons == ["the preview's renderer is not ready"] and finished == [1]

        lost = EngineViewportChannel(browse)
        _launched(lost)
        crashed = []
        lost.finished.connect(lambda code, status: crashed.append((code, status)))
        browse._process_finished(process, browse.process_generation, 3,  # noqa: SLF001
                                 QProcess.ExitStatus.CrashExit)
        QApplication.processEvents()
        assert crashed == [(3, QProcess.ExitStatus.CrashExit)] and browse.viewport_count == 0
    finally:
        browse.shutdown()


def test_without_the_capability_the_window_fails_to_start(tmp_path: Path) -> None:
    browse, _process = _browse(tmp_path, capable=False)
    try:
        assert browse.viewport_blocker()
        reasons, errors = [], []
        channel = EngineViewportChannel(browse, on_refused=reasons.append)
        channel.errorOccurred.connect(errors.append)
        _launched(channel)
        assert errors == [QProcess.ProcessError.FailedToStart] and reasons
        assert channel.state() == channel.NotRunning
    finally:
        browse.shutdown()


class _Resident(QObject):
    from PySide6.QtCore import Signal as _Signal

    protocol_event = _Signal(object)
    state_changed = _Signal(str, str)

    def __init__(self, blocker=""):
        super().__init__()
        self.is_running = True
        self.capabilities = frozenset()
        self.blocker = blocker

    def viewport_blocker(self):
        return self.blocker


def test_the_factory_gives_a_window_only_while_browse_s_process_can_open_one(monkeypatch) -> None:
    router = EngineCaptureRouter()
    browse = _Resident()
    router.register(browse, resident=True)
    monkeypatch.setattr(engine_capture, "engine_capture_router", lambda: router)
    refusals: dict = {}
    make = engine_viewport_factory(refusals)
    dialog = QObject()
    first = make(dialog)
    assert isinstance(first, EngineViewportChannel)
    first._refused("no room")  # noqa: SLF001 - Browse's process said no once
    assert isinstance(make(dialog), QProcess)  # this dialog launches its own from now on
    assert isinstance(make(QObject()), EngineViewportChannel)  # other dialogs still ask
    browse.blocker = "the preview process is not ready"
    assert isinstance(make(QObject()), QProcess)
    browse.is_running = False
    assert isinstance(make(QObject()), QProcess)


def test_a_dialog_controller_launches_into_browse_s_process(tmp_path: Path, monkeypatch) -> None:
    from cdmw.ui.preview.dotnet_session import RustPreviewSessionController
    from cdmw.ui.preview.profile import DotNetPreviewProfile
    from tests.test_dotnet_preview_shared_host import _own, _package, _resolution

    (tmp_path / "browse").mkdir()
    browse, process = _browse(tmp_path / "browse")
    router = EngineCaptureRouter()
    router.register(browse, resident=True)
    monkeypatch.setattr(engine_capture, "engine_capture_router", lambda: router)
    executable = tmp_path / "helper.exe"
    executable.write_bytes(b"test")
    dialog = _own(RustPreviewSessionController(host_hwnd=lambda: 9001, profile=DotNetPreviewProfile.PREVIEW,
                                          configured_executable=executable, terminate_on_close=True,
                                          process_factory=engine_viewport_factory()))
    try:
        with (
            patch("cdmw.ui.preview.dotnet_session.resolve_rust_mesh_editor", return_value=_resolution(executable)),
            patch("cdmw.ui.preview.dotnet_session.validate_rust_mesh_editor_package", return_value=""),
        ):
            assert dialog.load_package(_package(tmp_path, "dialog-package"))
        QApplication.processEvents()
        opened = [write for write in process.writes if write.get("event") == "viewport_open"]
        assert len(opened) == 1 and opened[0]["parent_hwnd"] == 9001
        assert isinstance(dialog.process, EngineViewportChannel)
        assert dialog.process_id == browse.process_id
    finally:
        dialog.shutdown()
        browse.shutdown()


def test_a_page_opens_in_browse_s_process_and_its_lines_are_its_own(tmp_path: Path) -> None:
    from cdmw.ui.preview.engine_viewport import NEW_ITEM_UI_PROTOCOL, PAGE_OPEN_CAPABILITY, EnginePageChannel

    controller, process, _package = _start_controller(tmp_path)
    controller._test_handshake_capabilities = {PAGE_OPEN_CAPABILITY}  # noqa: SLF001
    _make_ready(controller)
    try:
        assert controller.page_blocker() == ""
        page = EnginePageChannel(controller)
        page.setArguments(["--cdmw-new-item-session", "C:/sessions/studio.json", "--embedded-parent-hwnd", "55"])
        page.start()
        QApplication.processEvents()
        assert process.writes[-1] == {"protocol": NEW_ITEM_UI_PROTOCOL, "type": "page_open",
                                      "page_id": page.window_id, "manifest": "C:/sessions/studio.json",
                                      "parent_hwnd": 55}
        # The tab's own messages name the page; its replies come back without the id.
        page.write(_line({"protocol": NEW_ITEM_UI_PROTOCOL, "session": "s", "type": "shutdown"}))
        assert process.writes[-1]["page_id"] == page.window_id and page.bytesToWrite() == 0
        heard = []
        page.readyReadStandardOutput.connect(lambda: heard.append(bytes(page.readAllStandardOutput())))
        _emit_stdout(process, _line({"protocol": NEW_ITEM_UI_PROTOCOL, "type": "ready", "session": "s",
                                     "page_id": page.window_id, "child_hwnd": 66}))
        assert heard and json.loads(heard[0]) == {"protocol": NEW_ITEM_UI_PROTOCOL, "type": "ready",
                                                  "session": "s", "child_hwnd": 66}
        finished = []
        page.finished.connect(lambda code, status: finished.append(code))
        _emit_stdout(process, _line({"protocol": NEW_ITEM_UI_PROTOCOL, "type": "page_closed",
                                     "page_id": page.window_id}))
        QApplication.processEvents()
        assert finished == [0] and controller.page_count == 0
    finally:
        controller.shutdown()


def test_the_page_factory_asks_browse_s_process_first(monkeypatch) -> None:
    from cdmw.ui.preview.engine_viewport import EnginePageChannel, engine_page_factory

    router = EngineCaptureRouter()

    class _PageResident(_Resident):
        def page_blocker(self):
            return self.blocker

    browse = _PageResident()
    router.register(browse, resident=True)
    monkeypatch.setattr(engine_capture, "engine_capture_router", lambda: router)
    make = engine_page_factory()
    assert isinstance(make(QObject()), EnginePageChannel)
    browse.blocker = "this preview process cannot open pages"
    assert isinstance(make(QObject()), QProcess)
