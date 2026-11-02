"""Action Chart Editor: edit a `.paac` chart, read it back, and export a DMM loose mod.

Charts are the owned fixtures built in `tests/test_action_chart_binary.py` from the
loader layout; no game file is read. Nothing here says anything about the game.
"""

from __future__ import annotations

import json
import struct
import time
from types import SimpleNamespace

import pytest

from cdmw.core.action_chart_binary import ActionChartError, ChartValueEdit, decode_action_chart
from cdmw.models import ArchiveEntry, ModPackageInfo
from cdmw.services.action_chart_edit_service import (
    ActionChartEditRequest,
    ClipRetarget,
    animation_value_rows,
    apply_action_chart_edits,
    chart_clip_names,
    clip_rows,
    compare_charts,
    export_action_chart_mod,
    load_editable_chart,
    request_from_pending,
    unknown_clips,
)
from tests.test_action_chart_binary import CLIPS, chart_bytes

PATH = "actionchart/bin__/upperaction/1_pc/1_phm/sword_upper.paac"
NEW_CLIP = "1_pc/1_phm/cd_phm_sword_attack_heavy_longer_name_01.paa"


def _f32(value: float) -> float:
    return struct.unpack("<f", struct.pack("<f", value))[0]


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


# --- service ------------------------------------------------------------------------


def test_retarget_and_timing_edits_are_read_back_from_the_new_bytes():
    data = chart_bytes()
    request = ActionChartEditRequest(
        (ClipRetarget(CLIPS[0], NEW_CLIP),),
        (
            ChartValueEdit("chart.action_speed_rate", 1.25),
            ChartValueEdit("animation.end_time", 1.75, animation=0),
            ChartValueEdit("speed.rate", 1.5, animation=0, item=0),
            ChartValueEdit("event.begin", 0.35, animation=0, item=1),
        ),
    )

    result = apply_action_chart_edits(data, request, virtual_path=PATH)

    chart = decode_action_chart(result.data, virtual_path=PATH)
    assert len(result.data) == len(data) + len(NEW_CLIP) - len(CLIPS[0])
    assert chart.clip_name(chart.animations[0]) == NEW_CLIP
    assert chart.clip_name(chart.animations[1]) == CLIPS[1]
    assert chart.action_speed_rate == 1.25 and chart.animations[0].end_time == 1.75
    assert [(change.old, change.new) for change in result.changes.clips] == [(CLIPS[0], NEW_CLIP)]
    changed = {(change.row.field, change.row.item): (change.old, change.row.value) for change in result.changes.values}
    assert changed == {
        ("chart.action_speed_rate", 0): (1.0, 1.25),
        ("animation.end_time", 0): (1.5, 1.75),
        ("speed.rate", 0): (1.0, 1.5),
        ("event.begin", 1): (_f32(0.3), _f32(0.35)),
    }


def test_edits_on_an_edited_copy_are_listed_against_the_shipped_chart():
    shipped = chart_bytes()
    first = apply_action_chart_edits(shipped, ActionChartEditRequest((ClipRetarget(CLIPS[0], NEW_CLIP),)), virtual_path=PATH)
    second = apply_action_chart_edits(
        first.data,
        ActionChartEditRequest(values=(ChartValueEdit("frame_tag.end_time", 0.45, animation=0),)),
        virtual_path=PATH,
        original=shipped,
    )
    assert [change.new for change in second.changes.clips] == [NEW_CLIP]
    assert [change.row.field for change in second.changes.values] == ["frame_tag.end_time"]
    # Retargeting back and resetting the value leaves nothing to list.
    back = apply_action_chart_edits(
        second.data,
        request_from_pending({NEW_CLIP: CLIPS[0]}, {("frame_tag.end_time", 0, 0): _f32(0.4)}),
        virtual_path=PATH,
        original=shipped,
    )
    assert back.changes.empty and back.data == shipped


@pytest.mark.parametrize(
    "request_, message",
    [
        (ActionChartEditRequest(values=(ChartValueEdit("animation.start_time", 2.0, animation=0),)), "end before it starts"),
        (ActionChartEditRequest(values=(ChartValueEdit("chart.action_speed_rate", 0.0),)), "above 0"),
        (ActionChartEditRequest(values=(ChartValueEdit("speed.rate", 1.0, animation=1),)), "no animationSpeedInfoArray"),
        (ActionChartEditRequest((ClipRetarget("1_pc/not_in_chart.paa", NEW_CLIP),)), "has no entry"),
        (ActionChartEditRequest((ClipRetarget(CLIPS[0], "badéname.paa"),)), "printable ASCII"),
    ],
)
def test_edits_outside_the_proven_scope_are_refused(request_, message):
    with pytest.raises(ActionChartError, match=message):
        apply_action_chart_edits(chart_bytes(), request_, virtual_path=PATH)


