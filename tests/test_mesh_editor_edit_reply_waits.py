"""What an edit's reply no longer waits for (2026-11-23).

A transform on the Demenissian Council Robes took 10-14 s in the app, though the
edit, its Morph state and the read-back of the mesh take under half a second alone.
The reply waited behind three things:

- the recovery autosave, which started 0.75 s after the edit, took the session's
  export lock before the reply was built and held it for the whole save;
- the read-back of the resident mesh, which made one pre-created temp file per
  payload (15 per Part) and never removed them, each create and read waiting for
  Python's lock behind busy threads;
- Browse's warm-ups (Finder thumbnails, item icons, Create New Item's preload),
  which paused while the editor opened but ran through every edit.
"""

from __future__ import annotations

import tempfile
import time
from pathlib import Path
from types import SimpleNamespace

import pytest

from cdmw.domain.mesh import MeshEditCommand, MeshEditSelection
from cdmw.modding.mesh_native_availability import native_mesh_core_available
from tests.test_mesh_history_journal import _open

native = pytest.mark.skipif(not native_mesh_core_available(), reason="the native mesh core is not built")


def _transform(service, session_id: str) -> None:
    service.apply_command(session_id, MeshEditCommand(
        "transform", selection=MeshEditSelection.from_maps(vertices_by_submesh={0: (0,)}),
        params={"translate": (0.25, 0.0, 0.0)}))


def _wait(check, timeout: float = 15.0) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if check():
            return True
        time.sleep(0.05)
    return bool(check())


@native
def test_the_autosave_due_during_an_editor_request_starts_after_it(tmp_path) -> None:
    service, session_id = _open(tmp_path)
    session = service._session(session_id)
    try:
        with service.foreground_request(session_id):
            _transform(service, session_id)
            requested = session.mesh_layer_autosave_requested_key
            time.sleep(1.5)  # past the autosave's 0.75 s delay
            assert session.mesh_layer_autosave_thread is None, "the autosave started during the request"
            assert session.mesh_layer_autosave_saved_key != requested
            assert session.mesh_layer_autosave_after_foreground
        assert _wait(lambda: session.mesh_layer_autosave_saved_key == requested), "the autosave never ran"
        assert not session.mesh_layer_autosave_error
        assert session.foreground_requests == 0 and not session.mesh_layer_autosave_after_foreground
    finally:
        service.close_edit_session(session_id)


@native
def test_an_autosave_outside_editor_requests_still_runs_on_its_delay(tmp_path) -> None:
    service, session_id = _open(tmp_path)
    session = service._session(session_id)
    try:
        _transform(service, session_id)
        requested = session.mesh_layer_autosave_requested_key
        assert _wait(lambda: session.mesh_layer_autosave_saved_key == requested)
    finally:
        service.close_edit_session(session_id)


def _snapshot_payloads() -> set[str]:
    root = Path(tempfile.gettempdir())
    return {path.name for path in root.glob("cdmw_mesh_preview_delta_*_editor_snapshot_*.bin")}


def _tracked_vertex_payloads() -> set[Path]:
    # The tracked set is process-wide: an earlier test's sessions can still own
    # folders in it, so only files that appear during this test are its own.
    from cdmw.modding import mesh_native_core_temp_paths as temp_paths

    with temp_paths._native_preview_delta_paths_lock:
        tracked = set(temp_paths._native_preview_delta_dirs)
    return {file for path in tracked if path.exists() for file in path.glob("*_vertices.bin")}


@native
def test_reading_the_resident_mesh_back_leaves_no_payload_files(tmp_path) -> None:
    service, session_id = _open(tmp_path)
    try:
        before = _snapshot_payloads()
        vertex_payloads_before = _tracked_vertex_payloads()
        x = float(service.working_mesh(session_id, clone=True).submeshes[0].vertices[0][0])
        _transform(service, session_id)
        assert service.native_editor_mesh_dirty(session_id)
        moved = float(service.working_mesh(session_id, clone=True).submeshes[0].vertices[0][0])
        assert moved == pytest.approx(x + 0.25)
        assert not service.native_editor_mesh_dirty(session_id)
        assert _snapshot_payloads() <= before, "the read-back left its payload files behind"
        assert _tracked_vertex_payloads() <= vertex_payloads_before, "the read-back left vertex payloads behind"
    finally:
        service.close_edit_session(session_id)


