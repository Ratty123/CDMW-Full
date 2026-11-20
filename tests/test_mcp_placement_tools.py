"""Typed placement calls against the real window, with the studio's owned game-file fixtures."""
from __future__ import annotations

import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from concurrent.futures import ThreadPoolExecutor
from types import SimpleNamespace

import pytest
from PySide6.QtCore import QCoreApplication, QEvent
from PySide6.QtGui import QImage
from PySide6.QtWidgets import QApplication

from cdmw.mcp.errors import ToolError
from cdmw.mcp.placement_tools import placement_tools
from cdmw.mcp.schema import validate_arguments
from cdmw.mcp.server import ToolCall
from cdmw.mcp.tools import ON_WORKER
from cdmw.ui.ai_connections.executor import UiExecutor
from tests.test_placement_studio_animation_editor import TARGET, _wait, window
from tests.test_placement_studio_carry_plan import _hierarchy
from tests.test_placement_studio_carry_timing import CHART, TWO_HAND, chart_bytes
from tests.test_placement_studio_operations import BODY
from tests.test_placement_studio_task_layout import _papr
from tests.test_posemodifier_xml import SAMPLE_BYTES
from tools.placement_studio.rig_files import RigFiles
from tools.placement_studio.tab import PlacementStudioTab


@pytest.fixture
def client(window, monkeypatch, tmp_path):
    # The baseline and clip are the animation editor's fixtures. Keep archive discovery local too.
    monkeypatch.setattr(PlacementStudioTab, "_bootstrap", lambda self: None)
    tab = PlacementStudioTab()
    tab._studio = window
    shell = SimpleNamespace(placement_studio_tab=tab, _activate_tool_key=lambda key: None)
    executor = UiExecutor(tab)
    context = SimpleNamespace(window=SimpleNamespace(shell=shell), ui_call=executor.call,
                              game_folder=lambda: str(tmp_path / "game"))
    table = {tool.name: tool for tool in placement_tools()}
    path = "character/model/1_pc/1_phm/phm_01.papr"
    window._session.skeleton_path = path.removesuffix(".papr") + ".pab"
    window._rig_files_cache = RigFiles((path,), {path: _papr()}, SAMPLE_BYTES)
    window._clip_index_started = True
    window._edits.add_base_file(CHART, chart_bytes())

    def call(tool_name, **args):
        tool = table["placement." + tool_name]
        request = ToolCall(tool, validate_arguments(args, tool.input_schema), context)
        if tool.runs_on != ON_WORKER:
            return tool.handler(request)
        with ThreadPoolExecutor(max_workers=1) as pool:
            future = pool.submit(tool.handler, request)
            _wait(future.done)
            return future.result()

    call.tab = tab
    yield call
    tab._studio = None
    tab.close()
    tab.deleteLater()
    QCoreApplication.sendPostedEvents(None, QEvent.DeferredDelete)


def test_open_and_state_show_the_windows_own_selections(client, window):
    from tools.placement_studio.armour import ArmourIndex, ArmourPiece, SLOT_KEYS
    state = client("state")
    assert state["open"] and state["ready"] and state["events"] and state["routes"]
    assert BODY in {s["file"] for s in state["sockets"]}
    assert client("open", action="prepare")["ready"]
    name = state["characters"][0]["id"]
    client("open", action="character", name=name)
    assert window._model_box.currentData() == name
    weapon = next(item["id"] for item in state["weapons"] if item["id"])
    client("open", action="weapon", name=weapon)
    assert window._session.weapon.weapon_id == weapon
    client("open", action="weapon", name=window._weapon_box.itemText(0))
    assert window._session.weapon is None
    piece = ArmourPiece("character/model/test_hat.pac", SLOT_KEYS[0], name)
    window._armour_index = ArmourIndex([piece])
    client("open", action="armour", slot=piece.slot, name=piece.name)
    assert window._armour_choice == {piece.slot: piece.path}
    client("open", action="armour", slot=piece.slot, name="")
    assert not window._armour_choice


