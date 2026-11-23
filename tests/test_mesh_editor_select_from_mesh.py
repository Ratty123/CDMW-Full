"""Select From Mesh Selection in the Mesh Editor's docked Texture Editor, and its MCP tools.

The real docked panel and Texture Editor against a synthetic editing session: the button
turns the selected faces into a texture selection by the selection Mode, as one Undo step
that edits no pixels; refusals say why; textures_select_from_mesh and textures_mesh_at
drive the same path through the real AI connection."""

from __future__ import annotations

import os
import time

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest
from PySide6.QtWidgets import QApplication, QWidget

from cdmw.app import app_folder
from cdmw.domain.mesh.editing import MeshEditSelection
from cdmw.domain.textures.editor_selection_masks import build_texture_editor_selection_mask
from cdmw.models import TextureEditorDocument, TextureEditorLayer, TextureEditorSourceBinding
from cdmw.services.settings_service import create_settings
from cdmw.ui.mesh_editor.texture_tools_dock import LiveTextureTarget, MeshEditorTextureTools

SHA = "ab" * 32
WIDTH, HEIGHT = 16, 8


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication([])


def _quad(u0, v0, u1, v1):
    return [(u0, v0), (u1, v0), (u1, v1), (u0, v1)]


def _session(selection: MeshEditSelection, *, flip_part_1: bool = False):
    # Chest: the left half, twice (a mirrored copy, faces 2 and 3, on the same pixels).
    chest = SimpleNamespace(name="Chest", uvs=_quad(0.0, 0.0, 0.5, 1.0) * 2,
                            faces=[(0, 1, 2), (0, 2, 3), (4, 6, 5), (4, 7, 6)])
    # Legs: the top right quarter, at U 1.5-2 (it repeats onto 0.5-1).
    legs = SimpleNamespace(name="Legs", uvs=_quad(1.5, 0.0, 2.0, 0.5), faces=[(0, 1, 2), (0, 2, 3)])
    belt = SimpleNamespace(name="Belt", uvs=_quad(0.0, 0.0, 1.0, 1.0), faces=[(0, 1, 2), (0, 2, 3)])
    payload = {
        "textures": [{"file": {"sha256": SHA.upper()}, "role": "base_color", "material_indices_by_lod": [[0, 1]]}],
        "material_presentations": [{"lod_index": 0, "material_index": 1, "texture_flip_vertical": flip_part_1}],
    }
    state = SimpleNamespace(selection=selection)

    class Service:
        def session_view(self, _sid):
            return SimpleNamespace(lod_index=0, selection=state.selection)

        def working_mesh(self, _sid):
            return SimpleNamespace(submeshes=[chest, legs, belt])

    return SimpleNamespace(shadow_service=Service(), shadow_session_id="s", closed=False,
                           archive_refit_material_cache={"base": payload}, active_material_key="base",
                           state=state)


def _docked(app, tmp_path, session, *, role="base_color"):
    tools = MeshEditorTextureTools(settings=create_settings(settings_file_path=tmp_path / "t.cfg"), base_dir=tmp_path)
    editor = tools._ensure_editor()
    editor.document = TextureEditorDocument(
        "Probe", WIDTH, HEIGHT, active_layer_id="paint", layers=(TextureEditorLayer("paint", "Paint", "unused.png"),),
        source_binding=TextureEditorSourceBinding(source_path=str(tmp_path / "chest_d.png"), mesh_resource_id=SHA))
    editor.layer_pixels = {"paint": np.full((HEIGHT, WIDTH, 4), 90, dtype=np.uint8)}
    editor._push_history("Open Document")
    editor._refresh_ui()
    tools.target = LiveTextureTarget(session_id="doc", source_path=str(tmp_path / "chest_d.png"), source_sha256=SHA,
                                     channel=role, display_name="chest_d.dds")
    tools.mesh_session_reader = lambda: session
    tools.select_from_mesh_button.setEnabled(True)
    return tools, editor


