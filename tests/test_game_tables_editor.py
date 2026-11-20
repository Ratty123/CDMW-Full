"""The game table editor: loading a table, choosing values, and the draft Create New Item plans from."""
import os
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')

import pytest
from PySide6.QtWidgets import QApplication

from cdmw.core.static_table_records import TableFieldEdit
from cdmw.ui.new_item.controller import NewItemStudioController
from cdmw.ui.new_item.game_tables_editor import parse_value
from cdmw.ui.new_item.panels_stats import StatsPanel
from cdmw.ui.new_item.rust_ui_document import PresentationDocument
from cdmw.ui.new_item.state import NewItemDraft
from tests.test_game_table_edits import layers
from tests.test_independent_items import setup_game


@pytest.fixture
def app():
    return QApplication.instance() or QApplication([])


@pytest.fixture
def panel(tmp_path, app, monkeypatch):
    import cdmw.services.new_item_table_edits as table_edits

    monkeypatch.setattr(table_edits, 'snapshot_layers', lambda _snapshot, table, data=None: layers())
    service, snapshot, _ = setup_game(tmp_path)
    controller = NewItemStudioController(service=service, synchronous=True)
    controller.snapshot = snapshot
    controller.draft = NewItemDraft(template_key=1001295, internal_name='Tables', display_names={'eng': 'Tables'})
    stats = StatsPanel(controller)
    stats.rebuild()
    yield controller, stats
    stats.deleteLater()


def select(table, text):
    for position in range(table.rowCount()):
        if table.item(position, 1 if table.columnCount() == 3 else 0).text() == text:
            table.selectRow(position)
            return
    raise AssertionError(f'{text!r} is not listed')


def test_values_chosen_on_the_game_tables_page_reach_the_spec(panel):
    controller, stats = panel
    editor = stats.game_tables
    stats.open_game_tables.click()
    assert stats.views.currentWidget() is stats._game_tables_page

    editor.table.setCurrentIndex(editor.table.findData('inventory'))
    editor.load.click()
    assert editor.rows.rowCount() == 4 and 'exist only in the DLC copy' in editor.message.text()

    select(editor.rows, 'Character')
    select(editor.values, 'Maximum slots')
    assert editor.value.text() == '240' and editor.set.isEnabled()
    editor.value.setText('480')
    editor.set.click()
    assert controller.draft.table_edits == (TableFieldEdit('inventory', 2, '_maxSlotCount', 480),)
    assert controller.current_spec().table_edits == controller.draft.table_edits
    assert stats.game_tables_summary.text().startswith('1 other game table value')
    assert editor.values.item(1, 2).text() == '480'

    editor.value.setText('70000')
    editor.set.click()
    assert 'Enter a value from' in editor.message.text()
    assert controller.draft.table_edits[0].value == 480

    select(editor.rows, 'DlcHouse')
    select(editor.values, 'Maximum slots')
    assert not editor.set.isEnabled()

    editor.pending.selectRow(0)
    editor.remove.click()
    assert controller.draft.table_edits == ()
    stats.back_to_stats.click()
    assert stats.views.currentWidget() is stats._stats_page


def test_the_draft_refills_the_editor_and_the_page_projects(panel):
    controller, stats = panel
    controller.draft.table_edits = (TableFieldEdit('inventory', 1, '_maxSlotCount', 300),)
    stats.rebuild()
    assert stats.game_tables.pending.rowCount() == 1

    stats.open_game_tables.click()
    stats.game_tables.load.click()
    document = PresentationDocument()
    snapshot = document.snapshot(stats)
    assert document.unsupported == []

    def tables(node):
        if node.get("kind") == "table":
            yield node
        for child in node.get("children", ()):
            yield from tables(child)

    # The Rust view sizes a table only as a stretched child of a column; tables placed
    # side by side in a row were drawn as one line each.
    stretch = {tuple(column.get("text") for column in node["props"].get("columns", ()))[:1]: node.get("stretch", 0)
               for node in tables(snapshot["root"])}
    assert stretch[("Key",)] > 0 and stretch[("Value",)] > 0


def test_typed_values_follow_the_field_rule():
    from cdmw.core.static_table_records import EDITABLE_FIELDS

    rule = EDITABLE_FIELDS['inventory']['_maxSlotCount']
    assert parse_value(rule, ' 1,200 ') == 1200
    with pytest.raises(ValueError):
        parse_value(rule, '1.5')
    with pytest.raises(ValueError):
        parse_value(rule, str(int(rule.maximum) + 1))


class _Shell:
    def __init__(self):
        self.status = []

    def _background_task_active(self):
        return False

    def set_status_message(self, message, error=False):
        self.status.append((message, error))

    def _run_utility_task(self, *, status_message, task, on_complete=None, on_error=None, task_accepts_cancel=False):
        import threading

        try:
            result = task(lambda _line: None, threading.Event())
        except Exception as exc:  # the shell reports worker errors as text
            on_error(str(exc))
        else:
            on_complete(result)


