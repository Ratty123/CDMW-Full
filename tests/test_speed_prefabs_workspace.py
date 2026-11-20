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
    assert dialog.move_table.horizontalHeader().sectionSize(4) == 96
    assert not dialog.kind_sliders["jump"].isEnabled() and dialog.kind_sliders["attack"].isEnabled()
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


def _prefab_rows(*names):
    return [{"path": f"object/prefab/{name}.prefab", "category_label": "Moving and wind-driven objects",
             "members": ["VelocityComponent", "WindComponent"]} for name in names]


def test_prefab_list_columns_share_the_width_and_never_scroll_sideways(qt_app):
    from PySide6.QtCore import Qt

    dialog, _calls = _dialog()
    dialog.resize(1100, 700)
    dialog.show()
    dialog.show_page("prefabs")
    dialog.show_prefab_results(_prefab_rows("a_very_long_prefab_file_name_for_a_wind_driven_object_0001", "crate"))
    qt_app.processEvents()
    table = dialog.prefab_table
    header = table.horizontalHeader()
    assert table.horizontalScrollBarPolicy() == Qt.ScrollBarPolicy.ScrollBarAlwaysOff
    assert sum(header.sectionSize(column) for column in range(3)) <= table.viewport().width()
    assert header.sectionSize(0) >= header.sectionSize(2)  # the name gets the room before the speed values
    dialog.resize(760, 700)
    qt_app.processEvents()
    assert sum(header.sectionSize(column) for column in range(3)) <= table.viewport().width()
    dialog.close()


def test_picking_another_prefab_asks_before_dropping_unsaved_changes(qt_app):
    from PySide6.QtWidgets import QLabel

    answers, asked = [False], []

    class Inspector(QLabel):
        unsaved = True

        def has_unsaved_changes(self):
            return self.unsaved

    def confirm(name):
        asked.append(name)
        return answers[-1]

    dialog, calls = _dialog(confirm_discard=confirm)
    dialog._open_prefab = lambda path: (calls.prefabs.append(path),
                                        dialog.show_prefab_inspector(path, Inspector(path)))
    dialog.show_prefab_results(_prefab_rows("first", "second"))
    dialog.prefab_table.selectRow(0)
    assert calls.prefabs == ["object/prefab/first.prefab"] and not asked
    dialog.prefab_table.selectRow(1)  # the answer is no: the first prefab stays open and selected
    assert asked == ["first.prefab"] and calls.prefabs == ["object/prefab/first.prefab"]
    assert dialog.selected_prefab() == "object/prefab/first.prefab" and dialog.state()["prefab_unsaved_changes"]
    assert not dialog.open_prefab("object/prefab/second.prefab", discard=False)  # an AI tool never asks
    answers.append(True)
    dialog.prefab_table.selectRow(1)
    assert calls.prefabs[-1] == "object/prefab/second.prefab" and dialog.selected_prefab().endswith("second.prefab")
    dialog.prefab_inspector.unsaved = False
    dialog.prefab_table.selectRow(0)  # nothing unsaved: no question
    assert len(asked) == 2 and calls.prefabs[-1] == "object/prefab/first.prefab"
    # A new search keeps the open prefab marked when it is listed again.
    dialog.show_prefab_results(_prefab_rows("zero", "first"))
    assert dialog.selected_prefab() == "object/prefab/first.prefab" and len(calls.prefabs) == 3


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
    # The failure is still known, and Search says why it is off, while another page shows.
    dialog.show()
    dialog.show_page("prefabs")
    qt_app.processEvents()
    assert dialog.load_failed and dialog.state()["loading"] is False and "No character" in dialog.state()["load_error"]
    assert "No character" in dialog.prefab_search_button.toolTip()
    dialog.show_page("animation")
    dialog.retry_button.click()
    assert retried == [True] and dialog.loading and not dialog.load_failed
    dialog.close()


def test_a_set_that_is_not_listed_is_reported_not_silently_ignored(qt_app):
    dialog, _calls = _dialog()
    assert dialog.has_set(PATH) and not dialog.has_set("actionchart/bin__/npc/wolf.paac")
    assert dialog.open_set(PATH) and not dialog.open_set("actionchart/bin__/npc/wolf.paac")
    assert dialog.state()["set"] == PATH  # the open set stays


class _Shell:
    """The shell's one-task-at-a-time worker, with the tasks held so a test can finish them."""

    def __init__(self):
        self.tasks, self.activated, self.status = [], [], []
        self.worker_thread = None
        self.other_task = False  # Text Search or a texture export
        self.busy_once_started = False  # a started task keeps the worker until the test frees it

    def set_status_message(self, message, error=False):
        self.status.append((message, error))

    def _activate_tool_key(self, key):
        self.activated.append(key)

    def _background_task_active(self):
        return self.worker_thread is not None or self.other_task

    def _run_utility_task(self, **kwargs):
        assert not self._background_task_active(), "the shell would drop this task"
        self.tasks.append(kwargs)
        if self.busy_once_started:
            self.worker_thread = object()