def _wait(app, tools, timeout=10.0):
    deadline = time.monotonic() + timeout
    while tools.mesh_selection.busy and time.monotonic() < deadline:
        app.processEvents()
        time.sleep(0.005)
    app.processEvents()
    assert not tools.mesh_selection.busy


def _selected(editor) -> np.ndarray:
    document = editor.document
    mask = build_texture_editor_selection_mask(document.width, document.height, document.selection)
    return np.zeros((document.height, document.width), bool) if mask is None else mask > 0


def _set_mode(editor, mode):
    editor.selection_mode_combo.setCurrentIndex(editor.selection_mode_combo.findData(mode))
    editor._handle_tool_settings_changed()


def test_the_button_selects_the_faces_pixels_by_the_mode_as_one_undo_step(app, tmp_path) -> None:
    session = _session(MeshEditSelection.from_maps(faces_by_submesh={0: (0, 1)}))
    tools, editor = _docked(app, tmp_path, session)
    edits, statuses = [], []
    tools.texture_edited.connect(lambda *args: edits.append(args))
    tools.status_message.connect(lambda text, refused: statuses.append((text, refused)))
    try:
        # The button sits with the selection Mode, in the Selection section of the docked rail.
        section = editor.selection_section
        assert section.parent() is tools.select_from_mesh_button.parent().parent() or section.isAncestorOf(
            tools.select_from_mesh_button)
        assert tools.isAncestorOf(section)
        start = editor.history_index
        tools.select_from_mesh_button.click()
        _wait(app, tools)
        expected = np.zeros((HEIGHT, WIDTH), bool)
        expected[:, :8] = True
        assert np.array_equal(_selected(editor), expected)
        assert editor.history_index == start + 1 and not edits
        assert np.all(editor.layer_pixels["paint"] == 90)
        assert "Selected 64 pixels from 2 faces on Chest (Replace)." in tools.mesh_selection_text
        # The mirrored copy shares the pixels: the line says painting changes it too.
        assert "2 faces outside the selection share these pixels" in tools.mesh_selection_text
        assert statuses[-1] == (tools.mesh_selection_text, False)

        # Add: the Legs part, wrapped from U 1.5-2 onto the top right quarter.
        session.state.selection = MeshEditSelection.from_maps(source_indices=(1,))
        _set_mode(editor, "add")
        tools.select_from_mesh()
        _wait(app, tools)
        expected[:4, 8:] = True
        assert np.array_equal(_selected(editor), expected)
        assert "(Add)" in tools.mesh_selection_text and "wrapped" in tools.mesh_selection_text

        # Subtract the Chest again, by its four corners (a vertex selection).
        session.state.selection = MeshEditSelection.from_maps(vertices_by_submesh={0: (0, 1, 2, 3)})
        _set_mode(editor, "subtract")
        tools.select_from_mesh()
        _wait(app, tools)
        expected[:, :8] = False
        assert np.array_equal(_selected(editor), expected)

        # Undo takes the steps back one at a time.
        editor.undo()
        editor.undo()
        assert _selected(editor)[:, :8].all() and not _selected(editor)[4:, 8:].any()
    finally:
        tools.deleteLater()


def test_the_button_refuses_with_the_reason(app, tmp_path) -> None:
    session = _session(MeshEditSelection.from_maps(faces_by_submesh={2: (0, 1)}))
    tools, editor = _docked(app, tmp_path, session)
    try:
        start = editor.history_index
        assert not tools.select_from_mesh()
        assert tools.mesh_selection_text == ("The selected faces do not use chest_d.dds: they are on Belt. "
                                             "chest_d.dds is used by: Chest, Legs.")
        assert tools.mesh_selection_label.objectName() == "WarningText"
        session.state.selection = MeshEditSelection()
        assert not tools.select_from_mesh()
        assert tools.mesh_selection_text.startswith("Nothing is selected in the 3D view.")
        tools.mesh_session_reader = lambda: None
        assert not tools.select_from_mesh() and "Open the mesh in the Mesh Editor" in tools.mesh_selection_text
        assert editor.history_index == start and editor.document.selection.mode == "none"
        tools.show_empty()
        assert not tools.select_from_mesh_button.isEnabled() and not tools.mesh_selection_text
    finally:
        tools.deleteLater()


