"""Hair Tools beside an open Mesh Editor document.

Real Mesh Editor documents in a real documents view, the real shell bridge and
the real hair entry flow. Only the setup dialog and the helper process are
stand-ins: the dialog hands over an entry and geometry it prepared, as the real
one does.
"""

from __future__ import annotations

import time
from pathlib import Path
from types import SimpleNamespace

import pytest
from PySide6.QtCore import QSettings
from PySide6.QtWidgets import QApplication, QComboBox, QDialog, QWidget

from cdmw.core.archive import ArchiveEntry
from cdmw.services.mesh_service import MeshService
from cdmw.ui.mesh_editor import hair_flow, hair_setup_dialog
from cdmw.ui.mesh_editor.documents import MeshDocumentsView, document_label
from cdmw.ui.mesh_editor.live_edit import end_edit_prompt
from cdmw.ui.mesh_editor.shell_bridge import MeshEditorShellBridgeMixin
from cdmw.ui.mesh_editor.tab import MeshEditorTab
from cdmw.workers.mesh_editor_aux_workers import MeshArchiveSessionLoadResult
from tests.test_mesh_geometry_layers import _layer_mesh
from tests.test_p15_round2_pending import _authoring, _editor_step

_APP = QApplication.instance() or QApplication([])

SWORD = "character/model/sword.pac"
HAIR = "character/model/1_pc/1_phm/head/hair/phm_00_hair_00_0022_player.pac"
OTHER_HAIR = "character/model/1_pc/1_phm/head/hair/phm_00_hair_00_0023_player.pac"


def _entry(tmp_path: Path, path: str, offset: int = 0) -> ArchiveEntry:
    return ArchiveEntry(path=path, pamt_path=tmp_path / "0009" / "0.pamt", paz_file=tmp_path / "0009" / "0.paz",
                        offset=offset, comp_size=4, orig_size=4, flags=0, paz_index=0)


def _prepared(entry: ArchiveEntry) -> MeshArchiveSessionLoadResult:
    mesh = _layer_mesh()
    mesh.path = entry.path
    service = MeshService()
    return MeshArchiveSessionLoadResult(service=service, view=service.open_edit_session(mesh, mode="edit"),
                                        mesh=mesh, source_sha256="a" * 64)


def _settle(seconds: float = 0.4) -> None:
    """Long enough for a queued open (retried every 25 ms) and a session's dispose thread."""

    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        _APP.processEvents()
        time.sleep(0.005)


class _Shell(MeshEditorShellBridgeMixin):
    """The shell's Mesh Editor bridge over the real documents view."""

    def __init__(self, view: MeshDocumentsView) -> None:
        self.archive = self
        self.shell = self
        self.mesh_editor_tab = view
        self._modeless_alignment_dialogs = {}
        self.activated: list[object] = []
        self.statuses: list[str] = []

    def _activate_tool_widget(self, widget) -> None:
        self.activated.append(widget)

    def set_status_message(self, message: str, **_options) -> None:
        self.statuses.append(str(message))


def _document(settings: QSettings, parent: QWidget | None) -> MeshEditorTab:
    document = MeshEditorTab(settings=settings, parent=parent)
    # No native stroke dispatcher and no texture resolution worker: neither is under test.
    document._ensure_standalone_live_stroke_dispatcher = lambda: None
    document._start_archive_material_context_resolution = lambda *_args: False
    return document


@pytest.fixture
def rig(tmp_path, monkeypatch):
    settings = QSettings(str(tmp_path / "settings.ini"), QSettings.Format.IniFormat)
    window = QWidget()
    view = MeshDocumentsView(lambda parent=None: _document(settings, parent), window)
    shell = _Shell(view)
    window.shell = shell
    monkeypatch.setattr("cdmw.ui.mesh_editor.tab.native_mesh_core_available", lambda: False)
    chosen: dict[str, object] = {}

    class Setup(QDialog):
        """What the setup dialog hands over on Start: an entry and the geometry it prepared."""

        def __init__(self, owner, **_options) -> None:
            super().__init__(owner)
            self._closed = False
            self.selected_entry = chosen["entry"]
            self.selected_dependencies = None
            self.prepared_result = _prepared(self.selected_entry)
            self.context = SimpleNamespace(character="Kliff")
            self.mode, self.preset = QComboBox(), QComboBox()
            self.mode.addItem("Create", chosen["mode"])

    monkeypatch.setattr(hair_setup_dialog, "HairSetupDialog", Setup)

    def open_mesh(document, path: str, *, edited: bool):
        """Open ``path`` in ``document`` with an editor session, as a finished open leaves it."""

        entry = _entry(tmp_path, path)
        document.open_archive_session(entry, prepared_result=_prepared(entry))
        root = tmp_path / f"session-{len(list(tmp_path.glob('session-*')))}"
        root.mkdir()
        session = _authoring(root)
        if edited:
            _editor_step(session)
        document.standalone_rust_authoring_session = session
        document.standalone_rust_session_root = root
        return entry, session

    def start_hair(tab, path: str, mode: str = "generated", *, offset: int = 64):
        """Hair Tools started from ``tab``; Start in its setup with ``path`` chosen."""

        chosen.update(entry=_entry(tmp_path, path, offset), mode=mode)
        hair_flow.start_hair_workflow(tab).accept()
        _settle()
        return chosen["entry"]

    try:
        yield SimpleNamespace(view=view, shell=shell, window=window, open_mesh=open_mesh, start_hair=start_hair,
                              tmp_path=tmp_path)
    finally:
        view.request_shutdown()
        _settle()
        window.deleteLater()
        _settle(0.05)


