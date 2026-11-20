"""Speed & Prefabs tab (experimental), offscreen, with fake sets."""

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
from cdmw.ui.speed_prefabs.workspace import TOOL_TITLE, SpeedPrefabsWorkspace, plan_summary
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
    dialog = SpeedPrefabsWorkspace(characters, **options)
    return dialog, calls


def test_the_tab_is_marked_experimental_and_fills_from_a_set(qt_app):
    from PySide6.QtWidgets import QLabel

    dialog, _calls = _dialog()
    assert TOOL_TITLE == "Speed & Prefabs"
    assert any(label.text() == "Experimental" for label in dialog.findChildren(QLabel))
    assert dialog.character_combo.count() == 2 and dialog.set_list.count() == 2
    assert not dialog.export_button.isEnabled()  # no set open yet
    assert dialog.select_set(PATH)
    assert dialog.move_table.rowCount() == 3
    assert dialog.kind_spins["attack"].isEnabled() and not dialog.kind_spins["jump"].isEnabled()
    assert "included by this set" in dialog.linked_label.text() and dialog.linked_checkbox.isChecked()
    assert dialog.linked_paths() == (LINKED,)
    assert not dialog.export_button.isEnabled()  # nothing changed yet
    assert dialog.move_table.horizontalHeader().sectionSize(4) == 112
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


def test_prefab_search_shows_progress_lists_results_and_opens_one_beside_them(qt_app):
    from PySide6.QtWidgets import QLabel

    dialog, calls = _dialog()
    dialog.prefab_category_combo.setCurrentIndex(1)
    dialog.prefab_search_button.click()
    assert calls.searches == ["cameras"] and not dialog.prefab_search_button.isEnabled()
    assert not dialog.prefab_progress.isHidden()
    dialog.show_prefab_progress(500, 2000)
    assert dialog.prefab_progress.maximum() == 2000 and dialog.prefab_progress.value() == 500
    assert "500 of 2,000" in dialog.prefab_status_label.text()
    dialog.show_prefab_results([{"path": "object/prefab/cam.prefab", "category_label": "Scene cameras",
                                 "members": ["CameraComponent"]}])
    assert dialog.prefab_progress.isHidden()
    assert dialog.prefab_table.rowCount() == 1 and dialog.prefab_table.item(0, 1).text() == "Scene cameras"
    assert dialog.prefab_table.item(0, 0).text() == "cam.prefab"
    assert dialog.prefab_table.item(0, 0).toolTip() == "object/prefab/cam.prefab"
    assert dialog.prefab_table.item(0, 2).text() == "Camera"
    assert dialog.prefab_search_button.isEnabled()
    dialog.prefab_table.selectRow(0)
    assert calls.prefabs == ["object/prefab/cam.prefab"]
    inspector = QLabel("inspector")
    dialog.show_prefab_inspector("object/prefab/cam.prefab", inspector)
    assert dialog.prefab_host.currentWidget() is inspector and dialog.state()["prefab_open"].endswith("cam.prefab")
    dialog.show_prefab_inspector("object/prefab/gone.prefab", None, note="Could not read it")
    assert dialog.prefab_host.currentIndex() == 0 and "Could not read" in dialog.prefab_empty_detail.text()


def test_game_tables_page_loads_each_speed_table_in_place(qt_app):
    from cdmw.ui.archive_browser.game_table_actions import GameTableEditPanel

    opened = []
    panel = GameTableEditPanel(side_by_side=True)
    dialog, _calls = _dialog(open_game_table=opened.append, game_table_panel=panel)
    assert panel.parent() is not None
    dialog.show_page("tables")
    assert opened == ["aimovespeedinfo"]  # the first visit loads the first table
    dialog.table_buttons["gimmickinfo"].click()
    assert opened == ["aimovespeedinfo", "gimmickinfo"]
    assert dialog.table_buttons["gimmickinfo"].isChecked() and not dialog.table_buttons["aimovespeedinfo"].isChecked()


