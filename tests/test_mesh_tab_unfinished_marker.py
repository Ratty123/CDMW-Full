"""A Mesh Editor tab's ``*`` marks a change, not an open editor (2026-11-17).

A freshly opened item set (cd_m0001_00_de_phm_ub_24004.pac, three files) showed
``*`` with a clean history: revision 0, no undo, no redo. The label used
``has_pending_edit``, which also counts an editor merely open in its viewport so
the close guard can offer Finish; every ready editor read as changed. The label now
asks ``has_unfinished_changes``; closing still asks while the editor is open.

Real tabs in a real documents view over real authoring sessions; only the helper
process is absent.
"""
from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from pathlib import Path

from PySide6.QtCore import QSettings
from PySide6.QtWidgets import QApplication

from cdmw.models import ArchiveEntry
from cdmw.ui.mesh_editor.controller import MeshEditorController
from cdmw.ui.mesh_editor.documents import MeshDocumentsView, document_label
from cdmw.ui.mesh_editor.live_edit import end_edit_prompt
from cdmw.ui.mesh_editor.tab import MeshEditorTab
from tests.test_p15_round2_pending import _authoring, _editor_step
from tests.test_pending_edit_revision_lock import _call_while_locked

_APP = QApplication.instance() or QApplication([])
NAME = "cd_m0001_00_de_phm_ub_24004.pac"


def _view(tmp_path: Path) -> MeshDocumentsView:
    settings = QSettings(str(tmp_path / "settings.ini"), QSettings.Format.IniFormat)
    return MeshDocumentsView(lambda: MeshEditorTab(settings=settings))


def _open_editor(view: MeshDocumentsView, tmp_path: Path):
    """The shown document with a session just opened and its editor ready."""

    document = view.active
    session = _authoring(tmp_path)
    marks = getattr(session, "_shadow_marks", None)
    if callable(marks):
        session.shadow_base_marks = marks()  # as create() takes them
    controller = MeshEditorController(mesh_service=session.authoritative_service)
    controller.active_session_id = session.authoritative_session_id
    document.standalone_controller = controller
    document.current_archive_selection = ArchiveEntry(
        f"character/model/1_pc/1_phm/{NAME}", tmp_path / "0.pamt", tmp_path / "0.paz", 0, 0, 0, 0, 0)
    document.standalone_authoring_session = None
    document.standalone_rust_authoring_session = session
    document.standalone_rust_ready = True  # the editor is open in its viewport
    view.refresh_labels()
    return document, session


def _close(view: MeshDocumentsView, document) -> None:
    document.standalone_rust_authoring_session = None
    document.standalone_rust_ready = False
    document.standalone_controller = None
    view.deleteLater()
    _APP.processEvents()


def test_a_freshly_opened_set_holds_no_unfinished_change(tmp_path, monkeypatch) -> None:
    from cdmw.domain.mesh import MeshEditCommand, MeshEditSelection
    from tests.test_mesh_texture_status_routes import _item_set_session

    service, controller, session = _item_set_session(tmp_path, monkeypatch, (0, 1))
    try:
        # Composing the set, seeding its layers and morph state and writing its
        # files are not edits, and nothing reached the document's own session.
        assert session.shadow_base_marks == session._shadow_marks()
        assert not session.has_unfinished_changes()
        assert service.session_revision(controller.active_session_id) == 0
        assert session.shadow_service.apply_command(session.shadow_session_id, MeshEditCommand(
            "transform", selection=MeshEditSelection.from_maps(vertices_by_submesh={0: (0,)}),
            params={"translate": (0.25, 0.0, 0.0)})).ok
        assert session.has_unfinished_changes()
    finally:
        session.cancel()
        service.close_edit_session(controller.active_session_id, force_without_saving=True)


def test_an_open_editor_without_changes_has_no_marker_and_closing_still_asks(tmp_path, monkeypatch) -> None:
    view = _view(tmp_path)
    document, session = _open_editor(view, tmp_path)
    try:
        assert document_label(document) == NAME
        assert view.tab_bar.tabText(0) == NAME
        # The close guard is unchanged: an open editor asks, with Finish offered.
        assert end_edit_prompt.has_pending_edit(document)
        assert view.pending_documents() == (document,)
        asked: list[str] = []
        monkeypatch.setattr(end_edit_prompt, "ask_to_end_edit",
                            lambda parent, label, finish_available=True:
                            asked.append(f"{label}:{finish_available}") or end_edit_prompt.KEEP)
        assert end_edit_prompt.resolve_pending_edit(None, document) == end_edit_prompt.KEEP
        assert asked == [f"{NAME}:True"]

        _editor_step(session)  # the first step the editor sends
        document._set_rust_status("Mesh Editor command completed.")  # as its reply does
        assert view.tab_bar.tabText(0) == f"{NAME} *"
    finally:
        _close(view, document)


def test_a_layer_only_change_marks_the_tab(tmp_path) -> None:
    view = _view(tmp_path)
    document, session = _open_editor(view, tmp_path)
    try:
        from cdmw.services.mesh_service import _MeshGeometryLayer

        shadow, shadow_id = session.shadow_service, session.shadow_session_id
        # A draft that already has a layer of its own, as the editor opened it.
        state = shadow._session(shadow_id)
        state.geometry_layers = (*state.geometry_layers, _MeshGeometryLayer(
            layer_id="sleeves", name="Sleeves", submesh_indices=(0,)))
        session.shadow_base_marks = session._shadow_marks()
        assert document_label(document) == NAME
        shadow.rename_geometry_layer(shadow_id, "sleeves", "Long sleeves")
        assert session.shadow_service.session_view(shadow_id).revision == session.shadow_base_revision
        assert document_label(document) == f"{NAME} *"
    finally:
        _close(view, document)


def test_a_morph_only_change_marks_the_tab(tmp_path) -> None:
    view = _view(tmp_path)
    document, session = _open_editor(view, tmp_path)
    try:
        assert document_label(document) == NAME
        # A slider, definition or preset change moves the morph revision alone.
        session.shadow_service._session(session.shadow_session_id).morph_session_revision += 1
        assert document_label(document) == f"{NAME} *"
    finally:
        _close(view, document)


def test_the_marker_does_not_wait_for_the_editor_session_lock(tmp_path) -> None:
    view = _view(tmp_path)
    document, session = _open_editor(view, tmp_path)
    try:
        _editor_step(session)
        answered, result = _call_while_locked(session.shadow_service, session.shadow_session_id,
                                              lambda: document_label(document))
        assert answered, "the tab's label waited for the lock a worker holds"
        assert result == [f"{NAME} *"]
    finally:
        _close(view, document)


def test_a_texture_edit_marks_the_tab_when_it_is_made(tmp_path) -> None:
    from types import SimpleNamespace

    view = _view(tmp_path)
    document, _session = _open_editor(view, tmp_path)
    try:
        assert view.tab_bar.tabText(0) == NAME
        document.live_edit._live_texture_keeping = SimpleNamespace(unkept_count=lambda: 1)
        # The keeper's kept_changed reaches this slot on each edit and each save.
        document.live_edit._show_live_texture_kept_text("Texture edits are not kept yet.")
        assert view.tab_bar.tabText(0) == f"{NAME} *"
    finally:
        document.live_edit._live_texture_keeping = None
        _close(view, document)
