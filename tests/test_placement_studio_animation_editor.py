"""The Edit animation tab, headless: start an edit, change it, preview it, put it in the mod."""

from __future__ import annotations

import time
from pathlib import Path

import pytest
from PySide6.QtCore import QSettings
from PySide6.QtWidgets import QApplication

from tools.paa_motion.encode import encode_paa
from tools.paa_motion.format import parse_paa
from tools.placement_studio import corpus, save_mod
from tools.placement_studio.clips import ClipEntry
from tests.test_paa_motion_edit import _clip, _skeleton
from tests.test_placement_studio_operations import FILES

TARGET = "character/motion/1_pc/1_phm/cd_phm_test_clip.paa"


def _wait(predicate, seconds: float = 5.0) -> None:
    app = QApplication.instance()
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        app.processEvents()
        if predicate():
            return
        time.sleep(0.01)
    raise AssertionError("timed out")


@pytest.fixture
def window(monkeypatch, tmp_path):
    QApplication.instance() or QApplication([])
    from tools.placement_studio.window import PlacementStudioWindow

    monkeypatch.setattr(PlacementStudioWindow, "_start_armour_index", lambda self: None)
    monkeypatch.setattr(PlacementStudioWindow, "_start_archive_content_load",
                        lambda *a, **k: None)
    settings = QSettings(str(tmp_path / "settings.ini"), QSettings.Format.IniFormat)
    monkeypatch.setattr(PlacementStudioWindow, "_mod_settings", lambda self: settings)
    skeleton = _skeleton()
    monkeypatch.setattr(PlacementStudioWindow, "_editor_skeleton", lambda self: skeleton)
    base = tmp_path / "vanilla"
    records = {path: corpus._pin(base, path, data, "0009") for path, data in FILES.items()}
    studio = PlacementStudioWindow(corpus.Baseline(base, records), background_loading=False)
    clip = parse_paa(encode_paa(_clip()))
    studio._playback.load(clip, "cd_phm_test_clip")
    studio._playback_entry = ClipEntry(TARGET, "1_phm", "idle", False, None)
    yield studio
    studio.close()
    studio.deleteLater()


def _rendered(window):
    return window._clip_edit_rendered


def test_the_tab_sits_after_animations(window) -> None:
    tabs = [window._lower.tabText(i) for i in range(window._lower.count())]
    assert tabs[:3] == ["Position", "Animations", "Edit animation"]
    assert not window._clip_edit_add_button.isEnabled()


def test_editing_the_playing_animation_previews_every_change(window) -> None:
    window._start_clip_edit()
    assert window._clip_edit_target == TARGET
    assert "cd_phm_test_clip" in window._clip_edit_title.text()
    window._edit_speed.setValue(2.0)
    _wait(lambda: _rendered(window) is not None and abs(_rendered(window).duration - 0.5) < 1e-6)
    assert abs(window._playback.clip.duration - 0.5) < 1e-6
    window._undo_clip_edit()
    _wait(lambda: abs(_rendered(window).duration - 1.0) < 1e-6)


def test_turning_a_bone_keys_it_at_the_playhead(window) -> None:
    window._start_clip_edit()
    index = window._pose_bone_box.findText("Bip01 R Hand")
    window._pose_bone_box.setCurrentIndex(index)
    window._playback.seek(12)
    window._pose_turn[2].setValue(25.0)
    track = window._clip_edit.pose_track(0x1007)
    assert [key.frame for key in track.keys] == [12]
    assert window._pose_keys.count() == 1
    window._remove_pose_key()
    assert window._clip_edit.pose_track(0x1007) is None


def test_adding_to_the_mod_twice_keeps_one_version_and_saves_the_file(window, tmp_path) -> None:
    window._start_clip_edit()
    window._edit_mirror.setChecked(True)
    window._add_clip_edit_to_mod()
    _wait(lambda: len(window._edits.operations()) == 1)
    first = window._edits.operations()[0].operation_id
    window._edit_speed.setValue(1.5)
    window._add_clip_edit_to_mod()
    _wait(lambda: [op.operation_id for op in window._edits.operations()] not in ([], [first]))
    titles = [c.title for c in window._mod_changes()]
    assert titles == ["Edited animation: cd_phm_test_clip"]

    out = tmp_path / "mods"
    out.mkdir()
    include = [c.key for c in window._mod_changes()]
    outcome = save_mod.save_mod(window._edits, save_mod.SaveRequest(
        name="Mirrored clip", folder=Path(out), include=tuple(include)))
    assert outcome.saved, outcome.problems
    written = parse_paa((out / "Mirrored clip - DMM" / TARGET).read_bytes())
    assert abs(written.duration - 1.0 / 1.5) < 2e-3


