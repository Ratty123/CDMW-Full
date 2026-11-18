"""AI connections: the Mesh Editor, Browse view, Texture Editor and Create New Item tools,
each through the real server and bridge, driving the handlers the interface's controls drive."""
from __future__ import annotations

import base64
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from pathlib import Path
from types import SimpleNamespace

import pytest
from PySide6.QtCore import QObject, QSettings, QTimer, Signal
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


def test_mesh_state_says_why_the_editor_cannot_start(connect, app) -> None:
    """A page whose helper failed its checks says so, as its status line does."""

    holder = QWidget()
    holder.active = SimpleNamespace(standalone_rust_incompatible_reason="provenance manifest is missing",
                                    standalone_rust_authoring_session=None)
    holder.documents = [holder.active]
    try:
        mcp = connect(SimpleNamespace(shell=SimpleNamespace(mesh_editor_tab=holder)))
        state = mcp.ok("mesh_state")
        assert state["open"] is False
        assert state["unavailable"] == "Mesh Editor unavailable: provenance manifest is missing"
        assert "asks" not in state
        assert mcp.error("mesh_draft_choice", {"answer": "fresh"})["code"] == "unavailable"
        # "Continue where you left off?": shown as 'asks', answered by its own buttons.
        pressed = []
        page = SimpleNamespace(**{name: SimpleNamespace(click=lambda n=name: pressed.append(n)) for name in (
            "draft_resume_button", "draft_start_fresh_button", "draft_choice_cancel_button")})
        holder.active.__dict__.update(page.__dict__, _draft_choice_showing=lambda: not pressed,
                                      draft_choice_label=SimpleNamespace(text=lambda: "1 saved draft"))
        asks = mcp.ok("mesh_state")["asks"]
        assert asks["text"] == "1 saved draft" and asks["answers"] == ["cancel", "fresh", "resume"]
        assert mcp.ok("mesh_draft_choice", {"answer": "fresh"})["answered"] == "fresh"
        assert pressed == ["draft_start_fresh_button"] and "asks" not in mcp.ok("mesh_state")
    finally:
        holder.deleteLater()


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
    # After Finish the helper and its session are gone; the finished document still builds.
    hair[0], building[0] = False, False
    session, ui.standalone_rust_authoring_session = ui.standalone_rust_authoring_session, None
    ui.standalone_controller = SimpleNamespace(active_session_id="finished")
    try:
        assert mcp.ok("mesh_build_mod", {"output_folder": str(out), "mod_name": "After finish"})["started"]
        assert built[-1][0] == "After finish"
        ui.standalone_controller = None  # nothing open at all
        assert mcp.error("mesh_build_mod", {"output_folder": str(out)})["code"] == "unavailable"
    finally:
        ui.standalone_rust_authoring_session = session
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