def test_the_actions_open_the_window_and_the_game_table_editor(qt_app, monkeypatch):
    from cdmw.ui.archive_browser.speed_tuning_actions import (
        ArchiveSpeedTuningActionsMixin,
        PreparedSpeedTuning,
        speed_export_message,
    )
    from cdmw.services.animation_speed_service import SpeedExportResult

    text = speed_export_message(SpeedExportResult(None, "Fast", (), 0, (PATH,)), True)
    assert "removed" in text
    text = speed_export_message(SpeedExportResult(__import__("pathlib").Path("m"), "Fast", (PATH,), 2), False)
    assert "experimental" in text and PATH in text


def test_the_tab_opens_on_a_loading_page_and_fills_when_the_sets_are_read(qt_app):
    retried = []
    dialog = SpeedPrefabsWorkspace((), load_set=lambda path: _chart(path), plan=lambda *args: (),
                                   prefab_search=lambda category: None, retry_load=lambda: retried.append(True))
    dialog.show_loading("Indexing the game's action charts and clips")
    assert dialog.loading and "Indexing" in dialog.loading_detail.text()
    assert not dialog.prefab_search_button.isEnabled()  # the search needs the file index
    dialog.open_set(PATH)  # remembered until the sets are read
    dialog.set_characters((SpeedCharacter("Kliff", (SpeedSet(SECOND, "Dagger"), SpeedSet(PATH, "Sword"))),))
    assert not dialog.loading and dialog.character_combo.count() == 1
    assert dialog.set_list.currentItem().text() == "Sword" and dialog.prefab_search_button.isEnabled()
    dialog.show_load_error("No character action charts were found in the game archives.")
    assert dialog.load_failed and "No character" in dialog.loading_detail.text()
    dialog.retry_button.click()
    assert retried == [True] and dialog.loading and not dialog.load_failed


def test_opening_speed_tuning_shows_the_tab_and_reads_the_charts_once(qt_app):
    from PySide6.QtWidgets import QWidget

    from cdmw.ui.archive_browser.game_table_actions import ArchiveGameTableActionsMixin
    from cdmw.ui.archive_browser.speed_tuning_actions import ArchiveSpeedTuningActionsMixin, PreparedSpeedTuning

    tasks, activated = [], []

    class Browser(ArchiveSpeedTuningActionsMixin, ArchiveGameTableActionsMixin, QWidget):
        def __init__(self, root="C:/game"):
            super().__init__()
            self.root = root
            self.shell = SimpleNamespace(
                set_status_message=lambda *args, **kwargs: None,
                _activate_tool_key=activated.append,
                _background_task_active=lambda: bool(tasks),
                _run_utility_task_when_idle=lambda **kwargs: tasks.append(kwargs))

        def _action_chart_root(self):
            return self.root

        def _game_table_root(self):
            return self.root

        def _open_action_chart_editor(self, path):
            pass

    browser = Browser()
    workspace = browser.create_speed_workspace()
    browser.shell.speed_prefabs_tab = workspace
    assert workspace.loading and len(tasks) == 1
    browser._open_speed_tuning(PATH)
    assert activated == ["speed_prefabs"] and len(tasks) == 1  # still reading: no second read
    characters = (SpeedCharacter("Kliff", (SpeedSet(PATH, "Sword"),)),)
    tasks[0]["on_complete"](PreparedSpeedTuning(SimpleNamespace(), characters))
    assert not workspace.loading and workspace.set_list.currentItem().text() == "Sword"
    browser._open_speed_game_table("gimmickinfo")
    assert workspace.current_page() == "tables" and workspace.table_buttons["gimmickinfo"].isChecked()
    assert tasks[-1]["status_message"] == "Reading the gimmickinfo table..."

    failing = Browser()
    other = failing.create_speed_workspace()
    tasks[-1]["on_error"]("The archives are not open.")
    assert other.load_failed and "not open" in other.loading_detail.text()
    failing.shell.speed_prefabs_tab = other
    failing._open_speed_tuning()  # opening again after a failure reads again
    assert not other.load_failed

    empty = Browser(root="")
    assert empty.create_speed_workspace().load_failed
