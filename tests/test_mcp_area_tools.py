"""AI connections: the Mesh Editor, Browse view, Texture Editor and Create New Item tools,
each through the real server and bridge, driving the handlers the interface's controls drive."""
from __future__ import annotations

import base64
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from pathlib import Path
from types import SimpleNamespace

import pytest
from PySide6.QtCore import QSettings, QTimer, Signal
from PySide6.QtGui import QColor, QImage
from PySide6.QtWidgets import QApplication, QComboBox, QLineEdit, QMessageBox, QPushButton, QSlider, QWidget

from cdmw.app import app_folder
from cdmw.mcp import approvals
from cdmw.services.settings_service import create_settings
from cdmw.ui.commands.registry import command_registry
from tests.mcp_full_helpers import McpApp
# The automation tests' stand-ins: a real host session behind the Mesh Editor's protocol
# code, and Create New Item's Template page with the real New painting dialog.
from tests.test_automation_authoring_commands import editor, studio  # noqa: F401

pytestmark = pytest.mark.skipif(os.name != "nt", reason="AI connections are Windows-only")


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication([])


@pytest.fixture
def profile(monkeypatch, tmp_path) -> Path:
    folder = tmp_path / "profile"
    folder.mkdir()
    monkeypatch.setenv(app_folder.PROFILE_DIR_ENV, str(folder))
    app_folder._reset_for_tests()
    yield folder
    app_folder._reset_for_tests()


@pytest.fixture
def settings(tmp_path):
    return create_settings(settings_file_path=tmp_path / "ai.cfg")


@pytest.fixture
def connect(app, profile, settings):
    """``connect(window)``: the AI connection around ``window``, closed afterwards."""

    sessions: list[McpApp] = []

    def make(window) -> McpApp:
        sessions.append(McpApp(app, profile, settings, window))
        return sessions[-1]

    yield make
    for session in sessions:
        session.close()


def _game(tmp_path, settings) -> Path:
    game = tmp_path / "Crimson Desert"
    (game / "meta").mkdir(parents=True)
    (game / "meta" / "0.papgt").write_bytes(b"\0")
    settings.setValue(approvals.GAME_FOLDER_KEY, str(game))
    return game


# ===== the Mesh Editor ==================================================================
@pytest.fixture
def mesh(editor, connect):  # noqa: F811 - the imported fixture
    """The stand-in editor with a recording helper, and the connection around its window."""

    ui = editor.ui
    # Record what would go to the helper; nothing answers, so no worker starts.
    ui._send_rust_message = lambda message: (editor.sent.append(dict(message)), True)[1]
    highlights: list[object] = []
    ui.live_edit = SimpleNamespace(viewport_binding=None, highlight_part_in_view=highlights.append)
    editor.highlights = highlights
    editor.mcp = connect(editor.window)
    yield editor
    from cdmw.ui.mesh_editor.editor_commands import clear_helper_commands

    clear_helper_commands(command_registry())


def test_mesh_state_is_empty_until_a_mesh_is_open(connect) -> None:
    mcp = connect(SimpleNamespace(shell=SimpleNamespace(mesh_editor_tab=None)))
    assert mcp.ok("mesh_state") == {"documents": [], "open": False}
    for tool, arguments in (("mesh_geometry", {"part": 0}), ("mesh_select_parts", {"parts": [0]}),
                            ("mesh_undo", {}), ("mesh_export", {"path": str(Path.home() / "nowhere-x.obj")}),
                            ("mesh_discard", {}), ("textures_stroke", {"points": [[0, 0]]})):
        error = mcp.error(tool, arguments)
        assert error["code"] == "unavailable" and "Mesh Editor" in error["message"], tool


def test_mesh_state_and_geometry_are_the_sessions_parts_counts_and_selection(mesh) -> None:
    mcp = mesh.mcp
    service, session_id = mesh.host.shadow_service, mesh.host.shadow_session_id
    model = service.working_mesh(session_id)
    state = mcp.ok("mesh_state")
    assert state["open"] and state["ready"] and not state["busy"]
    assert [(part["index"], part["name"], part["vertices"], part["triangles"]) for part in state["parts"]] == [
        (index, part.name, len(part.vertices), len(part.faces)) for index, part in enumerate(model.submeshes)]
    assert state["vertices"] == sum(len(part.vertices) for part in model.submeshes) > 0
    assert state["selection"] == {"parts": [], "vertices": 0, "edges": 0, "faces": 0, "by_part": []}
    assert state["history"]["undo"] == 0 and not state["history"]["can_undo"]
    assert state["revision"] == service.session_view(session_id).revision

    part = model.submeshes[0]
    summary = mcp.ok("mesh_geometry", {"part": 0})
    assert summary["vertices"] == len(part.vertices) and summary["triangles"] == len(part.faces)
    xs = [vertex[0] for vertex in part.vertices]
    assert summary["bounds"]["min"][0] == pytest.approx(min(xs)) and summary["bounds"]["max"][0] == pytest.approx(
        max(xs))
    page = mcp.ok("mesh_geometry", {"part": 0, "what": "vertices", "limit": 2})
    assert page["total"] == len(part.vertices) and len(page["rows"]) == 2
    assert page["rows"][0] == pytest.approx(list(part.vertices[0]))
    triangles = mcp.ok("mesh_geometry", {"part": 0, "what": "triangles", "limit": 500})
    assert triangles["rows"][0] == list(part.faces[0])
    assert mcp.ok("mesh_geometry", {"part": 0, "what": "selection"})["vertices"] == []
    assert mcp.error("mesh_geometry", {"part": 99})["code"] == "not_found"
    # A hairstyle being made (Hair Tools): its style, template and how much is authored.
    assert "hair" not in state
    session = service._session(session_id)
    session.hair_state = SimpleNamespace(revision=4, payload={
        "style_name": "Braids", "startup_preset": "bob", "revision": 4,
        "template": {"path": "character/model/cd_phw_hair_0003.pac", "character": "phw"},
        "guides": [{}, {}, {}], "groups": [{}], "locks": [{}, {}], "prepared_parts": [0]})
    try:
        assert mcp.ok("mesh_state")["hair"] == {
            "style_name": "Braids", "preset": "bob", "template": "character/model/cd_phw_hair_0003.pac",
            "character": "phw", "guides": 3, "groups": 1, "locks": 2, "prepared_parts": 1, "revision": 4}
    finally:
        session.hair_state = None