def test_the_texture_tools_paint_adjust_and_undo_a_real_texture_editor(connect, tmp_path) -> None:
    """The real Texture Editor, not a stand-in: a stroke and an adjustment are one Undo step
    each, and Undo brings the pixels back."""

    import numpy as np

    from cdmw.models import TextureEditorDocument, TextureEditorLayer
    from cdmw.ui.texture_editor_tab import TextureEditorTab

    editor = TextureEditorTab(settings=create_settings(settings_file_path=tmp_path / "texture.cfg"),
                              base_dir=tmp_path, get_png_root=lambda: str(tmp_path))
    panel, holder = QWidget(), QWidget()
    try:
        editor.document = TextureEditorDocument("Probe", 128, 64, active_layer_id="paint",
                                                layers=(TextureEditorLayer("paint", "Paint", "unused.png"),))
        editor.layer_pixels = {"paint": np.full((64, 128, 4), 90, dtype=np.uint8)}
        editor._push_history("Open Document")
        editor._refresh_ui()
        panel.editor = editor
        panel.isFloating = lambda: False
        panel.notice_text = panel.sharing_text = panel.kept_text = ""
        holder.active = SimpleNamespace(_texture_tools_panel=lambda: panel)
        mcp = connect(SimpleNamespace(shell=SimpleNamespace(mesh_editor_tab=holder)))
        opened = mcp.ok("textures_state")
        assert opened["open"] and (opened["width"], opened["height"]) == (128, 64)
        start, before = opened["history_index"], editor.layer_pixels["paint"].copy()
        chosen = mcp.ok("textures_tool", {"tool": "paint", "colour": "#FF0000", "size": 12, "opacity": 100})
        assert chosen["tool"] == "paint" and chosen["colour"].upper() == "#FF0000"
        stroke = mcp.ok("textures_stroke", {"points": [[10, 32], [100, 32]]})
        assert stroke["changed"] and stroke["history_index"] == start + 1
        painted = editor.layer_pixels["paint"].copy()
        assert not np.array_equal(painted, before) and painted[32, 50, 0] > painted[32, 50, 1]
        kinds = [str(editor.adjustment_add_combo.itemData(row)) for row in range(editor.adjustment_add_combo.count())]
        added = mcp.ok("textures_adjust", {"type": kinds[0]})
        assert added["history_index"] == start + 2  # adding alone is one Undo step
        adjustment = editor.document.adjustment_layers[-1]
        set_too = mcp.ok("textures_adjust", {"type": kinds[0], "opacity": 40})
        assert set_too["history_index"] == start + 4  # adding, then its sliders: two
        assert editor.document.adjustment_layers[-1].opacity == 40 and adjustment.opacity != 40
        for step in (start + 3, start + 2, start + 1):
            assert mcp.ok("textures_undo")["history_index"] == step
        np.testing.assert_array_equal(editor.layer_pixels["paint"], painted)
        assert mcp.ok("textures_undo")["history_index"] == start
        np.testing.assert_array_equal(editor.layer_pixels["paint"], before)
        assert mcp.ok("textures_redo")["history_index"] == start + 1
        np.testing.assert_array_equal(editor.layer_pixels["paint"], painted)
    finally:
        editor.request_shutdown()
        for widget in (editor, panel, holder):
            widget.deleteLater()


def test_the_texture_editor_is_read_and_driven_through_its_own_controls(textures) -> None:
    mcp, editor_widget = textures.mcp, textures.editor
    state = mcp.ok("textures_state")
    assert state["open"] and (state["title"], state["width"], state["height"]) == ("belt_d.dds", 64, 32)
    assert state["tools"] == ["erase", "fill", "paint"] and state["tool"] == "paint"
    assert state["layers"] == [{"id": "l1", "name": "Background", "visible": True, "active": True,
                                "opacity": 100, "blend": "normal", "locked": False, "alpha_locked": False,
                                "mask": None, "mask_enabled": False}]
    assert state["sharing"] == "Only this model uses this texture." and state["not_kept_yet"] == 1
    # Open: by the panel's id or by game path, as a double-click on the row.
    assert mcp.ok("textures_open", {"texture": "character/texture/belt_n.dds"})["texture"] == "tex-1"
    assert mcp.ok("textures_open", {"texture": "tex-0"})["opening"] and textures.opened == ["tex-1", "tex-0"]
    assert mcp.error("textures_open", {"texture": "nothing.dds"})["code"] == "not_found"
    # Tool and settings, then one stroke: one history step.
    chosen = mcp.ok("textures_tool", {"tool": "erase", "colour": "#00FF00", "size": 24})
    assert chosen == {"tool": "erase", "colour": "#00FF00", "size": 24, "editor": "docked",
                      "history_before": 0, "history_after": 0, "history_index": 0}
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


