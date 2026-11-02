"""The Add Bones dialog, its service helpers and the .pab context menu."""

from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import json
import math

import pytest
from PySide6.QtCore import QEvent, QPoint, QPointF, Qt
from PySide6.QtGui import QMouseEvent
from PySide6.QtWidgets import QApplication, QMenu

from cdmw.modding.skeleton_writer import (
    PabEditRefused,
    _compose_local,
    append_child_bone,
    read_pab_document,
)
from cdmw.services.pab_skeleton_edit_service import (
    PAB_CHAIN_DIRECTIONS,
    PabAppendEdit,
    dumps_pab_edit_json,
    euler_degrees_to_quaternion,
    plan_bone_chain,
    preview_pab_edits,
    quaternion_to_euler_degrees,
    read_pab_edit_json,
)
from tests.test_pab_skeleton_writer import pab

PATH = "character/model/test/owned.pab"
_APPLICATION: QApplication | None = None


def application() -> QApplication:
    global _APPLICATION
    _APPLICATION = QApplication.instance() or QApplication([])
    return _APPLICATION


def close(left, right, tolerance=1e-5):
    return all(abs(a - b) <= tolerance for a, b in zip(left, right, strict=True))


def world(document, name):
    return next(bone for bone in document.bones if bone.name == name).bind_matrix[12:15]


@pytest.mark.parametrize("angles", [(0, 0, 0), (30, -45, 120), (-170, 80, 5), (90, 0, 0)])
def test_rotation_angles_round_trip_and_turn_the_expected_way(angles):
    quaternion = euler_degrees_to_quaternion(*angles)
    assert math.isclose(sum(value * value for value in quaternion), 1.0, abs_tol=1e-12)
    assert close(quaternion_to_euler_degrees(quaternion), angles, 1e-6)
    # 90 degrees about Z turns the bone's X axis onto +Y; about X turns Y onto +Z.
    assert close(_compose_local((1, 1, 1), euler_degrees_to_quaternion(0, 0, 90), (0, 0, 0))[:3], (0, 1, 0))
    assert close(_compose_local((1, 1, 1), euler_degrees_to_quaternion(90, 0, 0), (0, 0, 0))[4:7], (0, 0, 1))


@pytest.mark.parametrize("direction", sorted(PAB_CHAIN_DIRECTIONS))
def test_a_chain_hangs_from_its_parent_in_character_space(direction):
    data = pab()
    source = read_pab_document(data)  # the fixture root is turned 90 degrees, so local and character axes differ
    edits = plan_bone_chain(source, "Bip01 Spine", "Cape", 4, 0.25, PAB_CHAIN_DIRECTIONS[direction])
    assert [(edit.parent, edit.name) for edit in edits] == [
        ("Bip01 Spine", "Cape_00"), ("Cape_00", "Cape_01"), ("Cape_01", "Cape_02"), ("Cape_02", "Cape_03")]
    document = preview_pab_edits(data, edits)
    start = world(source, "Bip01 Spine")
    for index in range(4):
        expected = tuple(s + 0.25 * index * d for s, d in zip(start, PAB_CHAIN_DIRECTIONS[direction]))
        assert close(world(document, f"Cape_{index:02d}"), expected)


@pytest.mark.parametrize("fault", ["count", "length", "direction", "taken", "parent"])
def test_chain_planning_refuses_with_a_reason(fault):
    source = read_pab_document(pab())
    arguments = {"parent": "Bip01 Spine", "prefix": "Cape", "count": 3, "segment_length": 0.1,
                 "direction": (0.0, -1.0, 0.0)}
    if fault == "count":
        arguments["count"] = 0
    elif fault == "length":
        arguments["segment_length"] = 0.0
    elif fault == "direction":
        arguments["direction"] = (0.0, 0.0, 0.0)
    elif fault == "taken":
        source = append_child_bone(source, "Bip01", "Cape_01")
    elif fault == "parent":
        arguments["parent"] = "Tail"
    with pytest.raises(PabEditRefused):
        plan_bone_chain(source, **arguments)


