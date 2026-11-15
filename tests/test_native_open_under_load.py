"""Finish does not fail because the native core is slow to open a session (2026-11-13).

Journey 3 saw "Resident C++ Edit Mesh session failed to open" after Finish in 3 of 5
runs: Finish's commit reopens the document's resident C++ session with a 10 s
limit, the open took 6 to 10 s on a loaded machine (0.7 s idle), and a timed-out
job ends the whole native service, the editor's own session with it.

Real MeshService, real draft, the real native core and Finish's own reopen step
(``_ensure_native_morph_session_locked``). Only the time the core takes to answer
``open`` is made 11 s: a reply wait shorter than that times out exactly as the
client does then (it ends the service and raises); a longer one gets the answer.
"""

from __future__ import annotations

import threading

import pytest

from cdmw.core.common import ProcessTimeoutExpired
from cdmw.modding import mesh_native_client as client
from cdmw.modding.mesh_native_availability import native_mesh_core_available
from cdmw.services.mesh_service import _close_native_editor_session
from tests.test_mesh_history_journal import _move, _open

SLOW_OPEN_SECONDS = 11.0


@pytest.fixture
def slow_open(monkeypatch):
    state = threading.local()
    run_inline = client.NativeMeshCoreServiceClient.run_inline_job
    read = client.NativeMeshCoreServiceClient._read_stdout_line_locked
    waits: list[float] = []

    def run_inline_job(self, command, payload, **kwargs):
        state.open = dict(payload).get("command") == "open"
        try:
            return run_inline(self, command, payload, **kwargs)
        finally:
            state.open = False

    def read_line(self, timeout_seconds, *, stop_event=None, keep_alive=False):
        if getattr(state, "open", False):
            waits.append(float(timeout_seconds))
            if timeout_seconds < SLOW_OPEN_SECONDS:
                if not keep_alive:
                    self._kill_locked()  # what the client does when the reply is late
                raise ProcessTimeoutExpired([str(self.binary), "--service"], float(timeout_seconds))
        return read(self, timeout_seconds, stop_event=stop_event, keep_alive=keep_alive)

    monkeypatch.setattr(client.NativeMeshCoreServiceClient, "run_inline_job", run_inline_job)
    monkeypatch.setattr(client.NativeMeshCoreServiceClient, "_read_stdout_line_locked", read_line)
    return waits


@pytest.mark.skipif(not native_mesh_core_available(), reason="the native mesh core is not built")
def test_finish_s_reopen_waits_for_a_slow_native_open(tmp_path, slow_open) -> None:
    service, session_id = _open(tmp_path)
    try:
        _move(service, session_id, 0.25)
        session = service._session(session_id)
        with session.export_lock:
            # As Finish finds the document: its geometry current in Python, no resident session.
            service._working_mesh_locked(session, clone=False)
            _close_native_editor_session(session)
            assert not session.native_editor_session_ready
            service._ensure_native_morph_session_locked(session)
        assert session.native_editor_session_ready
        assert slow_open and min(slow_open) >= SLOW_OPEN_SECONDS, slow_open
    finally:
        service.close_edit_session(session_id)