def test_mesh_state_reports_textures_from_the_materials_the_view_draws(mesh) -> None:
    """Preview Core layers texture a part with no DDS payload; mesh_state said
    "unavailable" over a textured view, and named no part (2026-11-17)."""

    host, mcp = mesh.host, mesh.mcp
    model = host.shadow_service.working_mesh(host.shadow_session_id)
    reason = "Resolved Archive Browser material bindings did not contain readable DDS texture payloads."
    saved = (dict(host.archive_refit_material_cache), host.active_material_key, host.texture_unavailable_reason)
    host.archive_refit_material_cache["layers-only"] = {
        "textures": [], "preview_core_material_graph": {"materials": [
            {"lod_index": 0, "material_index": 0, "layers": [{"diffuse": {"file": {"path": "a.dds"}}}]}]}}
    host.active_material_key = "layers-only"
    host.texture_unavailable_reason = reason
    try:
        state = mcp.ok("mesh_state")
        textures = state["textures"]
        assert textures["available"] and textures["textured_parts"] == 1
        assert textures["from_material_layers"] == 1 and textures["from_dds"] == 0
        assert textures["parts"] == len(model.submeshes) == 1 and textures["untextured_parts"] == []
        assert "textures_unavailable" not in state and textures["warning"] == reason
        # Really untextured: said so, with the part named.
        host.archive_refit_material_cache["layers-only"]["preview_core_material_graph"] = None
        state = mcp.ok("mesh_state")
        assert not state["textures"]["available"] and state["textures_unavailable"] == reason
        assert state["textures"]["untextured_parts"] == [{"index": 0, "name": model.submeshes[0].name}]
    finally:
        host.archive_refit_material_cache.clear()
        host.archive_refit_material_cache.update(saved[0])
        host.active_material_key, host.texture_unavailable_reason = saved[1], saved[2]


def test_parts_are_selected_and_highlighted_with_the_parts_lists_own_messages(mesh) -> None:
    mcp = mesh.mcp
    assert mcp.ok("mesh_select_parts", {"parts": [1, 0, 1]})["selected_parts"] == [0, 1]
    sent = mesh.sent[-1]
    assert sent["event"] == "select_parts" and sent["indices"] == [0, 1]
    assert mcp.ok("mesh_highlight_part", {"part": 1}) == {"highlighted": 1}
    mcp.ok("mesh_highlight_part")
    assert mesh.highlights == [1, None]
    # Not ready: nothing is sent, and the reason is the editor's.
    mesh.ui.standalone_rust_ready = False
    count = len(mesh.sent)
    assert "preparing" in mcp.error("mesh_select_parts", {"parts": [0]})["message"] and len(mesh.sent) == count


