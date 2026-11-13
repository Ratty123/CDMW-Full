"""A Discard chosen while the editor opens holds when that open then fails or stops (section 8.9).

The real prepare worker over a real draft with a recovery point; only the session
it would create is replaced, by one that fails or one that the stop catches.
"""

from __future__ import annotations

import threading
from types import SimpleNamespace

import pytest

from cdmw.workers import mesh_rust_editor_workers as workers
from tests.test_mesh_history_journal import _move, _open


@pytest.fixture
def draft(tmp_path):
    service, session_id = _open(tmp_path / "draft")
    _move(service, session_id, 0.25)
    project_root = service._session(session_id).mesh_layer_project_path.parent
    marker = project_root / "editor_recovery.json"
    marker.write_text("{}", encoding="utf-8")  # the draft keeps unfinished edits
    try:
        yield SimpleNamespace(service=service, session_id=session_id, marker=marker, root=tmp_path)
    finally:
        service.close_edit_session(session_id)


def _worker(draft, discarded: threading.Event) -> workers.MeshRustSessionPrepareWorker:
    controller = SimpleNamespace(mesh_service=draft.service, active_session_id=draft.session_id)
    return workers.MeshRustSessionPrepareWorker(1, controller, draft.root / "session", process_generation=1,
                                                discarded=discarded)


def _failing_create(*_args, **_kwargs):
    raise RuntimeError("the session could not be prepared")


@pytest.mark.parametrize("chose_discard", [True, False])
def test_an_open_that_fails_after_a_discard_ends_the_recovery_point(draft, monkeypatch, chose_discard) -> None:
    monkeypatch.setattr(workers.RustMeshAuthoringSession, "create", staticmethod(_failing_create))
    discarded = threading.Event()
    if chose_discard:
        discarded.set()
    _worker(draft, discarded).run()
    assert draft.marker.exists() is not chose_discard


@pytest.mark.parametrize("chose_discard", [True, False])
def test_an_open_stopped_after_a_discard_closes_its_session_as_discarded(draft, monkeypatch, chose_discard) -> None:
    closes: list[bool] = []
    discarded = threading.Event()
    worker = _worker(draft, discarded)

    def create(*_args, **_kwargs):
        if chose_discard:
            discarded.set()
        worker.stop()  # the Discard's close stops the open while it runs
        return SimpleNamespace(closed=False, root_identity=(0, 0), authoritative_session_id=draft.session_id,
                               close=lambda *, discard=False: closes.append(discard))

    monkeypatch.setattr(workers.RustMeshAuthoringSession, "create", staticmethod(create))
    worker.run()
    assert closes and closes[-1] is chose_discard