@pytest.mark.parametrize("action,fields", [
    ("translate", {"translation": [0.12, -0.23, 0.34]}),
    ("rotate", {"euler": [12, -24, 35]}),
    ("rotate", {"quaternion": [0, 1, 0, 0]}),
    ("reparent", {"parent": "Bip01 Spine2"}),
])
def test_socket_edits_undo_and_redo_the_same_window_command(client, window, action, fields):
    window._session.hierarchy = _hierarchy()
    window._after_edit()
    name = "Pelvis_L_Socket"
    read = lambda: window._edits.socket(BODY, name)
    original = read()
    result = client("socket", action=action, name=name, **fields)
    assert result["history_before"]["placement"]["position"] == 0
    assert result["history_after"]["placement"]["position"] > 0
    edited = read()
    assert edited != original and window._mod_changes()
    if "translation" in fields:
        assert [edited.translation.x, edited.translation.y, edited.translation.z] == pytest.approx(fields["translation"])
    client("undo")
    assert read() == original and not window._mod_changes()
    client("redo")
    assert read() == edited


def test_add_and_route_restore_independently(client, window):
    window._session.hierarchy = _hierarchy()
    window._after_edit()
    client("socket", action="add", file=BODY, name="TestSocket", parent="Bip01 Pelvis")
    assert window._session.placed("TestSocket")
    original = next(b.part.in_socket for b in window._bindings if b.part_name == TWO_HAND)
    client("socket", action="route", name="TestSocket", part=TWO_HAND, role="stowed")
    assert next(b.part.in_socket for b in window._bindings if b.part_name == TWO_HAND) == "TestSocket"
    client("undo")
    assert next(b.part.in_socket for b in window._bindings if b.part_name == TWO_HAND) == original
    client("undo")
    assert not window._session.placed("TestSocket")


@pytest.mark.parametrize("lane", ["pose", "reach"])
def test_timeline_keys_and_clip_replacement(client, window, lane):
    client("animation", action="start")
    box = window._pose_bone_box if lane == "pose" else window._reach_end_box
    track = box.currentText()
    args = dict(lane=lane, track=track)
    client("animation", action="edit_key", seconds=0.2, translation=[0.02, 0, 0], **args)
    get_track = lambda: (window._clip_edit.pose if lane == "pose" else window._clip_edit.reach)[0]
    assert get_track().keys[0].frame == 6
    result = client("animation", action="move_key", seconds=0.2, to_seconds=0.5, **args)
    assert result["history_after"]["animation"]["position"] == result["history_before"]["animation"]["position"] + 1
    assert get_track().keys[0].frame == 15
    client("undo")
    assert get_track().keys[0].frame == 6
    client("redo")
    assert get_track().keys[0].frame == 15
    client("animation", action="remove_key", seconds=0.5, **args)
    assert not (window._clip_edit.pose if lane == "pose" else window._clip_edit.reach)
    client("undo")
    assert get_track().keys[0].frame == 15
    if lane == "reach":
        client("animation", action="plant", seconds=0.1, **args)
        assert get_track().keys[0].pinned
        client("animation", action="release", seconds=0.1, **args)
        assert not get_track().keys[0].pinned
        client("undo")
        assert get_track().keys[0].pinned
    before_clear = get_track()
    client("animation", action="clear_track", **args)
    assert not (window._clip_edit.pose if lane == "pose" else window._clip_edit.reach)
    client("undo")
    assert get_track() == before_clear
    client("animation", action="replace_clip", target=TARGET)
    assert TARGET in window._edits.modified_paths()
    client("undo", area="placement")
    assert TARGET not in window._edits.modified_paths()