def test_shared_action_tables_are_not_editable():
    with pytest.raises(ActionChartError, match="shared action table"):
        load_editable_chart(chart_bytes(), "actionchart/bin__/actionchart/xml/description/commonactioninfo.paac")


def test_rows_clip_names_and_unknown_clips():
    data = chart_bytes()
    chart = load_editable_chart(data, PATH)
    assert [(row.clip, row.uses) for row in clip_rows(chart)] == [(CLIPS[0], 1), (CLIPS[1], 1)]
    rows = animation_value_rows(chart, data, 0)
    assert [row.field for row in rows].count("event.begin") == 2
    assert {row.event_kind for row in rows if row.field.startswith("event.")} == {"ModelAttachmentSocket", "Effect"}
    assert animation_value_rows(chart, data, 1)[2:] == ()

    names = chart_clip_names([
        "character/motion/" + CLIPS[0],
        "Character\\Motion\\1_pc/Other.paa",
        "object/animation/animation/door.paa",
        "character/motion/readme.txt",
    ])
    assert names == (CLIPS[0], "1_pc/Other.paa")
    request = ActionChartEditRequest((ClipRetarget(CLIPS[0], "1_PC/other.paa"), ClipRetarget(CLIPS[1], NEW_CLIP)))
    assert unknown_clips(request, names) == (NEW_CLIP,)


def test_export_writes_only_the_chart_into_a_dmm_loose_folder(stored, tmp_path):
    data = chart_bytes()
    entry = stored(PATH, data)
    edited = apply_action_chart_edits(data, ActionChartEditRequest((ClipRetarget(CLIPS[0], NEW_CLIP),)), virtual_path=PATH).data
    logs: list[str] = []

    result = export_action_chart_mod(
        entry, data, edited,
        parent_root=tmp_path / "exports",
        package_info=ModPackageInfo(title="Sword chart edit"),
        on_log=logs.append,
    )

    written = result.package_root / PATH
    assert written.read_bytes() == edited
    payloads = [path for path in result.package_root.rglob("*") if path.is_file() and path.suffix == ".paac"]
    assert payloads == [written]
    manifest = json.loads((result.package_root / "manifest.json").read_text(encoding="utf-8"))
    assert "dmm" in json.dumps(manifest).lower()
    assert any("1 clip retarget(s)" in line for line in logs)
    assert compare_charts(data, written.read_bytes(), virtual_path=PATH).clips[0].new == NEW_CLIP


def test_export_refuses_an_unchanged_or_foreign_payload(stored, tmp_path):
    data = chart_bytes()
    entry = stored(PATH, data)
    info = ModPackageInfo(title="x")
    with pytest.raises(ActionChartError, match="no changes"):
        export_action_chart_mod(entry, data, data, parent_root=tmp_path, package_info=info)
    prefab = stored("character/sword.prefab", data)
    with pytest.raises(ActionChartError, match="not an action chart"):
        export_action_chart_mod(prefab, data, data, parent_root=tmp_path, package_info=info)
    assert not any(tmp_path.glob("**/manifest.json"))


# --- dialog -------------------------------------------------------------------------


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


def test_dialog_applies_on_a_worker_and_shows_the_reread_chart(qt_app):
    from cdmw.ui.archive_browser.action_chart_editor_dialog import ActionChartEditorDialog

    data = chart_bytes()
    dialog = ActionChartEditorDialog(data, virtual_path=PATH, known_clips=(CLIPS[0], CLIPS[1], NEW_CLIP))
    assert dialog.clip_table.rowCount() == 2 and dialog.animation_table.rowCount() == 2
    assert not dialog.apply_button.isEnabled() and not dialog.export_button.isEnabled()

    dialog.clip_table.selectRow(0)
    dialog.new_clip_edit.setText(NEW_CLIP)
    dialog.retarget_button.click()
    dialog.animation_table.selectRow(0)
    dialog.value_table.item(_value_row(dialog, "speed.rate"), 2).setText("1.5")
    dialog.rate_spin.setValue(1.25)
    assert dialog.apply_button.isEnabled() and not dialog.export_button.isEnabled()

    dialog.apply_button.click()
    assert dialog.busy() and not dialog.close_button.isEnabled()
    _wait_idle(dialog)

    assert dialog.clip_table.item(0, 0).text() == NEW_CLIP and dialog.clip_table.item(0, 2).text() == ""
    assert dialog.animation_table.item(0, 1).text() == NEW_CLIP
    assert dialog.value_table.item(_value_row(dialog, "speed.rate"), 1).text() == "1.5"
    assert dialog.rate_spin.value() == 1.25
    changes = dialog.changes_view.toPlainText()
    assert f"Clip {CLIPS[0]} -> {NEW_CLIP}" in changes
    assert "Chart speed rate: 1 -> 1.25" in changes and "Speed window 1 rate: 1 -> 1.5" in changes
    assert dialog.export_button.isEnabled()

    dialog.export_button.click()
    payload = dialog.result_payload
    assert payload is not None and payload.data != data
    assert decode_action_chart(payload.data, virtual_path=PATH).clip_name(
        decode_action_chart(payload.data, virtual_path=PATH).animations[0]) == NEW_CLIP