def test_the_editors_commands_run_by_id_with_their_reason_and_class(mesh, settings) -> None:
    from cdmw.ui.mesh_editor.editor_commands import mirror_helper_commands

    mcp = mesh.mcp
    ran: list[str] = []
    mirror_helper_commands(command_registry(), [
        {"id": "tool.grab", "label": "Grab", "keys": ["G"]},
        {"id": "topology.delete_selection", "label": "Delete Selection", "keys": ["Delete"]},
        {"id": "topology.merge", "label": "Merge", "reason": "Select two or more vertices."},
        {"id": "session.undo", "label": "Undo", "keys": ["Ctrl+Z"]},
    ], lambda helper_id: ran.append(helper_id) or True, lambda: True)
    assert mcp.ok("mesh_state")["commands"] == 4
    assert mcp.ok("mesh_command", {"command": "tool.grab"})["sent"] and ran == ["tool.grab"]
    assert mcp.ok("mesh_command", {"command": "mesh_editor.tool.grab"})["sent"], "the registry's id works too"
    assert mcp.error("mesh_command", {"command": "topology.merge"}) == {
        "code": "unavailable", "message": "Select two or more vertices."}
    assert mcp.error("mesh_command", {"command": "tool.nothing"})["code"] == "not_found"
    # Undo is mirrored: it runs as the palette runs it. Redo and Finish are not in this
    # helper's list: they are sent by id, as the editor's own Finish button's host sends them.
    mcp.ok("mesh_undo")
    assert ran[-1] == "session.undo"
    mcp.ok("mesh_redo")
    mcp.ok("mesh_finish")
    assert [(m["event"], m["command"]) for m in mesh.sent[-2:]] == [("run_command", "session.redo"),
                                                                    ("run_command", "session.finish")]
    # A command that deletes asks as destructive, by its own name.
    settings.setValue(approvals.FULL_ACCESS_KEY, False)
    mcp.send("mesh_command", {"command": "topology.delete_selection"})
    prompt = mcp.wait_for_prompt()
    assert prompt.request.effect == "destructive"
    assert prompt.request.tool == "mesh.command:mesh_editor.topology.delete_selection"
    prompt.deny_button.click()
    assert mcp.read()["isError"] and "topology.delete_selection" not in ran


def test_export_and_import_replacement_send_the_panel_buttons_messages(mesh, tmp_path, settings) -> None:
    mcp = mesh.mcp
    target = tmp_path / "part.obj"
    assert mcp.ok("mesh_export", {"path": str(target)}) == {"sent": True, "path": str(target), "format": "obj"}
    sent = mesh.sent[-1]
    assert (sent["event"], sent["command"]) == ("cdmw_command", "export_mesh")
    assert sent["arguments"] == {"path": str(target), "format": "obj"}
    count = len(mesh.sent)
    # Never into the game, never over a file, and only the formats the button writes without Blender.
    game = _game(tmp_path, settings)
    assert "does not write into" in mcp.error("mesh_export", {"path": str(game / "part.obj")})["message"]
    (tmp_path / "old.obj").write_text("o")
    assert mcp.error("mesh_export", {"path": str(tmp_path / "old.obj")})["code"] == "refused"
    assert mcp.error("mesh_export", {"path": str(tmp_path / "part.fbx")})["code"] == "invalid_arguments"
    assert len(mesh.sent) == count

    state = mcp.ok("mesh_replacement_state")
    assert state["ready"] and state["supported"] and state["pending"] is None and state["parts"]
    assert mcp.error("mesh_replacement_import", {"path": str(tmp_path / "model.fbx")})["code"] == "invalid_arguments"
    assert mcp.error("mesh_replacement_import", {"path": str(tmp_path / "missing.obj")})["code"] == (
        "invalid_arguments")
    assert "import one first" in mcp.error("mesh_replacement_apply")["message"]
    model = tmp_path / "model.obj"
    model.write_text("o a\nv 0 0 0\nv 1 0 0\nv 0 1 0\nf 1 2 3\n", encoding="utf-8")
    assert mcp.ok("mesh_replacement_import", {"path": str(model)})["sent"]
    sent = mesh.sent[-1]
    assert sent["command"] == "replacement_choose" and sent["arguments"] == {"scope": "entire", "part_ids": []}
    assert mcp.ok("mesh_replacement_cancel")["sent"] and mesh.sent[-1]["command"] == "replacement_cancel"


def test_build_mod_presses_the_button_with_its_dialog_filled_and_reports_a_refusal(mesh, tmp_path, settings) -> None:
    from cdmw.ui.mesh_editor import tab_direct_output

    mcp = mesh.mcp
    ui = mesh.ui
    holder = QWidget()
    validated, building, built = [False], [False], []

    hair = [False]

    def press() -> None:  # the button's handler, cut down to its question and its dialog
        if hair[0]:  # a hairstyle asks for the folder with a chooser instead of the dialog
            from PySide6.QtWidgets import QFileDialog

            built.append(("hair", QFileDialog.getExistingDirectory(None, "Build Additional Hairstyle"), None, None))
            building[0] = bool(built[-1][1])
            return
        if not validated[0]:
            QMessageBox.warning(None, "Build Mod", "Run validation successfully before building a mesh mod.")
            return
        dialog = tab_direct_output.MeshModExportDialog(holder, title="Probe Mesh Mod", description="",
                                                       output_parent="", output_choice="", manager_profile="dmm")
        if dialog.exec() == dialog.DialogCode.Accepted:
            built.append((dialog.mod_name.text(), dialog.output_parent.text(), dialog.create_zip.isChecked(),
                          dialog.open_folder.isChecked()))
            building[0] = True

    ui._start_mesh_mod_build_requested = press
    ui._mesh_direct_output_busy = lambda: building[0]
    out = tmp_path / "mods"
    out.mkdir()
    refused = mcp.ok("mesh_build_mod", {"output_folder": str(out)})
    assert not refused["started"] and built == []
    assert refused["asked"][0]["text"] == "Run validation successfully before building a mesh mod."
    validated[0] = True
    started = mcp.ok("mesh_build_mod", {"output_folder": str(out), "mod_name": "Red cloak"})
    assert started["started"] and built == [("Red cloak", str(out), False, False)]
    assert mcp.ok("mesh_state")["building"]
    # The output folder must exist and never be in the game.
    game = _game(tmp_path, settings)
    assert "does not write into" in mcp.error("mesh_build_mod", {"output_folder": str(game)})["message"]
    assert mcp.error("mesh_build_mod", {"output_folder": str(tmp_path / "missing" / "x")})["code"] == "refused"
    assert len(built) == 1 and tab_direct_output.MeshModExportDialog.__name__ == "MeshModExportDialog"
    # A hairstyle: the same folder answers its chooser.
    hair[0], building[0] = True, False
    assert mcp.ok("mesh_build_mod", {"output_folder": str(out)})["started"]
    assert built[-1] == ("hair", str(out), None, None)
    holder.deleteLater()