class _TemplateSearch(QObject):
    """Create New Item's controller as its search sees it: results arrive later, on a signal."""

    template_search_ready = Signal(object)
    ready = True
    busy = False


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

    controller = _TemplateSearch()

    def search_later(text: str) -> None:  # as the page: the old rows stay until the result is in
        QTimer.singleShot(150, lambda: (refill(text), controller.template_search_ready.emit([])))

    panel.filter_edit.textChanged.connect(search_later)
    panel.matches.itemClicked.connect(lambda item, _column: picked.append(item.text(0)))
    refill("")
    item_name = QLineEdit()
    item_name.setObjectName("item_name")
    for widget in (panel.filter_edit, panel.matches, item_name, QPushButton("Next")):
        layout.addWidget(widget)
    workflow.template_panel = panel
    workflow.controller = controller
    from cdmw.ui.new_item.workflow_header import WorkflowHeader

    workflow.steps = WorkflowHeader(["Template", "Identity", "Model"])  # the step header, as the page has
    workflow.steps.setCurrentRow(1)
    tab = QWidget()
    tab.workflow = workflow
    tab._bridge = object()  # the page is drawn by its helper from these controls
    chooser_open = [False]
    tab._dialogs = SimpleNamespace(dialogs=lambda: (), native_modal=lambda: chooser_open[0])
    window = SimpleNamespace(shell=SimpleNamespace(
        new_item_studio_tab=tab, compact_workspace=SimpleNamespace(_active_tool_key="new_item_studio")))
    mcp = connect(window)
    # Still building its pages: the page has no template list yet, and the tools say so.
    workflow.template_panel = None
    for tool, arguments in (("new_item_search", {"text": "x"}), ("new_item_pick", {"row": 0})):
        assert mcp.error(tool, arguments)["code"] == "unavailable", tool
    workflow.template_panel = panel
    state = mcp.ok("new_item_state")
    assert state["ready"] and state["templates"] == list(names) and state["picked"] == ""
    assert [row["name"] for row in state["steps"]] == ["Template", "Identity", "Model"]
    assert state["step"] == ["Template", "Identity", "Model"][workflow.steps.currentRow()]
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
    for widget in (workflow, tab, workflow.steps):
        widget.deleteLater()


def test_mesh_state_history_counts_texture_edits_as_the_editor_does() -> None:
    """A texture edit is a step of the document's one history: mesh_state counts it as the
    editor's History list and Undo do, and still says how many are mesh steps."""

    from cdmw.mcp.mesh_tools import _shared_history
    from cdmw.ui.mesh_editor.shared_edit_history import SharedEditHistory

    history = SharedEditHistory()
    session = SimpleNamespace(shared_history=history)
    history.merged([{"action": "select", "label": "Select", "state": "applied"}])
    assert _shared_history(session) is None  # mesh steps only: the session's own counts hold
    opened, painted = object(), object()
    history.observe_texture("key", "belt_d.dds", [opened], 0)
    history.observe_texture("key", "belt_d.dds", [opened, painted], 1)
    merged = _shared_history(session)
    assert merged["undo"] == 2 and merged["redo"] == 0 and merged["can_undo"] and merged["cursor"] == 2
    assert merged["steps"] == ["Select", "Texture edit (belt_d.dds)"]
    history.observe_texture("key", "belt_d.dds", [opened, painted], 0)  # undone in the Texture Editor
    assert (_shared_history(session)["undo"], _shared_history(session)["redo"]) == (1, 1)


@pytest.fixture
def texture_pair(connect, tmp_path):
    import numpy as np
    from cdmw.models import TextureEditorDocument, TextureEditorLayer
    from cdmw.ui.texture_editor_tab import TextureEditorTab

    editors = []
    panel, holder = QWidget(), QWidget()
    try:
        for location, colour in (("docked", [90, 110, 130, 255]), ("tool", [10, 60, 80, 255])):
            widget = TextureEditorTab(settings=create_settings(settings_file_path=tmp_path / f"{location}.cfg"),
                                      base_dir=tmp_path, get_png_root=lambda: str(tmp_path))
            editors.append(widget)
            widget.document = TextureEditorDocument(location, 32, 24, active_layer_id="top",
                layers=(TextureEditorLayer("base", "Base", "base.png"), TextureEditorLayer("top", "Top", "top.png")))
            widget.layer_pixels = {"base": np.full((24, 32, 4), 20, dtype=np.uint8),
                                   "top": np.tile(np.uint8(colour), (24, 32, 1))}
            widget._push_history("Open Document")
            widget._refresh_ui()
        panel.editor = editors[0]
        panel.isFloating = lambda: False
        holder.active = SimpleNamespace(_texture_tools_panel=lambda: panel)
        window = SimpleNamespace(shell=SimpleNamespace(mesh_editor_tab=holder, texture_editor_tab=editors[1]))
        yield connect(window), editors[0], editors[1]
    finally:
        for widget in editors:
            widget.request_shutdown()
        for widget in [*editors, panel, holder]:
            widget.deleteLater()


