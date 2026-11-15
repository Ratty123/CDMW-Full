"""A native job that times out ends only its own session (2026-11-13).

Until now a timed-out or cancelled job ended the whole resident native service,
and every open document's session with it: one slow open on a loaded machine
cost the other drafts their resident state too. The reviews of 7ab62e5e8 and
5d3785f5f asked for the timeout to end only the job's own session.

Real MeshService, two real drafts and the real native core. Only the client's
wait for one reply is made to give up early; the core still answers, and that
late answer must be skipped, not taken for the next job's reply.
"""

from __future__ import annotations

import pytest

from cdmw.core.common import ProcessTimeoutExpired
from cdmw.modding import mesh_native_client as client
from cdmw.modding import mesh_native_core as core
from cdmw.modding.mesh_native_availability import native_mesh_core_available
from tests.test_mesh_history_journal import _move, _open, _x

pytestmark = pytest.mark.skipif(not native_mesh_core_available(), reason="the native mesh core is not built")


@pytest.fixture
def give_up_once(monkeypatch):
    """The next reply wait for ``state["session"]`` gives up before the reply comes."""

    state: dict[str, object] = {"session": "", "gave_up": 0}
    read_reply = client.NativeMeshCoreServiceClient._read_reply_locked

    def read(self, timeout_seconds, *, stop_event, session_id=""):
        if session_id and session_id == state["session"]:
            state["session"] = ""
            state["gave_up"] = int(state["gave_up"]) + 1
            self._give_up_on_job_locked(session_id)
            raise ProcessTimeoutExpired([str(self.binary), "--service"], float(timeout_seconds))
        return read_reply(self, timeout_seconds, stop_event=stop_event, session_id=session_id)

    monkeypatch.setattr(client.NativeMeshCoreServiceClient, "_read_reply_locked", read)
    return state


def _service_process():
    service = core._native_mesh_core_service
    return None if service is None else service._process


def test_a_timed_out_job_leaves_the_other_draft_s_session_open(tmp_path, give_up_once) -> None:
    first, first_id = _open(tmp_path / "a")
    second, second_id = _open(tmp_path / "b")
    try:
        _move(first, first_id, 0.25)
        _move(second, second_id, 0.25)
        assert first._session(first_id).native_editor_session_ready
        assert second._session(second_id).native_editor_session_ready
        process = _service_process()
        assert process is not None and process.poll() is None

        give_up_once["session"] = first_id
        with pytest.raises(RuntimeError, match="ProcessTimeoutExpired"):
            _move(first, first_id, 0.25)  # its wait gives up; the core answers late; the step is refused
        assert give_up_once["gave_up"] == 1

        # The other draft keeps its resident session in the same service.
        assert _service_process() is process and process.poll() is None
        assert second._session(second_id).native_editor_session_ready
        before = _x(second, second_id)
        _move(second, second_id, 0.25)
        assert second._session(second_id).native_editor_session_ready
        assert _x(second, second_id) == pytest.approx(before + 0.25)
        assert core._native_mesh_core_service._late_replies == 0  # both late lines were skipped

        # The draft whose job timed out opens its session again on the next step.
        before = _x(first, first_id)
        _move(first, first_id, 0.25)
        assert _x(first, first_id) == pytest.approx(before + 0.25)
        assert _service_process() is process
        assert first._session(first_id).native_editor_session_ready
    finally:
        first.close_edit_session(first_id)
        second.close_edit_session(second_id)


def test_a_stuck_service_is_still_ended(tmp_path, monkeypatch) -> None:
    """Past a few owed replies the service is taken to be stuck, not slow."""

    service, session_id = _open(tmp_path)
    try:
        _move(service, session_id, 0.25)
        native = core._native_mesh_core_service
        assert native is not None and native._process is not None
        with native._lock:
            native._late_replies = client._MAX_LATE_REPLIES
            native._give_up_on_job_locked("")
            assert native._process is None and native._late_replies == 0
    finally:
        service.close_edit_session(session_id)