def test_open_show_document_and_close_go_through_the_shells_own_calls(mesh, settings) -> None:
    mcp = mesh.mcp
    shell = mesh.window.shell
    wanted = "character/model/cd_probe_0001.pac"
    current = [None]
    opened, shown, closed = [], [], []
    mesh.window.archive = SimpleNamespace(
        _note_archive_ui_activity=lambda: None,
        _reveal_archive_path_in_live_catalogue=lambda path: (
            QTimer.singleShot(50, lambda: current.__setitem__(0, SimpleNamespace(path=path))), True)[1],
        _current_archive_mesh_entry=lambda: current[0])
    shell._open_current_archive_mesh_editor = lambda: opened.append(current[0].path)
    result = mcp.ok("mesh_open", {"path": wanted})
    assert result["opening"] and result["path"] == wanted and opened == [wanted]
    # Documents: the tab strip's own set_active.
    holder = shell.mesh_editor_tab
    holder.documents = (mesh.ui,)
    holder.set_active = shown.append
    assert mcp.ok("mesh_state")["documents"][0]["shown"]
    assert mcp.ok("mesh_show_document", {"index": 0})["shown"] == 0 and shown == [0]
    assert mcp.error("mesh_show_document", {"index": 3})["code"] == "not_found"
    # Closing the edit asks as destructive.
    mesh.ui.close_standalone_session = lambda: closed.append(True) or True
    settings.setValue(approvals.FULL_ACCESS_KEY, False)
    mcp.send("mesh_discard")
    prompt = mcp.wait_for_prompt()
    assert prompt.request.effect == "destructive"
    prompt.allow_once_button.click()
    assert mcp.read()["structuredContent"]["discarded"] and closed == [True]


# ===== Browse Archives' view ================================================================
class _PreviewHost:
    def __init__(self) -> None:
        self.state = {"yaw": 30.0, "pitch": 10.0, "roll": 0.0, "zoom_factor": 1.0, "pan": [0.0, 0.0, 0.0]}
        self.captures: list[Path] = []
        self.ready = True

    def view_state_snapshot(self) -> dict:
        return dict(self.state)

    def set_view(self, **values) -> bool:
        self.state.update({key: value for key, value in values.items() if value is not None})
        return True

    def reset_view(self) -> None:
        self.state.update(yaw=0.0, pitch=0.0, zoom_factor=1.0)

    def request_frame_capture(self, target: Path) -> bool:
        if not self.ready:
            return False
        self.captures.append(Path(target))

        def write() -> None:  # the helper delivers the frame a moment later
            image = QImage(400, 200, QImage.Format.Format_RGB32)
            image.fill(QColor("#2060C0"))
            image.save(str(target), "PNG")

        QTimer.singleShot(50, write)
        return True


@pytest.fixture
def browse(app, connect, tmp_path, monkeypatch):
    from cdmw.ui.archive_browser.item_set_components import ScenePanel
    from cdmw.ui.preview import preview_settings_hub as hub_module

    monkeypatch.setattr(hub_module, "_open_settings",
                        lambda: QSettings(str(tmp_path / "preview.ini"), QSettings.Format.IniFormat))
    monkeypatch.setattr(app, "_cdmw_preview_settings_hub", None, raising=False)
    panel = ScenePanel()
    sword = "character/model/cd_phm_02_sword_0015.pac"
    panel.set_parts([{"index": index, "material_name": f"Material {index}", "editor_identity": {
        "source_submesh_index": index, "source_local_submesh_index": index, "source_model_path": sword,
        "part_name": name}} for index, name in enumerate(("Blade_00", "Guard_01"))])
    host = _PreviewHost()
    selected = [None]
    archive = SimpleNamespace(
        archive_item_set_components=panel, archive_d3d11_preview_host=host, archive_preview_request_entry=None,
        _note_archive_ui_activity=lambda: None, _current_archive_entry=lambda: selected[0])

    def reveal(path: str) -> bool:
        def show() -> None:
            selected[0] = SimpleNamespace(path=path, pamt_path="0009/0.pamt")
            archive.archive_preview_request_entry = selected[0]

        QTimer.singleShot(50, show)
        return True

    archive._reveal_archive_path_in_live_catalogue = reveal
    window = SimpleNamespace(archive=archive, shell=SimpleNamespace(
        mesh_editor_tab=None, compact_workspace=SimpleNamespace(_active_tool_key="archive_browser")))
    yield SimpleNamespace(mcp=connect(window), window=window, host=host, panel=panel, sword=sword)
    panel.deleteLater()