def test_preview_names_the_first_bad_bone_and_drafts_round_trip():
    data = pab()
    edits = (PabAppendEdit("Bip01 Head", "Hair_00", position=(0.1, 0.0, 0.0),
                           rotation=euler_degrees_to_quaternion(0, 0, 30)),
             PabAppendEdit("Hair_00", "Hair_01", position=(0.1, 0.0, 0.0)))
    with pytest.raises(PabEditRefused, match=r"Added bone 2 \(Bip01 Spine\)"):
        preview_pab_edits(data, (edits[0], PabAppendEdit("Hair_00", "Bip01 Spine")))
    draft = dumps_pab_edit_json(data, PATH, edits)
    assert [row["name"] for row in json.loads(draft)["add_bones"]] == ["Hair_00", "Hair_01"]
    recipe = read_pab_edit_json(data, draft, virtual_path=PATH)
    assert recipe.add_bones == edits and recipe.path == PATH


def test_dialog_adds_offsets_chains_renames_and_removes_bones(tmp_path):
    from cdmw.ui.archive_browser.pab_bone_editor_dialog import PabBoneEditorDialog

    application()
    data = pab()
    dialog = PabBoneEditorDialog(data, PATH, draft_directory=tmp_path)
    try:
        assert not dialog.save_mod_button.isEnabled() and not dialog.remove_button.isEnabled()
        dialog._select_bone("Bip01 Head")
        dialog._add_child()
        assert dialog._selected == "NewBone_00" and dialog.remove_button.isEnabled()
        # Offsets are typed along character axes even though the head is turned 90 degrees.
        for box, value in zip(dialog.position_boxes, (0.0, 0.5, 0.0)):
            box.setValue(value)
        head = world(dialog._preview, "Bip01 Head")
        assert close(world(dialog._preview, "NewBone_00"), (head[0], head[1] + 0.5, head[2]))
        dialog.name_edit.setText("Hair_Root")
        dialog._rename_selected()
        assert dialog.add_chain("Hair", 3, 0.2, "down")
        assert [row.parent for row in dialog._rows] == ["Bip01 Head", "Hair_Root", "Hair_00", "Hair_01"]
        assert dialog.save_mod_button.isEnabled()
        assert "game bones + 4 added" in dialog.status_label.text()

        dialog._select_bone("Hair_00")
        before = dialog.edits()
        dialog.name_edit.setText("Bip01 Spine")  # a name the game already uses
        dialog._rename_selected()
        # Refused before anything moves: the bone keeps its name and its children.
        assert dialog.edits() == before and dialog.name_edit.text() == "Hair_00"
        assert "already exists" in dialog.status_label.text() and dialog.save_mod_button.isEnabled()
        dialog.name_edit.setText("Hair_A")
        dialog._rename_selected()
        assert not dialog._error and dialog._rows[2].parent == "Hair_A"

        draft = dumps_pab_edit_json(data, PATH, dialog.edits())
        dialog._select_bone("Hair_A")
        dialog._remove_selected()  # takes Hair_01 and Hair_02 with it
        assert [row.name for row in dialog._rows] == ["Hair_Root"] and dialog._selected == "Hair_Root"
        assert dialog.load_draft_text(draft)
        assert [edit.name for edit in dialog.edits()] == ["Hair_Root", "Hair_A", "Hair_01", "Hair_02"]
        assert close(preview_pab_edits(data, dialog.edits()).bones[-1].bind_matrix,
                     preview_pab_edits(data, read_pab_edit_json(data, draft).add_bones).bones[-1].bind_matrix)
    finally:
        dialog.close()


