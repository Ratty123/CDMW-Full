"""Speed & Prefabs tab (experimental), offscreen, with fake sets."""

from __future__ import annotations

from pathlib import Path
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
    calls = SimpleNamespace(plans=[], exports=[], opened=[], searches=[], prefabs=[], batches=[], mods=[],
                            scaled=[])
    characters = (SpeedCharacter("Kliff", (SpeedSet(PATH, "Sword"), SpeedSet(SECOND, "Dagger"))),
                  SpeedCharacter("Damiane", (SpeedSet(SECOND, "Dagger"),)))

    def plan(path, factors, linked):
        calls.plans.append((path, factors, tuple(linked)))
        return (plan_speed_edits(chart_bytes(), path, SpeedFactors(factors.set, factors.kinds,
                                                                   {k: v for k, v in factors.moves.items()
                                                                    if k in CLIPS},
                                                                   factors.named, factors.named_factor)),)

    options = dict(
        load_set=kwargs.pop("load_set", lambda path: _chart(path)),
        plan=plan,
        linked_of=lambda path: ((LINKED, True), ("actionchart/bin__/other.paac", False)),
        export=lambda path, factors, linked: calls.exports.append((path, factors, tuple(linked))),
        export_sets=lambda paths, factors: calls.batches.append((tuple(paths), factors)),
        open_mod=lambda summary=None: calls.mods.append(summary or "open"),
        close_mod=lambda: calls.mods.append("close"),
        open_chart=calls.opened.append,
        prefab_search=calls.searches.append,
        open_prefab=calls.prefabs.append,
        scale_prefabs=lambda paths, factor, category: calls.scaled.append((tuple(paths), factor, category)),
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


def test_prefab_list_shows_what_each_prefab_holds_and_scales_the_ones_with_values(qt_app):
    dialog, calls = _dialog()
    dialog.show_page("prefabs")
    assert not dialog.prefab_batch_button.isEnabled() and "No listed prefab" in dialog.prefab_batch_button.toolTip()
    dialog.search_prefabs("moving")
    rows = [{"path": "object/prefab/fan.prefab", "category_label": "Moving objects", "members": ["Rotate"],
             "values": 2, "labels": ["Spin speed", "Spin axis speed"], "state": ""},
            {"path": "object/prefab/declares.prefab", "category_label": "Moving objects", "members": ["Rotate"],
             "values": 0, "labels": [], "state": ""},
            {"path": "object/prefab/broken.prefab", "category_label": "Moving objects", "members": ["Rotate"],
             "values": 1, "labels": ["Spin speed"], "state": "partly read"}]
    dialog.show_prefab_results(rows)
    column = [dialog.prefab_table.item(row, 2).text() for row in range(3)]
    assert column == ["2: Spin speed, Spin axis speed", "none reached", "partly read"]
    assert dialog.prefab_status_label.text() == "1 prefab(s) hold speed values; 2 hold none that can be scaled."
    assert dialog.scalable_prefabs() == ("object/prefab/fan.prefab",) and dialog.state()["prefab_values"] == 1
    # At 1x nothing would change, so the button waits for a factor.
    assert not dialog.prefab_batch_button.isEnabled() and "1x" in dialog.prefab_batch_button.toolTip()
    assert dialog.scale_listed_prefabs(0.5)
    assert calls.scaled == [(("object/prefab/fan.prefab",), 0.5, "moving")]
    # While the caller reads the prefabs, neither button can be pressed; the note comes back afterwards.
    dialog.begin_prefab_scaling()
    assert not dialog.prefab_batch_button.isEnabled() and not dialog.prefab_search_button.isEnabled()
    assert dialog.state()["prefab_scaling"] and "Reading" in dialog.prefab_status_label.text()
    dialog.end_prefab_scaling()
    assert dialog.prefab_batch_button.isEnabled() and "hold speed values" in dialog.prefab_status_label.text()
    assert not dialog.scale_listed_prefabs(1000.0)
    # Rows without the new keys (an older caller) still show their members and cannot be scaled.
    dialog.show_prefab_results(_prefab_rows("crate"))
    assert dialog.prefab_status_label.text() == "1 prefab(s) found." and not dialog.prefab_batch_button.isEnabled()


def test_prefab_batch_summary_counts_what_changes_and_what_is_left_out():
    from cdmw.services.prefab_speed_service import NO_VALUE, PARTLY_READ, UNCHANGED, ZERO_VALUES, PrefabScaleOutcome
    from cdmw.ui.archive_browser.speed_tuning_actions import prefab_batch_summary

    outcomes = (
        PrefabScaleOutcome("a.prefab", b"s", b"p", 3, (1.0, 4.0), (0.5, 2.0), ""),
        PrefabScaleOutcome("b.prefab", b"s", b"p", 5, (2.0, 2.0), (1.0, 1.0), ""),
        PrefabScaleOutcome("c.prefab", b"s", None, 0, None, None, PARTLY_READ),
        PrefabScaleOutcome("d.prefab", b"s", None, 0, None, None, NO_VALUE),
        PrefabScaleOutcome("e.prefab", b"s", None, 1, (0.0, 0.0), (0.0, 0.0), ZERO_VALUES),
        PrefabScaleOutcome("f.prefab", b"s", None, 1, (2.0, 2.0), (2.0, 2.0), UNCHANGED),
    )
    text, details, count = prefab_batch_summary(outcomes, 0.5, ("gone.prefab",))
    assert count == 2
    assert text.splitlines()[0] == "Scale 8 value(s) in 2 prefab(s) by 0.5x and save them as one item package?"
    assert ("Left out: partly read (1), no speed value reached (1), the values are 0 (1), "
            "no value changed (1), not in the game archives (1).") in text
    assert "not been tested in game" in text
    assert "a.prefab: 3 value(s), 1 to 4 -> 0.5 to 2" in details and "b.prefab: 5 value(s), 2 -> 1" in details
    assert "c.prefab: left out, partly read" in details and "gone.prefab: left out, not in the game archives" in details
    text, _details, count = prefab_batch_summary(outcomes[2:], 0.5)
    assert count == 0 and text.startswith("None of the listed prefabs")
    many = tuple(PrefabScaleOutcome(f"{n}.prefab", b"s", b"p", 1, (1.0, 1.0), (2.0, 2.0), "") for n in range(129))
    text, _details, count = prefab_batch_summary(many, 2.0)
    assert count == 129 and text.startswith("A package holds at most 128 prefabs")


def _prefab_rows(*names):
    return [{"path": f"object/prefab/{name}.prefab", "category_label": "Moving and wind-driven objects",
             "members": ["VelocityComponent", "WindComponent"]} for name in names]


def test_prefab_list_columns_share_the_width_and_never_scroll_sideways(qt_app):
    from PySide6.QtCore import Qt
    from PySide6.QtWidgets import QHeaderView

    dialog, _calls = _dialog()
    dialog.resize(1100, 700)
    dialog.show()
    dialog.show_page("prefabs")
    dialog.show_prefab_results(_prefab_rows("a_very_long_prefab_file_name_for_a_wind_driven_object_0001", "crate"))
    qt_app.processEvents()
    table = dialog.prefab_table
    header = table.horizontalHeader()
    assert table.horizontalScrollBarPolicy() == Qt.ScrollBarPolicy.ScrollBarAsNeeded
    assert table.textElideMode() == Qt.TextElideMode.ElideNone
    assert all(header.sectionResizeMode(column) == QHeaderView.ResizeMode.Interactive for column in range(3))
    assert header.sectionSize(0) >= header.sectionSize(2)  # the name gets the room before the speed values
    assert sum(header.sectionSize(column) for column in range(3)) >= table.viewport().width()
    dialog.resize(760, 700)
    qt_app.processEvents()
    assert header.sectionSize(0) >= header.sectionSize(2)
    header.resizeSection(0, 260)
    assert header.sectionSize(0) == 260
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
        self.settings_file_path = Path("C:/settings/settings.json")

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


# --- Moves named, all listed sets, starting points and the open mod -------------------------


def test_moves_named_pick_moves_by_name_and_show_in_the_factor_column(qt_app):
    dialog, calls = _dialog()
    dialog.select_set(PATH)
    assert dialog.named_label.text() == "Moves named:"
    # The factor has its own label and is greyed until a name is typed: alone it changes nothing.
    assert dialog.named_factor_label.text() == "Factor for these moves:"
    assert not dialog.named_slider.isEnabled() and not dialog.named_spin.isEnabled()
    dialog.kind_spins["attack"].setValue(2.0)
    dialog.named_edit.setText("Attack_01, idle")
    assert dialog.named_slider.isEnabled() and dialog.named_spin.isEnabled() and dialog.named_factor_label.isEnabled()
    dialog.named_spin.setValue(0.5)
    assert dialog.named_label.text() == "Moves named (2):"
    values = [dialog.move_table.cellWidget(row, 4).value() for row in range(3)]
    assert values == [2.0, 0.5, 0.5]  # the first attack keeps its kind's factor
    factors = dialog.factors()
    assert factors.named == ("attack_01", "idle") and factors.named_factor == 0.5 and factors.moves == {}
    dialog.move_table.cellWidget(1, 4).setValue(0.5)  # typing what the move gets anyway is no factor of its own
    assert dialog.factors().moves == {}
    dialog.move_table.cellWidget(1, 4).setValue(3.0)
    assert dialog.factors().moves == {"1_pc/1_phm/cd_phm_sword_attack_01.paa": 3.0}
    dialog.refresh_review()
    assert "Moves named" in dialog.review_text.toPlainText() or calls.plans[-1][1].named == ("attack_01", "idle")

    dialog.named_edit.setText("at")  # too short: said in the Review, as other factors that cannot be applied
    dialog.refresh_review()
    assert "cannot be applied" in dialog.review_text.toPlainText()

    again = SpeedFactors(kinds={"attack": 1.5}, named=("idle",), named_factor=2.0)
    dialog.apply_factors(again)
    assert dialog.factors() == again and dialog.named_edit.text() == "idle"
    dialog.reset_factors()
    assert dialog.named_edit.text() == "" and dialog.named_spin.value() == 1.0 and dialog.factors().is_identity
    assert not dialog.named_slider.isEnabled() and not dialog.named_spin.isEnabled()


def test_all_listed_sets_keeps_the_factors_and_exports_what_the_list_shows(qt_app):
    dialog, calls = _dialog()
    dialog.select_set(PATH)
    assert dialog.scope() == "set" and dialog.scope_combo.itemText(1) == "All 2 listed sets of Kliff"
    dialog.set_factor_spin.setValue(1.5)
    dialog.kind_spins["attack"].setValue(2.0)
    assert dialog.set_scope("listed") and dialog.scope() == "listed"
    assert dialog.set_factor_spin.value() == 1.0 and not dialog.set_factor_spin.isEnabled()
    assert dialog.whole_note_label.text() == "Works on one set at a time."
    assert dialog.kind_spins["jump"].isEnabled()  # another listed set may have jumps
    assert not dialog.linked_checkbox.isEnabled() and dialog.linked_paths() == ()
    assert dialog.select_set(SECOND)
    assert dialog.kind_spins["attack"].value() == 2.0  # picking another set keeps the factors
    dialog.refresh_review()
    assert dialog.review_text.toPlainText().startswith("These factors go to all 2 listed sets of Kliff.")
    state = dialog.state()
    assert state["scope"] == "listed" and state["scope_sets"] == [PATH, SECOND]

    dialog.set_filter_edit.setText("dagger")
    assert dialog.scope_combo.itemText(1) == "All 1 listed sets of Kliff"
    dialog.export_button.click()
    assert calls.batches == [((SECOND,), dialog.factors())] and not calls.exports
    dialog.set_filter_edit.setText("no such set")
    assert not dialog.export_button.isEnabled() and dialog.export_button.toolTip() == "No set is listed."
    dialog.set_filter_edit.setText("")

    dialog.show_batch_progress(6, 23, SECOND)
    assert dialog.review_text.toPlainText() == "Checking set 7 of 23…" and not dialog.export_button.isEnabled()
    dialog.end_batch()
    assert dialog.export_button.isEnabled() and "listed sets" in dialog.review_text.toPlainText()

    assert dialog.set_scope("set")
    assert dialog.set_factor_spin.isEnabled() and not dialog.kind_spins["jump"].isEnabled()
    assert dialog.linked_checkbox.isEnabled() and dialog.linked_checkbox.isChecked()
    assert dialog.whole_note_label.text().startswith("Applies on top")

    plain, _calls = _dialog(export_sets=None)  # without an owner that can write many sets, one set at a time
    assert not plain.scope_combo.isEnabled() and not plain.set_scope("listed")


def test_all_listed_sets_drops_the_open_sets_move_factors(qt_app):
    dialog, calls = _dialog()
    dialog.select_set(PATH)
    dialog.kind_spins["attack"].setValue(2.0)
    dialog.move_table.cellWidget(2, 4).setValue(0.5)
    assert dialog.factors().moves == {IDLE: 0.5}
    assert dialog.set_scope("listed")
    assert dialog.factors().moves == {} and dialog.factors().kinds == {"attack": 2.0}
    assert dialog.move_table.cellWidget(2, 4).value() == 1.0
    dialog.export_button.click()
    assert calls.batches == [((PATH, SECOND), SpeedFactors(kinds={"attack": 2.0}))]
    # A move factor typed while all sets are listed stays only while a shown set has that move.
    dialog.move_table.cellWidget(2, 4).setValue(0.5)
    assert dialog.factors().moves == {IDLE: 0.5}
    second = SpeedChart(SECOND, "Dagger", 1.0, (SpeedMove(ATTACK, "cd_phm_sword_attack_00", "attack", 1, 1, 1.5),),
                        SpeedFactors())
    dialog._load_set = lambda path: second if path == SECOND else _chart(path)
    assert dialog.select_set(SECOND) and dialog.move_table.rowCount() == 1
    assert dialog.factors().moves == {}


def test_all_listed_sets_at_one_still_exports_while_the_open_mod_holds_one(qt_app):
    dialog, calls = _dialog()
    dialog.select_set(PATH)
    assert dialog.set_scope("listed")
    assert not dialog.export_button.isEnabled()  # nothing to change and no mod open
    dialog.set_mod("Fast Kliff", {SECOND: "attacks x2"}, folder="C:/mods/Fast Kliff")
    assert dialog.export_button.isEnabled() and dialog.factors().is_identity
    dialog.export_button.click()
    assert calls.batches == [((PATH, SECOND), SpeedFactors())]
    dialog.set_filter_edit.setText("sword")  # the mod holds no listed set now
    assert not dialog.export_button.isEnabled()
    dialog.set_filter_edit.setText("")
    assert dialog.export_button.isEnabled()
    dialog.set_mod("", {}, reload=False)  # after the export took them out, the mod is closed
    assert not dialog.export_button.isEnabled()


def test_start_from_puts_a_starting_point_into_the_sliders(qt_app):
    dialog, calls = _dialog()
    dialog.select_set(PATH)
    dialog.kind_spins["idle"].setValue(0.8)
    combo = dialog.start_combo
    assert combo.itemText(0) == "Start from…" and combo.findData("close_mod") < 0
    position = combo.findData("preset:faster_attacks")
    combo.setCurrentIndex(position)
    dialog._start_chosen(position)
    assert combo.currentIndex() == 0  # it shows its caption again
    assert dialog.factors().kinds == {"attack": 1.25, "idle": 0.8}  # the other factors stay
    assert dialog.choose_start("preset:slow_finishers")
    assert dialog.factors().named == ("att_finish_link", "execute_lk", "takedown") and dialog.named_spin.value() == 0.5
    assert dialog.choose_start("open_mod") and calls.mods == ["open"]
    assert not dialog.choose_start("close_mod")  # no mod is open
    assert [item["key"] for item in dialog.state()["presets"]][0] == "faster_attacks"


def test_an_open_mod_marks_its_sets_and_reads_the_open_set_again(qt_app):
    loads = []

    def load(path):
        loads.append(path)
        return _chart(path, SpeedFactors(kinds={"attack": 2.0}) if len(loads) > 1 else SpeedFactors(),
                      mod="Fast Kliff" if len(loads) > 1 else "")

    dialog, calls = _dialog(load_set=load)
    dialog.select_set(PATH)
    assert loads == [PATH] and not dialog.mod_label.isVisibleTo(dialog)
    dialog.set_mod("Fast Kliff", {PATH: "attacks x2"}, folder="C:/mods/Fast Kliff", derived=True)
    assert loads == [PATH, PATH] and dialog.kind_spins["attack"].value() == 2.0
    assert dialog.mod_label.text().startswith("Mod: Fast Kliff, 1 chart(s)") and "rounded" in dialog.mod_label.text()
    assert dialog.set_list.item(0).font().bold() and not dialog.set_list.item(1).font().bold()
    assert "In the mod Fast Kliff: attacks x2" in dialog.set_list.item(0).toolTip()
    state = dialog.state()
    assert state["mod_title"] == "Fast Kliff" and state["mod_folder"] == "C:/mods/Fast Kliff"
    assert state["mod_charts"] == [PATH]
    assert dialog.start_combo.itemText(dialog.start_combo.findData("close_mod")) == "Close the mod Fast Kliff"
    assert dialog.choose_start("close_mod") and calls.mods == ["close"]
    dialog.set_mod("", {}, reload=False)  # after an export: the marks change, the controls stay
    assert len(loads) == 2 and not dialog.set_list.item(0).font().bold() and dialog.state()["mod_title"] == ""
    assert dialog.start_combo.findData("close_mod") < 0


def test_the_question_before_a_many_set_export_counts_every_outcome():
    from cdmw.services.animation_speed_service import SpeedProfileOutcome, SpeedProfilePlan
    from cdmw.ui.archive_browser.speed_tuning_actions import profile_summary, speed_export_message
    from cdmw.services.animation_speed_service import SpeedExportResult

    changed = plan_speed_edits(chart_bytes(), PATH, SpeedFactors(kinds={"attack": 2.0}))
    plan = SpeedProfilePlan((changed,), (SECOND,), ((LINKED, "It is not in the game archives."),))
    outcome = SpeedProfileOutcome((PATH,), (SECOND,), plan.left_out, ())
    text, details = profile_summary(plan, outcome, ((PATH, "Other Mod"),), "Fast Kliff")
    assert text.splitlines() == [
        "1 set(s) change (1 speed values).", "No change in 1 set(s).", "Left out: 1.",
        "Already served by another mounted DMM mod: 1.",
        "Taken out of the mod because these factors change nothing there: 1.", "", "Write the mod Fast Kliff?"]
    assert f"{PATH}: 1 value(s) (Attacks 1)" in details and f"{SECOND}: taken out of the mod" in details
    assert f"{LINKED}: left out. It is not in the game archives." in details

    nothing, _details = profile_summary(SpeedProfilePlan((), (PATH,), ()), SpeedProfileOutcome((), (), (), ()), (), "X")
    assert nothing.startswith("These factors change no speed value") and "Write the mod" not in nothing

    message = speed_export_message(SpeedExportResult(None, "Fast", (), 0, left_out=plan.left_out), False)
    assert "Nothing was written" in message and "Left out:" in message


def _ready_browser(qt_app, monkeypatch, tmp_path, *paths):
    """A browser whose tab holds ``paths`` as Kliff's sets, with the export dialog answered."""

    from cdmw.ui.archive_browser import speed_tuning_actions as actions

    browser = _browser()
    workspace = browser.create_speed_workspace()
    browser.shell.speed_prefabs_tab = workspace
    entries = {path: SimpleNamespace(path=path) for path in paths}
    index = SimpleNamespace(entry_for_path=lambda path: entries.get(path), root=None)
    monkeypatch.setattr(actions, "_read", lambda entry: chart_bytes())
    monkeypatch.setattr(actions, "linked_sets", lambda *args, **kwargs: ())
    browser.shell.tasks[0]["on_complete"](actions.PreparedSpeedTuning(
        index, (SpeedCharacter("Kliff", tuple(SpeedSet(path, path.rsplit("/", 1)[-1]) for path in paths)),)))
    plan = actions._Plan(tmp_path, False, "Fast Kliff", "", "1.0", "")
    browser._ask_speed_export = lambda dialog, holder: holder.__setitem__("plan", plan) or plan
    boxes = []
    from PySide6.QtWidgets import QMessageBox

    monkeypatch.setattr(QMessageBox, "exec", lambda self: boxes.append(self.text()) or QMessageBox.StandardButton.Yes)
    monkeypatch.setattr(QMessageBox, "warning", lambda *args: boxes.append("warning: " + str(args[2])))
    monkeypatch.setattr(QMessageBox, "information", lambda *args: boxes.append("done: " + str(args[2])))
    return browser, workspace, boxes


def test_exporting_all_listed_sets_checks_them_asks_and_writes_once(qt_app, monkeypatch, tmp_path):
    from cdmw.services.animation_speed_service import SpeedExportResult
    from cdmw.ui.archive_browser import speed_tuning_actions as actions

    browser, workspace, boxes = _ready_browser(qt_app, monkeypatch, tmp_path, PATH, SECOND)
    tasks = browser.shell.tasks
    workspace.kind_spins["attack"].setValue(2.0)
    workspace.set_scope("listed")
    workspace.export_button.click()
    assert tasks[-1]["status_message"] == "Checking the listed sets..." and tasks[-1]["task_accepts_cancel"]
    assert workspace.state()["checking_sets"] and not workspace.export_button.isEnabled()
    checked = tasks[-1]["task"](lambda _text: None, None)
    assert [item.path for item in checked.plan.plans] == [PATH, SECOND]
    count = len(tasks)
    tasks[-1]["on_complete"](checked)
    assert boxes[-1].startswith("2 set(s) change") and "Write the mod Fast Kliff?" in boxes[-1]
    assert len(tasks) == count + 1 and tasks[-1]["status_message"] == "Writing the Speed Tuning mod Fast Kliff..."
    written = []
    monkeypatch.setattr(actions, "export_speed_profile",
                        lambda *args, **kwargs: written.append((args[2], kwargs["plan"])) or SpeedExportResult(
                            None, "Fast Kliff", (), 0))
    result = tasks[-1]["task"](lambda _text: None, None)
    assert written == [((PATH, SECOND), checked.plan)]  # the plan the user said yes to, not a second check
    tasks[-1]["on_complete"](result)
    assert boxes[-1].startswith("done: Nothing was written") and not workspace.state()["checking_sets"]

    workspace.export_button.click()  # a failure is shown, and the page is usable again
    tasks[-1]["on_error"]("Checking the sets was cancelled.")
    assert boxes[-1] == "warning: Checking the sets was cancelled." and workspace.export_button.isEnabled()


def test_a_one_set_export_waits_its_turn_and_reports_a_failure(qt_app, monkeypatch, tmp_path):
    browser, workspace, boxes = _ready_browser(qt_app, monkeypatch, tmp_path, PATH)
    shell = browser.shell
    workspace.kind_spins["attack"].setValue(2.0)
    shell.worker_thread = object()  # another task runs
    count = len(shell.tasks)
    workspace.export_button.click()
    qt_app.processEvents()
    assert len(shell.tasks) == count
    shell.worker_thread = None
    _wait(qt_app, lambda: len(shell.tasks) == count + 1)
    assert shell.tasks[-1]["status_message"] == "Writing the Speed Tuning mod Fast Kliff..."
    shell.tasks[-1]["on_error"]("The disk is full.")
    assert boxes[-1] == "warning: The disk is full." and shell.status[-1] == (
        "Speed Tuning export failed: The disk is full.", True)


def test_a_speed_mod_is_read_on_a_worker_and_closed_again(qt_app, monkeypatch, tmp_path):
    from cdmw.services.animation_speed_service import SpeedModSummary

    browser, workspace, boxes = _ready_browser(qt_app, monkeypatch, tmp_path, PATH)
    shell = browser.shell
    holder = browser._speed_holder
    browser._open_speed_mod(workspace, holder, tmp_path / "Fast Kliff")
    assert shell.tasks[-1]["status_message"] == "Reading the speed mod..."
    shell.tasks[-1]["on_complete"](SpeedModSummary(tmp_path / "Fast Kliff", "Fast Kliff", "Me", "1.2",
                                                    {PATH: "attacks x2"}, {PATH: None}, None, False))
    assert holder["mod_folder"] == tmp_path / "Fast Kliff" and holder["plan"].title == "Fast Kliff"
    assert workspace.state()["mod_title"] == "Fast Kliff" and workspace.set_list.item(0).font().bold()
    assert workspace.choose_start("close_mod")
    assert "mod_folder" not in holder and workspace.state()["mod_title"] == ""
    browser._open_speed_mod(workspace, holder, tmp_path / "missing")
    shell.tasks[-1]["on_error"]("missing is not an action chart mod CDMW wrote.")
    assert boxes[-1] == "warning: missing is not an action chart mod CDMW wrote."


def test_scaling_the_listed_prefabs_reads_them_asks_and_writes_one_package(qt_app, monkeypatch, tmp_path):
    from PySide6.QtWidgets import QFileDialog

    from cdmw.services import independent_prefab_authoring as authoring
    from cdmw.services.prefab_speed_service import speed_values
    from cdmw.core.prefab_binary import decode_prefab_binary
    from cdmw.ui.archive_browser import speed_tuning_actions as actions
    from tests.prefab_speed_builder import build_speed_prefab

    browser, workspace, boxes = _ready_browser(qt_app, monkeypatch, tmp_path, PATH)
    shell = browser.shell
    fan = build_speed_prefab([("WindComponent", [("_windSpeedAccelerationScale", "float", 2.0)])])
    still = build_speed_prefab([("WindComponent", [("_windSpeedAccelerationScale", "float", 0.0)])])
    files = {"object/prefab/fan.prefab": fan, "object/prefab/still.prefab": still}
    index = SimpleNamespace(entry_for_path=lambda path: SimpleNamespace(path=path) if path in files else None)
    monkeypatch.setattr(actions, "_read", lambda entry: files[entry.path])
    asked = []
    monkeypatch.setattr(QFileDialog, "getSaveFileName",
                        lambda *args: asked.append(args[2]) or (str(tmp_path / "calm wind"), ""))
    workspace.show_prefab_results([{"path": path, "values": 1, "labels": ["Wind speed-up"], "state": ""}
                                   for path in (*files, "object/prefab/gone.prefab")])
    seen = {}
    monkeypatch.setattr(authoring, "prepare_prefab_packages",
                        lambda root, edits, **kw: seen.update(root=root, edits=edits, title=kw["title"])
                        or SimpleNamespace(lines=("Target prefab: object/prefab/fan.prefab",)))
    monkeypatch.setattr(authoring, "write_prefab_package",
                        lambda review, destination, **kw: seen.update(destination=destination))
    browser._scale_speed_prefabs(workspace, index, workspace.scalable_prefabs(), 0.5, "moving")
    assert shell.tasks[-1]["status_message"] == "Scaling the listed prefabs..." and shell.tasks[-1]["task_accepts_cancel"]
    assert workspace.state()["prefab_scaling"]
    scaled = shell.tasks[-1]["task"](lambda _text: None, None)
    assert [item.reason for item in scaled.outcomes] == ["", "the values are 0"] and scaled.missing == (
        "object/prefab/gone.prefab",)
    count = len(shell.tasks)
    shell.tasks[-1]["on_complete"](scaled)
    assert boxes[-1].startswith("Scale 1 value(s) in 1 prefab(s) by 0.5x")
    assert asked[-1].replace("\\", "/").endswith("prefab_packages/moving_speed_0_5x.cdmw")
    assert len(shell.tasks) == count + 1 and shell.tasks[-1]["status_message"] == "Building the prefab item package..."
    result = shell.tasks[-1]["task"](lambda _text: None, None)
    assert seen["root"] == "C:/game" and seen["title"] == "calm wind" and list(seen["edits"]) == ["object/prefab/fan.prefab"]
    assert seen["destination"] == tmp_path / "calm wind.cdmw"  # the extension is added when it was left off
    source, patched = seen["edits"]["object/prefab/fan.prefab"]
    assert source == fan and speed_values(decode_prefab_binary(patched))[0].value == 1.0
    shell.tasks[-1]["on_complete"](result)
    assert boxes[-1].startswith("done: Wrote prefab item package:") and not workspace.state()["prefab_scaling"]

    # Nothing to write: the box only informs, and no file is asked for.
    asked.clear()
    browser._scale_speed_prefabs(workspace, index, ("object/prefab/still.prefab",), 0.5, "")
    shell.tasks[-1]["on_complete"](shell.tasks[-1]["task"](lambda _text: None, None))
    assert boxes[-1].startswith("None of the listed prefabs") and not asked
    assert not workspace.state()["prefab_scaling"]
    # A failure is shown and the page is given back.
    browser._scale_speed_prefabs(workspace, index, ("object/prefab/fan.prefab",), 0.5, "")
    shell.tasks[-1]["on_error"]("Scaling the prefabs was cancelled.")
    assert boxes[-1] == "warning: Scaling the prefabs was cancelled." and not workspace.state()["prefab_scaling"]


def test_category_rows_never_overlap_moves_named_row_for_one_to_eight_categories(qt_app):
    from PySide6.QtCore import QPoint

    from cdmw.services.animation_speed_service import KIND_LABELS

    all_kinds = tuple(KIND_LABELS)
    sets = tuple(SpeedSet(f"actionchart/set_{count}.paac", f"Set {count}") for count in (1, 2, 4, 6, 7, 8))
    charts = {
        item.path: SpeedChart(
            item.path,
            item.label,
            1.0,
            tuple(
                SpeedMove(f"1_pc/1_phm/clip_{kind}.paa", f"clip_{kind}", kind, 1, 1, 1.0)
                for kind in all_kinds[: int(item.label.split()[-1])]
            ),
            SpeedFactors(),
            "",
            "",
        )
        for item in sets
    }
    dialog = SpeedPrefabsWorkspace(
        (SpeedCharacter("Kliff", sets),),
        load_set=lambda path: charts[path],
        plan=lambda *_args: (),
    )
    try:
        dialog.resize(1220, 740)
        dialog.show()
        qt_app.processEvents()
        card = dialog._factors_card
        for item in sets:
            assert dialog.select_set(item.path)
            for show_unused in (False, True, False):
                dialog.show_unused_kinds_checkbox.setChecked(show_unused)
                qt_app.processEvents()
                visible_rows = [row for row in dialog.kind_rows.values() if row.isVisible()]
                assert visible_rows
                named_top = dialog.named_edit.mapTo(card, QPoint(0, 0)).y()
                for row in visible_rows:
                    row_rect = row.rect()
                    top_left = row.mapTo(card, row_rect.topLeft())
                    row_bottom = top_left.y() + row_rect.height() - 1
                    assert row_bottom < named_top, (
                        f"{item.label} (show_unused={show_unused}): category row bottom {row_bottom} "
                        f"overlaps Moves named top {named_top}"
                    )
                for index, first in enumerate(visible_rows):
                    first_rect = first.geometry()
                    for second in visible_rows[index + 1 :]:
                        assert not first_rect.intersects(second.geometry())
    finally:
        dialog.close()
        dialog.deleteLater()
        qt_app.processEvents()


def test_speed_net_labels_and_moves_named_alignment_match_category_columns(qt_app):
    from PySide6.QtCore import QPoint, Qt

    chart = SpeedChart(
        "actionchart/kliff.paac",
        "Rapier",
        1.0,
        (
            SpeedMove("1_pc/1_phm/att_01.paa", "att_01", "attack", 1, 1, 1.0),
            SpeedMove("1_pc/1_phm/jump_01.paa", "jump_01", "jump", 1, 1, 1.0),
        ),
        SpeedFactors(),
        "",
        "",
    )
    dialog = SpeedPrefabsWorkspace(
        (SpeedCharacter("Kliff", (SpeedSet(chart.path, chart.label),)),),
        load_set=lambda _path: chart,
        plan=lambda *_args: (),
    )
    try:
        dialog.resize(1280, 760)
        dialog.show()
        qt_app.processEvents()
        assert dialog.select_set(chart.path)
        qt_app.processEvents()
        assert all(label.text() == "" for label in dialog.kind_net_labels.values())
        assert dialog.named_net_label.text() == ""
        for label in (*dialog.kind_net_labels.values(), dialog.named_net_label):
            assert label.alignment() & Qt.AlignmentFlag.AlignLeft

        dialog.set_factor_spin.setValue(2.0)
        qt_app.processEvents()
        assert dialog.kind_net_labels["attack"].text() == "Net 2x"
        assert dialog.named_net_label.text() == ""

        dialog.named_edit.setText("att_01")
        dialog.named_spin.setValue(1.5)
        qt_app.processEvents()
        assert dialog.named_net_label.text() == "Net 3x"

        card = dialog._factors_card
        jump_label_x = dialog.kind_labels["jump"].mapTo(card, QPoint(0, 0)).x()
        named_factor_x = dialog.named_factor_label.mapTo(card, QPoint(0, 0)).x()
        jump_slider_x = dialog.kind_sliders["jump"].mapTo(card, QPoint(0, 0)).x()
        named_slider_x = dialog.named_slider.mapTo(card, QPoint(0, 0)).x()
        jump_spin_x = dialog.kind_spins["jump"].mapTo(card, QPoint(0, 0)).x()
        named_spin_x = dialog.named_spin.mapTo(card, QPoint(0, 0)).x()
        assert abs(named_factor_x - jump_label_x) <= 2
        assert abs(named_slider_x - jump_slider_x) <= 2
        assert abs(named_spin_x - jump_spin_x) <= 2
    finally:
        dialog.close()
        dialog.deleteLater()
        qt_app.processEvents()
