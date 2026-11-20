"""Speed Tuning window (experimental), offscreen, with fake sets."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

pytest.importorskip("PySide6")

from PySide6.QtWidgets import QApplication

from cdmw.services.animation_speed_service import (
    SpeedChart,
    SpeedCharacter,
    SpeedFactors,
    SpeedMove,
    SpeedSet,
    plan_speed_edits,
)
from cdmw.ui.archive_browser.speed_tuning_dialog import WINDOW_TITLE, SpeedTuningDialog, plan_summary
from tests.test_action_chart_binary import CLIPS, chart_bytes

ATTACK, IDLE = CLIPS
PATH = "actionchart/bin__/upperaction/1_pc/1_phm/sword_upper.paac"
LINKED = "actionchart/bin__/upperaction/1_pc/1_phm/common_upper.paac"
SECOND = "actionchart/bin__/upperaction/1_pc/1_phm/dagger_upper.paac"


@pytest.fixture(scope="module")
def qt_app() -> QApplication:
    return QApplication.instance() or QApplication([])


def _chart(path=PATH, factors=SpeedFactors(), mod="", served=""):
    return SpeedChart(path, "Sword", 1.0, (
        SpeedMove(ATTACK, "cd_phm_sword_attack_00", "attack", 1, 1, 1.5),
        SpeedMove("1_pc/1_phm/cd_phm_sword_attack_01.paa", "cd_phm_sword_attack_01", "attack", 1, 2, 1.0),
        SpeedMove(IDLE, "cd_phm_sword_idle_00", "idle", 1, 0, 2.5),
    ), factors, mod, served)


def _dialog(**kwargs):
    calls = SimpleNamespace(plans=[], exports=[], opened=[], searches=[], prefabs=[])
    characters = (SpeedCharacter("Kliff", (SpeedSet(PATH, "Sword"), SpeedSet(SECOND, "Dagger"))),
                  SpeedCharacter("Damiane", (SpeedSet(SECOND, "Dagger"),)))

    def plan(path, factors, linked):
        calls.plans.append((path, factors, tuple(linked)))
        return (plan_speed_edits(chart_bytes(), path, SpeedFactors(factors.set, factors.kinds,
                                                                   {k: v for k, v in factors.moves.items()
                                                                    if k in CLIPS})),)

    options = dict(
        load_set=kwargs.pop("load_set", lambda path: _chart(path)),
        plan=plan,
        linked_of=lambda path: ((LINKED, True), ("actionchart/bin__/other.paac", False)),
        export=lambda path, factors, linked: calls.exports.append((path, factors, tuple(linked))),
        open_chart=calls.opened.append,
        prefab_search=calls.searches.append,
        open_prefab=calls.prefabs.append,
        prefab_categories=(("cameras", "Scene cameras"), ("moving", "Moving objects")),
    )
    options.update(kwargs)
    dialog = SpeedTuningDialog(characters, **options)
    return dialog, calls


def test_the_window_is_marked_experimental_and_fills_from_a_set(qt_app):
    dialog, _calls = _dialog()
    assert "Experimental" in dialog.windowTitle() == WINDOW_TITLE
    assert dialog.character_combo.count() == 2 and dialog.set_list.count() == 2
    assert not dialog.export_button.isEnabled()  # no set open yet
    assert dialog.select_set(PATH)
    assert dialog.move_table.rowCount() == 3
    assert dialog.kind_spins["attack"].isEnabled() and not dialog.kind_spins["jump"].isEnabled()
    assert "included by this set" in dialog.linked_label.text() and dialog.linked_checkbox.isChecked()
    assert dialog.linked_paths() == (LINKED,)
    assert not dialog.export_button.isEnabled()  # nothing changed yet
    for widget in (dialog.set_factor_spin, dialog.move_table, dialog.export_button, dialog.prefab_table):
        assert widget.objectName()


def test_kind_and_move_factors_produce_the_expected_speed_factors(qt_app):
    dialog, calls = _dialog()
    dialog.select_set(PATH)
    dialog.set_factor_spin.setValue(1.5)
    dialog.kind_spins["attack"].setValue(2.0)
    assert dialog.move_table.cellWidget(0, 4).value() == 2.0  # follows its kind
    dialog.move_table.cellWidget(1, 4).setValue(3.0)
    factors = dialog.factors()
    assert factors.set == 1.5 and factors.kinds == {"attack": 2.0}
    assert factors.moves == {"1_pc/1_phm/cd_phm_sword_attack_01.paa": 3.0}
    assert dialog.export_button.isEnabled()
    dialog.refresh_review()
    assert "value(s) change" in dialog.review_text.toPlainText()
    assert calls.plans[-1][2] == (LINKED,)
    dialog.export_button.click()
    assert calls.exports and calls.exports[-1][0] == PATH and calls.exports[-1][1] == factors


def test_reset_returns_every_factor_to_one(qt_app):
    dialog, _calls = _dialog()
    dialog.select_set(PATH)
    dialog.kind_spins["attack"].setValue(2.0)
    dialog.move_table.cellWidget(2, 4).setValue(0.5)
    dialog.reset_factors()
    assert dialog.factors().is_identity and not dialog.export_button.isEnabled()
    assert all(dialog.move_table.cellWidget(row, 4).value() == 1.0 for row in range(3))


def test_a_set_from_a_mod_shows_its_factors_and_can_be_exported_back_to_one(qt_app):
    factors = SpeedFactors(1.0, {"attack": 2.0}, {IDLE: 0.5})
    dialog, _calls = _dialog(load_set=lambda path: _chart(path, factors, mod="Fast", served="Other Mod"))
    dialog.select_set(PATH)
    assert dialog.kind_spins["attack"].value() == 2.0 and dialog.move_table.cellWidget(2, 4).value() == 0.5
    assert "Other Mod" in dialog.served_label.text()
    dialog.reset_factors()
    assert dialog.export_button.isEnabled()  # taking the set out of the mod is an export too


def test_review_text_summarises_each_kind():
    plan = plan_speed_edits(chart_bytes(), PATH, SpeedFactors(2.0, {"attack": 2.0}))
    text = plan_summary((plan,))
    assert "2 value(s) change" in text and "Attacks: 1 speed window(s), rate 1 -> 2" in text
    assert "Whole set rate: 1 -> 2" in text
    assert plan_summary(()).startswith("No speed values change")


def test_prefab_search_lists_results_by_category_and_opens_one(qt_app):
    dialog, calls = _dialog()
    dialog.prefab_category_combo.setCurrentIndex(1)
    dialog.prefab_search_button.click()
    assert calls.searches == ["cameras"] and not dialog.prefab_search_button.isEnabled()
    dialog.show_prefab_results([{"path": "object/prefab/cam.prefab", "category_label": "Scene cameras",
                                 "members": ["CameraComponent"]}])
    assert dialog.prefab_table.rowCount() == 1 and dialog.prefab_table.item(0, 1).text() == "Scene cameras"
    assert dialog.prefab_search_button.isEnabled()
    dialog.prefab_table.selectRow(0)
    assert dialog.prefab_open_button.isEnabled()
    dialog.prefab_open_button.click()
    assert calls.prefabs == ["object/prefab/cam.prefab"]


def test_game_tables_page_opens_each_speed_table(qt_app):
    opened = []
    dialog, _calls = _dialog(open_game_table=opened.append)
    dialog.table_buttons["aimovespeedinfo"].click()
    dialog.table_buttons["gimmickinfo"].click()
    assert opened == ["aimovespeedinfo", "gimmickinfo"]


def test_the_actions_open_the_window_and_the_game_table_editor(qt_app, monkeypatch):
    from cdmw.ui.archive_browser.speed_tuning_actions import (
        ArchiveSpeedTuningActionsMixin,
        PreparedSpeedTuning,
        speed_export_message,
    )
    from cdmw.services.animation_speed_service import SpeedExportResult

    opened = []
    browser = SimpleNamespace(_open_game_table_editor=opened.append, _open_action_chart_editor=lambda path: None)
    ArchiveSpeedTuningActionsMixin._open_speed_game_table(browser, "gimmickinfo")
    assert opened[0].path.endswith("gimmickinfo.staticinfobody")
    text = speed_export_message(SpeedExportResult(None, "Fast", (), 0, (PATH,)), True)
    assert "removed" in text
    text = speed_export_message(SpeedExportResult(__import__("pathlib").Path("m"), "Fast", (PATH,), 2), False)
    assert "experimental" in text and PATH in text
