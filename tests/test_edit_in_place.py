"""P4 V3: one process, two modes. Browse's viewport holds an edit without a second helper."""
from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pytest
from PySide6.QtCore import QProcess
from PySide6.QtWidgets import QApplication, QLabel, QSplitter, QVBoxLayout, QWidget

from cdmw.services.mesh_rust_contract import RUST_MESH_EDITOR_PROTOCOL, RUST_PREVIEW_PROTOCOL
from cdmw.ui.mesh_editor.live_edit import end_edit_prompt
from cdmw.ui.preview.engine_channel import EDIT_IN_PLACE_CAPABILITY
from tests.test_dotnet_preview_shared_host import _make_ready, _start_controller
from tests.test_dotnet_preview_shared_host import _package as _make_package

_APP = QApplication.instance() or QApplication([])


def _ready_controller(tmp_path: Path):
    controller, process, package = _start_controller(tmp_path)
    controller._test_handshake_capabilities = {EDIT_IN_PLACE_CAPABILITY}  # noqa: SLF001
    _make_ready(controller)
    controller._pending_package_generation = 0  # noqa: SLF001 - the package is shown
    return controller, process, package


def _line(payload: dict) -> bytes:
    return json.dumps(payload).encode("utf-8") + b"\n"


def _emit_stdout(process, data: bytes) -> None:
    process.stdout = data
    process.readyReadStandardOutput.emit()


def test_a_viewport_without_the_capability_cannot_edit(tmp_path: Path) -> None:
    controller, _process, _package = _start_controller(tmp_path)
    try:
        _make_ready(controller)
        assert controller.edit_in_place_blocker()
        assert controller.borrow_for_edit() is None
    finally:
        controller.shutdown()


def test_editor_lines_reach_the_edit_and_preview_lines_stay_with_the_preview(tmp_path: Path) -> None:
    controller, process, _package = _ready_controller(tmp_path)
    try:
        assert controller.edit_in_place_blocker() == ""
        channel = controller.borrow_for_edit()
        assert channel is not None and controller.editing_in_place
        assert controller.borrow_for_edit() is None  # one edit per viewport
        heard_preview, heard_edit = [], []
        controller.protocol_event.connect(lambda payload: heard_preview.append(payload.get("event")))
        channel.readyReadStandardOutput.connect(lambda: heard_edit.append(bytes(channel.readAllStandardOutput())))
        hello = {"event": "hello", "protocol": RUST_MESH_EDITOR_PROTOCOL, "child_hwnd": 7}
        _emit_stdout(process, _line(hello) + _line({"event": "view_state_changed", "protocol": RUST_PREVIEW_PROTOCOL}))
        assert heard_edit and json.loads(heard_edit[0]) == hello
        assert "hello" not in heard_preview
        # What the editor writes goes to the shared process.
        assert channel.write(_line({"event": "hello", "protocol": RUST_MESH_EDITOR_PROTOCOL})) > 0
        assert process.writes[-1]["protocol"] == RUST_MESH_EDITOR_PROTOCOL
        assert channel.processId() == controller.process_id
    finally:
        controller.shutdown()


def test_ending_the_edit_leaves_edit_mode_and_keeps_the_process(tmp_path: Path) -> None:
    controller, process, _package = _ready_controller(tmp_path)
    try:
        channel = controller.borrow_for_edit()
        finished = []
        channel.finished.connect(lambda code, status: finished.append((code, status)))
        channel.terminate()
        assert process.writes[-1] == {"event": "leave_edit", "protocol": RUST_MESH_EDITOR_PROTOCOL}
        assert channel.state() == channel.NotRunning and not controller.editing_in_place
        assert process.state() == QProcess.ProcessState.Running
        QApplication.processEvents()
        assert finished == [(0, QProcess.ExitStatus.NormalExit)]
        # The helper says edit_left later; nothing more is reported for it.
        _emit_stdout(process, _line({"event": "edit_left", "protocol": RUST_MESH_EDITOR_PROTOCOL}))
        QApplication.processEvents()
        assert len(finished) == 1
    finally:
        controller.shutdown()


def test_the_helper_leaving_edit_mode_ends_the_edit(tmp_path: Path) -> None:
    controller, process, _package = _ready_controller(tmp_path)
    try:
        channel = controller.borrow_for_edit()
        finished = []
        channel.finished.connect(lambda code, status: finished.append(code))
        _emit_stdout(process, _line({"event": "edit_left", "protocol": RUST_MESH_EDITOR_PROTOCOL}))
        QApplication.processEvents()
        assert finished == [0] and not controller.editing_in_place
        # The helper said it left: nothing is sent back.
        assert not any(write.get("event") == "leave_edit" for write in process.writes)
    finally:
        controller.shutdown()