def test_a_detail_texture_is_refused_and_a_flipped_material_flips_v(app, tmp_path) -> None:
    session = _session(MeshEditSelection.from_maps(source_indices=(1,)), flip_part_1=True)
    tools, editor = _docked(app, tmp_path, session, role="skin_detail_normal")
    try:
        assert not tools.select_from_mesh() and "is a detail texture" in tools.mesh_selection_text
        tools.target = LiveTextureTarget(session_id="doc", source_path=tools.target.source_path, source_sha256=SHA,
                                         channel="base_color", display_name="chest_d.dds")
        assert tools.select_from_mesh()
        _wait(app, tools)
        # The Legs' material flips V: its quarter lands on the bottom rows.
        selected = _selected(editor)
        assert selected[4:, 8:].all() and not selected[:4].any() and not selected[:, :8].any()
    finally:
        tools.deleteLater()


# ----- the MCP tools --------------------------------------------------------------------
@pytest.fixture
def connect(app, monkeypatch, tmp_path):
    from tests.mcp_full_helpers import McpApp

    folder = tmp_path / "profile"
    folder.mkdir()
    monkeypatch.setenv(app_folder.PROFILE_DIR_ENV, str(folder))
    app_folder._reset_for_tests()
    sessions = []

    def make(window):
        sessions.append(McpApp(app, folder, create_settings(settings_file_path=tmp_path / "ai.cfg"), window))
        return sessions[-1]

    yield make
    for session in sessions:
        session.close()
    app_folder._reset_for_tests()


@pytest.mark.skipif(os.name != "nt", reason="AI connections are Windows-only")
def test_the_mcp_tools_select_from_the_mesh_and_read_faces_back(app, tmp_path, connect) -> None:
    session = _session(MeshEditSelection.from_maps(faces_by_submesh={0: (0,)}))
    tools, editor = _docked(app, tmp_path, session)
    holder = QWidget()
    holder.active = SimpleNamespace(_texture_tools_panel=lambda: tools)
    try:
        mcp = connect(SimpleNamespace(shell=SimpleNamespace(mesh_editor_tab=holder)))
        assert mcp.error("textures_mesh_at", {})["code"] == "unavailable"  # no texture selection yet
        chosen = mcp.ok("textures_select_from_mesh", {"part_ids": [1], "mode": "replace", "grow": 0})
        assert chosen["selected_pixels"] == 32 and chosen["faces"] == 2 and chosen["mode"] == "Replace"
        assert chosen["parts"] == [{"part": 1, "name": "Legs", "faces": 2}] and chosen["from"] == "part_ids"
        assert chosen["wrapped_faces"] == 2 and chosen["history_after"] == chosen["history_before"] + 1
        assert tools.mesh_selection_text == chosen["status"]
        assert mcp.error("textures_select_from_mesh", {"part_ids": [2]})["code"] == "unavailable"
        assert mcp.error("textures_select_from_mesh", {"part_ids": [9]})["code"] == "unavailable"
        assert mcp.error("textures_select_from_mesh", {"editor": "tool"})["code"] == "invalid_arguments"

        # A pixel of the Chest: both mirrored faces are on it; one of the Legs: its face.
        at = mcp.ok("textures_mesh_at", {"x": 6, "y": 1})
        assert at["pixel"] == [6, 1] and [(row["part"], row["face_ids"]) for row in at["parts"]] == [(0, [0, 2])]
        assert mcp.ok("textures_mesh_at", {"x": 15, "y": 7})["parts"] == []
        covered = mcp.ok("textures_mesh_at")
        assert covered["selected_pixels"] == 32 and covered["parts"][0]["part"] == 1
        assert covered["parts"][0]["whole_part"] and covered["parts"][0]["face_ids"] == [0, 1]
        assert mcp.error("textures_mesh_at", {"x": 16, "y": 0})["code"] == "invalid_arguments"
        assert mcp.error("textures_mesh_at", {"x": 1})["code"] == "invalid_arguments"
    finally:
        tools.deleteLater()
        holder.deleteLater()