class _Archive:
    def __init__(self) -> None:
        self.holders: set[int] = set()
        self.events: list[str] = []

    def hold_background_warmups(self, owner: object) -> None:
        self.holders.add(id(owner))
        self.events.append("hold")

    def release_background_warmups(self, owner: object) -> None:
        if id(owner) in self.holders:
            self.holders.discard(id(owner))
            self.events.append("release")


def test_editor_commands_pause_browse_warmups_until_the_editor_is_idle(tmp_path, monkeypatch) -> None:
    from PySide6.QtWidgets import QApplication
    from cdmw.ui.mesh_editor import tab_rust_editor
    from tests.test_mesh_rust_editor_selection import _tab

    app = QApplication.instance() or QApplication([])
    monkeypatch.setattr(tab_rust_editor, "EDITOR_COMMAND_WARMUP_IDLE_MS", 50)
    tab = _tab(tmp_path)
    archive = _Archive()
    monkeypatch.setattr(tab, "_background_warmup_owner", lambda: archive)
    # The editor's protocol methods run on its live-edit component, which keeps the hold.
    try:
        tab._hold_warmups_for_editor_command()
        tab._hold_warmups_for_editor_command()  # the next gesture keeps the same hold
        assert len(archive.holders) == 1
        # The open's own hold is another owner and is left alone.
        archive.hold_background_warmups(tab_rust_editor.MESH_EDITOR_OPEN_WARMUP_HOLD)

        # A command ends while the next is already running: the hold stays.
        tab.standalone_rust_protocol_thread = SimpleNamespace()
        tab._release_warmups_after_editor_command()
        _wait(lambda: (app.processEvents(), False)[1], timeout=0.3)
        assert id(tab.live_edit._editor_command_warmup_token) in archive.holders

        tab.standalone_rust_protocol_thread = None
        tab._release_warmups_after_editor_command()
        assert _wait(lambda: (app.processEvents(), id(tab.live_edit._editor_command_warmup_token) not in archive.holders)[1],
                     timeout=2.0)
        assert archive.holders == {id(tab_rust_editor.MESH_EDITOR_OPEN_WARMUP_HOLD)}

        tab._hold_warmups_for_editor_command()
        tab.standalone_rust_protocol_thread = SimpleNamespace()
        tab._release_editor_command_warmups(force=True)  # shutdown releases at once
        assert id(tab.live_edit._editor_command_warmup_token) not in archive.holders
    finally:
        tab.standalone_rust_protocol_thread = None
        tab.request_shutdown()
        tab.deleteLater()
        app.processEvents()


def test_the_protocol_worker_holds_warmups_and_its_end_releases_them(tmp_path, monkeypatch) -> None:
    """The hold rides the real start and end of a protocol request."""

    from PySide6.QtWidgets import QApplication
    from cdmw.ui.mesh_editor import tab_rust_editor
    from tests.test_mesh_rust_editor_selection import _tab

    app = QApplication.instance() or QApplication([])
    monkeypatch.setattr(tab_rust_editor, "EDITOR_COMMAND_WARMUP_IDLE_MS", 50)
    tab = _tab(tmp_path)
    archive = _Archive()
    monkeypatch.setattr(tab, "_background_warmup_owner", lambda: archive)
    calls: list[str] = []
    monkeypatch.setattr(tab, "_hold_warmups_for_editor_command",
                        lambda original=tab._hold_warmups_for_editor_command: (calls.append("hold"), original())[1])
    try:
        thread = SimpleNamespace()
        tab.standalone_rust_protocol_thread = thread
        tab._hold_warmups_for_editor_command()
        monkeypatch.setattr(tab, "_start_next_rust_protocol_worker", lambda: None)
        tab._handle_rust_protocol_thread_finished(thread)
        assert tab.standalone_rust_protocol_thread is None
        assert _wait(lambda: (app.processEvents(), not archive.holders)[1], timeout=2.0)
        assert archive.events == ["hold", "release"]
    finally:
        tab.request_shutdown()
        tab.deleteLater()
        app.processEvents()