def test_dialog_keeps_game_bones_read_only_and_the_sketch_picks_bones(monkeypatch):
    from cdmw.ui.archive_browser import pab_bone_editor_dialog as module

    application()
    dialog = module.PabBoneEditorDialog(pab(), PATH)
    try:
        dialog._select_bone("Bip01 Spine")
        # A game bone gets an explanation and "add here" actions, not greyed-out fields.
        assert dialog.detail_pages.currentWidget() is dialog.game_page
        assert dialog.details_group.title() == "Game bone" and not dialog.remove_button.isEnabled()
        summary = dialog.game_summary.text()
        assert "Bip01 Spine" in summary and "Attached to: Bip01" in summary and "10.000, 22.000, 0.000 m" in summary
        assert "bone offset table" in dialog.game_reason.text()
        assert dialog.add_chain_here_button.isEnabled() and dialog.game_marker_warning.isHidden()
        warnings = []
        monkeypatch.setattr(module.QMessageBox, "warning", lambda *args: warnings.append(args))
        assert dialog.add_chain("Tail", 2, 0.1, "back")
        assert not dialog.add_chain("Tail", 1, 0.1, "back") and "Tail_00" in warnings[0][2]
        dialog.resize(900, 600)
        dialog.show()
        application().processEvents()
        picked = []
        dialog.sketch.boneClicked.connect(picked.append)
        _name, point = dialog.sketch._joints[2]
        event = QMouseEvent(QEvent.MouseButtonPress, QPointF(point), QPointF(point), Qt.LeftButton,
                            Qt.LeftButton, Qt.NoModifier)
        dialog.sketch.mousePressEvent(event)
        assert picked and picked[0] in {bone.name for bone in read_pab_document(pab()).bones}
    finally:
        dialog.close()


def test_pab_context_menu_offers_add_bones_and_the_json_actions(tmp_path, monkeypatch):
    from cdmw.models import ArchiveEntry
    from cdmw.ui.archive_browser import actions
    from tests.test_archive_mesh_export_modes import _ExportWindow
    from tools.format_explorer.catalogue import TOOLS

    application()
    entry = ArchiveEntry(path="character/model/1_pc/1_phm/phm_01.pab", pamt_path=tmp_path / "0.pamt",
                         paz_file=tmp_path / "0.paz", offset=0, comp_size=64, orig_size=64, flags=0, paz_index=0)
    window = _ExportWindow(entry, tmp_path)
    calls = []
    window._open_current_archive_pab_bone_editor = lambda: calls.append("add")
    window._export_current_archive_pab_edit_json = lambda: calls.append("export")
    window._import_current_archive_pab_edit_json = lambda: calls.append("import")
    location, label = TOOLS[".pab"].split(" > ")
    assert location == "Browse Archives"

    class PabMenu(QMenu):
        def exec(self, _position):
            choices = {action.text(): action for action in self.actions()}
            assert "capes" in choices[label].toolTip()
            for text in (label, "Export Skeleton Edit JSON...", "Import Skeleton Edit JSON..."):
                choices[text].trigger()

    monkeypatch.setattr(actions, "QMenu", PabMenu)
    try:
        window._show_archive_tree_context_menu(QPoint())
    finally:
        window.close()
    assert calls == ["add", "export", "import"]


def test_add_bones_action_opens_the_dialog_and_writes_its_bones(tmp_path, monkeypatch):
    from types import SimpleNamespace

    from cdmw.domain.archives.mesh_contracts import ArchiveLooseExportResult
    from cdmw.modding.skeleton_parser import parse_pab
    from cdmw.ui.archive_browser import pab_bone_editor_dialog
    from cdmw.ui.archive_browser import pab_json_actions as actions

    data = pab()
    monkeypatch.setattr(actions, "read_archive_entry_data", lambda entry: (data, False, ""))
    exports = []
    monkeypatch.setattr(actions, "export_archive_payloads_to_mod_ready_loose",
                        lambda requests, **kwargs: exports.append(requests) or ArchiveLooseExportResult(
                            package_root=tmp_path / "mod", written_files=[]))
    monkeypatch.setattr(actions.QMessageBox, "information", lambda *args: None)

    class FakeDialog:
        Accepted = 1

        def __init__(self, source, path, parent, *, draft_directory):
            assert source == data and path == PATH and draft_directory == tmp_path / "skeleton_edit_json"

        def exec(self):
            return 1

        def edits(self):
            return (PabAppendEdit("Bip01 Head", "Tail_00", position=(0.0, 0.1, 0.0)),)

    monkeypatch.setattr(pab_bone_editor_dialog, "PabBoneEditorDialog", FakeDialog)
    tasks = []
    entry = SimpleNamespace(path=PATH, basename="owned.pab")
    shell = SimpleNamespace(set_status_message=lambda *args, **kwargs: None,
                            settings_file_path=tmp_path / "settings.json",
                            _run_utility_task=lambda **kwargs: tasks.append(kwargs))
    browser = SimpleNamespace(shell=shell, _current_archive_pab_entry=lambda: entry,
                              _collect_archive_mod_ready_export_target=lambda **kwargs: (tmp_path, object(), True, False, None))
    mixin = actions.ArchivePabJsonActionsMixin
    browser._default_archive_pab_edit_json_path = lambda entry: mixin._default_archive_pab_edit_json_path(browser, entry)
    browser._show_pab_bone_editor = lambda *args: mixin._show_pab_bone_editor(browser, *args)
    browser._write_pab_edit_loose_mod = lambda *args: mixin._write_pab_edit_loose_mod(browser, *args)
    mixin._open_current_archive_pab_bone_editor(browser)
    while tasks:
        task = tasks.pop(0)
        task["on_complete"](task["task"](lambda _message: None))
    (request,) = exports[0]
    assert parse_pab(request.payload_data).bones[-1].name == "Tail_00"


