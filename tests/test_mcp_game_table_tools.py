"""MCP gap plan item 13: Edit Game Table Values through typed tools."""
from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from types import SimpleNamespace

import pytest
from PySide6.QtWidgets import QApplication, QLineEdit, QMessageBox, QWidget

from cdmw.core.static_table_records import TableFieldEdit
from tests.mcp_rail_helpers import RailClient
from tests.test_game_table_edits import layers
from tests.test_game_tables_editor import _Shell


@pytest.fixture
def app():
    return QApplication.instance() or QApplication([])


@pytest.fixture
def browse(tmp_path, app, monkeypatch):
    import cdmw.services.settings_service as settings_service
    import cdmw.ui.archive_browser.game_table_actions as actions
    import cdmw.services.dmm_send as dmm_send
    import cdmw.ui.new_item.dmm_send_ui as dmm_send_ui
    from cdmw.services.game_table_edits import TableModResult

    written = {}

    def write(files, **kwargs):
        written.update(files=files, **kwargs)
        return TableModResult(kwargs["parent"] / kwargs["title"], False, kwargs["title"], tuple(files))

    ini = tmp_path / "cdmw.ini"
    monkeypatch.setattr(settings_service, "resolve_settings_file_path", lambda: ini)
    monkeypatch.setattr(dmm_send_ui, "resolve_settings_file_path", lambda: ini)
    # A real DMM install on the test machine must not be found.
    monkeypatch.setattr(dmm_send, "usual_dmm_places", lambda: [str(tmp_path / "no-usual-dmm")])
    monkeypatch.setattr(actions, "archive_table_layers", lambda root, table, **_kw: layers())
    monkeypatch.setattr(actions, "write_table_edit_mod", write)
    monkeypatch.setattr(actions, "composed_files", lambda layer: {"inventory.staticinfobody": (None, layer.body)})
    monkeypatch.setattr(QMessageBox, "information", lambda *args: None)

    class Browser(actions.ArchiveGameTableActionsMixin, QWidget):
        def __init__(self):
            super().__init__()
            self.shell = _Shell()
            self.archive_package_root_edit = QLineEdit(str(tmp_path))

    browser = Browser()
    dmm = tmp_path / "DMM"
    (dmm / "mods").mkdir(parents=True)
    (dmm / "DMM.exe").write_bytes(b"")
    client = RailClient(tmp_path, window=SimpleNamespace(archive=browser, shell=browser.shell))
    yield client, browser, written, dmm
    from PySide6.QtCore import QEvent

    dialog = getattr(browser, "_game_table_dialog", None)
    if dialog is not None:
        dialog.close()
        dialog.deleteLater()
    browser.deleteLater()
    # Delete them now, not at some later test's event loop, so nothing of this test outlives it,
    # and flush the remembered DMM folder to this test's settings file before the file goes.
    QApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
    from cdmw.ui.widgets import _flush_requested_settings_syncs

    _flush_requested_settings_syncs()


def test_open_read_set_and_write_a_table_through_the_dialog(browse) -> None:
    client, browser, written, dmm = browse
    assert client.ok("tables.editor_state")["open"] is False
    state = client.ok("tables.editor_edit", action="open", table="inventory")
    assert state["loaded"] == "inventory" and state["can_write"] is False
    money = next(row for row in state["rows"] if row["name"] == "Money")
    values = client.ok("tables.editor_state", row=money["row"])["values"]
    slots = next(value for value in values if value["label"] == "Maximum slots")

    changed = client.ok("tables.editor_edit", action="set", row=money["row"], value=slots["value"], new_value=500)
    assert changed["can_write"] is True
    assert changed["changes"] == [{"change": 0, "table": "inventory", "table_name": changed["changes"][0]["table_name"],
                                   "row": money["row"], "target": "_maxSlotCount", "value": 500}]
    assert next(v for v in changed["values"] if v["value"] == slots["value"])["in_this_mod"] == 500

    wrong = client.call("tables.editor_edit", action="set", row=money["row"], value=slots["value"], new_value=70000)
    assert wrong["error"]["code"] == "invalid_arguments" and "Enter a value from" in wrong["error"]["message"]

    result = client.ok("tables.editor_write", name="Bigger bags", dmm_folder=str(dmm))
    assert result["dmm_mods_folder"] == str(dmm / "mods")
    assert written["title"] == "Bigger bags" and written["parent"] == dmm / "mods"
    assert written["edits"] == (TableFieldEdit("inventory", money["row"], "_maxSlotCount", 500),)
    assert browser.shell.status[-1] == ("Wrote game table mod Bigger bags.", False)


def test_dlc_rows_unknown_tables_and_removing_a_change(browse) -> None:
    client, browser, _written, _dmm = browse
    refused = client.call("tables.editor_edit", action="open", table="no_such_table")
    assert refused["error"]["code"] == "refused"
    assert client.call("tables.editor_edit", action="load", table="inventory")["error"]["code"] == "unavailable"

    state = client.ok("tables.editor_edit", action="open",
                      path="gamedata/binarystaticinfo__/bin/inventory.dlc_01.staticinfoheader")
    locked = next(row for row in state["rows"] if not row["can_change"])
    dlc = client.call("tables.editor_edit", action="set", row=locked["row"], value=0, new_value=1)
    assert dlc["error"]["code"] == "refused" and "DLC" in dlc["error"]["message"]

    character = next(row for row in state["rows"] if row["name"] == "Character")
    client.ok("tables.editor_edit", action="set", row=character["row"], value=0, new_value=480)
    assert len(client.ok("tables.editor_state")["changes"]) == 1
    assert client.ok("tables.editor_edit", action="remove", change=0)["changes"] == []
    assert client.call("tables.editor_edit", action="set", row=999999, value=0, new_value=1)["error"]["code"] == (
        "not_found")