def _raster_state(editor):
    doc = editor.document
    return (doc.width, doc.height, doc.layers, doc.adjustment_layers, doc.selection, doc.quick_mask_enabled, doc.floating_selection,
            {key: (pixels.shape, pixels.tobytes()) for key, pixels in editor.layer_pixels.items()})


def _undoable_texture_call(mcp, editor, tool, args):
    before = _raster_state(editor)
    start = editor.history_index
    result = mcp.ok(tool, {"editor": "tool", **args})
    assert (result["history_before"], result["history_after"]) == (start, start + 1), (tool, args, result)
    assert _raster_state(editor) != before
    undo = mcp.ok("textures_undo", {"editor": "tool"})
    assert (undo["history_before"], undo["history_after"]) == (start+1, start)
    assert _raster_state(editor) == before, (tool, args)


def test_texture_layers_masks_and_editor_ownership(texture_pair):
    mcp, dock, rail = texture_pair
    states = mcp.ok("textures_state", {"editor": "tool"})
    assert states["title"] == "tool" and states["editors"]["docked"]["title"] == "docked"
    dock_start = _raster_state(dock)
    for action, parameters in [
        ("add", {}), ("duplicate", {}), ("remove", {}), ("merge_down", {}), ("move_down", {}),
        ("rename", {"name": "Leather"}), ("opacity", {"opacity": 28}), ("blend", {"mode": "multiply"}),
        ("visibility", {"enabled": False}), ("lock", {"enabled": True}), ("alpha_lock", {"enabled": True}),
        ("mask_add", {}),
    ]:
        _undoable_texture_call(mcp, rail, "textures_layer", {"action": action, **parameters})
    mcp.ok("textures_layer", {"editor": "tool", "action": "mask_add"})
    for action, parameters in [("mask_invert", {}), ("mask_enable", {"enabled": False}),
                               ("mask_delete", {}), ("mask_to_selection", {})]:
        _undoable_texture_call(mcp, rail, "textures_layer", {"action": action, **parameters})
    before = rail.history_index
    result = mcp.ok("textures_layer", {"editor": "tool", "action": "mask_target", "enabled": True})
    assert rail._editing_mask_target and result["history_before"] == result["history_after"] == before
    mcp.ok("textures_layer", {"editor": "tool", "action": "mask_target", "enabled": False})
    mcp.ok("textures_select", {"editor": "tool", "action": "rect", "points": [[2, 2], [15, 14]]})
    _undoable_texture_call(mcp, rail, "textures_layer", {"action": "selection_to_mask"})
    active = mcp.ok("textures_layer", {"editor": "tool", "action": "active", "layer": "base"})
    assert rail.document.active_layer_id == "base" and active["history_before"] == active["history_after"]
    _undoable_texture_call(mcp, rail, "textures_layer", {"action": "move_up"})
    assert _raster_state(dock) == dock_start


def test_texture_selection_fill_generate_and_derive_undo(texture_pair):
    mcp, dock, rail = texture_pair
    for args in ({"action": "all"}, {"action": "rect", "points": [[4, 5], [19, 18]]},
                 {"action": "lasso", "points": [[2, 2], [20, 2], [8, 19]]}, {"action": "quick_mask"}):
        _undoable_texture_call(mcp, rail, "textures_select", args)
    mcp.ok("textures_select", {"editor": "tool", "action": "rect", "points": [[4, 5], [19, 18]]})
    for action in ("invert", "grow", "shrink", "copy_to_layer", "clear"):
        _undoable_texture_call(mcp, rail, "textures_select", {"action": action})
    for tool, actions in (("textures_fill", ["fill", "gradient"]), ("textures_generate", ["solid", "gradient", "pattern", "noise"])):
        for action in actions:
            args = {"action": action, "colour": "#ff0000", "points": [[8, 8]]}
            if action in ("solid", "gradient"):
                args.update(secondary="#0000ff", points=[[8, 8], [19, 18]])
            _undoable_texture_call(mcp, rail, tool, args)
    for args in ({"action": "pack", "channel": "green"}, {"action": "unpack", "channel": "alpha"},
                 {"action": "resize", "width": 20, "height": 17}, {"action": "canvas_size", "width": 17, "height": 20}):
        _undoable_texture_call(mcp, rail, "textures_derive", args)
    for action, value, control in (("mips", "single", rail.native_dds_mip_combo),
                                   ("format", rail.native_dds_format_combo.itemData(0), rail.native_dds_format_combo)):
        result = mcp.ok("textures_derive", {"editor": "tool", "action": action, "value": value})
        assert result["history_before"] == result["history_after"] and control.currentData() == value


