"""The task layout: Position, Animations, Armour, Your mod, Advanced, Help.

Headless construction over the synthetic placement files, so the wiring between the moved
controls is exercised by a real window rather than read off the source.
"""

from __future__ import annotations


import pytest
from PySide6.QtCore import QSettings, Qt
from PySide6.QtWidgets import QApplication, QMessageBox

from tools.placement_studio import corpus
from tests.test_papr_format import _doc, _driver_block, _entry
from tests.test_placement_studio_operations import BODY, FILES, W1H


@pytest.fixture
def window(monkeypatch, tmp_path):
    QApplication.instance() or QApplication([])
    from tools.placement_studio.window import PlacementStudioWindow

    monkeypatch.setattr(PlacementStudioWindow, "_start_armour_index", lambda self: None)
    monkeypatch.setattr(PlacementStudioWindow, "_start_archive_content_load",
                        lambda *a, **k: None)
    settings = QSettings(str(tmp_path / "settings.ini"), QSettings.Format.IniFormat)
    monkeypatch.setattr(PlacementStudioWindow, "_mod_settings", lambda self: settings)
    base = tmp_path / "vanilla"
    records = {path: corpus._pin(base, path, data, "0009") for path, data in FILES.items()}
    studio = PlacementStudioWindow(corpus.Baseline(base, records), background_loading=False)
    yield studio
    studio.close()
    studio.deleteLater()


def test_the_tabs_are_named_for_the_jobs(window) -> None:
    tabs = [window._lower.tabText(i) for i in range(window._lower.count())]
    assert tabs == ["Position", "Animations", "Edit animation", "Armour", "Your mod", "Advanced", "Help"]
    advanced = [window._advanced_tabs.tabText(i) for i in range(window._advanced_tabs.count())]
    assert advanced[:4] == ["Attach points", "Driven bones", "Rig behaviour", "Action charts"]
    assert advanced[4].startswith("File changes")


def test_fine_tune_starts_on_a_point_and_avoids_a_shared_one(window) -> None:
    # The fixture's in-hand grip is shared by every held row, so a change to it could never
    # be saved: Fine-tune starts on the body spot instead and says so in the Adjust choice.
    assert window._selected_socket == "RHand_Socket"
    assert window._adjust_target_box.currentData() == "body"

    window._adjust_target_box.setCurrentIndex(window._adjust_target_box.findData("item"))
    assert window._selected_socket == "Basic_ChildSocket"
    assert window._share_note.isVisibleTo(window)
    assert "Shared by" in window._share_note.text()
    assert "Grip (in hand)" in window._edit_target.text()


def test_the_adjust_choice_always_names_the_live_point(window) -> None:
    for role in (0, 1, 0):
        window._mesh_role_box.setCurrentIndex(role)
        own = window._selected_socket in window._session.weapon.sockets
        assert window._adjust_target_box.currentData() == ("item" if own else "body")


def test_drag_mode_buttons_and_the_mode_record_agree(window) -> None:
    window._mode_buttons["rotate"].click()
    assert window._mode_box.currentData() == "rotate"
    assert window._mode_buttons["rotate"].isChecked()
    assert not window._mode_buttons["off"].isChecked()
    window._advanced_mode_buttons["route"].click()
    assert window._mode_box.currentData() == "route"
    assert not any(button.isChecked() for button in window._mode_buttons.values())
    window._advanced_mode_buttons["route"].click()
    assert window._mode_box.currentData() == "off"
    assert window._mode_buttons["off"].isChecked()


def test_the_step_size_stays_usable_outside_move_mode(window) -> None:
    window._set_mode("off")
    assert window._step_box.isEnabled()


def test_an_adjustment_is_listed_and_saved_as_one_dmm_mod(window, monkeypatch, tmp_path) -> None:
    assert window._mod_summary_button.text() == "Your mod: no changes"
    assert not window._save_mod_button.isEnabled()

    window._edits.nudge(BODY, "Pelvis_L_Socket", 0.02, 0.0, 0.0)
    window._after_edit()
    assert window._mod_summary_button.text() == "Your mod: 1 change"
    assert window._lower.tabText(window._lower.indexOf(window._mod_page)) == "Your mod (1)"
    item = window._mod_list.topLevelItem(0)
    assert item.text(0) == "Manual adjustments"
    assert window._mod_name_edit.placeholderText() == "Left hip adjustment"
    assert item.checkState(0) == Qt.Checked
    assert window._save_mod_button.isEnabled()

    out = tmp_path / "mods"
    out.mkdir()
    window._save_to_folder.setChecked(True)
    window._mod_name_edit.setText("Left hip out")
    monkeypatch.setattr(window, "_save_folder", lambda into_dmm: out)
    shown = []
    monkeypatch.setattr(QMessageBox, "exec", lambda box: shown.append(box.windowTitle()) or 0)
    window._on_save_mod()

    assert shown == ["Mod saved"]
    saved = out / "Left hip out - DMM"
    # DMM gets the shared body socket file as a patch, never a full copy.
    assert (saved / (BODY + ".patch")).is_file()
    assert not (saved / BODY).exists()
    assert (saved / "modinfo.json").is_file()
    assert "Saved" in window._save_result.text()
    assert window._mod_settings().value("placement_studio/save_folder") == str(out)


