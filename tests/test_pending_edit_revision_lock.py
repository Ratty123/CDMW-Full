"""A Mesh Editor tab's label reads the edit's revision without the session's lock.

Each tab's text says whether its edit is pending (``name *``), which asks
``pending_edit_revision``. That read a session view, and a view waits for the
session's lock, which a worker holds through a native job. Reopening a finished
and built file in the 2026-11-17 cold review held the window thread for 323 ms
there (``documents.py document_label`` -> ``end_edit_prompt.py
pending_edit_revision`` -> ``mesh_service.py session_view``).
"""
from __future__ import annotations

import threading
from types import SimpleNamespace
from uuid import uuid4

from cdmw.services.mesh_service import MeshService
from cdmw.ui.mesh_editor.controller import MeshEditorController
from cdmw.ui.mesh_editor.documents import document_label
from cdmw.ui.mesh_editor.live_edit.end_edit_prompt import pending_edit_revision
from tests.test_mesh_geometry_layers import _layer_mesh


def _tab(controller: MeshEditorController) -> SimpleNamespace:
    return SimpleNamespace(
        has_active_standalone_session=lambda: bool(controller.active_session_id),
        standalone_controller=controller,
        live_edit=None,
        standalone_rust_authoring_session=None,
        standalone_rust_parked=False,
        _current_target_entry=lambda: SimpleNamespace(basename="cd_phm_00_ub_00_0374.pac", path="x"),
    )


def _call_while_locked(service: MeshService, session_id: str, call):
    """Run ``call`` on another thread while a worker holds the session's lock."""

    held, release = threading.Event(), threading.Event()

    def worker() -> None:
        with service._session(session_id).export_lock:
            held.set()
            release.wait(10)

    holder = threading.Thread(target=worker, daemon=True)
    holder.start()
    assert held.wait(5)
    result: list[object] = []
    reader = threading.Thread(target=lambda: result.append(call()), daemon=True)
    reader.start()
    reader.join(2)
    answered_under_lock = bool(result)
    release.set()
    holder.join(5)
    reader.join(5)
    return answered_under_lock, result


def test_the_tab_label_does_not_wait_for_the_session_lock() -> None:
    service = MeshService()
    controller = MeshEditorController(mesh_service=service)
    session_id = f"label-{uuid4().hex}"
    controller.open_mesh(_layer_mesh(), session_id=session_id, mode="edit")
    try:
        service._session(session_id).revision = 3  # an accepted edit
        tab = _tab(controller)

        answered, result = _call_while_locked(service, session_id, lambda: pending_edit_revision(tab))
        assert answered, "pending_edit_revision waited for the lock a worker holds"
        assert result == [3]

        answered, result = _call_while_locked(service, session_id, lambda: document_label(tab))
        assert answered, "the tab's label waited for the lock a worker holds"
        assert result == ["cd_phm_00_ub_00_0374.pac *"]
    finally:
        controller.close_active_session(force_without_saving=True)


def test_a_controller_without_the_revision_reader_still_reports_a_pending_edit() -> None:
    """A stand-in controller must not read as "nothing pending" to the close guard."""

    from cdmw.ui.mesh_editor.controller import controller_session_revision

    controller = SimpleNamespace(active_session_id="s",
                                 session_view=lambda: SimpleNamespace(revision=5))
    assert controller_session_revision(controller) == 5
    tab = SimpleNamespace(has_active_standalone_session=lambda: True, standalone_controller=controller)
    assert pending_edit_revision(tab) == 5