def _browser(root="C:/game"):
    from PySide6.QtWidgets import QWidget

    from cdmw.ui.archive_browser.game_table_actions import ArchiveGameTableActionsMixin
    from cdmw.ui.archive_browser.speed_tuning_actions import ArchiveSpeedTuningActionsMixin

    class Browser(ArchiveSpeedTuningActionsMixin, ArchiveGameTableActionsMixin, QWidget):
        def __init__(self):
            super().__init__()
            self.root = root
            self.shell = _Shell()

        def _action_chart_root(self):
            return self.root

        def _game_table_root(self):
            return self.root

        def _open_action_chart_editor(self, path):
            pass

    return Browser()


def _wait(qt_app, done, timeout=3.0):
    import time

    deadline = time.monotonic() + timeout
    while not done() and time.monotonic() < deadline:
        qt_app.processEvents()
        time.sleep(0.01)
    assert done()


def test_opening_speed_tuning_shows_the_tab_and_reads_the_charts_once(qt_app):
    from cdmw.ui.archive_browser.speed_tuning_actions import PreparedSpeedTuning

    browser = _browser()
    tasks = browser.shell.tasks
    workspace = browser.create_speed_workspace()
    browser.shell.speed_prefabs_tab = workspace
    assert workspace.loading and len(tasks) == 1
    browser._open_speed_tuning(PATH)
    assert browser.shell.activated == ["speed_prefabs"] and len(tasks) == 1  # still reading: no second read
    characters = (SpeedCharacter("Kliff", (SpeedSet(PATH, "Sword"),)),)
    tasks[0]["on_complete"](PreparedSpeedTuning(SimpleNamespace(), characters))
    assert not workspace.loading and workspace.set_list.currentItem().text() == "Sword"
    browser._open_speed_game_table("gimmickinfo")
    assert workspace.current_page() == "tables" and workspace.table_buttons["gimmickinfo"].isChecked()
    assert tasks[-1]["status_message"] == "Reading the gimmickinfo table..."
    workspace.table_buttons["gimmickinfo"].click()  # a second click while it is read starts no second read
    assert len(tasks) == 2

    browser._open_speed_tuning("actionchart/bin__/npc/wolf.paac")  # not a set: said, not silently ignored
    assert browser.shell.status[-1] == ("Speed & Prefabs lists no set for actionchart/bin__/npc/wolf.paac.", True)

    failing = _browser()
    other = failing.create_speed_workspace()
    failing.shell.tasks[-1]["on_error"]("The archives are not open.")
    assert other.load_failed and "not open" in other.loading_detail.text()
    failing.shell.speed_prefabs_tab = other
    other.show_page("tables")  # the failure is remembered while another page shows
    failing._open_speed_tuning()  # opening again after a failure reads again
    assert not other.load_failed and len(failing.shell.tasks) == 3  # the charts, the first table, the charts again

    empty = _browser(root="")
    assert empty.create_speed_workspace().load_failed


def test_the_game_table_opens_when_the_tab_is_built_later(qt_app):
    browser = _browser()
    created = []
    browser.shell.speed_prefabs_tab = SimpleNamespace(when_created=created.append)
    browser._open_speed_game_table("gimmickinfo")  # the tab does not exist yet: nothing to act on now
    assert browser.shell.activated == ["speed_prefabs"] and len(created) == 1
    workspace = browser.create_speed_workspace()
    created[0](workspace)
    assert workspace.current_page() == "tables" and workspace.table_buttons["gimmickinfo"].isChecked()


def test_page_tasks_wait_for_a_running_task_instead_of_giving_up(qt_app):
    from cdmw.ui.archive_browser.speed_tuning_actions import PreparedSpeedTuning

    browser = _browser()
    shell = browser.shell
    shell.worker_thread = object()  # another task runs, longer than the shell's own five-second wait
    workspace = browser.create_speed_workspace()
    qt_app.processEvents()
    assert workspace.loading and not shell.tasks and "Waiting" in workspace.loading_detail.text()
    shell.worker_thread = None
    _wait(qt_app, lambda: len(shell.tasks) == 1)
    shell.tasks[0]["on_complete"](PreparedSpeedTuning(SimpleNamespace(paths_by_extension={}),
                                                      (SpeedCharacter("Kliff", (SpeedSet(PATH, "Sword"),)),)))

    shell.worker_thread = object()
    workspace.show_page("prefabs")
    workspace.prefab_search_button.click()
    workspace.show_page("tables")  # the first visit reads the AI movement table
    qt_app.processEvents()
    assert len(shell.tasks) == 1 and "Waiting" in workspace.prefab_status_label.text()
    assert "Waiting" in workspace.game_table_panel.editor.message.text()
    shell.busy_once_started = True  # the first of the two runs; the other keeps waiting for its turn
    shell.worker_thread = None
    _wait(qt_app, lambda: len(shell.tasks) == 2)
    import time

    until = time.monotonic() + 0.4  # longer than two polls
    while time.monotonic() < until:
        qt_app.processEvents()
        time.sleep(0.01)
    assert len(shell.tasks) == 2
    shell.worker_thread = None
    _wait(qt_app, lambda: len(shell.tasks) == 3)
    assert {task["status_message"] for task in shell.tasks[1:]} == {"Searching prefabs for speed values...",
                                                                    "Reading the aimovespeedinfo table..."}