def test_dialog_reports_a_refused_edit_and_keeps_the_chart(qt_app):
    from cdmw.ui.archive_browser.action_chart_editor_dialog import ActionChartEditorDialog

    data = chart_bytes()
    dialog = ActionChartEditorDialog(data, virtual_path=PATH)
    dialog.animation_table.selectRow(0)
    dialog.value_table.item(_value_row(dialog, "animation.start_time"), 2).setText("9")
    dialog.value_table.item(_value_row(dialog, "frame_tag.end_time"), 2).setText("not a number")
    assert "is not a number" in dialog.status_label.text()
    dialog.apply_button.click()
    _wait_idle(dialog)

    assert "The edit was refused" in dialog.status_label.text()
    assert dialog._data == data and not dialog.export_button.isEnabled()
    assert dialog.apply_button.isEnabled(), "the pending edit stays so it can be corrected"
    dialog.reset_button.click()
    assert dialog._data == data and not dialog.apply_button.isEnabled()


# --- Archive Browser action ---------------------------------------------------------


def test_opening_reads_off_the_ui_thread_and_refuses_shared_tables(monkeypatch):
    from cdmw.ui.archive_browser import action_chart_actions as actions

    reads: list[str] = []
    monkeypatch.setattr(actions, "read_archive_entry_data", lambda entry: (reads.append(entry.path), (chart_bytes(), False, ""))[1])
    entry = SimpleNamespace(path=PATH, basename="sword_upper.paac")
    calls: list[dict] = []
    shown: list[tuple] = []
    browser = SimpleNamespace(
        shell=SimpleNamespace(
            set_status_message=lambda message, error=False: None,
            _run_utility_task_when_idle=lambda **kwargs: calls.append(kwargs),
        ),
        archive_entries_by_extension={".paa": [SimpleNamespace(path="character/motion/" + clip) for clip in CLIPS]},
        _current_archive_action_chart_entry=lambda: entry,
        _show_action_chart_editor=lambda *args: shown.append(args),
    )

    actions.ArchiveActionChartActionsMixin._open_current_archive_action_chart_editor(browser)

    assert reads == [] and len(calls) == 1 and calls[0]["show_archive_progress"] is True
    result = calls[0]["task"](lambda _message: None)
    calls[0]["on_complete"](result)
    assert reads == [PATH] and shown == [(entry, chart_bytes(), tuple(sorted(CLIPS)))]

    entry.path = "actionchart/bin__/actionchart/xml/description/commonactioninfo.paac"
    actions.ArchiveActionChartActionsMixin._open_current_archive_action_chart_editor(browser)
    with pytest.raises(ActionChartError, match="shared action table"):
        calls[1]["task"](lambda _message: None)


def test_export_action_runs_the_dmm_export_on_the_worker(monkeypatch, stored, tmp_path):
    from cdmw.domain.packages.export_policy import ModPackageExportOptions
    from cdmw.ui.archive_browser import action_chart_actions as actions
    from cdmw.ui.archive_browser.action_chart_editor_dialog import ActionChartEditorResult

    data = chart_bytes()
    entry = stored(PATH, data)
    result = apply_action_chart_edits(data, ActionChartEditRequest((ClipRetarget(CLIPS[0], NEW_CLIP),)), virtual_path=PATH)
    monkeypatch.setattr(actions.QMessageBox, "information", lambda *args, **kwargs: None)
    targets: list[dict] = []
    calls: list[dict] = []
    statuses: list[str] = []

    def _target(**kwargs):
        targets.append(kwargs)
        return tmp_path / "exports", ModPackageInfo(title=kwargs["initial_package_title"]), True, False, ModPackageExportOptions()

    browser = SimpleNamespace(
        shell=SimpleNamespace(
            set_status_message=lambda message, error=False: statuses.append(message),
            _run_utility_task_when_idle=lambda **kwargs: calls.append(kwargs),
        ),
        _collect_archive_mod_ready_export_target=_target,
    )

    actions.ArchiveActionChartActionsMixin._export_edited_action_chart(
        browser, entry, data, ActionChartEditorResult(result.data, result.changes))

    assert targets[0]["initial_package_title"] == "sword_upper chart edit"
    assert NEW_CLIP in targets[0]["initial_package_description"]
    assert not (tmp_path / "exports").exists(), "nothing is written before the worker runs"
    written = calls[0]["task"](lambda _message: None)
    calls[0]["on_complete"](written)
    assert (written.package_root / PATH).read_bytes() == result.data
    assert statuses[-1].startswith("Wrote action chart DMM mod")
