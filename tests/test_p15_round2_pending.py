"""Section 8.8, cause 3 and R1: one definition of a pending edit.

A real authoring session over a real shadow MeshService, attached to real Mesh
Editor tabs in a real documents view. Only the helper process is absent.
"""

from __future__ import annotations

from pathlib import Path
from uuid import uuid4

from PySide6.QtCore import QSettings
from PySide6.QtWidgets import QApplication

from cdmw.domain.mesh import MeshEditCommand, MeshEditSelection
from cdmw.services.mesh_rust_authoring import RustMeshAuthoringSession
from cdmw.services.mesh_service import MeshService
from cdmw.ui.mesh_editor.documents import MeshDocumentsView
from cdmw.ui.mesh_editor.live_edit import end_edit_prompt
from cdmw.ui.mesh_editor.tab import MeshEditorTab
from tests.test_mesh_geometry_layers import _layer_mesh

_APP = QApplication.instance() or QApplication([])


def _authoring(tmp_path: Path) -> RustMeshAuthoringSession:
    shadow = MeshService()
    shadow_id = shadow.open_edit_session(_layer_mesh(), session_id=f"shadow-{uuid4().hex}", mode="edit").session_id
    authoritative = MeshService()
    authoritative_id = authoritative.open_edit_session(_layer_mesh(), session_id=f"doc-{uuid4().hex}",
                                                       mode="edit").session_id
    session = RustMeshAuthoringSession(
        authoritative_service=authoritative, authoritative_session_id=authoritative_id,
        shadow_service=shadow, shadow_session_id=shadow_id, root=tmp_path, root_identity=(0, 0),
        session_id=f"rust-{uuid4().hex}", process_generation=1, base_revision=0,
        base_geometry_layer_revision=0, base_morph_session_revision=0, source_weights_available=False,
        manifest_path=tmp_path / "manifest.json", theme={},
    )
    session.shadow_base_revision = int(shadow.session_view(shadow_id).revision)
    return session


def _editor_step(session: RustMeshAuthoringSession) -> None:
    session.shadow_service.apply_command(session.shadow_session_id, MeshEditCommand(
        "transform", selection=MeshEditSelection.from_maps(vertices_by_submesh={0: (0,)}),
        params={"translate": (0.25, 0.0, 0.0)}))


def test_unfinished_steps_are_the_shadow_steps_since_the_editor_opened(tmp_path) -> None:
    session = _authoring(tmp_path)
    assert session.unfinished_steps() == 0
    _editor_step(session)
    assert session.unfinished_steps() == 1
    session.recovered_edits_at = 1.0  # restored from a recovery point: one more
    assert session.unfinished_steps() == 2


def _parked_document(view: MeshDocumentsView, tmp_path: Path):
    document = view.active
    session = _authoring(tmp_path)
    _editor_step(session)
    document.standalone_rust_authoring_session = session
    document.standalone_rust_ready = False  # parked or restarting: no editor answers
    document.standalone_rust_parked = True
    return document, session


def test_a_parked_document_with_unfinished_steps_is_pending_and_asks_before_closing(tmp_path, monkeypatch) -> None:
    """R1: it was not pending, so closing CDMW or its tab lost the steps unasked."""

    settings = QSettings(str(tmp_path / "settings.ini"), QSettings.Format.IniFormat)
    view = MeshDocumentsView(lambda: MeshEditorTab(settings=settings))
    try:
        document, _session = _parked_document(view, tmp_path)
        assert end_edit_prompt.has_pending_edit(document)
        assert view.pending_documents() == (document,)  # what closing CDMW asks about
        asked: list[str] = []
        monkeypatch.setattr(end_edit_prompt, "prompt_override",
                            lambda parent, label: asked.append(label) or end_edit_prompt.KEEP)
        assert end_edit_prompt.resolve_pending_edit(None, document) == end_edit_prompt.KEEP
        assert len(asked) == 1
    finally:
        view.deleteLater()


def test_a_recovery_point_alone_makes_a_document_pending(tmp_path) -> None:
    settings = QSettings(str(tmp_path / "settings.ini"), QSettings.Format.IniFormat)
    tab = MeshEditorTab(settings=settings)
    try:
        session = _authoring(tmp_path)
        session.recovery_project_root = tmp_path
        (tmp_path / "editor_recovery.json").write_text("{}", encoding="utf-8")
        tab.standalone_rust_authoring_session = session
        assert end_edit_prompt.has_pending_edit(tab)
        (tmp_path / "editor_recovery.json").unlink()
        assert not end_edit_prompt.has_pending_edit(tab)
    finally:
        tab.deleteLater()