def test_browse_selects_previews_and_shows_or_hides_parts(browse) -> None:
    mcp = browse.mcp
    assert mcp.ok("view_selection")["selected"] == ""
    opened = mcp.ok("view_open", {"path": browse.sword})
    assert opened["selected"] == opened["previewed"] == browse.sword and opened["preview"]["has_3d_view"]
    files = mcp.ok("view_parts")["files"]
    assert [(part["part"], part["label"], part["ticked"]) for part in files[0]["parts"]] == [
        (0, "Blade_00", True), (1, "Guard_01", True)]
    hidden = mcp.ok("view_set_parts", {"part": 1, "ticked": False})["files"][0]["parts"]
    assert [part["ticked"] for part in hidden] == [True, False] and tuple(browse.panel.hidden_indices) == (1,)
    assert all(part["ticked"] for part in mcp.ok("view_set_parts", {"action": "show_all"})["files"][0]["parts"])
    assert mcp.error("view_set_parts", {"part": 9})["code"] == "not_found"


def test_the_preview_camera_and_settings_are_read_and_set(browse, settings) -> None:
    mcp = browse.mcp
    assert mcp.ok("view_camera")["camera"]["yaw"] == 30.0
    turned = mcp.ok("view_camera", {"yaw": 90, "zoom": 2})["camera"]
    assert (turned["yaw"], turned["pitch"], turned["zoom_factor"]) == (90.0, 10.0, 2.0), "pitch is kept"
    assert mcp.ok("view_camera", {"reset": True})["camera"]["yaw"] == 0.0
    before = mcp.ok("view_settings")["settings"]
    assert before["shadows"] is True
    # Reading runs; changing a setting is an edit and asks.
    settings.setValue(approvals.FULL_ACCESS_KEY, False)
    assert mcp.ok("view_settings")["settings"] == before and mcp.controller.prompts == []
    mcp.send("view_settings", {"values": {"shadows": False, "no_such_setting": 1}})
    prompt = mcp.wait_for_prompt()
    assert prompt.request.effect == "edit"
    prompt.allow_once_button.click()
    changed = mcp.read()["structuredContent"]
    assert changed["changed"] == ["shadows"] and changed["not_taken"] == ["no_such_setting"]
    assert changed["settings"]["shadows"] is False


def test_a_capture_of_browse_is_the_frame_the_preview_renders(browse) -> None:
    mcp = browse.mcp
    mcp.ok("view_open", {"path": browse.sword})
    result = mcp.call("view_capture", {"view": "browse", "max_side": 200})
    assert not result["isError"], result["structuredContent"]
    picture = QImage.fromData(base64.b64decode(result["content"][0]["data"]), "PNG")
    assert (picture.width(), picture.height()) == (200, 100)
    assert QColor(picture.pixel(10, 10)).name() == "#2060c0"
    facts = result["structuredContent"]
    assert facts["view"] == "browse" and facts["file"] == browse.sword and facts["width"] == 200
    # The capture file was the tool's own and is gone again.
    assert not browse.host.captures[0].exists() and not browse.host.captures[0].parent.exists()
    browse.host.ready = False
    assert mcp.error("view_capture", {"view": "browse"})["code"] == "unavailable"


def test_a_capture_of_the_mesh_editor_is_its_viewports_rectangle(browse, app) -> None:
    mcp = browse.mcp
    assert "Mesh Editor" in mcp.error("view_capture", {"view": "mesh_editor"})["message"]
    frame = QWidget()
    frame.setStyleSheet("background: #C02040;")
    frame.resize(320, 240)
    frame.show()
    app.processEvents()
    holder = QWidget()
    holder.active = SimpleNamespace(standalone_native_host_frame=frame, live_edit=None,
                                    _current_target_entry=lambda: None)
    browse.window.shell.mesh_editor_tab = holder
    browse.window.shell.compact_workspace._active_tool_key = "mesh_editor"
    # No picture from the helper's window (none here): the screen is copied, but only
    # while CDMW is the window in front, so no other program's window can be in it.
    other = QWidget()
    other.show()
    other.activateWindow()
    mcp.wait_until(lambda: not frame.isActiveWindow())
    assert "window in front" in mcp.error("view_capture")["message"]
    other.close()
    other.deleteLater()
    frame.activateWindow()
    mcp.wait_until(frame.isActiveWindow)
    result = mcp.call("view_capture")  # the view that is shown
    assert not result["isError"], result["structuredContent"]
    facts = result["structuredContent"]
    assert facts["view"] == "mesh_editor" and facts["how"] == "copied from the screen"
    assert (facts["width"], facts["height"]) == (320, 240)
    frame.hide()
    assert "not on screen" in mcp.error("view_capture", {"view": "mesh_editor"})["message"]
    frame.deleteLater()
    holder.deleteLater()