def test_a_refused_edit_says_why(tmp_path: Path) -> None:
    controller, process, _package = _ready_controller(tmp_path)
    try:
        channel = controller.borrow_for_edit()
        reasons, finished = [], []
        channel.refused.connect(reasons.append)
        channel.finished.connect(lambda code, status: finished.append(code))
        _emit_stdout(process, _line({"event": "edit_refused", "protocol": RUST_MESH_EDITOR_PROTOCOL,
                                     "reason": "Leave the comparison view before editing the mesh here."}))
        QApplication.processEvents()
        assert reasons == ["Leave the comparison view before editing the mesh here."]
        assert channel.refusal == reasons[0] and finished == [1]
    finally:
        controller.shutdown()


def test_a_selection_made_while_editing_loads_when_the_edit_ends(tmp_path: Path) -> None:
    controller, process, _package = _ready_controller(tmp_path)
    try:
        channel = controller.borrow_for_edit()
        before = len(process.writes)
        other = _make_package(tmp_path, "package-b")
        with patch("cdmw.ui.preview.dotnet_session.validate_rust_mesh_editor_package", return_value=""):
            controller.load_package(other)
        assert not any(w.get("event") == "package_load_request" for w in process.writes[before:])
        channel.terminate()
        QApplication.processEvents()
        loads = [w for w in process.writes[before:] if w.get("event") == "package_load_request"]
        assert loads and loads[-1]["package_path"] == str(other.package_dir)
    finally:
        controller.shutdown()


def test_the_helper_exiting_is_a_crash_of_the_edit(tmp_path: Path) -> None:
    controller, process, _package = _ready_controller(tmp_path)
    try:
        channel = controller.borrow_for_edit()
        finished = []
        channel.finished.connect(lambda code, status: finished.append((code, status)))
        controller._process_finished(process, controller.process_generation, 3,  # noqa: SLF001
                                     QProcess.ExitStatus.CrashExit)
        QApplication.processEvents()
        assert finished == [(3, QProcess.ExitStatus.CrashExit)]
        assert not controller.editing_in_place
    finally:
        controller.shutdown()


class _Tab:
    """The Mesh Editor tab as the prompt sees it."""

    def __init__(self, revision: int, ready: bool = False) -> None:
        self.closed = 0
        self.finishes = 0
        self.standalone_controller = SimpleNamespace(session_view=lambda: SimpleNamespace(revision=revision))
        self.live_edit = SimpleNamespace(is_ready=ready, request_finish=self._finish)
        self._open = True

    def has_active_standalone_session(self) -> bool:
        return self._open

    def close_standalone_session(self) -> None:
        self.closed += 1

    def _finish(self) -> bool:
        self.finishes += 1
        return True

    def _current_target_entry(self):
        return SimpleNamespace(basename="cd_phm_00_ub_0001.pac")


@pytest.mark.parametrize("answer", [end_edit_prompt.FINISH, end_edit_prompt.DISCARD, end_edit_prompt.KEEP])
def test_each_answer_of_the_prompt(monkeypatch, answer) -> None:
    asked = []
    monkeypatch.setattr(end_edit_prompt, "prompt_override", lambda parent, label: asked.append(label) or answer)
    tab = _Tab(revision=2)
    assert end_edit_prompt.resolve_pending_edit(None, tab) == answer
    assert asked == ["cd_phm_00_ub_0001.pac"]
    assert tab.finishes == (answer == end_edit_prompt.FINISH)
    assert tab.closed == (answer == end_edit_prompt.DISCARD)


def test_no_question_without_a_pending_edit(monkeypatch) -> None:
    monkeypatch.setattr(end_edit_prompt, "prompt_override", lambda *_: pytest.fail("asked"))
    tab = _Tab(revision=0)
    assert end_edit_prompt.resolve_pending_edit(None, tab) == end_edit_prompt.NONE
    tab._open = False
    assert end_edit_prompt.resolve_pending_edit(None, tab) == end_edit_prompt.NONE


def test_an_open_editor_counts_as_pending_even_before_its_first_change(monkeypatch) -> None:
    monkeypatch.setattr(end_edit_prompt, "prompt_override", lambda *_: end_edit_prompt.KEEP)
    assert end_edit_prompt.resolve_pending_edit(None, _Tab(revision=0, ready=True)) == end_edit_prompt.KEEP