def test_a_loaded_file_needs_a_target_before_it_can_be_added(window) -> None:
    window._playback_entry = ClipEntry("C:/clips/loose.paa", "", "", False, None)
    window._start_clip_edit()
    assert window._clip_edit_target == ""
    assert not window._clip_edit_add_button.isEnabled()


def test_toggling_a_layer_off_again_leaves_no_edit(window) -> None:
    window._start_clip_edit()
    window._edit_mirror.setChecked(True)
    window._edit_mirror.setChecked(False)
    window._edit_distance.setValue(50.0)
    window._edit_distance.setValue(100.0)
    assert window._clip_edit.is_identity


def test_a_new_animation_added_over_a_game_clip_is_saved(window, tmp_path) -> None:
    window._playback.seek(15)
    window._start_from_pose()
    window._clip_edit_target = TARGET
    _wait(lambda: _rendered(window) is not None)
    window._add_clip_edit_to_mod()
    out = tmp_path / "mods"
    out.mkdir()
    include = [c.key for c in window._mod_changes()]
    outcome = save_mod.save_mod(window._edits, save_mod.SaveRequest(
        name="Held pose", folder=Path(out), include=tuple(include)))
    assert outcome.saved, outcome.problems
    assert (out / "Held pose - DMM" / TARGET).is_file()


def test_add_waits_for_the_preview_instead_of_rendering_on_the_window(window) -> None:
    window._start_clip_edit()
    window._edit_speed.setValue(2.0)
    window._add_clip_edit_to_mod()  # the preview for 2x may still be baking
    _wait(lambda: any(c.title.startswith("Edited animation") for c in window._mod_changes()))
    written = window._edits.preview()[TARGET]
    assert abs(parse_paa(written).duration - 0.5) < 1e-6


def test_a_new_animation_starts_from_the_pose_on_screen(window) -> None:
    window._playback.seek(15)
    window._new_length.setValue(3.0)
    window._start_from_pose()
    _wait(lambda: _rendered(window) is not None)
    assert abs(window._clip_edit.base.duration - 3.0) < 1e-6
    assert window._clip_edit_target == ""


def test_moving_a_hand_keys_a_reach_at_the_playhead(window) -> None:
    window._start_clip_edit()
    labels = [window._reach_end_box.itemText(i) for i in range(window._reach_end_box.count())]
    assert labels == ["Left hand", "Right hand"]
    window._playback.seek(9)
    window._reach_move[1].setValue(12.0)  # up
    track = window._clip_edit.reach_track(window._selected_reach_end())
    assert [key.frame for key in track.keys] == [9]
    assert abs(track.keys[0].offset[1] - 0.12) < 1e-9
    assert window._reach_keys.count() == 1
    _wait(lambda: _rendered(window) is not None and _rendered(window) is window._playback.clip)


def test_plant_and_let_go_make_pinned_and_released_keys(window) -> None:
    window._start_clip_edit()
    window._playback.seek(5)
    window._plant_reach()
    window._playback.seek(20)
    window._release_reach()
    keys = window._clip_edit.reach_track(window._selected_reach_end()).keys
    assert [(k.frame, k.pinned, k.weight) for k in keys] == [(5, True, 1.0), (20, False, 1.0)]
    lanes = {lane.key: lane for lane in window._key_timeline.lanes()}
    assert lanes["reach"].frames == (5, 20)
    assert lanes["reach"].filled == (5,)


def test_dragging_a_key_on_the_timeline_retimes_it(window) -> None:
    window._start_clip_edit()
    window._playback.seek(6)
    window._pose_turn[0].setValue(30.0)
    window._move_key_on_timeline("pose", 6, 18)
    track = window._clip_edit.pose_track(window._selected_bone_hash())
    assert [key.frame for key in track.keys] == [18]
    assert int(round(window._playback.frame)) == 18
    window._remove_key_on_timeline("pose", 18)
    assert window._clip_edit.pose_track(window._selected_bone_hash()) is None