def test_texture_png_transfer_and_compare(texture_pair, tmp_path):
    from io import BytesIO
    import numpy as np
    from PIL import Image
    mcp, dock, rail = texture_pair
    patch = np.tile(np.uint8([250, 35, 15, 77]), (3, 4, 1))
    png = tmp_path / "patch.png"
    Image.fromarray(patch).save(png)
    data = base64.b64encode(png.read_bytes()).decode("ascii")
    target = {"editor": "tool"}
    for tool, source in (("textures_import_pixels", {"path": str(png), "name": "Decal"}),
                         ("textures_write_region", {"data": data})):
        before = _raster_state(rail)
        result = mcp.ok(tool, {**target, **source, "x": 5, "y": 6})
        assert result["history_after"] == result["history_before"] + 1
        added = tool == "textures_import_pixels"
        x, y = (0, 0) if added else (5, 6)
        read = mcp.ok("textures_read_region", {**target, "layer": result["layer"], "x": x, "y": y, "width": 4, "height": 3})
        np.testing.assert_array_equal(Image.open(BytesIO(base64.b64decode(read["data"]))), patch)
        if added:
            assert rail.document.layers[-1].name == "Decal"
        picture = mcp.call("view_texture_image", {**target, "max_side": 16})
        assert not picture["isError"] and picture["content"][0]["type"] == "image"
        assert picture["structuredContent"]["width"] == 16
        mcp.ok("textures_undo", target)
        assert _raster_state(rail) == before
    assert mcp.error("textures_write_region", {**target, "x": 31, "y": 23, "data": data})["code"] == "invalid_arguments"
    assert mcp.error("textures_import_pixels", {**target, "data": "abcd", "path": str(png)})["code"] == "invalid_arguments"
    assert mcp.error("textures_read_region", {**target, "width": 33, "height": 24})["code"] == "invalid_arguments"
    compare = mcp.ok("textures_compare", {**target, "mode": "split", "split": 35})
    assert compare == {"mode": "split", "split": 35} and rail.view_mode_combo.currentData() == "split"
    assert dock.view_mode_combo.currentData() == "edited"


def test_texture_export_and_reopen_project(texture_pair, tmp_path, settings):
    import numpy as np
    from PIL import Image
    mcp, dock, rail = texture_pair
    target = {"editor": "tool"}
    game = _game(tmp_path, settings)
    export = {**target, "format": "png", "path": str(game / "image.png")}
    assert mcp.error("textures_export", export)["code"] == "refused"
    png = tmp_path / "output.png"
    mcp.ok("textures_export", {**export, "path": str(png)})
    mcp.wait_until(lambda: png.exists() and not rail._busy())
    np.testing.assert_array_equal(np.array(Image.open(png)), rail._current_composite_rgba())
    assert mcp.error("textures_export", {**export, "path": str(png)})["code"] == "refused"
    from cdmw.core.texture_native import find_directxtex_texture_binary
    dds = tmp_path / "output.dds"
    dds_args = {**target, "format": "dds", "path": str(dds)}
    if find_directxtex_texture_binary():
        mcp.ok("textures_derive", {**target, "action": "mips", "value": "single"})
        failure = mcp.error("textures_export", dds_args)
        assert failure["code"] == "failed" and "mips" in failure["message"] and not dds.exists()
        mcp.ok("textures_derive", {**target, "action": "mips", "value": "full"})
        mcp.ok("textures_export", dds_args)
        mcp.wait_until(lambda: dds.exists() and not rail._busy())
        data = dds.read_bytes()
        assert data[:4] == b"DDS " and int.from_bytes(data[12:16], "little") == 24
        assert int.from_bytes(data[16:20], "little") == 32 and int.from_bytes(data[28:32], "little") == 6
    else:
        assert mcp.error("textures_export", dds_args)["code"] == "unavailable"
    project = tmp_path / "layers.ctfedit.json"
    mcp.ok("textures_export", {**target, "format": "project", "path": str(project)})
    mcp.wait_until(lambda: project.exists() and not rail._busy())
    before = _raster_state(rail)
    mcp.ok("textures_open", {**target, "texture": str(png), "source": "file"})
    mcp.wait_until(lambda: not rail._busy() and rail.document.title != "tool")
    mcp.ok("textures_open", {**target, "texture": str(project), "source": "project"})
    mcp.wait_until(lambda: not rail._busy() and rail.document.title == "tool")
    assert rail.document.layers[1].name == "Top"
    assert _raster_state(rail)[-1] == before[-1]
    project.unlink()
    assert mcp.error("textures_export", {**target, "format": "project", "path": str(project)})["code"] == "refused"