def _browser() -> QWidget:
    browser = QWidget()
    outer = QVBoxLayout(browser)
    browser.archive_splitter = QSplitter()
    for width in (200, 300, 700):
        pane = QWidget()
        pane.setMinimumWidth(120)
        browser.archive_splitter.addWidget(pane)
    preview = browser.archive_splitter.widget(2)
    browser.archive_preview_main_layout = QVBoxLayout(preview)
    browser.archive_preview_meta_label = QLabel("details", preview)
    browser.archive_preview_main_layout.addWidget(browser.archive_preview_meta_label)
    outer.addWidget(browser.archive_splitter)
    browser.resize(1200, 600)
    browser.archive_splitter.setSizes([200, 300, 700])
    browser.show()
    QApplication.processEvents()
    return browser


def test_the_browse_layout_gives_the_editor_the_room_and_restores_itself() -> None:
    from cdmw.ui.archive_browser.edit_in_place import STRIP_WIDTH, BrowseEditLayout

    browser = _browser()
    try:
        before = browser.archive_splitter.sizes()
        layout = BrowseEditLayout(browser)
        entry = SimpleNamespace(basename="sword.pac", identity="a")
        layout.enter(entry)
        QApplication.processEvents()
        sizes = browser.archive_splitter.sizes()
        assert sizes[0] == STRIP_WIDTH and sizes[1] == STRIP_WIDTH and sizes[2] > before[2]
        assert layout.banner.isVisible() and "sword.pac" in layout.banner_label.text()
        assert not browser.archive_preview_meta_label.isVisible()
        # Another file selected: its details show, the viewport stays on the edit.
        assert not layout.preview_selected_button.isVisible()
        layout.selection_changed(SimpleNamespace(identity="b"))
        assert layout.preview_selected_button.isVisible()
        layout.open_strips()
        assert browser.archive_splitter.sizes()[0] > STRIP_WIDTH
        layout.leave()
        QApplication.processEvents()
        assert browser.archive_splitter.sizes() == before
        assert browser.archive_preview_meta_label.isVisible() and not layout.banner.isVisible()
    finally:
        browser.deleteLater()


def test_the_borrowed_frame_accepts_only_browse_s_own_window() -> None:
    from cdmw.ui.mesh_editor.live_edit.browse_viewport import BrowseViewportBinding

    host = SimpleNamespace(_embedded_child_hwnd=77, controller=SimpleNamespace(_safe_host_hwnd=lambda: 5))
    binding = BrowseViewportBinding(host, "sword.pac")
    assert binding.frame.prepare_launch() == 5
    assert binding.frame.attach_child_window(77, 1, 5) == (True, "")
    assert binding.frame.attach_child_window(78, 1, 5)[0] is False
    heard = []
    binding.status.connect(lambda kind, message: heard.append(kind))
    binding.frame.show_editor()
    binding.frame.detach_child_window()  # the window stays Browse's
    ended = []
    binding.ended.connect(lambda: ended.append(1))
    binding.end()
    binding.end()
    from cdmw.ui.mesh_editor.live_edit.browse_viewport import STATUS_EDITING

    assert heard == [STATUS_EDITING] and ended == [1]


class _KeptSession:
    """The shadow session as crash recovery sees it."""

    def __init__(self) -> None:
        self.closed = False
        self.session_id = "shadow-1"
        self.rewrites: list[int] = []
        self.shadow_session_id = "s"
        self.shadow_service = SimpleNamespace(session_view=lambda _id: SimpleNamespace(revision=4))

    def rewrite_for_relaunch(self, generation: int) -> None:
        self.rewrites.append(generation)

    def request_cancel(self) -> bool:
        return False


def _crashing_tab(tmp_path: Path):
    from tests.test_mesh_rust_editor_selection import _BufferedProcess, _tab

    tab = _tab(tmp_path)
    session = _KeptSession()
    tab.standalone_rust_authoring_session = session
    tab.standalone_rust_hello_received = True
    tab.standalone_rust_ready = True
    process = _BufferedProcess()
    tab.standalone_rust_process = process
    return tab, session, process


def _wait_for(predicate, timeout: float = 5.0) -> None:
    import time

    deadline = time.monotonic() + timeout
    while not predicate() and time.monotonic() < deadline:
        QApplication.processEvents()
        time.sleep(0.01)
    assert predicate()