def test_archive_browser_dialog_writes_the_changed_tables_as_a_dmm_mod(tmp_path, app, monkeypatch):
    from PySide6.QtWidgets import QLineEdit, QMessageBox, QWidget

    import cdmw.ui.archive_browser.game_table_actions as actions
    import cdmw.ui.new_item.dmm_send_ui as dmm_send_ui
    from cdmw.services.game_table_edits import TableModResult

    written = {}

    def write(files, **kwargs):
        written.update(files=files, **kwargs)
        return TableModResult(kwargs['parent'] / kwargs['title'], False, kwargs['title'], tuple(files))

    monkeypatch.setattr(actions, 'archive_table_layers', lambda root, table, **_kw: layers())
    monkeypatch.setattr(actions, 'write_table_edit_mod', write)
    monkeypatch.setattr(actions, 'composed_files', lambda layer: {'inventory.staticinfobody': (None, layer.body)})
    monkeypatch.setattr(dmm_send_ui, 'choose_dmm_mods_folder', lambda _parent: tmp_path / 'mods')
    monkeypatch.setattr(QMessageBox, 'information', lambda *args: None)

    class Browser(actions.ArchiveGameTableActionsMixin, QWidget):
        def __init__(self):
            super().__init__()
            self.shell = _Shell()
            self.archive_package_root_edit = QLineEdit(str(tmp_path))

    browser = Browser()
    try:
        assert actions.table_kind('gamedata/binarystaticinfo__/bin/inventory.dlc_01.staticinfoheader') == 'inventory'
        browser._open_game_table_editor(SimpleEntry('gamedata/binarystaticinfo__/bin/inventory.staticinfobody'))
        dialog = browser._game_table_dialog
        editor = dialog.editor
        assert editor.loaded_table() == 'inventory' and not dialog.write.isEnabled()
        select(editor.rows, 'Money')
        select(editor.values, 'Maximum slots')
        editor.value.setText('500')
        editor.set.click()
        assert dialog.write.isEnabled()
        dialog.mod_name.setText('Bigger bags')
        dialog.write.click()
        assert written['title'] == 'Bigger bags' and written['parent'] == tmp_path / 'mods'
        assert written['edits'] == (TableFieldEdit('inventory', 1, '_maxSlotCount', 500),)
        assert browser.shell.status[-1] == ('Wrote game table mod Bigger bags.', False)
    finally:
        browser.deleteLater()


class SimpleEntry:
    def __init__(self, path):
        self.path = path
        self.basename = path.rsplit('/', 1)[-1]


# -- many changes at once (Speed & Prefabs' Game tables page) --------------------------------


def test_many_changes_merge_once_keep_their_labels_and_go_together(app):
    from cdmw.services.game_table_speed import scale_speed_rows
    from cdmw.ui.archive_browser.game_table_actions import GameTableEditPanel
    from cdmw.ui.new_item.game_tables_editor import GameTablesEditor
    from tests.test_game_table_edits import _ai_index

    assert GameTableEditPanel().scale_button is None  # Edit Game Table Values has no multiply row
    assert GameTableEditPanel(side_by_side=True).scale_button is None
    plain = GameTablesEditor(include_speed=True)
    assert plain.rows_layout is None and plain.pending_box is None

    panel = GameTableEditPanel(side_by_side=True, bulk=True)
    editor = panel.editor
    assert not panel.scale_button.isEnabled() and panel.scale_field.count() == 0  # no table loaded yet
    index = _ai_index([(key, f"AIMove_{name}", True, [(5.0, 3.5, 180.0), (8.0, 6.0, 90.0)])
                       for key, name in enumerate(("Bear", "Boar", "Deer"), start=1)])
    editor.set_index(index)
    assert [panel.scale_field.itemText(n) for n in range(panel.scale_field.count())] == [
        "Move and minimum speed", "Turn speed"]
    assert panel.scale_button.text() == "Add 3 matching rows" and not panel.write.isEnabled()
    editor.search.setText("b")
    assert panel.scale_button.text() == "Add 2 matching rows"
    editor.search.setText("wolf")
    assert panel.scale_button.text() == "Add 0 matching rows" and not panel.scale_button.isEnabled()
    editor.search.setText("")

    emitted = []
    editor.edits_changed.connect(emitted.append)
    panel.scale_factor.setValue(1.5)
    panel.scale_button.click()
    assert len(emitted) == 1 and len(editor.edits()) == 12 and panel.write.isEnabled()
    assert editor.message.text() == "12 values in 3 rows added to Changes in this mod."
    assert editor.pending_box.title() == "Changes in this mod (12)"
    assert editor.pending.item(0, 1).text() == "AIMove_Bear (1)"
    assert editor.pending.item(0, 2).text() == "Speed entry 1: minimum move speed"
    panel.scale_button.click()  # the game's value is multiplied: pressing twice does not stack
    assert len(editor.edits()) == 12 and {edit.value for edit in editor.edits()} == {7.5, 5.25, 12.0, 9.0}

    editor.clear_index()  # another table loads: the changes keep their row and value texts
    assert editor.pending.item(0, 2).text() == "Speed entry 1: minimum move speed"
    assert not panel.scale_button.isEnabled()
    editor.set_index(index)

    editor.pending.selectRow(0)
    editor.pending.selectionModel().select(
        editor.pending.model().index(1, 0),
        editor.pending.selectionModel().SelectionFlag.Select | editor.pending.selectionModel().SelectionFlag.Rows)
    editor.remove.click()
    assert len(editor.edits()) == 10

    panel.scale_field.setCurrentIndex(1)
    panel.scale_factor.setValue(2.0)
    asked = []
    panel.confirm_bulk = lambda count: asked.append(count) or False
    import cdmw.ui.archive_browser.game_table_actions as actions

    limit, actions.BULK_ASK_ABOVE = actions.BULK_ASK_ABOVE, 5
    try:
        assert not panel.add_scaled_rows() and asked == [6] and len(editor.edits()) == 10  # the answer was no
    finally:
        actions.BULK_ASK_ABOVE = limit
    assert panel.add_scaled_rows() and len(editor.edits()) == 16

    panel.scale_field.setCurrentIndex(0)
    panel.scale_factor.setValue(1.0)  # back at the game's values: the move changes are taken back
    panel.scale_button.click()
    assert len(editor.edits()) == 6 and editor.message.text() == "12 values are back at the game's value."
    assert scale_speed_rows(index, choice="turn", factor=2.0).edits == editor.edits()
    panel.deleteLater()