def test_hair_tools_opens_its_hairstyle_beside_an_edited_mesh(rig) -> None:
    """Fredric, 2026-11-17: with a mesh open, Create new hair left the mesh's tab on
    "Preparing the embedded Mesh Editor..." for good.

    Hair Tools belongs to the document its button is in. The shell made a new
    document for the hairstyle and showed it, and the flow then opened the
    hairstyle in the first one: that closed the mesh's edit unasked, loaded the
    hairstyle into a hidden document, and left the new, shown document empty.
    """

    view = rig.view
    first = view.active
    sword, session = rig.open_mesh(first, SWORD, edited=True)
    assert end_edit_prompt.has_pending_edit(first)

    hair = rig.start_hair(first, HAIR)

    assert len(view.documents) == 2
    second = view.documents[1]
    # The mesh keeps its document, its session and its unfinished step.
    assert first._current_target_entry().identity == sword.identity
    assert first.standalone_rust_authoring_session is session and not session.closed
    assert session.unfinished_steps() == 1
    assert not first.standalone_rust_closing
    # The hairstyle is in the new document, which is the one shown.
    assert view.active is second
    assert second.has_active_standalone_session()
    assert second._current_target_entry().identity == hair.identity
    assert [document_label(document).rstrip(" *") for document in view.documents] == [sword.basename, hair.basename]
    # Hair Tools' start, character and reference context go with the hairstyle.
    assert second._pending_hair_start == (hair.identity, "generated")
    assert second._pending_hair_character == "Kliff"
    assert getattr(first, "_pending_hair_start", None) is None
    assert second.hair_entry_status.text() == "Loading character…"
    # The shell raises the Mesh Editor, not one document inside it.
    assert rig.shell.activated and all(widget is view for widget in rig.shell.activated)


def test_both_documents_keep_their_own_mesh_when_switching_back_and_forth(rig) -> None:
    view = rig.view
    first = view.active
    sword, session = rig.open_mesh(first, SWORD, edited=True)
    hair = rig.start_hair(first, HAIR)
    second = view.documents[1]
    for index in (0, 1, 0, 1):
        view.set_active(index)
        _settle(0.05)
        assert view.active is view.documents[index]
        assert first._current_target_entry().identity == sword.identity
        assert second._current_target_entry().identity == hair.identity
        assert first.standalone_rust_authoring_session is session and not session.closed
        assert not view.active.empty_state.isVisibleTo(view.active)


def test_a_mesh_opened_while_a_hairstyle_is_edited_gets_its_own_document(rig) -> None:
    """The reverse order: the hairstyle keeps its document and its edit."""

    view = rig.view
    first = view.active
    hair, session = rig.open_mesh(first, HAIR, edited=True)
    sword = _entry(rig.tmp_path, SWORD, 128)
    assert rig.shell._prepare_mesh_editor_archive_launch(sword) is True
    second = view.active
    assert second is not first and len(view.documents) == 2
    rig.shell.mesh_editor_tab.open_archive_session(sword, prepared_result=_prepared(sword))
    _settle()
    assert first._current_target_entry().identity == hair.identity
    assert first.standalone_rust_authoring_session is session and not session.closed
    assert session.unfinished_steps() == 1
    assert second._current_target_entry().identity == sword.identity


def test_hair_tools_in_an_empty_document_uses_that_document(rig) -> None:
    view = rig.view
    first = view.active
    hair = rig.start_hair(first, HAIR)
    assert view.documents == (first,)
    assert first._current_target_entry().identity == hair.identity
    assert first._pending_hair_start == (hair.identity, "generated")


def test_hair_tools_from_character_finder_reaches_the_document_that_opens(rig) -> None:
    """Character Finder starts Hair Tools on the Mesh Editor as the shell knows it, a lazy
    tab around the documents: what it set for the start stayed on that wrapper."""

    from cdmw.ui.shell.lazy_tool_tab import LazyToolTab

    view = rig.view
    lazy = LazyToolTab(lambda: view)
    lazy.setParent(rig.window)
    assert lazy.ensure_widget() is view
    rig.shell.mesh_editor_tab = lazy
    first = view.active
    sword, session = rig.open_mesh(first, SWORD, edited=True)

    hair = rig.start_hair(lazy, HAIR, mode="edit")

    second = view.active
    assert second is not first and second._current_target_entry().identity == hair.identity
    assert second._pending_hair_start == (hair.identity, "edit")
    assert second._pending_hair_character == "Kliff"
    assert first._current_target_entry().identity == sword.identity
    assert first.standalone_rust_authoring_session is session and not session.closed
    assert rig.shell.activated == [lazy]


def test_setting_up_the_open_hairstyle_again_asks_before_replacing_it(rig, monkeypatch) -> None:
    """Setup run again on the hairstyle that is open (another mode or character) replaces
    it, so it asks Finish, Discard or Keep editing. It opened the same file a second
    time in a new document instead, beside its own unfinished edit."""

    view = rig.view
    first = view.active
    hair, session = rig.open_mesh(first, HAIR, edited=True)
    asked: list[str] = []
    answer = [end_edit_prompt.KEEP]
    monkeypatch.setattr(end_edit_prompt, "prompt_override", lambda _parent, label: asked.append(label) or answer[0])

    rig.start_hair(first, HAIR, mode="edit", offset=0)

    assert len(asked) == 1
    assert view.documents == (first,)
    assert first.standalone_rust_authoring_session is session and not session.closed
    assert session.unfinished_steps() == 1
    assert first.hair_entry_status.text() == "Hair setup cancelled. The current scene is unchanged."

    answer[0] = end_edit_prompt.DISCARD
    rig.start_hair(first, HAIR, mode="edit", offset=0)

    assert len(asked) == 2
    assert view.documents == (first,)  # replaced where it is: no second document of the same file
    assert session.closed
    assert first._current_target_entry().identity == hair.identity
    assert first._pending_hair_start == (hair.identity, "edit")