def test_a_renderer_crash_keeps_the_shadow_session_and_starts_again(tmp_path: Path) -> None:
    from tests.test_mesh_rust_editor_selection import _dispose

    tab, session, process = _crashing_tab(tmp_path)
    launched = []
    tab.live_edit._launch_rust_editor_process = lambda current: launched.append(current)
    notices = []
    tab.status_message_requested.connect(lambda message, error: notices.append(message))
    try:
        generation = tab.standalone_rust_process_generation
        tab._handle_rust_process_finished(process, 3, QProcess.ExitStatus.CrashExit)
        assert not tab.standalone_rust_dispose_pending and not session.closed
        assert any("restarted" in notice and "kept" in notice for notice in notices)
        _wait_for(lambda: launched)
        # The files were written again for the next helper, at the next generation.
        assert session.rewrites == [generation + 1] and launched == [session]
        assert tab.standalone_rust_process_generation == generation + 1
    finally:
        _dispose(tab)


@pytest.mark.parametrize("answer", ["finish", "discard"])
def test_a_second_crash_within_a_minute_offers_finish_or_discard(tmp_path: Path, monkeypatch, answer) -> None:
    from cdmw.ui.mesh_editor import tab_rust_process
    from tests.test_mesh_rust_editor_selection import _BufferedProcess, _dispose

    tab, session, process = _crashing_tab(tmp_path)
    tab.live_edit._launch_rust_editor_process = lambda current: None
    started = []
    tab.live_edit._start_next_rust_protocol_worker = lambda: started.append(list(tab.standalone_rust_protocol_queue))
    monkeypatch.setattr(tab_rust_process, "crash_prompt_override", lambda _box: answer)
    closed = []
    tab.live_edit.closed.connect(lambda: closed.append(1))
    try:
        tab._handle_rust_process_finished(process, 3, QProcess.ExitStatus.CrashExit)
        _wait_for(lambda: session.rewrites)
        again = _BufferedProcess()
        tab.standalone_rust_process = again
        tab.standalone_rust_hello_received = True
        tab._handle_rust_process_finished(again, 3, QProcess.ExitStatus.CrashExit)
        if answer == "finish":
            _wait_for(lambda: started)
            assert started[0][-1]["event"] == "finish_request" and started[0][-1]["hidden_parts"] == []
            assert not tab.standalone_rust_dispose_pending
        else:
            _wait_for(lambda: closed)  # the session was handed to disposal
        assert len(session.rewrites) == 1  # no second restart
    finally:
        _dispose(tab)


def test_closing_the_app_with_a_pending_edit_asks_first(monkeypatch) -> None:
    from cdmw.ui.shell.close_controller import CloseControllerMixin

    class _Window(CloseControllerMixin):
        def __init__(self, tab) -> None:
            self.mesh_editor_tab = tab
            self.messages: list[str] = []

        def set_status_message(self, message: str, **_kwargs) -> None:
            self.messages.append(message)

    tab = QWidget()
    tab.standalone_controller = SimpleNamespace(session_view=lambda: SimpleNamespace(revision=3))
    tab.has_active_standalone_session = lambda: True
    tab.close_standalone_session = lambda: None
    tab.live_edit = SimpleNamespace(is_ready=True, request_finish=lambda: True)
    window = _Window(tab)
    try:
        for answer, allowed in ((end_edit_prompt.KEEP, False), (end_edit_prompt.FINISH, False),
                                (end_edit_prompt.DISCARD, True)):
            monkeypatch.setattr(end_edit_prompt, "prompt_override", lambda *_args, a=answer: a)
            assert window._pending_edit_allows_close() is allowed
        assert window.messages and "Close CDMW again" in window.messages[0]
        tab.has_active_standalone_session = lambda: False
        tab.live_edit.is_ready = False
        monkeypatch.setattr(end_edit_prompt, "prompt_override", lambda *_: pytest.fail("asked"))
        assert window._pending_edit_allows_close() is True
    finally:
        tab.deleteLater()


def test_after_a_crash_the_session_files_are_written_again_at_the_accepted_step(tmp_path: Path) -> None:
    from tests.test_mesh_rust_authoring import RustMeshAuthoringTests, _candidate_reference, _request

    authoritative, session = RustMeshAuthoringTests()._create(tmp_path / "session")
    try:
        request = _request(session, "transaction_request", 1)
        request["candidate"] = _candidate_reference(session, request_id=1, first_x=0.75)
        request["label"] = "Move"
        session.apply_candidate(request)
        session.rewrite_for_relaunch(8)
        manifest = json.loads(session.manifest_path.read_text(encoding="utf-8"))
        assert manifest["process_generation"] == 8 and session.process_generation == 8
        assert manifest["shadow_revision"] == 1  # the accepted Move is what the new helper opens
        # The undo history stays in the shadow session.
        assert session.shadow_service.session_view(session.shadow_session_id).undo_count == 1
    finally:
        session.cancel()
        authoritative.close_edit_session(session.authoritative_session_id, force_without_saving=True)