def test_retime_is_scoped_saveable_and_undoable(client, window):
    initial = window._edits.chart_bytes(CHART)
    result = client("animation", action="retime_event", chart=CHART, animation=0, event=0, seconds=0.45)
    assert result["history_after"]["placement"]["position"] == 1
    state = client("state", chart=CHART)
    assert state["events"][0]["seconds"] == pytest.approx(0.45)
    assert state["pending"][0]["saveable"]
    client("undo")
    assert window._edits.chart_bytes(CHART) == initial


def test_constraints_and_rig_use_their_pages_and_history(client, window):
    client("open", action="constraints")
    chain = window._selected_chain()
    client("constraints", action="off", chain=chain.name)
    assert window._selected_chain().strength == 0 and window.constraint_mod_files()
    client("undo")
    assert window._selected_chain().strength == chain.strength and not window.constraint_changes()
    client("redo")
    assert window._selected_chain().strength == 0
    client("open", action="rig")
    row = next(i for i, s in enumerate(window._behaviour_rows) if s.label == "YawRange")
    original = window._behaviour_rows[row].value
    client("rig", action="set", row=row, value="-50 50")
    assert window._behaviour_rows[row].value == "-50 50" and window.rig_behaviour_changes()
    client("undo")
    assert window._behaviour_rows[row].value == original and not window.rig_behaviour_changes()
    client("redo")
    assert window._behaviour_rows[row].value == "-50 50"


def test_empty_rig_page_keeps_placement_undo_available(client, window):
    initial = window._edits.chart_bytes(CHART)
    client("animation", action="retime_event", chart=CHART, animation=0, event=0, seconds=0.45)
    client("open", action="rig")
    assert window._undo_button.isEnabled()
    assert client("undo")["area"] == "placement"
    assert window._edits.chart_bytes(CHART) == initial


def test_playback_and_capture_the_actual_viewport(client, window):
    client("playback", action="play")
    assert window._playback_timer.isActive()
    client("playback", action="pause")
    assert not window._playback_timer.isActive()
    client("playback", action="scrub", seconds=0.4)
    assert window._playback.frame == 12
    image = client("capture", max_side=256)
    assert image.facts["playback"]["seconds"] == 0.4
    png = QImage.fromData(image.data)
    assert 0 < png.width() == image.facts["width"] <= 256
    assert 0 < png.height() == image.facts["height"] <= 256


def test_save_mod_writes_checked_bytes_only_to_a_new_folder(client, window, tmp_path, monkeypatch):
    client("animation", action="retime_event", chart=CHART, animation=0, event=0, seconds=0.45)
    timing_key = window._mod_changes()[0].key
    client("open", action="constraints")
    client("constraints", action="off", chain=window._selected_chain().name)
    excluded_path = next(iter(window.constraint_mod_files()))
    assert len(window._mod_changes()) == 2
    out = tmp_path / "mods"
    out.mkdir()
    from tools.placement_studio import save_mod
    from PySide6.QtCore import QThread
    save = save_mod.save_mod

    def checked_save(edits, *args, **kwargs):
        assert QThread.currentThread() is not QApplication.instance().thread()
        assert edits is not window._edits
        return save(edits, *args, **kwargs)

    monkeypatch.setattr(save_mod, "save_mod", checked_save)
    result = client("save_mod", folder=str(out), name="New timing", include=[timing_key])
    assert result["saved"], result
    root = out / "New timing - DMM"
    assert (root / CHART).read_bytes() == window._edits.chart_bytes(CHART)
    assert (root / "manifest.json").is_file()
    assert not (root / excluded_path).exists()
    included = {entry["key"] for entry in client("state")["pending"] if entry["included"]}
    assert included == {timing_key}
    assert str(root) in window._save_result.text()
    assert result["history_after"] == result["history_before"]
    with pytest.raises(ToolError, match="already exists"):
        client("save_mod", folder=str(out), name="New timing", accept_warnings=True)
    game = tmp_path / "game"
    game.mkdir()
    with pytest.raises(ToolError, match="game folder"):
        client("save_mod", folder=str(game), name="New timing")
    assert not list(game.iterdir())