def test_the_mesh_editors_picture_is_what_its_own_window_draws(browse, app) -> None:
    import ctypes
    from ctypes import wintypes

    user32 = ctypes.windll.user32
    user32.CreateWindowExW.restype = wintypes.HWND
    user32.CreateWindowExW.argtypes = [wintypes.DWORD, wintypes.LPCWSTR, wintypes.LPCWSTR, wintypes.DWORD,
                                       ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int, wintypes.HWND,
                                       wintypes.HMENU, wintypes.HINSTANCE, wintypes.LPVOID]
    user32.DestroyWindow.argtypes = [wintypes.HWND]
    # A native window far off the screen, with no taskbar entry and never activated (Windows
    # gives no picture of a hidden one): a button, which draws a frame and its text.
    hwnd = user32.CreateWindowExW(0x08000000 | 0x80, "BUTTON", "Viewport", 0x80000000 | 0x10000000, -32000, -32000,
                                  200, 120, None, None, None, None)
    assert hwnd
    frame = QWidget()  # hidden: the helper's window gives the picture, the screen is not needed
    holder = QWidget()
    document = SimpleNamespace(standalone_native_host_frame=frame, standalone_rust_child_hwnd=hwnd,
                               standalone_rust_ready=False, live_edit=None, _current_target_entry=lambda: None)
    holder.active = document
    browse.window.shell.mesh_editor_tab = holder
    try:
        from cdmw.mcp.view_tools import _one_colour, window_picture

        # The button paints itself once its thread has handled its first messages.
        picture = browse.mcp.wait_until(lambda: (lambda p: p if p is not None and not _one_colour(p) else None)(
            window_picture(hwnd)))
        assert (picture.width(), picture.height()) == (200, 120)
        # A helper that is not ready is not asked for its picture (the call would wait on it).
        assert "not on screen" in browse.mcp.error("view_capture", {"view": "mesh_editor"})["message"]
        document.standalone_rust_ready = True
        result = browse.mcp.call("view_capture", {"view": "mesh_editor"})
        assert not result["isError"], result["structuredContent"]
        facts = result["structuredContent"]
        assert facts["how"] == "drawn by the editor's window" and (facts["width"], facts["height"]) == (200, 120)
    finally:
        user32.DestroyWindow(hwnd)
        frame.deleteLater()
        holder.deleteLater()
    assert window_picture(hwnd) is None and window_picture(0) is None


# ===== the Texture Editor =====================================================================
class _TextureEditor(QWidget):
    """The editor's controls the tools drive, recording what its handlers were asked."""

    stroke = Signal(object)

    def __init__(self) -> None:
        super().__init__()
        self.calls: list[tuple] = []
        self.history_index = 0
        self.document = SimpleNamespace(
            title="belt_d.dds", width=64, height=32, active_layer_id="l1",
            source_binding=SimpleNamespace(source_path="D:/session/belt_d.dds"),
            layers=(SimpleNamespace(layer_id="l1", name="Background", visible=True),), adjustment_layers=())
        self.current_tool_settings = SimpleNamespace(tool="paint", color_hex="#C85A30")
        self.tool_buttons = {"paint": QPushButton(), "erase": QPushButton(), "fill": QPushButton()}
        self.paint_color_edit = QLineEdit("#C85A30")
        self.brush_size_slider, self.hardness_slider, self.opacity_slider, self.flow_slider = (
            QSlider(), QSlider(), QSlider(), QSlider())
        self.brush_size_slider.setRange(1, 500)
        self.adjustment_add_combo = QComboBox()
        for kind in ("levels", "hue_saturation"):
            self.adjustment_add_combo.addItem(kind.title(), kind)
        self.adjustment_param_a_slider, self.adjustment_param_b_slider, self.adjustment_param_c_slider, \
            self.adjustment_opacity_slider = QSlider(), QSlider(), QSlider(), QSlider()
        for slider in (self.adjustment_param_a_slider, self.adjustment_param_b_slider,
                       self.adjustment_param_c_slider):
            slider.setRange(-180, 180)
        self.canvas = SimpleNamespace(stroke_committed=self.stroke)
        self.stroke.connect(self._stroke)

    def _busy(self) -> bool:
        return False

    def _set_active_tool(self, tool: str) -> None:
        self.current_tool_settings.tool = tool
        self.calls.append(("tool", tool))

    def _handle_tool_settings_changed(self) -> None:
        self.current_tool_settings.color_hex = self.paint_color_edit.text()
        self.calls.append(("settings", self.brush_size_slider.value()))

    def _stroke(self, stroke: dict) -> None:
        self.history_index += 1
        self.calls.append(("stroke", stroke["tool"], list(stroke["points"])))

    def add_adjustment_layer(self) -> None:
        kind = self.adjustment_add_combo.currentData()
        self.document.adjustment_layers += (SimpleNamespace(layer_id=f"a{len(self.document.adjustment_layers)}",
                                                            adjustment_type=kind, enabled=True),)

    def preview_selected_adjustment_properties(self) -> None:
        self.calls.append(("preview", self.adjustment_param_a_slider.value()))

    def commit_selected_adjustment_properties(self) -> None:
        self.history_index += 1
        self.calls.append(("commit",))

    def undo(self) -> None:
        self.history_index -= 1

    def redo(self) -> None:
        self.history_index += 1