def test_a_deferred_open_says_morphs_are_preparing_until_its_query_answers(tmp_path: Path) -> None:
    import threading

    from cdmw.services.mesh_rust_authoring import deferred_morph_placeholder
    from tests.test_mesh_rust_authoring import RustMeshAuthoringTests

    authoritative, session = RustMeshAuthoringTests()._create(tmp_path / "session")
    try:
        session.defer_morph_state = True
        session.deferred_morph_ready = False
        assert session.state_payload(include_document=False)["morph_refit"] == deferred_morph_placeholder()
        answered, arrived = threading.Event(), []
        assert session.query_deferred_morph_state(lambda payload: (arrived.append(payload), answered.set()))
        assert answered.wait(30)
        assert arrived[0] != deferred_morph_placeholder()
        assert session.state_payload(include_document=False)["morph_refit"] == arrived[0]
        assert not session.query_deferred_morph_state(lambda _payload: None)  # asked once
    finally:
        session.cancel()
        authoritative.close_edit_session(session.authoritative_session_id, force_without_saving=True)


# ----- one view mode, one background for every viewport (P4 V3) ----------------

def test_the_view_mode_list_is_the_union_and_old_values_migrate(tmp_path: Path) -> None:
    from PySide6.QtCore import QSettings

    from cdmw.domain.preview_view_modes import (
        LEGACY_VIEW_MODE_KEY, SHARED_VIEW_MODE_IDS, VIEW_MODE_KEY, read_view_mode, shared_view_mode, write_view_mode,
    )
    from cdmw.models import D3D11_PREVIEW_VIEW_MODES, ModelPreviewRenderSettings, clamp_model_preview_render_settings

    assert D3D11_PREVIEW_VIEW_MODES == SHARED_VIEW_MODE_IDS
    assert {"game_outdoor", "normal_map", "layer_mask", "wire", "xray", "island_colors"} <= set(SHARED_VIEW_MODE_IDS)
    assert [shared_view_mode(v) for v in ("lit", "base_direct", "part_id", "normal", "bogus")] == [
        "textured", "base_color", "part_colors", "normal_map", "textured"]
    assert clamp_model_preview_render_settings(ModelPreviewRenderSettings(d3d11_view_mode="normal")).d3d11_view_mode \
        == "normal_map"
    settings = QSettings(str(tmp_path / "s.ini"), QSettings.Format.IniFormat)
    settings.setValue(LEGACY_VIEW_MODE_KEY, "base_direct")
    assert read_view_mode(settings) == "base_color"
    write_view_mode(settings, "wire")
    assert settings.value(VIEW_MODE_KEY) == "wire" and settings.value(LEGACY_VIEW_MODE_KEY) is None


def test_the_store_carries_view_mode_and_background_to_every_viewport(tmp_path: Path) -> None:
    from PySide6.QtCore import QSettings

    from cdmw.ui.preview.preview_settings_hub import PreviewSettingsHub

    settings = QSettings(str(tmp_path / "s.ini"), QSettings.Format.IniFormat)
    settings.setValue("preview/d3d11_view_mode", "normal")
    hub = PreviewSettingsHub(settings)
    assert hub.values()["view_mode"] == "normal_map" and hub.values()["background_color"] == "#3B3B3B"
    heard = []
    hub.changed.connect(heard.append)
    assert hub.update(view_mode="xray", background_color="#0a0b0c")
    assert heard[-1]["view_mode"] == "xray" and heard[-1]["background_color"] == "#0A0B0C"
    assert settings.value("preview/view_mode") == "xray" and settings.value("preview/d3d11_view_mode") is None
    assert not hub.update(background_color="not a colour", view_mode="xray")  # invalid colour keeps the default