def test_discard_only_after_the_window_confirmation(client, window):
    client("animation", action="retime_event", chart=CHART, animation=0, event=0, seconds=0.4)
    key = window._mod_changes()[0].key
    no = client("discard", action="change", key=key)
    assert no["asked"][0]["answer"] == "no" and window._mod_changes()
    yes = client("discard", action="change", key=key, confirm="yes")
    assert yes["asked"][0]["answer"] == "yes" and not window._mod_changes()


def test_mirrored_carry_reports_and_undoes_the_entire_move(client, window):
    window._session.hierarchy = _hierarchy()
    window._session._reposition()
    window._populate_carry_box()
    part = window._current_binding().part
    initial = window._edits.preview()
    review = client("socket", action="review_move", name=part.in_socket, part=part.part_name)
    assert review["review"] and review["history_before"] == review["history_after"]
    result = client("socket", action="carry", name=part.in_socket, part=part.part_name, mirror=True)
    assert result["asked"][-1]["kind"] == "information"
    assert window._edits.operations()[0].created_sockets()
    client("undo", area="placement")
    assert window._edits.preview() == initial and not window._mod_changes()


def test_measured_draw_and_put_away_are_one_undo(client, window):
    from tests.test_placement_studio_carry_timing import _measured
    window._part_box.setCurrentIndex(window._part_box.findData(TWO_HAND))
    rows = _measured(window)
    result = client("animation", action="apply_timing")
    assert result["history_after"]["placement"]["position"] == len(rows)
    assert len(window._edits.latest_operation().retimed_events()) == len(rows)
    client("undo")
    assert window._edits.chart_bytes(CHART) == chart_bytes()


def test_prepare_uses_the_tab_worker_before_installing_the_window(client, window, monkeypatch):
    import threading
    from tools.placement_studio import tab as owner
    from PySide6.QtCore import QThread
    # Release the owned data only after the tool has replied.
    gate = threading.Event()
    original = window._baseline
    def prepare(*args, **kwargs):
        assert QThread.currentThread() is not QApplication.instance().thread()
        assert gate.wait(4)
        return original
    monkeypatch.setattr(owner, "_prepare_startup", prepare)
    tab = client.tab
    tab._studio = None
    monkeypatch.setattr(tab, "_install", lambda baseline: setattr(tab, "_studio", window)
                        if baseline is original else None)
    try:
        started = client("open", action="prepare")
        assert not started["ready"] and not tab._action.isEnabled()
        assert client("state")["ready"] is False
        gate.set()
        _wait(lambda: tab._studio is window)
        assert client("state")["ready"]
    finally:
        gate.set()


def test_export_writes_glb_paa_and_edited_files_without_a_mod(client, window, tmp_path):
    out = tmp_path / "exports"
    out.mkdir()
    client("animation", action="start")
    glb = client("export", kind="blender_glb", save_file=str(out / "clip.glb"))
    assert (out / "clip.glb").read_bytes()[:4] == b"glTF", glb
    paa = client("export", kind="animation", save_file=str(out / "clip.paa"))
    assert paa["saved"] == str(out / "clip.paa") and (out / "clip.paa").stat().st_size > 0
    with pytest.raises(ToolError, match=r"\.paa"):
        client("export", kind="animation", save_file=str(out / "clip.glb"))
    client("animation", action="retime_event", chart=CHART, animation=0, event=0, seconds=0.45)
    files = out / "files"
    files.mkdir()
    client("export", kind="edited_files", folder=str(files))
    assert (files / CHART).read_bytes() == window._edits.chart_bytes(CHART)


def test_view_sets_the_show_menu_and_resets_the_view(client, window):
    shown = client("view")["show"]
    assert shown["bones"] is True and shown["unused_sockets"] is False
    after = client("view", bones=False, solid_body=True, reset=True)["show"]
    assert after["bones"] is False and after["solid_body"] is True
    assert not window._show_bones.isChecked() and window._solid_body.isChecked()
