"""Messages to the Mesh Editor read the session's revision without a session view.

Each message the window sends the Mesh Editor carries the geometry revision. It
was read through ``session_view``, which waits for the session's lock and prunes
the selection; pruning can rebuild the native session, copying every part's
per-vertex attributes to compare them. Closing a set's tab paid 110 to 120 ms
for that on the window thread in the 2026-11-17 review, and while a worker held
the lock through a native job, Finish waited 530 to 600 ms for it.
"""
from __future__ import annotations

import threading
from types import SimpleNamespace
from uuid import uuid4

from cdmw.services.mesh_service import MeshService
import cdmw.ui.mesh_editor.tab  # noqa: F401  (loads the facade the mixins use)
from cdmw.ui.mesh_editor.tab_rust_process import MeshEditorRustProcessMixin
from tests.test_mesh_geometry_layers import _layer_mesh


class _ViewlessService:
    def session_view(self, session_id):
        raise AssertionError("the window built a session view to stamp a message")

    def session_revision(self, session_id):
        assert session_id == "shadow-1"
        return 7


def test_a_message_is_stamped_without_a_session_view() -> None:
    session = SimpleNamespace(closed=False, session_id="edit-1", shadow_service=_ViewlessService(),
                              shadow_session_id="shadow-1")
    tab = SimpleNamespace(standalone_rust_authoring_session=session, standalone_rust_process_generation=2)
    message = MeshEditorRustProcessMixin._rust_host_message(tab, "cancel", request_id=3, extra={"reason": "closed"})
    assert message["base_revision"] == 7
    assert message["session_id"] == "edit-1" and message["request_id"] == 3 and message["reason"] == "closed"


def test_the_revision_is_read_while_a_worker_holds_the_session_lock() -> None:
    service = MeshService()
    session_id = f"revision-{uuid4().hex}"
    service.open_edit_session(_layer_mesh(), session_id=session_id, mode="edit")
    try:
        expected = service.session_view(session_id).revision
        held, release = threading.Event(), threading.Event()

        def worker() -> None:
            with service._session(session_id).export_lock:
                held.set()
                release.wait(10)

        thread = threading.Thread(target=worker, daemon=True)
        thread.start()
        assert held.wait(5)
        read: list[int] = []
        reader = threading.Thread(target=lambda: read.append(service.session_revision(session_id)), daemon=True)
        reader.start()
        reader.join(2)
        release.set()
        thread.join(5)
        assert read == [expected]
    finally:
        service.close_edit_session(session_id, force_without_saving=True)