def test_texture_registry_commands_follow_the_shown_owner(texture_pair):
    mcp, dock, rail = texture_pair
    dock.show()
    dock_size, rail_size = len(dock.document.layers), len(rail.document.layers)
    mcp.ok("app_run_command", {"command": "texture_editor.new_layer"})
    assert len(dock.document.layers) == dock_size + 1 and len(rail.document.layers) == rail_size
    dock.hide()
    rail.show()
    mcp.ok("app_run_command", {"command": "texture_editor.new_layer"})
    assert len(rail.document.layers) == rail_size + 1
    mcp.ok("textures_undo", {"editor": "tool"})
    assert len(rail.document.layers) == rail_size and len(dock.document.layers) == dock_size + 1


def test_texture_adjustments_floating_channels_and_stamp(texture_pair, tmp_path):
    from PIL import Image
    mcp, dock, rail = texture_pair
    target = {"editor": "tool"}
    adj = mcp.ok("textures_adjust", {**target, "type": "levels"})["id"]
    for args in ({"action": "update", "opacity": 30}, {"action": "enable", "enabled": False},
                 {"action": "mask_active"}, {"action": "duplicate"}, {"action": "remove"}):
        _undoable_texture_call(mcp, rail, "textures_adjust", {**args, "id": adj})
    for args in ({"action": "swap_channels", "channel": "red", "other_channel": "blue"},
                 {"action": "channel_to_selection", "channel": "red"}):
        _undoable_texture_call(mcp, rail, "textures_derive", args)
    _undoable_texture_call(mcp, rail, "textures_layer", {"action": "float_copy"})
    mcp.ok("textures_layer", {**target, "action": "float_copy"})
    for action, args in [("float_transform", {"scale": 75, "rotation": 25}), ("float_flip_h", {}),
                         ("float_commit", {}), ("float_cancel", {})]:
        _undoable_texture_call(mcp, rail, "textures_layer", {"action": action, **args})
    mcp.ok("textures_undo", target)
    stamp = tmp_path / "stamp.png"
    Image.new("RGBA", (5, 5), "white").save(stamp)
    result = mcp.ok("textures_fill", {**target, "action": "load_stamp", "path": str(stamp)})
    assert rail.current_tool_settings.custom_brush_tip_path == str(stamp)
    assert result["history_before"] == result["history_after"]
    _undoable_texture_call(mcp, rail, "textures_fill", {"action": "stamp", "colour": "#ff8822", "points": [[9, 7]]})
    result = mcp.ok("textures_fill", {**target, "action": "clear_stamp"})
    assert not rail.current_tool_settings.custom_brush_tip_path and result["history_before"] == result["history_after"]
    mcp.ok("textures_tool", {**target, "tool": "clone", "clone_source": [4, 3],
           "settings": {"roundness": 45, "symmetry_mode": "horizontal", "clone_aligned": False}})
    settings = rail.current_tool_settings
    assert (settings.roundness, settings.symmetry_mode, settings.clone_aligned) == (45, "horizontal", False)
    assert settings.clone_source_point == (4, 3)
    mcp.ok("textures_select", {**target, "action": "rect", "points": [[2, 3], [12, 11]]})
    _undoable_texture_call(mcp, rail, "textures_select", {"action": "feather", "radius": 2})



