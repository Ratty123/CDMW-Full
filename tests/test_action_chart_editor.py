"""Action Chart Editor: edit a `.paac` chart, read it back, and export a DMM mod.

Charts are the owned fixtures built in `tests/test_action_chart_binary.py` from the
loader layout; no game file is read. Nothing here says anything about the game.
"""

from __future__ import annotations

import json
import os
import struct
import time
from pathlib import Path
from types import SimpleNamespace

import pytest

from cdmw.core.action_chart_binary import ActionChartError, ChartValueEdit, decode_action_chart
from cdmw.models import ArchiveEntry
from cdmw.services.action_chart_edit_service import (
    ActionChartEditRequest,
    AnimationResourceEdit,
    EventFieldEdit,
    StringRetarget,
    animation_event_rows,
    animation_value_rows,
    apply_action_chart_edits,
    build_resource_catalog,
    character_chart_rows,
    compare_charts,
    load_editable_chart,
    string_rows,
    unknown_resources,
    write_action_chart_mod,
)
from tests.test_action_chart_binary import CLIPS, chart_bytes, descriptor_bytes

PATH = "actionchart/bin__/upperaction/1_pc/1_phm/sword_upper.paac"
NEW_CLIP = "1_pc/1_phm/cd_phm_sword_attack_heavy_longer_name_01.paa"
BLEND = "character/binary/motionblending/phm_locomotion/sword_move.motionblending"
REPO = Path(__file__).resolve().parents[1]


def _f32(value: float) -> float:
    return struct.unpack("<f", struct.pack("<f", value))[0]


def _clip_retarget(old: str, new: str) -> StringRetarget:
    return StringRetarget(1, old, new)


@pytest.fixture
def stored(tmp_path, monkeypatch):
    monkeypatch.setenv("CDMW_TEMP_CACHE_ROOT", str(tmp_path / "cache"))

    def make(path: str, payload: bytes) -> ArchiveEntry:
        folder = tmp_path / "game" / "0008"
        folder.mkdir(parents=True, exist_ok=True)
        paz = folder / f"{len(list(folder.glob('*.paz')))}.paz"
        paz.write_bytes(payload)
        return ArchiveEntry(path, folder / "0.pamt", paz, 0, len(payload), len(payload), 0, 0)

    return make


@pytest.fixture
def accelerator(monkeypatch):
    """The archive-group writer needs the native accelerator; a worktree borrows the main checkout's."""

    from cdmw.core.archive_accelerator import ARCHIVE_ACCELERATOR_BINARY_NAME, find_native_archive_accelerator

    if find_native_archive_accelerator() is None:
        for root in (REPO, *REPO.parents):
            candidate = root / "native" / "cdmw_archive_accelerator" / "build" / "Release" / ARCHIVE_ACCELERATOR_BINARY_NAME
            if candidate.is_file():
                monkeypatch.setenv("CDMW_ARCHIVE_ACCELERATOR_BIN", str(candidate))
                break
        else:
            pytest.skip("needs the native archive accelerator")


# --- service ------------------------------------------------------------------------


def test_retarget_and_timing_edits_are_read_back_from_the_new_bytes():
    data = chart_bytes()
    request = ActionChartEditRequest(
        retargets=(_clip_retarget(CLIPS[0], NEW_CLIP),),
        values=(
            ChartValueEdit("chart.action_speed_rate", 1.25),
            ChartValueEdit("animation.end_time", 1.75, animation=0),
            ChartValueEdit("speed.rate", 1.5, animation=0, item=0),
            ChartValueEdit("event.begin", 0.35, animation=0, item=1),
        ),
    )

    result = apply_action_chart_edits(data, request, virtual_path=PATH)

    chart = decode_action_chart(result.data, virtual_path=PATH)
    assert chart.clip_name(chart.animations[0]) == NEW_CLIP and chart.clip_name(chart.animations[1]) == CLIPS[1]
    assert chart.action_speed_rate == 1.25 and chart.animations[0].end_time == 1.75
    assert [(c.table, c.old, c.new) for c in result.changes.strings] == [(1, CLIPS[0], NEW_CLIP)]
    changed = {(c.row.field, c.row.item): (c.old, c.row.value) for c in result.changes.values}
    assert changed == {
        ("chart.action_speed_rate", 0): (1.0, 1.25),
        ("animation.end_time", 0): (1.5, 1.75),
        ("speed.rate", 0): (1.0, 1.5),
        ("event.begin", 1): (_f32(0.3), _f32(0.35)),
    }


def test_one_animation_gets_its_own_clip_and_blend_space():
    data = chart_bytes()
    request = ActionChartEditRequest(resources=(AnimationResourceEdit(1, clip=CLIPS[0], blend=BLEND),
                                                AnimationResourceEdit(0, blend="")))
    result = apply_action_chart_edits(data, request, virtual_path=PATH)

    chart = result.chart
    assert [chart.clip_name(a) for a in chart.animations] == [CLIPS[0], CLIPS[0]]
    assert [chart.blend_name(a) for a in chart.animations] == ["", BLEND]
    assert {(c.animation, c.field, c.old, c.new) for c in result.changes.resources} == {
        (1, "clip", CLIPS[1], CLIPS[0]), (1, "blend", "", BLEND), (0, "blend", BLEND, "")}
    assert not result.changes.strings and not result.changes.appended

    added = apply_action_chart_edits(data, ActionChartEditRequest(
        resources=(AnimationResourceEdit(0, clip=NEW_CLIP),)), virtual_path=PATH)
    assert added.changes.appended == ((1, NEW_CLIP),)
    assert added.chart.clip_name(added.chart.animations[1]) == CLIPS[1], "the other animation keeps its clip"


