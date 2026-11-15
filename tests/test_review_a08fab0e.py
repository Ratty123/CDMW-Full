"""Review of a08fab0e (section 8.9): a Discard chosen while the editor is still opening.

A real MeshEditorTab over a real draft session, the real end-edit prompt path, the
real prepared-session handler and the real dispose worker. The tab's controller is a
stand-in that only names the draft's session, as the open has it then.
"""

from __future__ import annotations

import time
from types import SimpleNamespace

from PySide6.QtCore import QSettings, QThread
from PySide6.QtWidgets import QApplication

from cdmw.ui.mesh_editor.live_edit import end_edit_prompt
from cdmw.ui.mesh_editor.tab import MeshEditorTab
from tests.test_mesh_history_journal import _move, _open
from tests.test_p15_round2_pending import _authoring

_APP = QApplication.instance() or QApplication([])
_REVIEW = "Review of a08fab0e (REPORT-review.md): a Discard during the open is not remembered"


def test_discard_chosen_while_the_editor_opens_ends_the_recovery_point(tmp_path, monkeypatch) -> None:
    """Closing during the open now asks (the fix's half). If the user answers Discard,
    mark_discarded() marks standalone_rust_authoring_session, which does not exist
    yet; the session prepared afterwards is disposed with close(), which keeps the
    recovery point, so the discarded edits come back at the next open."""

    service, session_id = _open(tmp_path / "draft")
    _move(service, session_id, 0.25)
    project_root = service._session(session_id).mesh_layer_project_path.parent
    marker = project_root / "editor_recovery.json"
    marker.write_text("{}", encoding="utf-8")  # the draft keeps unfinished edits
    settings = QSettings(str(tmp_path / "settings.ini"), QSettings.Format.IniFormat)
    tab = MeshEditorTab(settings=settings)
    preparing = QThread()
    try:
        tab.standalone_controller = SimpleNamespace(mesh_service=service, active_session_id=session_id,
                                                    close_active_session=lambda: None)
        tab.standalone_rust_prepare_thread = preparing  # the editor is still opening
        assert end_edit_prompt.has_pending_edit(tab), "closing during the open must ask"
        monkeypatch.setattr(end_edit_prompt, "prompt_override", lambda parent, label: end_edit_prompt.DISCARD)
        assert end_edit_prompt.resolve_pending_edit(None, tab) == end_edit_prompt.DISCARD
        # The open finishes after the close: its session is disposed.
        tab.standalone_rust_prepare_thread = None
        root = tmp_path / "session"
        root.mkdir()
        session = _authoring(root)
        session.recovery_project_root = project_root
        session.recovered_edits_at = 1.0
        tab.standalone_rust_prepare_controller = None
        tab._handle_rust_session_prepared(tab.standalone_rust_prepare_active_request_id, session)
        deadline = time.monotonic() + 10
        while time.monotonic() < deadline and tab.standalone_rust_dispose_thread is not None:
            _APP.processEvents()
            time.sleep(0.01)
        assert session.closed
        assert not marker.exists(), "the user chose Discard, yet the recovery point stays and the edits return"
    finally:
        tab.standalone_controller = None
        tab.deleteLater()
        service.close_edit_session(session_id)
        _APP.processEvents()


_REVIEW_LAYERS = "Review of a08fab0e (REPORT-review.md): the Build snapshot carries no layer revision"


def test_a_layer_change_made_while_a_mesh_without_a_draft_builds_still_asks_on_close(tmp_path, monkeypatch) -> None:
    """The fix checks the snapshot's revision and, through getattr, its layer revision,
    but MeshExportSnapshot has no geometry_layer_revision: the layer half is never
    checked, so a rename made during the Build is marked built and lost on close."""

    from uuid import uuid4

    from cdmw.domain.mesh import MeshEditCommand, MeshEditSelection
    from cdmw.services import mesh_saved_work_service
    from cdmw.services.mesh_service import MeshService
    from cdmw.workers.mesh_editor_workers import MeshDirectOutputWorker
    from tests.test_mesh_geometry_layers import _layer_mesh

    monkeypatch.setattr(mesh_saved_work_service, "register_built_mod", lambda *args, **kwargs: object())
    monkeypatch.setattr("cdmw.workers.mesh_editor_workers.replace", lambda value, **changes: value)
    service = MeshService()
    session_id = service.open_edit_session(_layer_mesh(), session_id=f"disk-{uuid4().hex}", mode="edit").session_id
    try:
        service.apply_command(session_id, MeshEditCommand(
            "select", selection=MeshEditSelection.from_maps(faces_by_submesh={0: (0,)}),
            params={"operation": "replace"}))
        service.copy_selection(session_id, target="face")
        service.paste_selection(session_id)  # a layer of its own: "selection-copy-1"
        snapshot = service.capture_export_snapshot(session_id)  # what Build builds
        service.rename_geometry_layer(session_id, "selection-copy-1", "Renamed")  # during the Build
        assert service.closing_loses_work(session_id)
        worker = MeshDirectOutputWorker(1, service, session_id, SimpleNamespace(path="character/a.pac"),
                                        kind="loose_mod", saved_work_root=tmp_path / "saved")
        result = SimpleNamespace(output_path=tmp_path / "mod", zip_path=None, manager_profile="dmm")
        worker._register_saved_work(snapshot, result)
        assert service.closing_loses_work(session_id), "Build marked a layer change it did not build as clean"
    finally:
        service.close_edit_session(session_id)