def test_the_real_tab_and_session_select_and_undo_through_the_one_history(app, tmp_path) -> None:
    """The real Mesh Editor tab and a real editing session: the 3D selection reaches the
    button through the session's shadow, the step joins the document's one history, and
    the Mesh Editor's Undo and Redo (the panel's) take it back and forward."""

    from PySide6.QtCore import QSettings

    from cdmw.domain.mesh import MeshEditCommand
    from cdmw.ui.mesh_editor import shared_history_routing as routing
    from cdmw.ui.mesh_editor.tab import MeshEditorTab
    from cdmw.ui.mesh_editor.texture_tools_dock import _target_key
    from tests.test_archive_dds_preview_recovery import _dds_bytes
    from tests.test_mesh_rust_authoring_exact_output import _open_exact_session

    dds = tmp_path / "base.dds"
    dds.write_bytes(_dds_bytes())
    _source, _authority, host = _open_exact_session(tmp_path / "session", base_texture_path=dds)
    service, session_id = host.shadow_service, host.shadow_session_id
    part = service.working_mesh(session_id, clone=False).submeshes[0]
    part.uvs = [(0.0, 0.0), (1.0, 0.0), (0.0, 1.0), (1.0, 1.0)]  # faces (0, 1, 2) and (1, 3, 2)
    # What the session does with the selection the helper reports.
    assert service.apply_command(session_id, MeshEditCommand(
        "select", selection=MeshEditSelection.from_maps(faces_by_submesh={0: (0,)}),
        params={"operation": "replace"}, mode="edit")).ok
    sha = str(host.archive_refit_material_cache[host.active_material_key]["textures"][0]["file"]["sha256"])

    tab = MeshEditorTab(settings=QSettings(str(tmp_path / "tab.ini"), QSettings.Format.IniFormat))
    statuses = []
    tab.status_message_requested.connect(lambda text, refused: statuses.append((text, refused)))
    try:
        tab.standalone_rust_authoring_session = host
        tools = tab._texture_tools_panel()
        assert tools.mesh_session_reader() is host  # the tab's wiring
        history = routing.attach_shared_history(tab, host)
        editor = tools._ensure_editor()
        path = str(tmp_path / "base.png")
        editor.document = TextureEditorDocument(
            "Probe", 8, 8, active_layer_id="paint", layers=(TextureEditorLayer("paint", "Paint", "unused.png"),),
            source_binding=TextureEditorSourceBinding(source_path=path, mesh_resource_id=sha.lower()))
        editor.layer_pixels = {"paint": np.full((8, 8, 4), 90, dtype=np.uint8)}
        editor._push_history("Open Document")
        editor._refresh_ui()
        target = LiveTextureTarget(session_id="doc", source_path=path, source_sha256=sha.lower(),
                                   channel="base_color", display_name="base.dds")
        tools.target = target
        tools._targets[_target_key(path)] = target
        tools.observe_history(target)
        start = editor.history_index

        assert tools.select_from_mesh()
        _wait(app, tools)
        # The upper-left triangle, its diagonal included (pixel centres where x + y = 8).
        ys, xs = np.mgrid[0:8, 0:8]
        assert np.array_equal(_selected(editor), xs + ys <= 7)
        # Its neighbour only shares the diagonal: nothing else samples these pixels.
        assert tools.mesh_selection_text == "Selected 36 pixels from 1 faces on target (Replace)."
        assert statuses[-1] == (tools.mesh_selection_text, False)
        assert editor.history_index == start + 1

        routing.route_history_step(tab, {"event": "command_request", "command": "undo", "request_id": 1})
        assert editor.history_index == start and editor.document.selection.mode == "none"
        routing.route_history_step(tab, {"event": "command_request", "command": "redo", "request_id": 2})
        assert editor.history_index == start + 1 and np.array_equal(_selected(editor), xs + ys <= 7)
        assert history.current_history_payload()["history_entries"]
    finally:
        tab.deleteLater()
        app.processEvents()