def test_browse_keeps_the_shared_values_another_viewport_set(monkeypatch) -> None:
    from cdmw.models import ModelPreviewRenderSettings
    from cdmw.ui.archive_browser import preview_settings

    store = SimpleNamespace(values=lambda: {"view_mode": "wire", "background_color": "#102030", "shadows": False})
    monkeypatch.setattr("cdmw.ui.preview.preview_settings_hub.preview_settings_hub", lambda: store)
    merged = preview_settings._with_shared_values(ModelPreviewRenderSettings())
    assert (merged.d3d11_view_mode, merged.d3d11_background_color, merged.preview_shadows) == ("wire", "#102030", False)


# ----- view first, tools unlock as they become ready (P4 V4) --------------------

def test_the_click_shows_the_view_and_the_session_reuses_its_channel(tmp_path: Path) -> None:
    from cdmw.ui.mesh_editor.live_edit.browse_viewport import BrowseViewportBinding

    controller, process, _package = _ready_controller(tmp_path)
    try:
        host = SimpleNamespace(controller=controller, _embedded_child_hwnd=7)
        binding = BrowseViewportBinding(host, "upper.pac")
        assert binding.show_view_now()
        assert process.writes[-1] == {"event": "enter_edit", "protocol": RUST_MESH_EDITOR_PROTOCOL, "keep_view": True}
        first = binding.channel
        viewing = []
        first.viewing_started.connect(lambda: viewing.append(1))
        _emit_stdout(process, _line({"event": "edit_viewing", "protocol": RUST_MESH_EDITOR_PROTOCOL,
                                     "install_ms": 40.0}))
        assert viewing == [1] and first.viewing
        assert first.bytesAvailable() == 0  # the engine's own line is not the editor's
        assert binding.borrow() is first  # the session opens on the same channel
        binding.end()
        assert process.writes[-1]["event"] == "leave_edit"
    finally:
        controller.shutdown()


def test_the_morph_group_is_preparing_until_its_data_comes(tmp_path: Path) -> None:
    from tests.test_mesh_rust_editor_selection import _dispose, _tab

    tab = _tab(tmp_path)
    sent = []
    tab.live_edit._send_rust_message = lambda payload: sent.append(dict(payload)) or True

    class _Session:
        closed = False
        session_id = "s"
        shadow_session_id = "x"
        defer_morph_state = True
        deferred_morph_ready = False
        shadow_service = SimpleNamespace(session_view=lambda _id: SimpleNamespace(revision=1))

        def query_deferred_morph_state(self, done):
            self.done = done
            return True

    session = _Session()
    tab.standalone_rust_authoring_session = session
    tab.standalone_rust_ready = True
    try:
        tab.live_edit._query_deferred_rust_morph_state()
        assert sent[-1]["event"] == "tool_groups"
        assert sent[-1]["groups"] == {"morph": {"ready": False, "reason": "Morph data is still being prepared."}}
        session.done({"available": True})
        _wait_for(lambda: any(message["event"] == "morph_state" for message in sent))
        assert sent[-1] == {**sent[-1], "event": "tool_groups", "groups": {}}
    finally:
        _dispose(tab)


def test_the_view_shown_at_the_click_is_handed_on_or_dropped(tmp_path: Path) -> None:
    from cdmw.models import ArchiveEntry
    from cdmw.ui.mesh_editor.shell_bridge import MeshEditorShellBridgeMixin

    entry = ArchiveEntry(path="character/model/upper.pac", pamt_path=tmp_path / "0.pamt",
                         paz_file=tmp_path / "0.paz", offset=0, comp_size=1, orig_size=1, flags=0, paz_index=0)

    class _Binding:
        def __init__(self) -> None:
            self.is_ended = False

        def show_view_now(self) -> bool:
            return True

        def end(self) -> None:
            self.is_ended = True

    made = []

    class _Harness(MeshEditorShellBridgeMixin):
        def __init__(self) -> None:
            self.archive = SimpleNamespace(
                _current_archive_entry=lambda: entry, archive_preview_request_entry=entry,
                begin_edit_in_place=lambda current: made.append(_Binding()) or made[-1])

    harness = _Harness()
    harness._show_browse_view_first(entry)
    assert harness._take_early_browse_binding(entry) is made[0]  # handed on to the open
    harness._show_browse_view_first(entry)
    harness._drop_early_browse_binding()  # the open went another way
    assert made[1].is_ended
    harness.archive.archive_preview_request_entry = ArchiveEntry(
        path="character/model/other.pac", pamt_path=tmp_path / "0.pamt", paz_file=tmp_path / "0.paz",
        offset=0, comp_size=1, orig_size=1, flags=0, paz_index=0)
    harness._show_browse_view_first(entry)  # Browse is loading another file: no view
    assert len(made) == 2