def test_write_needs_a_dmm_folder_it_can_find(browse, tmp_path) -> None:
    client, _browser, _written, _dmm = browse
    client.ok("tables.editor_edit", action="open", table="inventory")
    missing = client.call("tables.editor_write", name="Mod")
    assert missing["error"]["code"] == "invalid_arguments" and "DMM.exe" in missing["error"]["message"]
    elsewhere = tmp_path / "not-dmm"
    elsewhere.mkdir()
    assert client.call("tables.editor_write", dmm_folder=str(elsewhere))["error"]["code"] == "not_found"


def test_a_given_dmm_folder_is_the_one_written_and_remembered(browse, tmp_path) -> None:
    from PySide6.QtCore import QSettings

    from cdmw.services.dmm_send import DMM_FOLDER_SETTING

    client, _browser, written, dmm = browse
    other = tmp_path / "OtherDMM"
    (other / "mods").mkdir(parents=True)
    (other / "DMM.exe").write_bytes(b"")
    settings = QSettings(str(tmp_path / "cdmw.ini"), QSettings.Format.IniFormat)
    settings.setValue(DMM_FOLDER_SETTING, str(other))
    settings.sync()

    state = client.ok("tables.editor_edit", action="open", table="inventory")
    money = next(row for row in state["rows"] if row["name"] == "Money")
    values = client.ok("tables.editor_state", row=money["row"])["values"]
    slots = next(value for value in values if value["label"] == "Maximum slots")
    assert client.ok("tables.editor_edit", action="set", row=money["row"], value=slots["value"],
                     new_value=500)["can_write"] is True
    result = client.ok("tables.editor_write", name="Given", dmm_folder=str(dmm))
    assert result["dmm_mods_folder"] == str(dmm / "mods") and written["parent"] == dmm / "mods"
    assert QSettings(str(tmp_path / "cdmw.ini"), QSettings.Format.IniFormat).value(DMM_FOLDER_SETTING) == str(dmm)


def test_where_speed_prefabs_works_the_tabs_game_tables_page(browse, monkeypatch) -> None:
    import cdmw.ui.archive_browser.game_table_actions as actions
    from cdmw.services.game_table_edits import TableLayer
    from cdmw.ui.speed_prefabs.workspace import SpeedPrefabsWorkspace
    from tests.test_game_table_edits import table
    from tests.test_static_table_records import minimal_record

    client, browser, written, dmm = browse
    raw, width = minimal_record("gimmickinfo", 7, "Crate")
    body, header = table([(7, raw)], width=width)
    read = []
    monkeypatch.setattr(actions, "archive_table_layers",
                        lambda root, name, **_kw: read.append(name) or [TableLayer(name, header, body)])
    panel = actions.GameTableEditPanel(side_by_side=True)
    browser._attach_game_table_panel(panel)
    tab = SpeedPrefabsWorkspace((), load_set=lambda path: None, plan=lambda *args: (),
                                open_game_table=lambda name: browser._show_game_table(panel, name),
                                game_table_panel=panel)
    activated = []
    browser.shell._tool_widgets_by_key = {"speed_prefabs": tab}
    browser.shell._activate_tool_key = activated.append
    try:
        assert client.ok("tables.editor_state", where="speed_prefabs")["tables"] == ["aimovespeedinfo", "gimmickinfo"]
        other = client.call("tables.editor_edit", action="open", table="inventory", where="speed_prefabs")
        assert other["error"]["code"] == "invalid_arguments" and "gimmickinfo" in other["error"]["message"]

        state = client.ok("tables.editor_edit", action="open", table="gimmickinfo", where="speed_prefabs")
        assert activated == ["speed_prefabs"] and tab.current_page() == "tables"
        assert state["loaded"] == "gimmickinfo" and read == ["gimmickinfo"]  # the page's first visit read no other
        assert [row["name"] for row in state["rows"]] == ["Crate"]
        changed = client.ok("tables.editor_edit", action="set", row=7, value=0, new_value=2.5, where="speed_prefabs")
        assert [(edit["table"], edit["row"], edit["value"]) for edit in changed["changes"]] == [("gimmickinfo", 7, 2.5)]
        assert tab.state()["table_changes"] == 1
        assert client.ok("tables.editor_state")["open"] is False  # the dialog was never opened, and holds no change

        client.ok("tables.editor_write", name="Faster crates", dmm_folder=str(dmm), where="speed_prefabs")
        assert written["title"] == "Faster crates" and written["parent"] == dmm / "mods"
        assert written["edits"] == (TableFieldEdit("gimmickinfo", 7, "_pushObjectSpeedRate", 2.5),)
    finally:
        tab.close()
        tab.deleteLater()