@pytest.fixture
def textures(app, connect):
    editor_widget = _TextureEditor()
    panel = QWidget()
    panel.editor = editor_widget
    panel.isFloating = lambda: False
    panel.notice_text, panel.sharing_text, panel.kept_text = "", "Only this model uses this texture.", ""
    opened: list[str] = []
    rows = [SimpleNamespace(texture_id="tex-0", game_path="character/texture/belt_d.dds"),
            SimpleNamespace(texture_id="tex-1", game_path="character/texture/belt_n.dds")]
    tab = SimpleNamespace(
        _texture_tools_panel=lambda: panel, open_texture_in_window=opened.append,
        standalone_workspace=SimpleNamespace(textures_dock=SimpleNamespace(groups=[SimpleNamespace(rows=rows)])),
        _live_texture_updates=SimpleNamespace(edited_textures=lambda: {"belt_d.dds"}),
        _live_texture_keeping=SimpleNamespace(unkept_count=lambda: 1))
    holder = QWidget()
    holder.active = tab
    window = SimpleNamespace(shell=SimpleNamespace(mesh_editor_tab=holder))
    yield SimpleNamespace(mcp=connect(window), editor=editor_widget, opened=opened)
    for widget in (editor_widget, panel, holder):
        widget.deleteLater()


def test_the_texture_editor_is_read_and_driven_through_its_own_controls(textures) -> None:
    mcp, editor_widget = textures.mcp, textures.editor
    state = mcp.ok("textures_state")
    assert state["open"] and (state["title"], state["width"], state["height"]) == ("belt_d.dds", 64, 32)
    assert state["tools"] == ["erase", "fill", "paint"] and state["tool"] == "paint"
    assert state["layers"] == [{"id": "l1", "name": "Background", "visible": True, "active": True}]
    assert state["sharing"] == "Only this model uses this texture." and state["not_kept_yet"] == 1
    # Open: by the panel's id or by game path, as a double-click on the row.
    assert mcp.ok("textures_open", {"texture": "character/texture/belt_n.dds"})["texture"] == "tex-1"
    assert mcp.ok("textures_open", {"texture": "tex-0"})["opening"] and textures.opened == ["tex-1", "tex-0"]
    assert mcp.error("textures_open", {"texture": "nothing.dds"})["code"] == "not_found"
    # Tool and settings, then one stroke: one history step.
    chosen = mcp.ok("textures_tool", {"tool": "erase", "colour": "#00FF00", "size": 24})
    assert chosen == {"tool": "erase", "colour": "#00FF00", "size": 24}
    assert mcp.error("textures_tool", {"tool": "airbrush"})["code"] == "not_found"
    stroke = mcp.ok("textures_stroke", {"tool": "paint", "points": [[0, 0], [10, 5], [63, 31]]})
    assert stroke["changed"] and stroke["history_index"] == 1
    assert editor_widget.calls[-2:] == [("tool", "paint"), ("stroke", "paint", [(0, 0), (10, 5), (63, 31)])]
    assert mcp.error("textures_stroke", {"points": [[64, 0]]})["code"] == "invalid_arguments"
    # An adjustment: chosen in the Add list, its slider set, previewed and committed.
    added = mcp.ok("textures_adjust", {"type": "hue_saturation", "a": 120})
    assert added["added"] == "hue_saturation" and added["history_index"] == 2
    assert editor_widget.calls[-2:] == [("preview", 120), ("commit",)]
    assert "levels, hue_saturation" in mcp.error("textures_adjust", {"type": "sepia"})["message"]
    assert mcp.ok("textures_undo")["history_index"] == 1 and mcp.ok("textures_redo")["history_index"] == 2
    assert mcp.ok("textures_state")["adjustments"] == [{"id": "a0", "type": "hue_saturation", "enabled": True}]
    # No texture open: it says how to open one.
    editor_widget.document = None
    assert mcp.ok("textures_state")["open"] is False
    assert "textures_open" in mcp.error("textures_undo")["message"]


