"""A failed resident Morph query names its cause (built-app passes 9 and 11).

Finish reported only "Resident C++ morph_state failed.": the dispatcher answers
None for every failure, so the core's reason, or the timeout, was lost.
"""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from cdmw.core.common import ProcessTimeoutExpired
from cdmw.modding import mesh_native_dispatch
from cdmw.services import mesh_service_morph
from cdmw.services.mesh_service import MeshService


@pytest.fixture
def job_slots(monkeypatch):
    monkeypatch.setattr(mesh_native_dispatch, "_LAST_NATIVE_JOB_ERROR", [""])
    monkeypatch.setattr(mesh_native_dispatch, "_LAST_NATIVE_JOB_REJECTION", [""])


def _query_with(monkeypatch, helper) -> str:
    """Run the real query path against the real dispatcher and a fake core."""

    monkeypatch.setattr(mesh_native_dispatch, "_get_native_mesh_core_service", lambda path: helper)

    def command(name, session_id, payload=None, *, timeout_seconds=5.0, **_kwargs):
        request = {**dict(payload or {}), "command": name, "session_id": session_id}
        return mesh_native_dispatch._run_native_mesh_core_service_inline_job(
            Path("cdmw-mesh-core.exe"), "mesh-editor-session-json", request, timeout_seconds=timeout_seconds)

    monkeypatch.setattr(mesh_service_morph, "native_mesh_editor_session_command", command)
    monkeypatch.setattr(MeshService, "_ensure_native_morph_session_locked", lambda self, session: None)
    with pytest.raises(RuntimeError) as raised:
        MeshService()._run_morph_query_locked(SimpleNamespace(session_id="shadow"), "morph_state")
    return str(raised.value)


def test_a_refused_query_says_what_the_core_said(monkeypatch, job_slots) -> None:
    helper = SimpleNamespace(run_inline_job=lambda *a, **k: {
        "inline_report": {"status": "error", "error": "missing mesh editor session"}})
    message = _query_with(monkeypatch, helper)
    assert message == (
        "Resident C++ morph_state failed: mesh-editor-session-json morph_state: "
        "inline status error: missing mesh editor session"
    )


def test_a_timed_out_query_says_it_timed_out(monkeypatch, job_slots) -> None:
    def timed_out(*_args, **_kwargs):
        raise ProcessTimeoutExpired(["cdmw-mesh-core.exe", "--service"], 5.0)

    message = _query_with(monkeypatch, SimpleNamespace(run_inline_job=timed_out))
    assert message == "Resident C++ morph_state timed out after 5 s."
    assert mesh_native_dispatch.last_native_mesh_core_job_error().startswith(
        "mesh-editor-session-json morph_state: inline ProcessTimeoutExpired")


def test_a_failure_with_no_recorded_reason_keeps_the_old_sentence() -> None:
    assert mesh_service_morph._morph_query_failure("morph_state", "", 5.0) == "Resident C++ morph_state failed."
