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
