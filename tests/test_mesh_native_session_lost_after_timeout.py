"""A resident job that times out costs its session; the next use opens it again.

Built-app passes 9 and 11 (2026-11-16): a 5 s session job on the Mesh Editor's
shadow session timed out while the machine was busy. The mesh-core client then
closed that session in the core, as designed, but the mesh service still took
it for open, so every later query got "missing mesh editor session" and Finish
failed at once with "Resident C++ morph_state failed.".

These run against the real resident core (skipped without it; point
CDMW_MESH_CORE_BIN at a built cdmw-mesh-core.exe). Only the 5 s wait is
skipped: the request reaches the core and the client's own timeout handling
runs, so the core really closes the session.
"""

from __future__ import annotations

from contextlib import contextmanager
from types import SimpleNamespace

import pytest

from cdmw.core.common import ProcessTimeoutExpired
from cdmw.modding import mesh_native_client, mesh_native_core
from cdmw.services.mesh_rust_authoring import RustMeshAuthoringSession
from cdmw.services.mesh_service import MeshService


@contextmanager
def _one_timed_out_query(command: str):
    """The next inline session ``command`` gives up as a real timeout does."""

    client_type = mesh_native_client.NativeMeshCoreServiceClient
    real_run = client_type.run_inline_job
    real_read = client_type._read_stdout_line_locked
    state = {"armed": False, "fired": 0}

    def run_inline_job(self, job, payload, **kwargs):
        state["armed"] = (
            not state["fired"]
            and job == "mesh-editor-session-json"
            and dict(payload).get("command") == command
        )
        return real_run(self, job, payload, **kwargs)

    def read(self, timeout_seconds, **kwargs):
        if state["armed"] and kwargs.get("keep_alive"):
            state["armed"] = False
            state["fired"] += 1
            raise ProcessTimeoutExpired([str(self.binary), "--service"], 5.0)
        return real_read(self, timeout_seconds, **kwargs)

    patch = pytest.MonkeyPatch()
    patch.setattr(client_type, "run_inline_job", run_inline_job)
    patch.setattr(client_type, "_read_stdout_line_locked", read)
    try:
        yield state
    finally:
        patch.undo()


def _require_core() -> None:
    if not mesh_native_core.native_mesh_core_available():
        pytest.skip("rebuilt native mesh core is required")


@pytest.fixture
def open_exact(tmp_path, monkeypatch):
    _require_core()
    from tests.test_mesh_rust_authoring_exact_output import _open_exact_session

    opened = []

    def open_session(*, defer_morph_state: bool):
        real_create = RustMeshAuthoringSession.create.__func__
        monkeypatch.setattr(RustMeshAuthoringSession, "create", classmethod(
            lambda cls, *args, **kwargs: real_create(cls, *args, defer_morph_state=defer_morph_state, **kwargs)))
        _, service, session = _open_exact_session(tmp_path / "session")
        opened.append((service, session))
        return service, session

    try:
        yield open_session
    finally:
        for service, session in opened:
            if not session.closed:
                session.cancel()
            service.close_edit_session(session.authoritative_session_id, force_without_saving=True)
        mesh_native_core.shutdown_native_mesh_core_service()


def _deferred_query_times_out(session: RustMeshAuthoringSession) -> None:
    """The app's case: the morph data asked for once the editor shows."""

    arrived = []
    with _one_timed_out_query("morph_state") as state:
        assert session.query_deferred_morph_state(arrived.append)
        session.morph_state_prefetch[0].join(30.0)
    assert state["fired"] == 1
    assert arrived and arrived[0]["available"] is False
    assert "timed out" in arrived[0]["reason"]


def _later_query_times_out(session: RustMeshAuthoringSession) -> None:
    shadow = session.shadow_service
    shadow.cached_morph_state_from_runtime(session.shadow_session_id)
    with _one_timed_out_query("morph_state") as state:
        with pytest.raises(RuntimeError, match="timed out after 5 s"):
            shadow.cached_morph_state_from_runtime(session.shadow_session_id)
    assert state["fired"] == 1


@pytest.mark.parametrize(("defer", "time_out"), [
    (True, _deferred_query_times_out),
    (False, _later_query_times_out),
], ids=["deferred-first-query", "later-query"])
def test_finish_after_a_timed_out_morph_query_opens_the_session_again(open_exact, defer, time_out) -> None:
    from tests.test_mesh_rust_authoring_exact_output import _request

    service, session = open_exact(defer_morph_state=defer)
    time_out(session)
    shadow = session.shadow_service._session(session.shadow_session_id)

    result = session.finish(_request(session, "finish_request", 2))

    assert result["status"] == "accepted"
    assert service.session_view(session.authoritative_session_id).revision == 1
    assert shadow.native_editor_lost_recoveries == 1


def test_a_core_that_started_again_reopens_the_session_it_lost(open_exact) -> None:
    from tests.test_mesh_rust_authoring_exact_output import _request

    service, session = open_exact(defer_morph_state=False)
    session.shadow_service.cached_morph_state_from_runtime(session.shadow_session_id)
    mesh_native_core.shutdown_native_mesh_core_service()

    result = session.finish(_request(session, "finish_request", 2))

    assert result["status"] == "accepted"
    assert service.session_view(session.authoritative_session_id).revision == 1


def test_a_lost_session_holding_morph_state_says_so_and_does_not_reopen(tmp_path) -> None:
    _require_core()
    from tests.test_mesh_morph_service import _Settings
    from tests.test_native_mesh_editor_morph_refit import _driver_garment_mesh

    service = MeshService(settings=_Settings(tmp_path / "settings.ini"))
    session_id = service.open_edit_session(_driver_garment_mesh(), mode="edit").session_id
    try:
        captured, state = service.capture_morph_baseline(session_id, (0,))
        assert captured.ok and state.authoring_baseline_ready
        with _one_timed_out_query("morph_state") as timed_out:
            with pytest.raises(RuntimeError, match="timed out after 5 s"):
                service.cached_morph_state_from_runtime(session_id)
        assert timed_out["fired"] == 1

        for _attempt in range(2):
            with pytest.raises(RuntimeError, match="lost this edit's Morph & Refit state"):
                service.cached_morph_state_from_runtime(session_id)
        assert service._session(session_id).native_editor_runtime_lost
    finally:
        service.close_edit_session(session_id, force_without_saving=True)
        mesh_native_core.shutdown_native_mesh_core_service()


def test_the_core_saying_it_has_no_such_session_marks_it_lost(monkeypatch) -> None:
    from pathlib import Path

    from cdmw.modding import mesh_native_dispatch, mesh_native_session_state

    monkeypatch.setattr(mesh_native_session_state, "_open_native_editor_sessions", {"shadow"})
    monkeypatch.setattr(mesh_native_session_state, "_lost_native_editor_sessions", set())
    monkeypatch.setattr(mesh_native_dispatch, "_get_native_mesh_core_service", lambda path: SimpleNamespace(
        run_inline_job=lambda *a, **k: {"inline_report": {"status": "error", "error": "missing mesh editor session"}}))
    assert mesh_native_dispatch._run_native_mesh_core_service_inline_job(
        Path("cdmw-mesh-core.exe"), "mesh-editor-session-json",
        {"command": "morph_state", "session_id": "shadow"}, timeout_seconds=5) is None
    assert mesh_native_core.native_mesh_editor_session_lost("shadow")