def test_a_closed_tab_lives_until_its_dispose_has_finished(tmp_path, monkeypatch) -> None:
    """R2: the wait covered only threads already running; an idle editor's dispose
    starts later, when its channel reports the end, after deleteLater was posted."""

    import json
    import time

    import shiboken6

    from cdmw.ui.preview.engine_channel import EngineEditChannel

    settings = QSettings(str(tmp_path / "settings.ini"), QSettings.Format.IniFormat)
    view = MeshDocumentsView(lambda: MeshEditorTab(settings=settings))
    try:
        document = view.add_document()
        root = tmp_path / "session"
        root.mkdir()
        session = _authoring(root)
        written: list[dict] = []
        document.standalone_rust_authoring_session = session
        document.standalone_rust_session_root = root
        document.standalone_rust_process = EngineEditChannel(
            lambda data: written.extend(json.loads(line) for line in bytes(data).splitlines()) or len(data),
            lambda: 7, lambda _channel: None, document)
        document._connect_rust_process_signals(document.standalone_rust_process)  # as adoption does
        document.standalone_rust_ready = True
        document.standalone_rust_hello_received = True
        started: list[bool] = []
        original = document._start_rust_dispose_worker
        monkeypatch.setattr(document, "_start_rust_dispose_worker",
                            lambda current, path: started.append(shiboken6.isValid(document))
                            or original(current, path))
        monkeypatch.setattr(end_edit_prompt, "prompt_override", lambda parent, label: end_edit_prompt.DISCARD)
        assert view.close_document(view.index_of(document))
        deadline = time.monotonic() + 10
        while time.monotonic() < deadline and shiboken6.isValid(document):
            _APP.processEvents()
            time.sleep(0.01)
        assert started == [True], "the dispose started on a deleted document, or never"
        assert not shiboken6.isValid(document), "the closed document was never deleted"
        # The worker deletes only roots inside the editor's own session folder; this
        # one is not, so the dispose shows as the session being closed.
        assert session.closed, "the session was never disposed"
    finally:
        view.deleteLater()


def test_an_unnamed_line_never_ends_another_document_s_channel(tmp_path) -> None:
    """R3: with Browse's channel gone, an id-less engine line went to the only window channel."""

    import json

    from cdmw.services.mesh_rust_contract import RUST_MESH_EDITOR_PROTOCOL
    from cdmw.ui.preview.engine_channel import (
        EDIT_IN_PLACE_CAPABILITY,
        MULTI_EDIT_CAPABILITY,
        OWN_VIEWPORT_EDIT_CAPABILITY,
    )
    from tests.test_dotnet_preview_shared_host import _make_ready, _start_controller
    from tests.test_edit_in_place import _emit_stdout

    controller, process, _ = _start_controller(tmp_path)
    controller._test_handshake_capabilities = (EDIT_IN_PLACE_CAPABILITY, MULTI_EDIT_CAPABILITY,
                                               OWN_VIEWPORT_EDIT_CAPABILITY)
    _make_ready(controller)
    try:
        view = controller.borrow_for_edit()
        window = controller.borrow_for_window_edit()
        window.session_id = "draft-a"
        view.terminate()  # a cancelled view-first edit: Browse's channel is gone
        _APP.processEvents()
        line = {"event": "edit_left", "protocol": RUST_MESH_EDITOR_PROTOCOL, "edit_slot": "view"}
        _emit_stdout(process, json.dumps(line).encode() + b"\n")
        refused = {"event": "edit_refused", "protocol": RUST_MESH_EDITOR_PROTOCOL, "reason": "x"}
        _emit_stdout(process, json.dumps(refused).encode() + b"\n")
        _APP.processEvents()
        assert window.is_running, "Browse's late edit_left ended the tab document's edit"
        # Lines Browse's channel writes carry the marker; a window edit's do not.
        written = []
        marked = controller.borrow_for_edit()
        marked._write = lambda data: written.append(bytes(data)) or len(data)
        marked.write(json.dumps({"event": "cancel"}).encode() + b"\n")
        assert json.loads(written[-1])["edit_slot"] == "view"
    finally:
        controller.shutdown()