# ===== Create New Item =========================================================================
def test_new_painting_is_opened_filled_and_built_with_the_dialogs_own_controls(studio, connect, tmp_path,  # noqa: F811
                                                                              settings) -> None:
    from PIL import Image

    mcp = connect(studio.window)
    assert mcp.ok("new_item_painting_state") == {"open": False}
    assert "painting_open" in mcp.error("new_item_painting_build", {"folder": str(tmp_path)})["message"]
    opened = mcp.ok("new_item_painting_open")
    assert opened["open"] and studio.shown == ["new_item_studio"]
    state = mcp.wait_until(lambda: (lambda s: s["frames"] and not s["building"] and s)(
        mcp.ok("new_item_painting_state")))
    assert [frame["stem"] for frame in state["frames"]] == ["cd_in_dpw_picture_01", "cd_in_dpw_picture_07"]
    picture = tmp_path / "my_landscape.png"
    Image.new("RGB", (300, 200), (30, 90, 160)).save(picture)
    filled = mcp.ok("new_item_painting_set", {
        "frame": "cd_in_dpw_picture_07", "picture": str(picture), "fit": "whole",
        "texts": {"eng": {"name": "Blue Field", "description": "A test picture."}}, "mod_name": "AI paintings"})
    painting = filled["paintings"][0]
    assert painting["frame"].endswith("cd_in_dpw_picture_07.pam") and painting["picture"] == str(picture)
    assert painting["names"] == {"eng": "Blue Field"} and filled["mod_name"] == "AI paintings"
    assert mcp.error("new_item_painting_set", {"frame": "no_such_frame"})["code"] == "invalid_arguments"
    # Build: into a folder outside the game only.
    game = _game(tmp_path, settings)
    assert "does not write into" in mcp.error("new_item_painting_build", {"folder": str(game)})["message"]
    assert studio.controller.builds == []
    out = tmp_path / "mods"
    out.mkdir()
    assert mcp.ok("new_item_painting_build", {"folder": str(out)})["started"]
    done = mcp.wait_until(lambda: (lambda s: not s["building"] and s)(mcp.ok("new_item_painting_state")))
    requests, folder, title = studio.controller.builds[0]
    assert folder == out and title == "AI paintings" and len(requests) == 1
    assert done["status"].startswith("Wrote 1 painting(s) to")
    assert mcp.ok("new_item_painting_close")["closed"] and not mcp.ok("new_item_painting_state")["open"]


def test_create_new_items_templates_are_searched_and_picked_and_its_controls_listed(app, connect) -> None:
    from PySide6.QtWidgets import QTreeWidget, QTreeWidgetItem, QVBoxLayout

    workflow = QWidget()
    layout = QVBoxLayout(workflow)
    panel = QWidget()
    panel.filter_edit = QLineEdit()
    panel.matches = QTreeWidget()
    names = ("Iron Sword", "Iron Shield", "Silk Cloak")
    picked: list[str] = []

    def refill(text: str) -> None:
        panel.matches.clear()
        for name in names:
            if text.casefold() in name.casefold():
                panel.matches.addTopLevelItem(QTreeWidgetItem([name]))

    panel.filter_edit.textChanged.connect(refill)
    panel.matches.itemClicked.connect(lambda item, _column: picked.append(item.text(0)))
    refill("")
    item_name = QLineEdit()
    item_name.setObjectName("item_name")
    for widget in (panel.filter_edit, panel.matches, item_name, QPushButton("Next")):
        layout.addWidget(widget)
    workflow.template_panel = panel
    workflow.controller = SimpleNamespace(ready=True, busy=False)
    tab = QWidget()
    tab.workflow = workflow
    tab._bridge = object()  # the page is drawn by its helper from these controls
    chooser_open = [False]
    tab._dialogs = SimpleNamespace(dialogs=lambda: (), native_modal=lambda: chooser_open[0])
    window = SimpleNamespace(shell=SimpleNamespace(
        new_item_studio_tab=tab, compact_workspace=SimpleNamespace(_active_tool_key="new_item_studio")))
    mcp = connect(window)
    state = mcp.ok("new_item_state")
    assert state["ready"] and state["templates"] == list(names) and state["picked"] == ""
    found = mcp.ok("new_item_search", {"text": "iron"})
    assert found["templates"] == ["Iron Sword", "Iron Shield"] and found["search"] == "iron"
    assert mcp.ok("new_item_pick", {"match": "shield"})["picked"] == "Iron Shield" and picked == ["Iron Shield"]
    assert mcp.error("new_item_pick", {"match": "axe"})["code"] == "unavailable"
    assert mcp.ok("new_item_state")["picked"] == "Iron Shield"
    # The page's controls are never shown themselves (its helper draws them), yet app_ui
    # lists them and app_ui_act uses them: by the id new_item_state gives, or by default
    # while Create New Item is the shown tool.
    assert not workflow.isVisible()
    for arguments in ({"widget": state["controls"]}, {}):
        kinds = [row["kind"] for row in mcp.ok("app_ui", arguments)["controls"]]
        assert kinds == ["field", "tree", "field", "button"], arguments
    mcp.ok("app_ui_act", {"text": "item_name", "action": "set_text", "value": "Kliff's Blade"})
    assert item_name.text() == "Kliff's Blade"
    # As the page itself: no input while one of its file or colour choosers is open.
    chooser_open[0] = True
    refused = mcp.error("app_ui_act", {"text": "item_name", "action": "set_text", "value": "Other"})
    assert refused == {"code": "unavailable",
                       "message": "Complete the file or colour dialog before editing the item."}
    assert item_name.text() == "Kliff's Blade"
    for widget in (workflow, tab):
        widget.deleteLater()