def test_a_task_the_shell_would_drop_is_reported_on_the_page(qt_app):
    browser = _browser()
    browser.shell.other_task = True  # Text Search or a texture export: the shell starts nothing and says nothing
    workspace = browser.create_speed_workspace()
    assert workspace.load_failed and "Another background task" in workspace.loading_detail.text()
    browser.shell.other_task = False
    workspace.retry_button.click()
    assert workspace.loading and not workspace.load_failed and len(browser.shell.tasks) == 1


def test_showing_the_tab_reads_again_after_the_game_folder_changes(qt_app):
    from cdmw.ui.archive_browser.speed_tuning_actions import PreparedSpeedTuning

    browser = _browser(root="")
    workspace = browser.create_speed_workspace()
    assert workspace.load_failed and not browser.shell.tasks
    browser.root = "C:/game"  # set in Browse Archives meanwhile
    workspace.show()
    qt_app.processEvents()
    assert workspace.loading and not workspace.load_failed and len(browser.shell.tasks) == 1
    browser.shell.tasks[0]["on_complete"](PreparedSpeedTuning(
        SimpleNamespace(), (SpeedCharacter("Kliff", (SpeedSet(PATH, "Sword"),)),)))
    assert workspace.state()["characters"] == ["Kliff"]
    workspace.hide()
    workspace.show()
    assert len(browser.shell.tasks) == 1  # the same folder: nothing is read again

    browser.root = "D:/other-game"
    workspace.hide()
    workspace.show()
    assert workspace.loading and len(browser.shell.tasks) == 2
    assert workspace.state()["characters"] == [] and workspace.state()["set"] == ""  # the old folder's sets are gone
    workspace.close()


def test_factor_sliders_follow_their_fields_on_a_log_scale(qt_app):
    from PySide6.QtWidgets import QSlider

    dialog, _calls = _dialog()
    dialog.select_set(PATH)
    slider = dialog.kind_sliders["attack"]
    spin = dialog.kind_spins["attack"]
    middle = slider.value()  # 1x
    spin.setValue(2.0)
    up = slider.value() - middle
    spin.setValue(0.5)
    assert abs((middle - slider.value()) - up) <= 1  # 2x and 0.5x sit equally far from 1x
    slider.setValue(slider.maximum())
    assert spin.value() == 5.0 and dialog.factors().kinds == {"attack": 5.0}
    whole = dialog.findChild(QSlider, "speedSetFactorSpinSlider")
    whole.setValue(whole.minimum())
    assert dialog.set_factor_spin.value() == 0.1


def test_a_dragged_slider_gives_round_factors_and_keeps_its_place(qt_app):
    dialog, _calls = _dialog()
    dialog.select_set(PATH)
    slider, spin = dialog.kind_sliders["attack"], dialog.kind_spins["attack"]
    seen = set()
    for position in range(slider.minimum(), slider.maximum() + 1):
        slider.setValue(position)
        assert slider.value() == position  # the handle stays under the pointer
        assert abs(spin.value() * 20 - round(spin.value() * 20)) < 1e-6  # steps of 0.05
        seen.add(round(spin.value(), 2))
    assert {0.1, 0.5, 1.0, 1.5, 2.0, 5.0} <= seen
    spin.setValue(1.23)  # a typed value is kept as typed, and the handle follows it
    assert spin.value() == 1.23 and dialog.factors().kinds == {"attack": 1.23}


def test_factors_can_be_put_into_the_controls_at_once(qt_app):
    dialog, _calls = _dialog()
    dialog.select_set(PATH)
    dialog.apply_factors(SpeedFactors(1.5, {"attack": 2.0}, {ATTACK: 1.0}), linked=False)
    assert dialog.set_factor_spin.value() == 1.5 and dialog.kind_spins["attack"].value() == 2.0
    assert dialog.move_table.cellWidget(0, 4).value() == 1.0 and dialog.move_table.cellWidget(1, 4).value() == 2.0
    assert dialog.factors() == SpeedFactors(1.5, {"attack": 2.0}, {ATTACK: 1.0}) and dialog.linked_paths() == ()
    assert dialog.move_clips()[0] == ATTACK


def test_scrolling_over_a_move_factor_scrolls_the_list_not_the_value(qt_app):
    from PySide6.QtCore import QPoint, QPointF, Qt
    from PySide6.QtGui import QWheelEvent
    from PySide6.QtWidgets import QApplication

    dialog, _calls = _dialog()
    dialog.select_set(PATH)
    spin = dialog.move_table.cellWidget(0, 4)
    event = QWheelEvent(QPointF(5, 5), QPointF(5, 5), QPoint(0, 0), QPoint(0, 120), Qt.MouseButton.NoButton,
                        Qt.KeyboardModifier.NoModifier, Qt.ScrollPhase.NoScrollPhase, False)
    QApplication.sendEvent(spin, event)
    assert spin.value() == 1.0