def test_joining_an_animation_lengthens_the_edit_and_shows_the_fade(window) -> None:
    window._start_clip_edit()
    window._join_read((ClipEntry("character/x.paa", "", "", False, None), 0.2,
                       parse_paa(encode_paa(_clip())), window._clip_edit.base), "")
    assert abs(window._clip_edit.duration - (1.0 + 1.0 - 0.2)) < 1e-9
    assert window._join_list.count() == 1
    _wait(lambda: _rendered(window) is not None and abs(_rendered(window).duration - 1.8) < 0.04)


def test_clicking_a_joint_picks_that_bone_while_the_tab_is_open(window) -> None:
    window._lower.setCurrentWidget(window._animation_editor_page)
    window._start_clip_edit()
    assert window._viewport._bone_picking
    window._on_bone_clicked("Bip01 L Hand")
    assert window._pose_bone_box.currentText() == "Bip01 L Hand"
    assert window._reach_end_box.currentText() == "Left hand"
    window._lower.setCurrentIndex(0)
    assert not window._viewport._bone_picking


def test_the_view_picks_the_joint_under_a_click_only_while_picking() -> None:
    QApplication.instance() or QApplication([])
    from PySide6.QtCore import QEvent, QPointF, Qt
    from PySide6.QtGui import QMouseEvent

    from tools.placement_studio.model import Vec3
    from tools.placement_studio.skeleton import BoneHierarchy, BoneNode
    from tools.placement_studio.viewport import SkeletonViewport

    def at(x, y, z):
        return (1.0, 0.0, 0.0, 0.0, 0.0, 1.0, 0.0, 0.0, 0.0, 0.0, 1.0, 0.0, x, y, z, 1.0)

    hierarchy = BoneHierarchy([
        BoneNode(0, "Bip01 Pelvis", -1, at(0.0, 1.0, 0.0), Vec3(0.0, 1.0, 0.0)),
        BoneNode(1, "Bip01 L Hand", 0, at(0.4, 1.3, 0.0), Vec3(0.4, 1.3, 0.0)),
    ], "test")
    view = SkeletonViewport()
    view.resize(800, 600)
    view.set_scene(hierarchy, [], {})
    _bones, sx, sy, _front = view._bone_points()
    hand = QPointF(float(sx[1]) + 3, float(sy[1]) - 2)
    assert view._bone_at(hand) == "Bip01 L Hand"
    assert view._bone_at(QPointF(float(sx[1]) + 40, float(sy[1]))) == ""

    clicked = []
    view.bone_clicked.connect(clicked.append)

    def click() -> None:
        press = QMouseEvent(QEvent.MouseButtonPress, hand, hand, Qt.LeftButton, Qt.LeftButton,
                            Qt.NoModifier)
        view.mousePressEvent(press)
        release = QMouseEvent(QEvent.MouseButtonRelease, hand, hand, Qt.LeftButton, Qt.NoButton,
                              Qt.NoModifier)
        view.mouseReleaseEvent(release)

    click()
    assert clicked == []
    view.set_bone_picking(True)
    click()
    assert clicked == ["Bip01 L Hand"]
    view.grab()  # paints the highlight without raising


def test_plant_after_let_go_still_reaches_fully(window) -> None:
    window._start_clip_edit()
    for frame, action in ((5, window._plant_reach), (15, window._release_reach),
                          (25, window._plant_reach)):
        window._playback.seek(frame)
        window._apply_playback_frame()
        action()
    keys = window._clip_edit.reach_track(window._selected_reach_end()).keys
    assert [(k.frame, k.pinned, k.weight) for k in keys] == [
        (5, True, 1.0), (15, False, 1.0), (25, True, 1.0)]
    texts = [window._reach_keys.item(i).text() for i in range(window._reach_keys.count())]
    assert texts[1].endswith("let go")


def test_changing_the_speed_keeps_keys_on_their_moment(window) -> None:
    window._start_clip_edit()
    window._playback.seek(24)
    window._pose_turn[0].setValue(20.0)
    window._edit_speed.setValue(2.0)
    track = window._clip_edit.pose_track(window._selected_bone_hash())
    assert [key.frame for key in track.keys] == [12]
    window._undo_clip_edit()
    track = window._clip_edit.pose_track(window._selected_bone_hash())
    assert [key.frame for key in track.keys] == [24]