def test_a_shared_socket_event_is_copied_or_changed_for_every_user():
    data = chart_bytes()
    chart = load_editable_chart(data, PATH)
    socket = animation_event_rows(chart, data, 0)[0]
    assert socket.kind_name == "ModelAttachmentSocket" and socket.shared_by == (0, 1)
    assert socket.field_value("parent socket") == "RHand_Socket" and socket.field_value("mode") == 2

    edits = (EventFieldEdit(0, 0, "parent socket", "Bip01 R Hand"), EventFieldEdit(0, 0, "mode", 1),
             EventFieldEdit(0, 0, "blend time", 0.25))
    only = apply_action_chart_edits(data, ActionChartEditRequest(events=edits), virtual_path=PATH)
    first = animation_event_rows(only.chart, only.data, 0)[0]
    other = animation_event_rows(only.chart, only.data, 1)[0]
    assert (first.field_value("parent socket"), first.field_value("mode"), first.field_value("blend time")) == ("Bip01 R Hand", 1, 0.25)
    assert (other.field_value("parent socket"), other.field_value("mode")) == ("RHand_Socket", 2)
    assert {(c.animation, c.field) for c in only.changes.events} == {
        (0, "parent socket"), (0, "mode"), (0, "blend time")}

    every = apply_action_chart_edits(data, ActionChartEditRequest(events=tuple(
        EventFieldEdit(e.animation, e.event, e.field, e.value, only_this_animation=False) for e in edits)),
        virtual_path=PATH)
    assert animation_event_rows(every.chart, every.data, 1)[0].field_value("mode") == 1
    assert {c.animation for c in every.changes.events} == {0, 1}


def test_a_name_replaced_in_its_table_is_listed_once():
    data = chart_bytes()
    result = apply_action_chart_edits(data, ActionChartEditRequest(
        retargets=(StringRetarget(6, "RHand_Socket", "LHand_Socket"),),
        events=(EventFieldEdit(0, 0, "mode", 0),)), virtual_path=PATH)
    assert [(c.table, c.new) for c in result.changes.strings] == [(6, "LHand_Socket")]
    assert [c.field for c in result.changes.events] == ["mode"], "the copied event's socket rename is the table's"
    assert animation_event_rows(result.chart, result.data, 1)[0].field_value("parent socket") == "LHand_Socket"


def test_edits_on_an_edited_copy_are_listed_against_the_shipped_chart():
    shipped = chart_bytes()
    first = apply_action_chart_edits(shipped, ActionChartEditRequest((_clip_retarget(CLIPS[0], NEW_CLIP),)),
                                     virtual_path=PATH)
    second = apply_action_chart_edits(
        first.data,
        ActionChartEditRequest(values=(ChartValueEdit("frame_tag.end_time", 0.45, animation=0),)),
        virtual_path=PATH,
        original=shipped,
    )
    assert [change.new for change in second.changes.strings] == [NEW_CLIP]
    assert [change.row.field for change in second.changes.values] == ["frame_tag.end_time"]
    back = apply_action_chart_edits(second.data, ActionChartEditRequest(
        (_clip_retarget(NEW_CLIP, CLIPS[0]),), values=(ChartValueEdit("frame_tag.end_time", _f32(0.4), animation=0),)),
        virtual_path=PATH, original=shipped)
    assert back.changes.empty and back.data == shipped


@pytest.mark.parametrize(
    "request_, message",
    [
        (ActionChartEditRequest(values=(ChartValueEdit("animation.start_time", 2.0, animation=0),)), "end before it starts"),
        (ActionChartEditRequest(values=(ChartValueEdit("chart.action_speed_rate", 0.0),)), "above 0"),
        (ActionChartEditRequest(values=(ChartValueEdit("speed.rate", 1.0, animation=1),)), "no animationSpeedInfoArray"),
        (ActionChartEditRequest((_clip_retarget("1_pc/not_in_chart.paa", NEW_CLIP),)), "has no entry"),
        (ActionChartEditRequest((_clip_retarget(CLIPS[0], "badéname.paa"),)), "printable ASCII"),
        (ActionChartEditRequest(resources=(AnimationResourceEdit(0, clip=""),)), "needs a clip"),
        (ActionChartEditRequest(events=(EventFieldEdit(0, 0, "mode", 5),)), "socket mode"),
        (ActionChartEditRequest(events=(EventFieldEdit(0, 0, "blend time", 99.0),)), "blend time"),
        (ActionChartEditRequest(events=(EventFieldEdit(0, 1, "mode", 1),)), "no editable field"),
    ],
)
def test_edits_outside_the_proven_scope_are_refused(request_, message):
    with pytest.raises(ActionChartError, match=message):
        apply_action_chart_edits(chart_bytes(), request_, virtual_path=PATH)


def test_shared_action_tables_are_not_editable():
    with pytest.raises(ActionChartError, match="shared action table"):
        load_editable_chart(chart_bytes(), "actionchart/bin__/actionchart/xml/description/commonactioninfo.paac")


def test_rows_say_who_uses_each_name():
    data = chart_bytes()
    chart = load_editable_chart(data, PATH)
    assert [(row.value, row.uses) for row in string_rows(chart, data, 1)] == [(CLIPS[0], 1), (CLIPS[1], 1)]
    assert [(row.value, row.uses) for row in string_rows(chart, data, 6)] == [("Bip01 R Hand", 2), ("RHand_Socket", 1)]
    assert [row.uses for row in string_rows(chart, data, 2)] == []
    assert string_rows(chart, data, 4) == ()
    rows = animation_value_rows(chart, data, 0)
    assert [row.field for row in rows].count("event.begin") == 2
    assert [row.field for row in animation_value_rows(chart, data, 1)][2:] == ["event.begin", "event.end"]


