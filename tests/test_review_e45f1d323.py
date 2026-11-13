"""Review of e45f1d323: a Discard chosen during the open when that open then fails or stops.

The real prepare worker over a real draft with a recovery point (the commit's own fixture).
"""

from __future__ import annotations

import threading

import pytest

from types import SimpleNamespace

from cdmw.workers import mesh_rust_editor_workers as workers
from tests.test_mesh_history_journal import _move, _open
_worker = pytest.importorskip("tests.test_p15_discard_during_open")._worker


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
        try:
            service.close_edit_session(session_id)
        except (KeyError, RuntimeError):
            pass  # the test closed it, as the document's close does

_ORDER = ("Review of e45f1d323 (REPORT-review.md): the Discard's close ends the mesh session first, so the "
          "worker cannot find the draft whose recovery point it should end")


def test_a_discard_that_closes_the_document_first_still_ends_the_recovery_point(draft, monkeypatch) -> None:
    """In the app the Discard runs close_standalone_session, which calls
    controller.close_active_session() before the open's worker reaches its abort path.
    _discard_draft_recovery then looks the draft up with service._session(...) at that
    point, gets KeyError, and returns: the discarded edits come back at the next open.
    The commit's test keeps the mesh session open, so it never meets this order."""

    discarded = threading.Event()

    def create(*_args, **_kwargs):
        discarded.set()  # the user answers Discard while the open runs ...
        draft.service.close_edit_session(draft.session_id)  # ... and the document's close ends the session
        raise RuntimeError("the open stopped")

    monkeypatch.setattr(workers.RustMeshAuthoringSession, "create", staticmethod(create))
    _worker(draft, discarded).run()
    assert not draft.marker.exists(), "the draft's recovery point survived the user's Discard"