def test_an_unticked_change_stays_out_and_nothing_ticked_saves_nothing(window, monkeypatch,
                                                                      tmp_path) -> None:
    window._edits.nudge(BODY, "Pelvis_L_Socket", 0.02, 0.0, 0.0)
    window._after_edit()
    window._mod_list.topLevelItem(0).setCheckState(0, Qt.Unchecked)
    assert not window._save_mod_button.isEnabled()
    called = []
    monkeypatch.setattr(window, "_save_folder", lambda into_dmm: called.append(1))
    window._on_save_mod()
    assert called == []
    # The choice survives a refresh of the list.
    window._after_edit()
    assert window._mod_list.topLevelItem(0).checkState(0) == Qt.Unchecked


def test_a_shared_point_edit_is_refused_with_a_plain_reason(window, monkeypatch, tmp_path) -> None:
    window._edits.nudge(W1H, "Basic_ChildSocket", 0.0, 0.05, 0.0)
    window._after_edit()
    out = tmp_path / "mods"
    out.mkdir()
    monkeypatch.setattr(window, "_save_folder", lambda into_dmm: out)
    texts = []
    monkeypatch.setattr(QMessageBox, "exec",
                        lambda box: texts.append((box.windowTitle(), box.informativeText())) or 0)
    window._save_to_folder.setChecked(True)
    window._on_save_mod()
    assert texts and texts[0][0] == "Not saved"
    assert "shared by several items" in texts[0][1]
    assert list(out.iterdir()) == []


def test_removing_a_change_takes_it_out_of_the_session(window, monkeypatch) -> None:
    window._edits.nudge(BODY, "Pelvis_L_Socket", 0.02, 0.0, 0.0)
    window._after_edit()
    window._mod_list.setCurrentItem(window._mod_list.topLevelItem(0))
    monkeypatch.setattr(QMessageBox, "question", lambda *a, **k: QMessageBox.Yes)
    window._discard_selected_change()
    assert window._edits.loose_commands() == []
    assert window._mod_list.topLevelItemCount() == 0
    assert window._mod_summary_button.text() == "Your mod: no changes"


def test_unsaveable_edits_are_shown_apart_and_removed_on_their_own(window, monkeypatch) -> None:
    from tests.test_placement_studio_operations import DESC

    window._edits.nudge(BODY, "Pelvis_L_Socket", 0.02, 0.0, 0.0)
    window._edits.set_route(DESC, "CD_TwoHandWeapon_Sword", "in_socket", "Pelvis_R_Socket")
    window._after_edit()
    rows = [window._mod_list.topLevelItem(i) for i in range(window._mod_list.topLevelItemCount())]
    assert [row.text(0) for row in rows] == ["Manual adjustments",
                                             "Advanced edits that cannot be saved as a mod"]
    assert not rows[1].flags() & Qt.ItemIsUserCheckable
    assert window._included_keys() == ["manual"]
    window._mod_list.setCurrentItem(rows[1])
    monkeypatch.setattr(QMessageBox, "question", lambda *a, **k: QMessageBox.Yes)
    window._discard_selected_change()
    assert [c.kind for c in window._edits.loose_commands()] == ["translate"]


def _papr() -> bytes:
    from cdmw.core.papr_format import encode_papr

    return encode_papr(_doc(
        _entry("Root", "Bip01"),
        _entry("B_Jiggle_M_Root", "Root", kind=3,
               block=_driver_block(("Bip01 Spine", 30.0), ("Bip01 Neck", 50.0))),
        record_count=6,
    ))


def test_softer_and_stiffer_change_the_chain(window) -> None:
    assert window.load_constraint_rig(_papr(), "character/model/1_pc/1_phm/phm_01.papr") is None
    window._chain_table.selectRow(0)
    before = window._selected_chain().strength
    window._chain_stiffer.click()
    assert window._selected_chain().strength > before
    window._chain_softer.click()
    window._chain_softer.click()
    assert window._selected_chain().strength < before
    assert any(change.key == "driven_bones" for change in window._mod_changes())


def test_a_chain_switched_off_can_be_turned_back_up(window) -> None:
    window.load_constraint_rig(_papr(), "character/model/1_pc/1_phm/phm_01.papr")
    window._chain_table.selectRow(0)
    shipped = window._selected_chain().strength
    window._chain_off.click()
    assert window._selected_chain().strength == 0
    window._apply_strength(int(shipped))
    assert window._selected_chain().strength == pytest.approx(shipped, abs=1)
    assert window.constraint_mod_files() == {}


def test_the_help_page_describes_the_tabs_that_exist(window) -> None:
    from tools.placement_studio.glossary import as_html

    html = as_html()
    for name in ("Position", "Animations", "Edit animation", "Armour", "Your mod", "Advanced"):
        assert name in html
    for gone in ("Hangs on", "Pending changes", "Build packages", "Swap animations"):
        assert gone not in html