def test_catalog_finds_how_each_table_names_files():
    data = chart_bytes()
    chart = load_editable_chart(data, PATH)
    paths = {
        ".paa": ["character/motion/" + clip for clip in CLIPS] + ["Character\\Motion\\1_pc/Other.paa",
                                                                   "object/animation/door.paa"],
        ".motionblending": [BLEND, "character/binary/motionblending/phm_locomotion/run.motionblending"],
    }
    catalogs = build_resource_catalog(chart, paths)
    assert catalogs[1].form == ("character/motion/", "") and set(catalogs[1].suggestions) == {*CLIPS, "1_pc/Other.paa"}
    assert catalogs[5].form == ("", "") and len(catalogs[5].suggestions) == 2
    assert catalogs[6].form == "names" and catalogs[6].suggestions == ("Bip01 R Hand", "RHand_Socket")
    request = ActionChartEditRequest(
        retargets=(StringRetarget(1, CLIPS[0], "1_PC/other.paa"),),
        resources=(AnimationResourceEdit(1, clip=NEW_CLIP, blend="character/binary/motionblending/missing.motionblending"),),
        events=(EventFieldEdit(0, 0, "parent socket", "Bip01 Head"), EventFieldEdit(0, 0, "child socket", "")),
    )
    assert unknown_resources(request, catalogs) == (
        (1, NEW_CLIP), (5, "character/binary/motionblending/missing.motionblending"), (6, "Bip01 Head"))


def test_character_packages_name_their_slot_charts():
    rows = character_chart_rows(descriptor_bytes())
    assert [(row.package, row.slot, row.main, row.archive_path) for row in rows] == [
        ("Player_Kliff", "DefaultUpperMain", True, "actionchart/bin__/upperaction/1_pc/1_phm/basic_upper.paac"),
        ("Player_Kliff", "Sword", False, PATH),
    ]