def test_texture_history_and_atlas(texture_pair, tmp_path):
    from PIL import Image
    mcp, dock, rail = texture_pair
    target = {"editor": "tool"}
    before = _raster_state(rail)
    selection = mcp.ok("textures_select", {**target, "action": "rect", "points": [[3, 2], [9, 10]]})
    step = selection["history_after"]
    selected = _raster_state(rail)
    region = tmp_path / "region.png"
    mcp.ok("textures_export", {**target, "format": "selection", "path": str(region), "padding": 1})
    with Image.open(region) as image:
        assert image.size == (8, 10)
    atlas = tmp_path / "atlas"
    mcp.ok("textures_export", {**target, "format": "grid", "path": str(atlas), "cell_size": 16, "padding": 0})
    assert len(list(atlas.glob("*.png"))) == 4
    assert mcp.error("textures_export", {**target, "format": "grid", "path": str(atlas)})["code"] == "refused"
    restored = mcp.ok("textures_history", {**target, "action": "restore", "index": step-1})
    assert restored["history_after"] == step-1 and _raster_state(rail) == before
    mcp.ok("textures_redo", target)
    assert _raster_state(rail) == selected
    cleared = mcp.ok("textures_history", {**target, "action": "clear"})
    assert cleared["history_after"] == 0 and cleared["steps"] == 1 and _raster_state(rail) == selected


def test_texture_worker_rejects_a_changed_document(texture_pair, tmp_path, monkeypatch):
    from threading import Event
    from PIL import Image
    from cdmw.ui.texture_workflow import editor_document_state
    mcp, dock, rail = texture_pair
    png = tmp_path / "import.png"
    Image.new("RGBA", (3, 4), "red").save(png)
    ready, resume = Event(), Event()
    prepare = editor_document_state.texture_editor_png_change

    def delayed(*args, **kwargs):
        ready.set()
        assert resume.wait(5)
        return prepare(*args, **kwargs)

    monkeypatch.setattr(editor_document_state, "texture_editor_png_change", delayed)
    mcp.send("textures_import_pixels", {"editor": "tool", "path": str(png)})
    try:
        mcp.wait_until(ready.is_set)
        rail.add_layer_button.click()
        expected = _raster_state(rail)
    finally:
        resume.set()
    result = mcp.read()
    assert result["structuredContent"]["error"]["code"] == "unavailable"
    assert _raster_state(rail) == expected and rail.history_index == 1


def test_docked_texture_output_plan_matches_build_mod(texture_pair):
    from types import MethodType
    from cdmw.ui.mesh_editor.tab_rust_process import MeshEditorRustProcessMixin
    mcp, dock, rail = texture_pair
    tab = mcp.window.shell.mesh_editor_tab.active
    tab._live_texture_plan = MethodType(MeshEditorRustProcessMixin._live_texture_plan, tab)
    rgba = dock._current_composite_rgba()
    image = QImage(rgba.data, 32, 24, 128, QImage.Format_RGBA8888).copy()
    path = "textures/owned.dds"
    source = SimpleNamespace(game_path=path, original=None, users=("Coat",))
    tab._live_texture_updates = SimpleNamespace(edited_textures=lambda: {"key": image}, sources={"key": source})
    tab._archive_texture_indexes = lambda: ({}, {})
    tab._parts_in_build = lambda *, include_body: ("Coat",) if include_body else ()
    expected = tab._live_texture_plan()
    plan = mcp.ok("textures_output_plan")
    assert plan["lines"] == list(expected.plan_lines) and path in plan["refusals"][0]
    without_body = mcp.ok("textures_output_plan", {"include_body": False})
    assert path in without_body["left_out"][0] and without_body["refusals"] == []
    assert dock.history_index == 0