def test_a_file_read_for_an_earlier_edit_is_dropped(window) -> None:
    window._start_clip_edit()
    stale = window._clip_edit.base
    window._playback.seek(10)
    window._start_from_pose()
    window._join_read((ClipEntry("character/x.paa", "", "", False, None), 0.2,
                       parse_paa(encode_paa(_clip())), stale), "")
    assert window._clip_edit.joins == ()


def test_a_new_character_closes_the_edit(window) -> None:
    window._start_clip_edit()
    window._edit_mirror.setChecked(True)
    window._clip_edit_model = "some_other_rig"
    window._editor_follow_character()
    assert window._clip_edit is None
    assert window._pose_bone_box.count() == 0
    assert window._key_timeline.lanes() == ()
    assert not window._clip_edit_add_button.isEnabled()
    window._start_clip_edit()  # and the next edit still renders
    window._edit_speed.setValue(2.0)
    _wait(lambda: _rendered(window) is not None and abs(_rendered(window).duration - 0.5) < 1e-6)


# ── alpha.32 release review ─────────────────────────────────────────


def test_a_new_character_forgets_which_animation_the_edit_replaced(window) -> None:
    window._start_clip_edit()
    assert window._clip_edit_target == TARGET
    window._clip_edit_model = "some_other_rig"  # the edit was made on another character
    window._editor_follow_character()
    assert window._clip_edit_target == "" and window._clip_edit_entry is None
    window._playback.seek(5)
    window._start_from_pose()  # must not inherit the other character's target
    assert window._clip_edit_target == ""
    assert not window._clip_edit_add_button.isEnabled()


def test_an_edit_from_another_character_is_never_added(window) -> None:
    window._start_clip_edit()
    window._edit_mirror.setChecked(True)
    _wait(lambda: _rendered(window) is not None and _rendered(window) is window._playback.clip)
    window._clip_edit_model = "some_other_rig"
    window._put_clip_edit_in_mod()
    assert window._edits.operations() == []
    assert "another character" in window._clip_edit_status.text()


def test_a_failed_re_add_keeps_the_earlier_version(window, monkeypatch) -> None:
    from tools.placement_studio import editing, window_animation_editor

    window._start_clip_edit()
    window._edit_mirror.setChecked(True)
    window._add_clip_edit_to_mod()
    _wait(lambda: len(window._edits.operations()) == 1)
    first = window._edits.operations()[0].operation_id
    window._edit_speed.setValue(1.5)
    _wait(lambda: _rendered(window) is not None and abs(_rendered(window).duration - 1 / 1.5) < 2e-3)

    def refuse(*_args, **_kwargs):
        raise editing.EditError("refused")

    monkeypatch.setattr(editing.OperationHandle, "replace_clip", refuse)
    warnings = []
    monkeypatch.setattr(window_animation_editor.QMessageBox, "warning",
                        lambda *args, **kwargs: warnings.append(args))
    window._put_clip_edit_in_mod()
    assert warnings
    assert [op.operation_id for op in window._edits.operations()] == [first]
    assert [c.title for c in window._mod_changes()] == ["Edited animation: cd_phm_test_clip"]


def test_the_replace_prompt_appears_in_any_language(window, tmp_path, monkeypatch) -> None:
    from tools.placement_studio import window_save
    from tools.placement_studio.save_mod import SaveOutcome

    existing = tmp_path / "Hip sword - DMM"
    existing.mkdir()
    outcomes = [SaveOutcome(problems=("Ein Mod-Ordner mit diesem Namen existiert bereits",),
                            destination=existing, already_exists=True),
                SaveOutcome()]
    monkeypatch.setattr(window, "_included_keys", lambda: ["x"])
    monkeypatch.setattr(window, "_mod_changes", lambda: [])
    monkeypatch.setattr(window, "_save_folder", lambda _into_dmm: tmp_path)
    requests = []
    monkeypatch.setattr(window, "_run_save", lambda request: (requests.append(request), outcomes.pop(0))[1])
    asked = []
    monkeypatch.setattr(window_save.QMessageBox, "question",
                        lambda *args, **kwargs: (asked.append(args), window_save.QMessageBox.Yes)[1])
    monkeypatch.setattr(window_save.QMessageBox, "exec", lambda self: 0)  # the "Not saved" box
    window._mod_name_edit.setText("Hip sword")
    window._on_save_mod()
    assert asked
    assert [r.replace_existing for r in requests] == [False, True]