def test_export_writes_a_dmm_archive_group_mod(stored, tmp_path, accelerator):
    from cdmw.core.archive_extraction import read_archive_entry_data
    from cdmw.core.archive_format import parse_archive_pamt

    data = chart_bytes()
    entry = stored(PATH, data)
    edited = apply_action_chart_edits(data, ActionChartEditRequest((_clip_retarget(CLIPS[0], NEW_CLIP),)),
                                      virtual_path=PATH).data
    logs: list[str] = []

    result = write_action_chart_mod(entry, data, edited, parent=tmp_path / "mods", title="Sword chart edit",
                                    author="me", description="Heavier attack", on_log=logs.append)

    assert result.folder == tmp_path / "mods" / "Sword chart edit" and not result.replaced and result.group == "0036"
    packaged = parse_archive_pamt(result.folder / "0036" / "0.pamt")
    assert [item.path for item in packaged] == [PATH] and read_archive_entry_data(packaged[0])[0] == edited
    manifest = json.loads((result.folder / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["structure"] == "archive_group" and manifest["archive_group"] == "0036"
    assert manifest["manager_targets"] == ["dmm"] and manifest["overrides"] == [PATH]
    assert manifest["author"] == "me" and manifest["description"] == "Heavier attack"
    assert json.loads((result.folder / "modinfo.json").read_text(encoding="utf-8"))["name"] == "Sword chart edit"
    assert any("1 change(s)" in line for line in logs)

    again = write_action_chart_mod(entry, data, edited, parent=tmp_path / "mods", title="Sword chart edit")
    assert again.replaced and [p.name for p in (tmp_path / "mods").iterdir()] == ["Sword chart edit"]


def test_export_refuses_unchanged_charts_and_foreign_folders(stored, tmp_path):
    data = chart_bytes()
    entry = stored(PATH, data)
    edited = apply_action_chart_edits(data, ActionChartEditRequest((_clip_retarget(CLIPS[0], NEW_CLIP),)),
                                      virtual_path=PATH).data
    with pytest.raises(ActionChartError, match="no changes"):
        write_action_chart_mod(entry, data, data, parent=tmp_path, title="x")
    with pytest.raises(ActionChartError, match="Name the mod"):
        write_action_chart_mod(entry, data, edited, parent=tmp_path, title="  ")
    foreign = tmp_path / "mods" / "Taken"
    foreign.mkdir(parents=True)
    (foreign / "keep.txt").write_text("someone else's mod", encoding="utf-8")
    with pytest.raises(ActionChartError, match="CDMW did not write it"):
        write_action_chart_mod(entry, data, edited, parent=tmp_path / "mods", title="Taken")
    assert [p.name for p in foreign.iterdir()] == ["keep.txt"]
    prefab = stored("character/sword.prefab", data)
    with pytest.raises(ActionChartError, match="not an editable action chart"):
        write_action_chart_mod(prefab, data, edited, parent=tmp_path, title="x")
    assert compare_charts(data, edited, virtual_path=PATH).strings[0].new == NEW_CLIP


# --- dialogs ------------------------------------------------------------------------


@pytest.fixture(scope="module")
def qt_app():
    pytest.importorskip("PySide6.QtWidgets")
    from PySide6.QtWidgets import QApplication

    return QApplication.instance() or QApplication([])


def _wait_idle(dialog, timeout: float = 10.0) -> None:
    from PySide6.QtWidgets import QApplication

    deadline = time.monotonic() + timeout
    while dialog.busy() and time.monotonic() < deadline:
        QApplication.processEvents()
        time.sleep(0.005)
    QApplication.processEvents()
    assert not dialog.busy(), "the apply task did not finish"


def _value_row(dialog, field: str, item: int = 0) -> int:
    from cdmw.ui.archive_browser.action_chart_editor_dialog import _KEY_ROLE

    for row in range(dialog.value_table.rowCount()):
        key = tuple(dialog.value_table.item(row, 0).data(_KEY_ROLE))
        if key[0] == field and key[2] == item:
            return row
    raise AssertionError(field)


def _editor(data=None, **kwargs):
    from cdmw.ui.archive_browser.action_chart_editor_dialog import ActionChartEditorDialog

    return ActionChartEditorDialog(chart_bytes() if data is None else data, virtual_path=PATH, **kwargs)


def test_dialog_applies_every_kind_of_edit_and_shows_the_reread_chart(qt_app, monkeypatch):
    from PySide6.QtWidgets import QMessageBox

    asked: list[str] = []
    monkeypatch.setattr(QMessageBox, "question", lambda *args, **kwargs: asked.append(args[2]) or QMessageBox.StandardButton.Yes)
    data = chart_bytes()
    dialog = _editor(data, used_by=("Player_Kliff (Sword)",))
    assert "Player_Kliff (Sword)" in dialog.header_label.text()
    assert dialog.animation_table.rowCount() == 2 and dialog.string_table.rowCount() == 2
    assert not dialog.apply_button.isEnabled() and not dialog.export_button.isEnabled()

    # Strings tab: rename a socket everywhere.
    dialog.table_combo.setCurrentIndex(6)
    dialog.string_table.selectRow(1)
    dialog.new_string_edit.setText("LHand_Socket")
    dialog.replace_button.click()
    # Animations tab: animation 1 plays the attack clip, animation 0 gets a slower speed window.
    dialog.animation_table.selectRow(1)
    dialog.clip_edit.setText(CLIPS[0])
    dialog.set_resources_button.click()
    dialog.animation_table.selectRow(0)
    dialog.value_table.item(_value_row(dialog, "speed.rate"), 2).setText("1.5")
    # The shared socket event, for animation 0 only.
    dialog.event_table.selectRow(0)
    dialog._event_widgets["mode"].setCurrentIndex(1)
    dialog.set_event_button.click()
    dialog.rate_spin.setValue(1.25)
    assert dialog.pending_list.count() == 5
    assert dialog.apply_button.isEnabled() and not dialog.export_button.isEnabled()

    dialog.apply_button.click()
    assert len(asked) == 1 and "LHand_Socket (Bones and sockets)" in asked[0]
    assert dialog.busy() and not dialog.close_button.isEnabled()
    _wait_idle(dialog)

    assert dialog.pending_list.count() == 0, dialog.status_label.text()
    clip_cell = dialog.animation_table.item(1, 1)
    assert clip_cell.text() == "cd_phm_sword_attack_00.paa" and clip_cell.toolTip() == CLIPS[0]
    dialog.animation_table.selectRow(0)
    assert dialog.value_table.item(_value_row(dialog, "speed.rate"), 1).text() == "1.5"
    assert dialog.event_table.item(0, 3).text() == "1", "the copied event is no longer shared"
    assert dialog.rate_spin.value() == 1.25
    changes = dialog.changes_view.toPlainText()
    assert "Replaced in Bones and sockets: RHand_Socket -> LHand_Socket" in changes
    assert f"Animation 1 clip: {CLIPS[1]} -> {CLIPS[0]}" in changes
    assert "Animation 0, frame event 1 (ModelAttachmentSocket), Socket mode: 2 -> 1" in changes
    assert "Chart speed rate: 1 -> 1.25" in changes and "Speed window 1 rate: 1 -> 1.5" in changes
    assert dialog.export_button.isEnabled()

    dialog.export_button.click()
    payload = dialog.result_payload
    assert payload is not None and payload.changes.count == 5
    chart = decode_action_chart(payload.data, virtual_path=PATH)
    assert chart.clip_name(chart.animations[1]) == CLIPS[0]


def test_cancelling_the_export_keeps_the_editor_and_its_edits(qt_app):
    asked: list = []
    dialog = _editor(export_details=lambda payload: asked.append(payload) or None)
    dialog.rate_spin.setValue(1.5)
    dialog.apply_button.click()
    _wait_idle(dialog)
    dialog.export_button.click()
    assert len(asked) == 1 and asked[0].changes.count == 1
    assert dialog.result_payload is None and dialog.result() == 0 and dialog.export_button.isEnabled()

    dialog._export_details = lambda payload: "plan"
    dialog.export_button.click()
    assert dialog.export_plan == "plan" and dialog.result_payload is not None


def test_dialog_reports_a_refused_edit_and_keeps_the_chart(qt_app, monkeypatch):
    from PySide6.QtWidgets import QMessageBox

    data = chart_bytes()
    dialog = _editor(data)
    dialog.animation_table.selectRow(0)
    dialog.value_table.item(_value_row(dialog, "animation.start_time"), 2).setText("9")
    dialog.value_table.item(_value_row(dialog, "frame_tag.end_time"), 2).setText("not a number")
    assert "is not a number" in dialog.status_label.text()
    dialog.apply_button.click()
    _wait_idle(dialog)

    assert "The edit was refused" in dialog.status_label.text() and "end before it starts" in dialog.status_label.text()
    assert dialog._data == data and not dialog.export_button.isEnabled()
    assert dialog.apply_button.isEnabled(), "the pending edit stays so it can be corrected"
    dialog.pending_list.setCurrentRow(0)
    dialog.remove_pending_button.click()
    assert dialog.pending_list.count() == 0 and not dialog.apply_button.isEnabled()

    asked: list[str] = []
    monkeypatch.setattr(QMessageBox, "question", lambda *args, **kwargs: asked.append(args[1]) or QMessageBox.StandardButton.No)
    dialog.rate_spin.setValue(2.0)
    dialog.reject()
    assert asked == ["Close Action Chart Editor"] and dialog.isVisible() is False and dialog.result() == 0


def test_dialog_warns_before_applying_names_nobody_has(qt_app, monkeypatch):
    from PySide6.QtWidgets import QMessageBox

    dialog = _editor()
    asked: list[str] = []
    monkeypatch.setattr(QMessageBox, "question", lambda *args, **kwargs: asked.append(args[2]) or QMessageBox.StandardButton.No)
    dialog.animation_table.selectRow(0)
    dialog.event_table.selectRow(0)
    dialog._event_widgets["parent socket"].setCurrentText("Bip01 Head")
    dialog.set_event_button.click()
    dialog.apply_button.click()
    assert asked and "Bip01 Head (Bones and sockets)" in asked[0] and not dialog.busy()


def test_finder_lists_slots_and_returns_the_chart_path(qt_app):
    from cdmw.ui.archive_browser.action_chart_finder_dialog import ActionChartFinderDialog

    rows = character_chart_rows(descriptor_bytes())
    dialog = ActionChartFinderDialog(rows, available={PATH})
    package = dialog.tree.topLevelItem(0)
    assert package.text(0) == "Player_Kliff" and package.childCount() == 2
    main, sword = package.child(0), package.child(1)
    assert main.isDisabled() and not sword.isDisabled()
    dialog.filter_edit.setText("sword")
    assert main.isHidden() and not sword.isHidden()
    dialog.tree.setCurrentItem(sword)
    dialog.edit_button.click()
    assert dialog.selected_path == PATH


def test_export_dialog_needs_a_mod_name(qt_app):
    from cdmw.ui.archive_browser.action_chart_export_dialog import SEND_TO_DMM, ActionChartExportDialog

    dialog = ActionChartExportDialog(title="", description="d")
    dialog.send_button.click()
    assert dialog.choice == "" and "Name the mod" in dialog.error_label.text()
    dialog.title_edit.setText("Mine")
    dialog.send_button.click()
    assert dialog.choice == SEND_TO_DMM and dialog.mod_title == "Mine" and dialog.mod_version == "1.0"


# --- archive index, clips and multi-chart mods --------------------------------------


BASIC = "actionchart/bin__/upperaction/1_pc/1_phm/basic_upper.paac"
DESCRIPTION = "actionchart/bin__/description/characteractionpackagedescription.paacdesc"


def _clip_bytes(duration: float) -> bytes:
    from tests.test_paa_motion_encode import _clip
    from tools.paa_motion.encode import encode_paa

    return encode_paa(_clip(duration=duration))


def _index(tmp_path, entries):
    from cdmw.services.action_chart_edit_service import chart_archive_index

    root = tmp_path / "game-root"
    root.mkdir(exist_ok=True)
    scans: list[int] = []

    def scan(_root):
        scans.append(1)
        return entries

    return chart_archive_index(root, scan=scan), scans, root


def test_the_index_is_built_once_and_finds_charts_clips_and_the_descriptor(stored, tmp_path):
    from cdmw.services.action_chart_edit_service import chart_archive_index, chart_users, character_rows_from_index, clip_info

    chart = stored(PATH, chart_bytes())
    clip = stored("character/motion/" + NEW_CLIP, _clip_bytes(1.75))
    description = stored(DESCRIPTION, descriptor_bytes())
    noise = SimpleNamespace(path="object/03_cube.hkx")
    index, scans, root = _index(tmp_path, [chart, clip, description, noise])
    assert chart_archive_index(root, scan=lambda _root: scans.append(1) or []) is index and scans == [1]
    assert index.entry_for_path(PATH.upper()) is chart and index.entry_for_path("object/03_cube.hkx") is None
    assert index.paths_by_extension[".paa"] == ("character/motion/" + NEW_CLIP,)
    read = lambda entry: entry.paz_file.read_bytes()  # noqa: E731
    rows = character_rows_from_index(index, read)
    assert chart_users(rows, PATH) == ("Player_Kliff (Sword)",)
    info = clip_info(index, NEW_CLIP, read)
    assert abs(info.duration - 1.75) < 1e-6 and info.frames >= 1
    with pytest.raises(ActionChartError, match="not in the game archives"):
        clip_info(index, "1_pc/missing.paa", read)
    with pytest.raises(ActionChartError, match="Set the game folder"):
        chart_archive_index("")


def test_one_mod_can_carry_several_charts_and_be_reopened(stored, tmp_path, accelerator):
    from cdmw.services.action_chart_edit_service import read_chart_mod

    data = chart_bytes()
    sword, basic = stored(PATH, data), stored(BASIC, data)
    index, _scans, _root = _index(tmp_path, [sword, basic])
    first = apply_action_chart_edits(data, ActionChartEditRequest((_clip_retarget(CLIPS[0], NEW_CLIP),)), virtual_path=PATH).data
    second = apply_action_chart_edits(data, ActionChartEditRequest(values=(ChartValueEdit("chart.action_speed_rate", 0.5),)),
                                      virtual_path=BASIC).data
    mods = tmp_path / "mods"

    write_action_chart_mod(sword, data, first, parent=mods, title="Moveset", shipped_entries=index.entry_for_path)
    both = write_action_chart_mod(basic, data, second, parent=mods, title="Moveset", shipped_entries=index.entry_for_path)

    assert both.replaced and set(both.charts) == {PATH, BASIC}
    mod = read_chart_mod(both.folder)
    assert mod.title == "Moveset" and dict(mod.charts) == {PATH: first, BASIC: second}
    manifest = json.loads((both.folder / "manifest.json").read_text(encoding="utf-8"))
    assert sorted(manifest["overrides"]) == sorted([PATH, BASIC])

    alone = write_action_chart_mod(basic, data, second, parent=mods, title="Moveset", keep_existing=False)
    assert alone.charts == (BASIC,)
    with pytest.raises(ActionChartError, match="not an action chart mod"):
        read_chart_mod(tmp_path)


# --- Archive Browser actions --------------------------------------------------------


def _shell(calls, statuses):
    return SimpleNamespace(
        set_status_message=lambda message, error=False: statuses.append(message),
        _run_utility_task_when_idle=lambda **kwargs: calls.append(kwargs),
        settings_file_path=Path("settings.ini"),
    )


def _browser(index, calls, statuses, **extra):
    return SimpleNamespace(
        shell=_shell(calls, statuses),
        archive_package_root_edit=SimpleNamespace(text=lambda: str(index.root)),
        _action_chart_root=lambda: str(index.root),
        **extra,
    )


def test_opening_reads_off_the_ui_thread_and_refuses_shared_tables(stored, tmp_path, monkeypatch):
    from cdmw.ui.archive_browser import action_chart_actions as actions

    shared = "actionchart/bin__/actionchart/xml/description/commonactioninfo.paac"
    entries = [stored(PATH, chart_bytes()), stored(shared, chart_bytes()), stored(DESCRIPTION, descriptor_bytes()),
               *(stored("character/motion/" + clip, _clip_bytes(1.0)) for clip in CLIPS)]
    index, _scans, _root = _index(tmp_path, entries)
    monkeypatch.setattr(actions, "chart_archive_index", lambda root: index)
    reads: list[str] = []
    monkeypatch.setattr(actions, "_read", lambda entry: reads.append(entry.path) or entry.paz_file.read_bytes())
    calls: list[dict] = []
    shown: list[tuple] = []
    browser = _browser(index, calls, [], _show_action_chart_editor=lambda *args: shown.append(args))

    actions.ArchiveActionChartActionsMixin._open_action_chart_editor(browser, PATH)

    assert reads == [] and len(calls) == 1 and calls[0]["show_archive_progress"] is True
    calls[0]["on_complete"](calls[0]["task"](lambda _message: None))
    prepared, mod = shown[0]
    assert mod is None and prepared.data == chart_bytes() and prepared.used_by == ("Player_Kliff (Sword)",)
    assert set(prepared.catalogs[1].suggestions) == set(CLIPS) and prepared.edited is None

    actions.ArchiveActionChartActionsMixin._open_action_chart_editor(browser, shared)
    with pytest.raises(ActionChartError, match="shared action table"):
        calls[1]["task"](lambda _message: None)


def test_finder_action_opens_the_chosen_chart(stored, tmp_path, monkeypatch):
    from cdmw.ui.archive_browser import action_chart_actions as actions

    index, _scans, _root = _index(tmp_path, [stored(PATH, chart_bytes()), stored(DESCRIPTION, descriptor_bytes())])
    monkeypatch.setattr(actions, "chart_archive_index", lambda root: index)
    seen: dict = {}

    class _Finder:
        def __init__(self, rows, available, includes, parent):
            seen.update(rows=rows, available=available, includes=includes)
            self.selected_path = PATH

        def exec(self):
            return 1

    monkeypatch.setattr(actions, "ActionChartFinderDialog", _Finder)
    calls: list[dict] = []
    opened: list = []
    browser = _browser(index, calls, [], _open_action_chart_editor=opened.append)

    actions.ArchiveActionChartActionsMixin._open_action_chart_finder(browser)
    calls[0]["on_complete"](calls[0]["task"](lambda _message: None))
    assert opened == [PATH] and seen["available"] == {PATH} and len(seen["rows"]) == 2


def test_a_mod_cdmw_wrote_reopens_with_its_edits(qt_app, stored, tmp_path, monkeypatch, accelerator):
    from cdmw.ui.archive_browser import action_chart_actions as actions

    data = chart_bytes()
    entry = stored(PATH, data)
    index, _scans, _root = _index(tmp_path, [entry])
    edited = apply_action_chart_edits(data, ActionChartEditRequest((_clip_retarget(CLIPS[0], NEW_CLIP),)), virtual_path=PATH).data
    written = write_action_chart_mod(entry, data, edited, parent=tmp_path / "mods", title="Sword chart edit", author="me")
    monkeypatch.setattr(actions.QFileDialog, "getExistingDirectory", lambda *args, **kwargs: str(written.folder))
    monkeypatch.setattr(actions, "chart_archive_index", lambda root: index)
    calls: list[dict] = []
    opened: list = []
    browser = _browser(index, calls, [], _action_chart_mods_start=lambda: tmp_path,
                       _open_action_chart_editor=lambda path, mod=None: opened.append((path, mod)))

    actions.ArchiveActionChartActionsMixin._open_action_chart_mod(browser)
    calls[0]["on_complete"](calls[0]["task"](lambda _message: None))
    path, mod = opened[0]
    assert path == PATH and mod.author == "me" and mod.charts[PATH] == edited

    shown: list = []
    browser = _browser(index, calls, [], _show_action_chart_editor=lambda *args: shown.append(args))
    actions.ArchiveActionChartActionsMixin._open_action_chart_editor(browser, PATH, mod=mod)
    prepared = calls[1]["task"](lambda _message: None)
    assert prepared.edited == edited and prepared.changes.strings[0].new == NEW_CLIP

    dialog = _editor(data, edited=prepared.edited, edited_changes=prepared.changes)
    assert dialog.export_button.isEnabled()
    assert NEW_CLIP in dialog.changes_view.toPlainText()


def test_use_clip_length_sets_clip_end_from_the_clip(qt_app):
    from cdmw.services.action_chart_edit_service import ClipInfo

    asked: list[str] = []
    dialog = _editor(clip_info=lambda clip: asked.append(clip) or ClipInfo(clip, "character/motion/" + clip, 2.25, 68))
    assert not dialog.clip_length_button.isHidden() and dialog.show_clip_button.isHidden()
    dialog.animation_table.selectRow(0)
    dialog.clip_edit.setText(NEW_CLIP)
    dialog.clip_length_button.click()
    _wait_idle(dialog)
    assert asked == [NEW_CLIP]
    assert "2.25 s, 68 frames" in dialog.clip_info_label.text()
    assert dialog._pending_values[("animation.end_time", 0, 0)] == 2.25
    assert dialog.value_table.item(_value_row(dialog, "animation.end_time"), 2).text() == "2.25"

    shown: list[str] = []
    dialog._show_in_browser = shown.append
    dialog.show_clip_button.click()
    assert shown == [NEW_CLIP]


def test_export_action_sends_the_mod_to_dmm_on_the_worker(qt_app, monkeypatch, stored, tmp_path, accelerator):
    from cdmw.ui.archive_browser import action_chart_actions as actions
    from cdmw.ui.archive_browser.action_chart_editor_dialog import ActionChartEditorResult
    from cdmw.ui.archive_browser.action_chart_export_dialog import SEND_TO_DMM

    data = chart_bytes()
    entry = stored(PATH, data)
    result = apply_action_chart_edits(data, ActionChartEditRequest((_clip_retarget(CLIPS[0], NEW_CLIP),)), virtual_path=PATH)
    infos: list[str] = []
    monkeypatch.setattr(actions.QMessageBox, "information", lambda parent, title, text: infos.append(text))
    seen: dict = {}

    class _Details:
        def __init__(self, *, title, description, author, version, parent):
            seen.update(title=title, description=description)
            self.choice, self.mod_title, self.mod_author, self.mod_version = SEND_TO_DMM, "My sword", "", "1.0"
            self.mod_description, self.keep_existing = "d", True

        def exec(self):
            return 1

    monkeypatch.setattr(actions, "ActionChartExportDialog", _Details)
    mods = tmp_path / "DMM" / "mods"
    mods.mkdir(parents=True)
    calls: list[dict] = []
    statuses: list[str] = []
    browser = SimpleNamespace(shell=_shell(calls, statuses),
                              _choose_action_chart_mod_parent=lambda choice, owner=None, start=None: mods)

    payload = ActionChartEditorResult(result.data, result.changes)
    plan = actions.ArchiveActionChartActionsMixin._ask_action_chart_export(browser, entry, payload)
    assert seen["title"] == "sword_upper chart edit" and NEW_CLIP in seen["description"]
    assert plan.parent == mods and plan.sent and plan.title == "My sword" and plan.keep_existing
    actions.ArchiveActionChartActionsMixin._write_edited_action_chart(browser, entry, data, payload, plan)

    assert not any(mods.iterdir()), "nothing is written before the worker runs"
    assert calls[0]["task_accepts_cancel"] is True
    import threading
    written = calls[0]["task"](lambda _message: None, threading.Event())
    calls[0]["on_complete"](written)
    assert (mods / "My sword" / "0036" / "0.pamt").is_file()
    assert "Sent the action chart mod to DMM" in infos[0] and PATH in infos[0]
    assert statuses[-1].startswith("Wrote action chart DMM mod")


def test_the_action_charts_button_works_with_nothing_selected(qt_app):
    from cdmw.ui.archive_browser.action_chart_actions import ArchiveActionChartActionsMixin

    triggered: list[str] = []
    browser = SimpleNamespace(_open_action_chart_finder=lambda: triggered.append("find"),
                              _open_action_chart_mod=lambda: triggered.append("mod"))
    button = ArchiveActionChartActionsMixin._build_action_chart_button(browser)
    actions = button.menu().actions()
    assert [action.text() for action in actions] == ["Find Action Chart by Character...", "Open Action Chart Mod..."]
    for action in actions:
        action.trigger()
    assert triggered == ["find", "mod"]


# --- other charts that play a clip ---------------------------------------------------


def test_the_usage_index_lists_every_chart_that_plays_a_clip(stored, tmp_path):
    from cdmw.services.action_chart_edit_service import apply_linked_clip_changes, charts_playing_clip, clip_usage_index

    data = chart_bytes()
    index, _scans, _root = _index(tmp_path, [stored(PATH, data), stored(BASIC, data)])
    read = lambda entry: entry.paz_file.read_bytes()  # noqa: E731
    uses = charts_playing_clip(index, CLIPS[0].upper(), read)
    assert sorted((use.chart, use.animations) for use in uses) == [(BASIC, 1), (PATH, 1)]
    assert clip_usage_index(index, read) is clip_usage_index(index, lambda entry: b"unread")

    from cdmw.services.action_chart_edit_service import LinkedClipChange
    change = LinkedClipChange(BASIC, CLIPS[0], NEW_CLIP)
    patched = apply_linked_clip_changes(data, BASIC, [change, LinkedClipChange(PATH, CLIPS[1], NEW_CLIP)])
    assert load_editable_chart(patched, BASIC).tables[1].values == (NEW_CLIP, CLIPS[1])
    assert apply_linked_clip_changes(patched, BASIC, [change]) == patched, "a change already made is skipped"


def test_linked_clip_changes_ship_in_the_same_mod(stored, tmp_path, accelerator):
    from cdmw.services.action_chart_edit_service import LinkedClipChange, read_chart_mod

    data = chart_bytes()
    sword, basic = stored(PATH, data), stored(BASIC, data)
    index, _scans, _root = _index(tmp_path, [sword, basic])
    read = lambda entry: entry.paz_file.read_bytes()  # noqa: E731
    edited = apply_action_chart_edits(data, ActionChartEditRequest((_clip_retarget(CLIPS[0], NEW_CLIP),)), virtual_path=PATH).data
    linked = (LinkedClipChange(BASIC, CLIPS[0], NEW_CLIP),)
    mods = tmp_path / "mods"

    result = write_action_chart_mod(sword, data, edited, parent=mods, title="Idle", shipped_entries=index.entry_for_path,
                                    linked=linked, read_shipped=read)

    assert set(result.charts) == {PATH, BASIC}
    charts = read_chart_mod(result.folder).charts
    assert load_editable_chart(charts[BASIC], BASIC).tables[1].values[0] == NEW_CLIP
    json_files = sorted(path.name for path in result.folder.rglob("*.json"))
    assert json_files == ["manifest.json", "modinfo.json"], "DMM reads every .json in a mod folder"

    only_linked = write_action_chart_mod(sword, data, data, parent=mods, title="Only linked", linked=linked,
                                         shipped_entries=index.entry_for_path, read_shipped=read)
    assert only_linked.charts == (BASIC,)


def test_the_editor_offers_the_other_charts_and_exports_them(qt_app, monkeypatch):
    from cdmw.services.action_chart_edit_service import ClipUse
    from cdmw.ui.archive_browser import action_chart_link_dialog as link

    uses = {CLIPS[0].lower(): (ClipUse(PATH, 1), ClipUse(BASIC, 3))}
    dialog = _editor(clip_uses=uses, chart_users_of=lambda path: ("Player_Kliff (Sword)",))
    dialog.animation_table.selectRow(0)
    assert "also played by 1 other chart" in dialog.clip_info_label.text() and dialog.other_charts_button.isEnabled()
    dialog.animation_table.selectRow(1)
    assert "No other chart plays" in dialog.clip_info_label.text() and not dialog.other_charts_button.isEnabled()

    class _Link:
        def __init__(self, clip, others, *, new_clip, users_of, parent):
            assert clip == CLIPS[0] and [use.chart for use in others] == [BASIC] and new_clip == NEW_CLIP
            assert users_of(BASIC) == ("Player_Kliff (Sword)",)
            self.selected_charts, self.new_clip = (BASIC,), NEW_CLIP

        def exec(self):
            return 1

    monkeypatch.setattr(link, "ActionChartLinkDialog", _Link)
    dialog.animation_table.selectRow(0)
    dialog.clip_edit.setText(NEW_CLIP)
    dialog.other_charts_button.click()
    assert dialog.pending_list.count() == 1 and "basic_upper.paac" in dialog.pending_list.item(0).text()
    assert f"At export, also in {BASIC}" in dialog.changes_view.toPlainText()
    assert dialog.export_button.isEnabled() and not dialog.apply_button.isEnabled(), "linked changes need no Apply"
    dialog.export_button.click()
    assert [(item.chart, item.old, item.new) for item in dialog.result_payload.linked] == [(BASIC, CLIPS[0], NEW_CLIP)]


def test_link_dialog_needs_a_new_clip_and_a_ticked_chart(qt_app):
    from cdmw.services.action_chart_edit_service import ClipUse
    from cdmw.ui.archive_browser.action_chart_link_dialog import ActionChartLinkDialog

    dialog = ActionChartLinkDialog(CLIPS[0], (ClipUse(BASIC, 3), ClipUse(PATH, 1)), users_of=lambda path: ())
    dialog.add_button.click()
    assert "Enter the clip" in dialog.error_label.text() and not dialog.selected_charts
    dialog.new_clip_edit.setText(NEW_CLIP)
    dialog.table.item(1, 0).setCheckState(dialog.table.item(1, 0).checkState().Unchecked)
    dialog.add_button.click()
    assert dialog.selected_charts == (BASIC,) and dialog.new_clip == NEW_CLIP


# --- included charts ------------------------------------------------------------------

BRANCHSET = "actionchart/bin__/upperaction/1_pc/1_phm/common_upper_branchset.paac"


def test_the_scan_records_included_charts_and_slots_reach_them(stored, tmp_path):
    from cdmw.services.action_chart_edit_service import chart_scan, chart_users, character_chart_rows, included_charts

    data = chart_bytes()  # table 0 entry 0, the chart's include, names common_upper_branchset
    index, _scans, _root = _index(tmp_path, [stored(PATH, data), stored(BRANCHSET, data)])
    scan = chart_scan(index, lambda entry: entry.paz_file.read_bytes())
    assert scan.includes[PATH.lower()] == (BRANCHSET,)
    assert included_charts(scan.includes, PATH) == (BRANCHSET,)
    assert included_charts(scan.includes, BRANCHSET) == (), "a chart never lists itself"
    rows = character_chart_rows(descriptor_bytes())
    assert chart_users(rows, BRANCHSET, scan.includes) == ("Player_Kliff (Sword, via sword_upper)",)
    assert chart_users(rows, BRANCHSET) == ()


def test_the_finder_lists_included_charts_under_each_slot(qt_app):
    from cdmw.ui.archive_browser.action_chart_finder_dialog import ActionChartFinderDialog

    rows = character_chart_rows(descriptor_bytes())
    includes = {PATH.lower(): (BRANCHSET,), BRANCHSET.lower(): (PATH,)}
    dialog = ActionChartFinderDialog(rows, available={PATH, BRANCHSET}, includes=includes)
    sword = dialog.tree.topLevelItem(0).child(1)
    assert sword.childCount() == 1, "a chart that includes its includer is not listed again"
    included = sword.child(0)
    assert (included.text(0), included.text(1)) == ("includes", "upperaction/1_pc/1_phm/common_upper_branchset")
    dialog.filter_edit.setText("branchset")
    assert not included.isHidden() and not sword.isHidden() and dialog.tree.topLevelItem(0).child(0).isHidden()
    dialog.tree.setCurrentItem(included)
    dialog.edit_button.click()
    assert dialog.selected_path == BRANCHSET