def test_dialog_reopens_given_bones_and_takes_a_caller_label():
    from cdmw.ui.archive_browser.pab_bone_editor_dialog import PabBoneEditorDialog

    application()
    edits = plan_bone_chain(read_pab_document(pab()), "Bip01 Spine", "Tail", 3, 0.1, PAB_CHAIN_DIRECTIONS["back"])
    dialog = PabBoneEditorDialog(pab(), PATH, initial_edits=edits, accept_text="Use These Bones",
                                 accept_tooltip="Bind the model to this rig.")
    try:
        assert dialog.save_mod_button.text() == "Use These Bones" and dialog.save_mod_button.isEnabled()
        assert dialog._selected == "Tail_02"
        assert all(close(a.position, b.position) and close(a.rotation, b.rotation)
                   for a, b in zip(dialog.edits(), edits, strict=True))
    finally:
        dialog.close()


def test_markers_are_grouped_and_warned_and_quick_picks_select_body_bones():
    from cdmw.ui.archive_browser.pab_bone_editor_dialog import (
        PabBoneEditorDialog,
        body_bone_names,
    )
    from tests.test_pab_skeleton_writer import BONES, IDENTITY

    application()
    marker = ("B_TL_Position_01", -1, IDENTITY, IDENTITY, IDENTITY, IDENTITY, (0., 0., 0., 1.), (0., 0., 0.))
    data = pab(bones=BONES + (marker,), secondary=(-1, 0, 1, -1), core=(1, 1, 0, 1))
    assert body_bone_names(read_pab_document(data)) == {"Bip01", "Bip01 Spine", "Bip01 Head"}
    dialog = PabBoneEditorDialog(data, PATH)
    try:
        group = dialog._tree_items["B_TL_Position_01"].parent()
        assert group is not None and group.data(0, 0x0100) is None and "Markers" in group.text(0)
        assert dialog._tree_items["B_TL_Position_01"].text(1) == "Marker"
        assert set(dialog.quick_pick_buttons) == {"upper_back", "head"}
        dialog.quick_pick_buttons["head"].click()
        assert dialog._selected == "Bip01 Head"
        dialog._select_bone("B_TL_Position_01")
        assert not dialog.game_marker_warning.isHidden()
        assert "does not move with the body" in dialog.game_marker_warning.text()
        dialog._add_child()
        assert dialog.detail_pages.currentWidget() is dialog.added_page
        assert not dialog.added_marker_warning.isHidden() and dialog.details_group.title() == "New bone"
        assert [label.font().bold() for label in dialog.step_labels] == [False, False, True]
        group = dialog._tree_items["B_TL_Position_01"].parent()  # rebuilt with the new bone
        dialog.bone_tree.setCurrentItem(group)  # the group is not a bone
        assert dialog._selected == "NewBone_00"
    finally:
        dialog.close()
